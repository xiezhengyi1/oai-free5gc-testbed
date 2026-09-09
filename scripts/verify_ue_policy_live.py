"""Exercise only phase2-isolated; keep reproducible policy and path receipts."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

root = Path(__file__).resolve().parents[1] / "artifacts/runs/phase2-isolated"
evidence = root / "ue-policy/evidence" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
evidence.mkdir(parents=True)
credentials = json.loads((root / "ue-policy/credentials.json").read_text())
scenario = yaml.safe_load((root / "source-scenario.yaml").read_text())
client = httpx.Client(
    timeout=120, trust_env=False, headers={"X-API-Key": credentials["multiagents_key"]}
)


def snapshot(label):
    response = client.post("http://127.0.0.1:18081/v1/snapshots", params={"trigger_event": label})
    response.raise_for_status()
    return response.json()


before = snapshot("Phase2VerificationBefore")
(evidence / "before.json").write_text(json.dumps(before, indent=2))
ue = scenario["ues"][0]
state = next(row for row in before["ue_policies"] if row["supi"] == ue["supi"])
association = state["ue_policy_associations"][0]
flow = next(row for row in before["flows"] if row["traffic"]["five_tuple"][4] == "tcp")
assert (
    flow["data_quality"]["correlation_status"] == "complete" and not flow["data_quality"]["stale"]
)
target = next(row for row in ue["sessions"] if row["dnn"] != flow["session"]["dnn"])
slice_ = next(row for row in scenario["slices"] if row["id"] == target["slice_id"])
policy = copy.deepcopy(association["policy"])
rule = next(
    row
    for row in policy["rules"]
    if row["precedence"] == flow["ue_policy_route"]["rule_precedence"]
)
rule["routes"] = [{"precedence": 1, "dnn": target["dnn"], "sst": slice_["sst"], "sd": slice_["sd"]}]
action = {
    "run_id": "phase2-isolated",
    "snapshot_id": before["snapshot_id"],
    "action_type": "ursp_apply",
    "target": {"supi": ue["supi"], "flow_id": flow["id"]},
    "parameters": {
        "associationId": association["id"],
        "expectedVersion": association["version"],
        "policy": policy,
    },
}
(evidence / "ursp-action.json").write_text(json.dumps(action, indent=2))
response = client.post("http://127.0.0.1:18080/v1/actions/policy", json=action)
response.raise_for_status()
receipt = response.json()
(evidence / "ursp-receipt.json").write_text(json.dumps(receipt, indent=2))
assert receipt["status"] == "verified"
assert receipt["observed_effect"]["session"]["dnn"] == target["dnn"]
assert receipt["observed_effect"]["route"]["pdu_session_id"] != flow["session"]["pdu_session_id"]
after = snapshot("Phase2VerificationAfterURSP")
am = next(row for row in after["ue_policies"] if row["supi"] == ue["supi"])[
    "am_policy_associations"
][0]
am_action = {
    "run_id": "phase2-isolated",
    "snapshot_id": after["snapshot_id"],
    "action_type": "am_policy_apply",
    "target": {"supi": ue["supi"]},
    "parameters": {"associationId": am["id"], "rfsp": 64 if am["rfsp"] != 64 else 65},
}
response = client.post("http://127.0.0.1:18080/v1/actions/policy", json=am_action)
response.raise_for_status()
am_receipt = response.json()
(evidence / "am-action.json").write_text(json.dumps(am_action, indent=2))
(evidence / "am-receipt.json").write_text(json.dumps(am_receipt, indent=2))
assert am_receipt["status"] == "verified"
final = snapshot("Phase2VerificationAfterAM")
(evidence / "after.json").write_text(json.dumps(final, indent=2))
print(
    json.dumps(
        {
            "ursp": receipt["status"],
            "from": flow["session"]["dnn"],
            "to": target["dnn"],
            "am": am_receipt["status"],
            "rfsp": am_action["parameters"]["rfsp"],
            "evidence": str(evidence),
        },
        ensure_ascii=False,
    )
)
