"""Explicit subscription provisioning, separate from AM policy authority."""
import copy
import hashlib
import json
import time
import yaml
from typing import Literal

from pydantic import Field

from testbed.gateway.ue_policy import UETarget, URSPPolicy, validate_subscription
from testbed.gateway.ue_policy import expected_rule
from testbed.gateway.policy_rebind import rebind_policy
from testbed.adapters.oai.ue_adapter import UeAdapter
from testbed.telemetry.session_tracker import refresh_sessions
from testbed.rendering.free5gc_renderer import _subscriber_payload
from testbed.scenario.schema import StrictModel

FIELDS = ("AccessAndMobilitySubscriptionData", "SessionManagementSubscriptionData",
          "SmfSelectionSubscriptionData", "SmPolicyData")


def authorization_digest(subscriber: dict) -> str:
    body = {key: subscriber[key] for key in FIELDS}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class AuthorizationParameters(StrictModel):
    expected_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_ids: list[str] = Field(min_length=1)
    policy: URSPPolicy


class AuthorizationAction(StrictModel):
    run_id: str
    snapshot_id: str
    action_type: Literal["subscription_authorization_update"]
    target: UETarget
    parameters: AuthorizationParameters


def project_authorization(scenario, ue, current: dict, parameters: AuthorizationParameters) -> dict:
    if authorization_digest(current) != parameters.expected_digest:
        raise ValueError("subscription changed since observation")
    declared = {session.id: session for session in ue.sessions}
    requested = set(parameters.session_ids)
    if len(requested) != len(parameters.session_ids) or not requested <= declared.keys():
        raise ValueError("authorization requires unique sessions from the deployed UE catalog")
    if ue.sessions[0].id not in requested:
        raise ValueError("the initial connectivity session must remain authorized")
    selected_ue = ue.model_copy(update={"sessions": tuple(session for session in ue.sessions if session.id in requested)})
    template = _subscriber_payload(scenario, selected_ue)
    result = copy.deepcopy(current)
    result["AccessAndMobilitySubscriptionData"]["nssai"].update(template["AccessAndMobilitySubscriptionData"]["nssai"])
    # Keep provisioned QoS/AMBR for retained DNNs; use the platform's explicit provisioning defaults for new grants.
    for row in template["SessionManagementSubscriptionData"]:
        for old in current["SessionManagementSubscriptionData"]:
            if old["singleNssai"] == row["singleNssai"]:
                for dnn in row["dnnConfigurations"]:
                    if dnn in old["dnnConfigurations"]:
                        row["dnnConfigurations"][dnn] = copy.deepcopy(old["dnnConfigurations"][dnn])
                row.update({key: copy.deepcopy(value) for key, value in old.items() if key != "dnnConfigurations"})
    result["SessionManagementSubscriptionData"] = template["SessionManagementSubscriptionData"]
    for field, mapping, dnn_field in (
        ("SmfSelectionSubscriptionData", "subscribedSnssaiInfos", "dnnInfos"),
        ("SmPolicyData", "smPolicySnssaiData", "smPolicyDnnData"),
    ):
        desired_slices = template[field][mapping]
        for key, row in desired_slices.items():
            if key in current[field][mapping]:
                old = current[field][mapping][key]
                if dnn_field == "dnnInfos":
                    retained = {item["dnn"]: item for item in old[dnn_field]}
                    row[dnn_field] = [copy.deepcopy(retained[item["dnn"]]) if item["dnn"] in retained else item
                                      for item in row[dnn_field]]
                else:
                    for dnn in row[dnn_field]:
                        if dnn in old[dnn_field]:
                            row[dnn_field][dnn] = copy.deepcopy(old[dnn_field][dnn])
                row.update({name: copy.deepcopy(value) for name, value in old.items() if name != dnn_field})
        result[field][mapping] = desired_slices
    slices = {item.id: item for item in scenario.slices}
    allowed = {(f"{slices[s.slice_id].sst:02d}{slices[s.slice_id].sd}", s.dnn) for s in selected_ue.sessions}
    for field in ("FlowRules", "QosFlows", "ChargingDatas"):
        result[field] = [row for row in result[field] if (row["snssai"], row["dnn"]) in allowed]
    if parameters.policy.plmn != scenario.plmn.mcc + scenario.plmn.mnc:
        raise ValueError("policy PLMN differs from the subscription")
    validate_subscription(parameters.policy, result)
    services = {service.id: service for service in scenario.services}
    for flow in scenario.flows:
        if flow.ue_id == ue.id:
            expected_rule(parameters.policy, services[flow.service_instance_id].ip,
                          17 if flow.protocol == "udp" else 6, flow.dst_port)
    return result


def apply_authorization(executor, action: AuthorizationAction, accepted_at):
    if not (executor.run_dir / "ue-policy/dynamic-pdu.json").exists():
        raise ValueError("subscription linkage requires the dynamic PDU profile")
    ue = next(item for item in executor.scenario.ues if item.supi == action.target.supi)
    plmn = executor.scenario.plmn.mcc + executor.scenario.plmn.mnc
    current = executor.subscribers.get(ue.supi, plmn)
    desired = project_authorization(executor.scenario, ue, current, action.parameters)
    previous = executor.pcf.ue_policy(ue.supi)
    if len(previous["ue_policy_associations"]) != 1 or previous["ue_policy_associations"][0]["status"] != "complete":
        raise ValueError("subscription linkage requires one completed current UE policy")
    previous["ue_policy_associations"][0]["policy"] = action.parameters.policy.model_dump(mode="json", exclude_none=True)
    directory = executor.run_dir / "ue-policy/authorization" / executor._action_id(action, accepted_at)
    directory.mkdir(parents=True, mode=0o700)
    (directory / "subscriber-before.json").write_text(json.dumps(current, indent=2))
    (directory / "subscriber-before.json").chmod(0o600)
    journal = {"stage": "prepared", "supi": ue.supi, "before_digest": authorization_digest(current),
               "desired_digest": authorization_digest(desired)}

    def stage(value):
        journal["stage"] = value
        (directory / "progress.json").write_text(json.dumps(journal, indent=2))

    stage("prepared")
    compose = yaml.safe_load((executor.run_dir / "generated/compose.yaml").read_text())
    tracker = compose["services"]["session-tracker"]["container_name"]
    executor.docker.stop(tracker)
    executor.docker.stop(ue.traffic_sidecar)
    stage("traffic_stopped")
    executor.docker.stop(ue.container)
    stage("ue_stopped")
    executor.subscribers.upsert(desired)
    stage("subscription_committed")
    executor.docker.start(ue.container)
    state_path = executor.run_dir / "ue-policy" / ue.id / f"{ue.supi.removeprefix('imsi-')}.policy.state.json"
    deadline = time.monotonic() + executor.scenario.runtime.action_timeout_seconds
    while time.monotonic() < deadline:
        if not executor.docker.container_running(ue.container):
            raise RuntimeError("UE exited during subscription re-registration")
        nas = json.loads(state_path.read_text())
        if state_path.stat().st_mtime > accepted_at.timestamp() and any(row["active"] for row in nas["sessions"]):
            UeAdapter(executor.docker, ue.container).tunnel()
            break
        time.sleep(executor.scenario.runtime.readiness_poll_seconds)
    else:
        raise TimeoutError("UE initial PDU did not re-establish after subscription update")
    rebound = rebind_policy(executor.pcf, ue.supi, previous,
                           executor.scenario.runtime.action_timeout_seconds,
                           executor.scenario.runtime.readiness_poll_seconds)
    nas = json.loads(state_path.read_text())
    expected = {(row["sst"], row["sd"]) for row in desired["AccessAndMobilitySubscriptionData"]["nssai"]["defaultSingleNssais"]}
    if {(row["sst"], row["sd"]) for row in nas["allowed_nssai"]} != expected:
        raise RuntimeError("UE NAS Allowed NSSAI differs from the committed subscription")
    if state_path.stat().st_mtime <= accepted_at.timestamp():
        raise RuntimeError("UE NAS authorization evidence predates the update")
    stage("nas_authorization_verified")
    executor.docker.start(tracker)
    executor.docker.start(ue.traffic_sidecar)
    deadline = time.monotonic() + executor.scenario.runtime.action_timeout_seconds
    while time.monotonic() < deadline:
        refresh_sessions(executor.run_dir, executor.docker)
        snapshot = executor._snapshot("SubscriptionAuthorizationVerified")
        flows = [flow for flow in snapshot.flows if flow["supi"] == ue.supi]
        if snapshot.observed_from > accepted_at and all(
            flow["data_quality"]["correlation_status"] == "complete" and not flow["data_quality"]["stale"]
            and flow["telemetry"]["availability"] > 0
            and flow["telemetry"]["throughput_ul"] + flow["telemetry"]["throughput_dl"] > 0
            for flow in flows
        ):
            stage("verified")
            return executor._receipt(action, accepted_at, {
                "subscription_digest": authorization_digest(desired), "allowed_nssai": nas["allowed_nssai"],
                "policy_rebind": rebound, "subscription_stage": "verified", "ue_reregistered": True,
                "journal": str(directory / "progress.json"),
            }, snapshot)
        time.sleep(executor.scenario.runtime.readiness_poll_seconds)
    raise TimeoutError("subscription committed but post-registration traffic verification timed out")
