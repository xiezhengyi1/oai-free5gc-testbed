"""Verify SM re-registration preserves actual AM/URSP and refreshes session IDs."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("run_id", choices=["phase2-isolated", "s2-live-auto"])
args = parser.parse_args()
root = Path(__file__).resolve().parents[1] / "artifacts/runs" / args.run_id
snapshot_port, gateway_port = {"phase2-isolated": (18081, 18080), "s2-live-auto": (8081, 8080)}[
    args.run_id
]
key = json.loads((root / "ue-policy/credentials.json").read_text())["multiagents_key"]
client = httpx.Client(timeout=180, trust_env=False, headers={"X-API-Key": key})
before = client.post(
    f"http://127.0.0.1:{snapshot_port}/v1/snapshots", params={"trigger_event": "BeforeSMRebind"}
).json()
flow = next(row for row in before["flows"] if row["id"] == "video-4k-stream-1")
policy = next(row for row in before["ue_policies"] if row["supi"] == flow["supi"])
association = policy["ue_policy_associations"][0]
action = {
    "run_id": args.run_id,
    "snapshot_id": before["snapshot_id"],
    "action_type": "sm_policy_update",
    "target": {"supi": flow["supi"], "flow_id": flow["id"]},
    "parameters": {
        "five_qi": 82,
        "gbr_ul_mbps": 2,
        "mbr_ul_mbps": 4,
        "gbr_dl_mbps": 2,
        "mbr_dl_mbps": 4,
    },
}
directory = root / "ue-policy/evidence" / datetime.now(UTC).strftime("sm-rebind-%Y%m%dT%H%M%SZ")
directory.mkdir(parents=True)
(directory / "before.json").write_text(json.dumps(before, indent=2))
(directory / "action.json").write_text(json.dumps(action, indent=2))
response = client.post(f"http://127.0.0.1:{gateway_port}/v1/actions/policy", json=action)
(directory / "response.txt").write_text(response.text)
response.raise_for_status()
receipt = response.json()
assert receipt["status"] == "verified", receipt
after = client.get(
    f"http://127.0.0.1:{snapshot_port}/v1/snapshots/{receipt['snapshot_after']}"
).json()
(directory / "after.json").write_text(json.dumps(after, indent=2))
new = next(row for row in after["ue_policies"] if row["supi"] == flow["supi"])
assert new["ue_policy_associations"][0]["id"] != association["id"]
assert new["ue_policy_associations"][0]["policy"] == association["policy"]
assert new["ue_policy_associations"][0]["status"] == "complete"
assert new["am_policy_associations"][0]["rfsp"] == policy["am_policy_associations"][0]["rfsp"]
selected = next(row for row in after["flows"] if row["id"] == flow["id"])
assert selected["session"]["five_qi"] == 82
assert selected["session"]["dnn"] == flow["session"]["dnn"]
assert selected["session"]["ul_teid"] != flow["session"]["ul_teid"]
print(
    json.dumps({"sm": "verified", "am_ursp": "preserved_and_rebound", "evidence": str(directory)})
)
