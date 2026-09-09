"""Assert rejected operator requests do not mutate the PCF's committed version."""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

root = Path(__file__).resolve().parents[1] / "artifacts/runs/phase2-isolated"
credentials = json.loads((root / "ue-policy/credentials.json").read_text())
client = httpx.Client(
    timeout=120, trust_env=False, headers={"X-API-Key": credentials["multiagents_key"]}
)
snapshot = client.get(
    "http://127.0.0.1:18081/v1/snapshots/latest", params={"run_id": "phase2-isolated"}
).json()
ue = snapshot["ue_policies"][0]
association = ue["ue_policy_associations"][0]
flow = snapshot["flows"][0]
base = {
    "run_id": "phase2-isolated",
    "snapshot_id": snapshot["snapshot_id"],
    "action_type": "ursp_apply",
    "target": {"supi": ue["supi"], "flow_id": flow["id"]},
    "parameters": {
        "associationId": association["id"],
        "expectedVersion": association["version"],
        "policy": association["policy"],
    },
}
cases = {}
request = copy.deepcopy(base)
request["parameters"]["policy"]["rules"][0]["routes"][0]["dnn"] = "not-subscribed"
cases["unsubscribed_dnn"] = request
request = copy.deepcopy(base)
request["parameters"]["policy"]["rules"][0]["routes"][0]["sst"] = 250
cases["unsubscribed_slice"] = request
request = copy.deepcopy(base)
request["parameters"]["expectedVersion"] -= 1
cases["stale_version"] = request
request = copy.deepcopy(base)
request["parameters"]["policy"]["rules"].append(request["parameters"]["policy"]["rules"][0])
cases["duplicate_rule"] = request
request = copy.deepcopy(base)
request["target"]["supi"] = "imsi-208930000000999"
cases["unknown_ue"] = request
results = {}
for name, request in cases.items():
    response = client.post("http://127.0.0.1:18080/v1/actions/policy", json=request)
    result = response.json()
    assert response.status_code in (403, 404, 409, 422) or result["status"] == "rejected", (
        name,
        result,
    )
    state = client.get(f"http://127.0.0.1:18080/v1/ue-policies/{ue['supi']}").json()
    current = next(row for row in state["ue_policy_associations"] if row["id"] == association["id"])
    assert current["version"] == association["version"] and current["status"] == "complete"
    results[name] = {
        "http_status": response.status_code,
        "result": result,
        "version_unchanged": True,
    }
path = (
    root
    / "ue-policy/evidence"
    / datetime.now(UTC).strftime("rejections-%Y%m%dT%H%M%S.%fZ.json")
)
path.write_text(json.dumps(results, indent=2))
print(json.dumps({"passed": list(results), "evidence": str(path)}))
