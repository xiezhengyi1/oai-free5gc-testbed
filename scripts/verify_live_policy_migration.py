"""Verify all live sessions and reversible URSP path selection plus AM RFSP."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from testbed.state.run_store import RunStore

run = Path(__file__).resolve().parents[1] / "artifacts/runs/s2-live-auto"
scenario = yaml.safe_load((run / "source-scenario.yaml").read_text())
credentials = json.loads((run / "ue-policy/credentials.json").read_text())
client = httpx.Client(
    timeout=180, trust_env=False, headers={"X-API-Key": credentials["multiagents_key"]}
)
directory = run / "ue-policy/evidence" / datetime.now(UTC).strftime("live-%Y%m%dT%H%M%SZ")
directory.mkdir(parents=True)


def snapshot(label):
    response = client.post("http://127.0.0.1:8081/v1/snapshots", params={"trigger_event": label})
    response.raise_for_status()
    return response.json()


def state(native, supi):
    return next(row for row in native["ue_policies"] if row["supi"] == supi)


before = snapshot("LiveMigrationBefore")
(directory / "before.json").write_text(json.dumps(before, indent=2))
assert len(before["ue_policies"]) == len(scenario["ues"]) == 6
assert len(before["sessions"]) == sum(len(ue["sessions"]) for ue in scenario["ues"]) == 11
for ue in before["ue_policies"]:
    assert len(ue["ue_policy_associations"]) == len(ue["am_policy_associations"]) == 1
    assert ue["ue_policy_associations"][0]["status"] == "complete", ue["supi"]
for row in before["flows"]:
    assert (
        row["data_quality"]["correlation_status"] == "complete" and not row["data_quality"]["stale"]
    ), row["id"]
    assert row["telemetry"]["throughput_dl"] > 0, row["id"]
ue = next(row for row in scenario["ues"] if row["id"] == "ue-5")
flow = next(row for row in before["flows"] if row["id"] == "video-4k-stream-1")
original = copy.deepcopy(state(before, ue["supi"])["ue_policy_associations"][0]["policy"])
target = next(row for row in ue["sessions"] if row["dnn"] != flow["session"]["dnn"])
slice_ = next(row for row in scenario["slices"] if row["id"] == target["slice_id"])
switched = copy.deepcopy(original)
rule = next(
    row
    for row in switched["rules"]
    if row["precedence"] == flow["ue_policy_route"]["rule_precedence"]
)
rule["routes"] = [{"precedence": 1, "dnn": target["dnn"], "sst": slice_["sst"], "sd": slice_["sd"]}]
current = before
receipts = []
for label, policy, expected_dnn in [
    ("switch", switched, target["dnn"]),
    ("restore", original, flow["session"]["dnn"]),
]:
    association = state(current, ue["supi"])["ue_policy_associations"][0]
    action = {
        "run_id": "s2-live-auto",
        "snapshot_id": current["snapshot_id"],
        "action_type": "ursp_apply",
        "target": {"supi": ue["supi"], "flow_id": flow["id"]},
        "parameters": {
            "associationId": association["id"],
            "expectedVersion": association["version"],
            "policy": policy,
        },
    }
    (directory / f"{label}-action.json").write_text(json.dumps(action, indent=2))
    response = client.post("http://127.0.0.1:8080/v1/actions/policy", json=action)
    response.raise_for_status()
    receipt = response.json()
    (directory / f"{label}-receipt.json").write_text(json.dumps(receipt, indent=2))
    assert receipt["status"] == "verified", receipt
    assert receipt["observed_effect"]["session"]["dnn"] == expected_dnn
    receipts.append(receipt)
    current = snapshot(f"LiveURSP:{label}")
am = state(current, ue["supi"])["am_policy_associations"][0]
action = {
    "run_id": "s2-live-auto",
    "snapshot_id": current["snapshot_id"],
    "action_type": "am_policy_apply",
    "target": {"supi": ue["supi"]},
    "parameters": {"associationId": am["id"], "rfsp": 64},
}
response = client.post("http://127.0.0.1:8080/v1/actions/policy", json=action)
response.raise_for_status()
receipt = response.json()
(directory / "am-receipt.json").write_text(json.dumps(receipt, indent=2))
assert receipt["status"] == "verified", receipt
final = snapshot("LiveMigrationVerified")
(directory / "after.json").write_text(json.dumps(final, indent=2))
evidence = {
    "mode": "nas_ue_policy",
    "ues": 6,
    "sessions": 11,
    "flows": len(final["flows"]),
    "ursp_roundtrip": "verified",
    "am_rfsp": 64,
    "evidence": str(directory),
    "snapshot_id": final["snapshot_id"],
}
RunStore(run).recover(evidence)
(directory / "summary.json").write_text(json.dumps(evidence, indent=2))
print(json.dumps(evidence))
