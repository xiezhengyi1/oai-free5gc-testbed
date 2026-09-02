from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.adapters.free5gc.subscriber_adapter import SubscriberAdapter
from testbed.gateway.contracts import (
    ActionReceipt,
    Dispatch,
    LifecycleAction,
    PolicyAction,
    ResourceAction,
    SliceLifecycleAction,
    SliceResourceAction,
)
from testbed.gateway.policy_translator import translate_policy
from testbed.gateway.policy_watchdog import PolicyWatchdog
from testbed.gateway.postcondition_verifier import verify_resources, verify_restart
from testbed.gateway.receipt_store import ReceiptStore
from testbed.gateway.resource_translator import translate_resource
from testbed.gateway.slice_manager import SliceManager
from testbed.orchestration.readiness import Readiness
from testbed.scenario.ids import stable_digest
from testbed.scenario.schema import Scenario
from testbed.state.action_store import ActionStore
from testbed.state.flow_allocation_store import FlowAllocationStore
from testbed.state.slice_store import SliceStore
from testbed.telemetry.models import UnifiedSnapshot


class ActionExecutor:
    def __init__(self, run_dir: Path, scenario: Scenario) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.scenario = scenario
        self.docker = DockerAdapter(
            self.run_dir / "generated" / "compose.yaml",
            timeout_seconds=scenario.runtime.action_timeout_seconds,
        )
        gateway = self.docker.inspect("action-gateway")
        run_mount = next(item for item in gateway["Mounts"] if item["Destination"] == "/run")
        self.docker.compose_project_directory = Path(run_mount["Source"]) / "generated"
        self.readiness = Readiness(self.docker, scenario)
        self.subscribers = SubscriberAdapter(
            "http://free5gc-webui:5000", scenario.runtime.action_timeout_seconds
        )
        self.actions = ActionStore(self.run_dir)
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
        translated = translate_policy(self.scenario, action)
        self.subscribers.update_policy(
            action.target.supi,
            translated.plmn_id,
            translated.flow_rule,
            translated.qos_flow,
            translated.charging_data,
        )
        self.docker.restart(translated.ue_container)
        self.readiness.wait(lambda: self.readiness.pdu(ue))
        self.docker.restart(translated.traffic_sidecar)
        self.readiness.wait(self.readiness.traffic)
        watchdog = PolicyWatchdog(
            self.scenario.runtime.action_timeout_seconds,
            self.scenario.runtime.readiness_poll_seconds,
        )
        snapshot, effect = watchdog.wait(
            action, lambda: self._snapshot(f"PolicyAction:{action.target.flow_id}")
        )
        self.flow_allocations.update(
            action.target.flow_id,
            action.parameters.mbr_ul_mbps,
            action.parameters.mbr_dl_mbps,
            self._action_id(action, accepted_at),
        )
        snapshot = self._snapshot(f"PolicyAllocation:{action.target.flow_id}")
        return self._receipt(action, accepted_at, effect, snapshot)

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
