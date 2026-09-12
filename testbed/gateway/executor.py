from __future__ import annotations

import json
import os
import time
import yaml
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.adapters.free5gc.pcf_adapter import PcfAdapter
from testbed.adapters.free5gc.subscriber_adapter import SubscriberAdapter
from testbed.adapters.oai.ue_adapter import UeAdapter
from testbed.gateway.contracts import (
    ActionReceipt,
    Dispatch,
    LifecycleAction,
    PolicyAction,
    ResourceAction,
    SliceLifecycleAction,
    SliceResourceAction,
)
from testbed.gateway.policy_rebind import rebind_policy
from testbed.gateway.subscription_authorization import AuthorizationAction, apply_authorization
from testbed.gateway.policy_translator import translate_policy
from testbed.gateway.policy_watchdog import PolicyWatchdog
from testbed.gateway.postcondition_verifier import verify_resources, verify_restart
from testbed.gateway.receipt_store import ReceiptStore
from testbed.gateway.resource_translator import translate_resource
from testbed.gateway.slice_manager import SliceManager
from testbed.gateway.ue_policy import AMAction, URSPAction, expected_rule, validate_subscription
from testbed.orchestration.readiness import Readiness
from testbed.scenario.ids import stable_digest
from testbed.scenario.schema import Scenario
from testbed.state.action_store import ActionStore
from testbed.state.flow_allocation_store import FlowAllocationStore
from testbed.state.slice_store import SliceStore
from testbed.telemetry.models import UnifiedSnapshot
from testbed.telemetry.session_tracker import refresh_sessions


class ActionExecutor:
    def __init__(self, run_dir: Path, scenario: Scenario) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.scenario = scenario
        self.docker = DockerAdapter(
            self.run_dir / "generated" / "compose.yaml",
            timeout_seconds=scenario.runtime.action_timeout_seconds,
        )
        gateway = self.docker.inspect(os.environ.get("ACTION_GATEWAY_CONTAINER", "action-gateway"))
        run_mount = next(item for item in gateway["Mounts"] if item["Destination"] == "/run")
        self.docker.compose_project_directory = Path(run_mount["Source"]) / "generated"
        self.readiness = Readiness(self.docker, scenario)
        self.subscribers = SubscriberAdapter(
            "http://free5gc-webui:5000", scenario.runtime.action_timeout_seconds
        )
        self.actions = ActionStore(self.run_dir)
        self.pcf = PcfAdapter(scenario.runtime.action_timeout_seconds)
        self.flow_allocations = FlowAllocationStore(self.run_dir)
        self.receipts = ReceiptStore(self.actions)
        self.slice_store = SliceStore(self.run_dir)
        self.slice_manager = SliceManager(
            scenario,
            self.docker,
            self.readiness,
            self.slice_store,
        )

    def _snapshot(self, trigger: str) -> UnifiedSnapshot:
        response = httpx.post(
            "http://snapshot-builder:8081/v1/snapshots",
            params={"trigger_event": trigger},
            timeout=self.scenario.runtime.action_timeout_seconds,
        )
        response.raise_for_status()
        return UnifiedSnapshot.model_validate(response.json())

    def _action_id(self, action: object, accepted_at: datetime) -> str:
        payload = {
            "action": action.model_dump(mode="json"),  # type: ignore[union-attr]
            "accepted_at": accepted_at.isoformat(),
        }
        return "action-" + stable_digest(payload)[:20]

    def _receipt(
        self,
        action: (
            PolicyAction
            | ResourceAction
            | LifecycleAction
            | SliceLifecycleAction
            | SliceResourceAction
        ),
        accepted_at: datetime,
        effect: dict[str, Any],
        snapshot_after: UnifiedSnapshot,
    ) -> ActionReceipt:
        receipt = ActionReceipt(
            action_id=self._action_id(action, accepted_at),
            run_id=action.run_id,
            snapshot_before=action.snapshot_id,
            status="verified",
            dispatch=Dispatch(
                accepted_at=accepted_at,
                completed_at=datetime.now(UTC),
            ),
            observed_effect=effect,
            snapshot_after=snapshot_after.snapshot_id,
        )
        return self.receipts.write(receipt)

    def policy(self, action: PolicyAction) -> ActionReceipt:
        accepted_at = datetime.now(UTC)
        self.actions.append_action(action.model_dump(mode="json"))
        ue = next(item for item in self.scenario.ues if item.supi == action.target.supi)
        policy_before = None
        target_scenario = self.scenario
        if "UE_POLICY_ADMIN_TOKEN" in os.environ:
            policy_before = self.pcf.ue_policy(ue.supi)
            records = policy_before["ue_policy_associations"]
            if len(records) != 1 or records[0]["status"] != "complete":
                raise ValueError("SM re-registration requires a completed URSP to preserve")
            route = json.loads(
                (
                    self.run_dir / "ue-policy" / ue.id / f"{action.target.flow_id}.route.json"
                ).read_text()
            )
            if (accepted_at - datetime.fromisoformat(route["observed_at"])).total_seconds() > 5:
                raise ValueError("SM target has no fresh UE-selected PDU route")
            session = ue.sessions[route["pdu_session_id"] - 1]
            target_scenario = self.scenario.model_copy(
                update={
                    "flows": tuple(
                        flow.model_copy(update={"session_id": session.id})
                        if flow.id == action.target.flow_id
                        else flow
                        for flow in self.scenario.flows
                    )
                }
            )
        translated = translate_policy(target_scenario, action)
        self.subscribers.update_policy(
            action.target.supi,
            translated.plmn_id,
            translated.flow_rule,
            translated.qos_flow,
            translated.charging_data,
        )
        dynamic = (self.run_dir / "ue-policy/dynamic-pdu.json").exists()
        if dynamic:
            compose = yaml.safe_load((self.run_dir / "generated/compose.yaml").read_text())
            tracker = compose["services"]["session-tracker"]["container_name"]
            self.docker.stop(tracker)
            self.docker.stop(translated.traffic_sidecar)
        self.docker.restart(translated.ue_container)
        if dynamic:
            self.readiness.wait(lambda: UeAdapter(self.docker, ue.container).tunnel())
        else:
            self.readiness.wait(lambda: self.readiness.pdu(ue))
        rebind = None
        if policy_before is not None:
            rebind = rebind_policy(
                self.pcf,
                ue.supi,
                policy_before,
                self.scenario.runtime.action_timeout_seconds,
                self.scenario.runtime.readiness_poll_seconds,
            )
            refresh_sessions(self.run_dir, self.docker)
        self.docker.restart(translated.traffic_sidecar)
        if dynamic:
            self.docker.start(tracker)
        self.readiness.wait(self.readiness.traffic)
        watchdog = PolicyWatchdog(
            self.scenario.runtime.action_timeout_seconds,
            self.scenario.runtime.readiness_poll_seconds,
        )
        snapshot, effect = watchdog.wait(
            action, lambda: self._snapshot(f"PolicyAction:{action.target.flow_id}")
        )
        if rebind is not None:
            effect["policy_rebind"] = rebind
        self.flow_allocations.update(
            action.target.flow_id,
            action.parameters.mbr_ul_mbps,
            action.parameters.mbr_dl_mbps,
            self._action_id(action, accepted_at),
        )
        snapshot = self._snapshot(f"PolicyAllocation:{action.target.flow_id}")
        return self._receipt(action, accepted_at, effect, snapshot)

    def standard_policy(self, action: AMAction | URSPAction) -> ActionReceipt:
        accepted_at = datetime.now(UTC)
        self.actions.append_action(action.model_dump(mode="json"))
        try:
            return self._apply_standard_policy(action, accepted_at)
        except (ValueError, RuntimeError, TimeoutError, httpx.HTTPError) as error:
            rejected = isinstance(error, ValueError) or (
                isinstance(error, httpx.HTTPStatusError) and 400 <= error.response.status_code < 500
            )
            return self.receipts.write(
                ActionReceipt(
                    action_id=self._action_id(action, accepted_at),
                    run_id=action.run_id,
                    snapshot_before=action.snapshot_id,
                    status="rejected" if rejected else "failed",
                    dispatch=Dispatch(accepted_at=accepted_at, completed_at=datetime.now(UTC)),
                    observed_effect={"error": str(error), "verified": False},
                    snapshot_after=None,
                )
            )

    def _apply_standard_policy(
        self, action: AMAction | URSPAction, accepted_at: datetime
    ) -> ActionReceipt:
        if isinstance(action, AuthorizationAction):
            return apply_authorization(self, action, accepted_at)
        plmn = f"{self.scenario.plmn.mcc}{self.scenario.plmn.mnc}"
        subscriber = self.subscribers.get(action.target.supi, plmn)
        if isinstance(action, URSPAction):
            if action.parameters.policy.plmn != plmn:
                raise ValueError("URSP PLMN does not match this testbed")
            validate_subscription(action.parameters.policy, subscriber)
            ue = next(item for item in self.scenario.ues if item.supi == action.target.supi)
            slices = {item.id: item for item in self.scenario.slices}
            available = {
                (item.dnn, slices[item.slice_id].sst, slices[item.slice_id].sd)
                for item in ue.sessions
            }
            for rule in action.parameters.policy.rules:
                for route in rule.routes:
                    if (route.dnn, route.sst, route.sd) not in available:
                        raise ValueError(
                            "URSP route is subscribed but absent from the UE PDU session pool"
                        )
            declared_flow = next(
                item for item in self.scenario.flows if item.id == action.target.flow_id
            )
            service = next(
                item
                for item in self.scenario.services
                if item.id == declared_flow.service_instance_id
            )
            expected = expected_rule(
                action.parameters.policy,
                service.ip,
                17 if declared_flow.protocol == "udp" else 6,
                declared_flow.dst_port,
            )
            routes = {(row.dnn, f"{row.sst:02d}{row.sd}") for row in expected.routes}
        effect = self.pcf.apply_ue_policy(
            action.target.supi,
            "ursp" if isinstance(action, URSPAction) else "am",
            action.parameters.model_dump(mode="json", exclude_none=True),
        )
        if isinstance(action, AMAction):
            ue = next(item for item in self.scenario.ues if item.supi == action.target.supi)
            gnb = next(item for item in self.scenario.ran.gnbs if item.id == ue.serving_gnb)
            baseline = self._snapshot(f"AMPolicy:{action.target.supi}")
            session = next(row for row in baseline.sessions if row["supi"] == ue.supi)
            marker = (
                f"RFSP_POLICY ran_ue_id={session['cu_ue_id']} "
                f"rfsp={action.parameters.rfsp} response=sent"
            )
            deadline = time.monotonic() + self.scenario.runtime.action_timeout_seconds
            while time.monotonic() < deadline:
                if marker in self.docker.container_logs(
                    gnb.container, since=accepted_at.isoformat()
                ):
                    effect.update(
                        {
                            "verification_scope": "gnb_context_and_ngap_response",
                            "radio_mapping": "none",
                            "evidence": marker,
                        }
                    )
                    return self._receipt(
                        action, accepted_at, effect, self._snapshot(f"AMPolicyVerified:{ue.supi}")
                    )
                time.sleep(self.scenario.runtime.readiness_poll_seconds)
            raise TimeoutError("gNB did not acknowledge the requested RFSP")
        deadline = time.monotonic() + self.scenario.runtime.action_timeout_seconds
        while time.monotonic() < deadline:
            state = self.pcf.ue_policy(action.target.supi)
            association = next(
                row for row in state["ue_policy_associations"] if row["id"] == effect["id"]
            )
            if association["status"] in {"rejected", "transfer_failed", "delivery_timeout"}:
                raise RuntimeError(f"UE policy failed: {association}")
            if association["status"] == "complete":
                snapshot = self._snapshot(f"UEPolicy:{action.target.flow_id}")
                flow = next(
                    row for row in snapshot.flows if row["flow_id"] == action.target.flow_id
                )
                route = flow.get("ue_policy_route")
                if (
                    route is not None
                    and route["pti"] == effect["pti"]
                    and route["upsc"] == action.parameters.policy.upsc
                    and route["rule_precedence"] == expected.precedence
                    and (flow["session"]["dnn"], flow["session"]["snssai"]) in routes
                    and snapshot.observed_from > accepted_at
                    and route["observed_at"] > accepted_at.isoformat()
                    and not flow["data_quality"]["stale"]
                    and flow["data_quality"]["correlation_status"] == "complete"
                    and flow["telemetry"]["throughput_dl"] is not None
                    and flow["telemetry"]["throughput_dl"] > 0
                ):
                    effect.update(
                        {
                            "association": association,
                            "route": route,
                            "session": flow["session"],
                            "enforcement_mode": "nas_ue_policy",
                        }
                    )
                    return self._receipt(action, accepted_at, effect, snapshot)
            time.sleep(self.scenario.runtime.readiness_poll_seconds)
        raise TimeoutError("UE policy delivery or data-plane verification timed out")

    def resource(self, action: ResourceAction) -> ActionReceipt:
        accepted_at = datetime.now(UTC)
        self.actions.append_action(action.model_dump(mode="json"))
        translated = translate_resource(action)
        limits = self.docker.update_resources(
            translated.container, translated.cpus, translated.memory_mb
        )
        effect = verify_resources(translated.cpus, translated.memory_mb, limits)
        snapshot = self._snapshot(f"ResourceAction:{translated.container}")
        return self._receipt(action, accepted_at, effect, snapshot)

    def lifecycle(self, action: LifecycleAction) -> ActionReceipt:
        accepted_at = datetime.now(UTC)
        self.actions.append_action(action.model_dump(mode="json"))
        effect = verify_restart(self.docker.restart(action.target.container))
        effect["traffic_ready"] = self.readiness.wait(self.readiness.traffic)
        snapshot = self._snapshot(f"LifecycleAction:{action.target.container}")
        return self._receipt(action, accepted_at, effect, snapshot)

    def slice_lifecycle(self, action: SliceLifecycleAction) -> ActionReceipt:
        accepted_at = datetime.now(UTC)
        self.actions.append_action(action.model_dump(mode="json"))
        effect, _state = self.slice_manager.lifecycle(action)
        snapshot = self._snapshot(
            f"SliceLifecycleAction:{action.target.slice_id}:{action.action_type}"
        )
        return self._receipt(action, accepted_at, effect, snapshot)

    def slice_resources(self, action: SliceResourceAction) -> ActionReceipt:
        accepted_at = datetime.now(UTC)
        self.actions.append_action(action.model_dump(mode="json"))
        effect = self.slice_manager.resources(action)
        snapshot = self._snapshot(f"SliceResourceAction:{action.target.slice_id}")
        return self._receipt(action, accepted_at, effect, snapshot)
