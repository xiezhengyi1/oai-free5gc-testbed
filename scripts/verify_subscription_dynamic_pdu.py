"""Isolated end-to-end grant/revoke, NAS authorization and demand-driven PDU verification."""
import copy
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/phase2-isolated"
scenario = yaml.safe_load((run / "source-scenario.yaml").read_text())
ue = scenario["ues"][0]
credentials = json.loads((run / "ue-policy/credentials.json").read_text())
client = httpx.Client(timeout=180, trust_env=False)
project = {"X-API-Key": credentials["project_key"]}
agent = {"X-API-Key": credentials["multiagents_key"]}
directory = run / "ue-policy/evidence" / datetime.now(UTC).strftime("subscription-dynamic-%Y%m%dT%H%M%SZ")
directory.mkdir()
state_path = run / "ue-policy/ue-5/208930000000009.policy.state.json"


def snapshot(label):
    response = client.post("http://127.0.0.1:18081/v1/snapshots", params={"trigger_event": label})
    response.raise_for_status()
    return response.json()


def authorization():
    response = client.get(f"http://127.0.0.1:18080/v1/subscription-authorizations/{ue['supi']}", headers=project)
    response.raise_for_status()
    return response.json()


before = snapshot("BeforeSubscriptionLinkage")
(directory / "before.json").write_text(json.dumps(before, indent=2))
initial_state = json.loads(state_path.read_text())
assert len([pdu for pdu in initial_state["sessions"] if pdu["active"]]) == 2
marker = json.loads((run / "ue-policy/dynamic-pdu.json").read_text())
initial_only = json.loads((Path(marker["backup"]) / "before-demand-nas-state.json").read_text())
assert len([pdu for pdu in initial_only["sessions"] if pdu["active"]]) == 1
(directory / "initial-only.json").write_text(json.dumps(initial_only, indent=2))
(directory / "after-demand.json").write_text(json.dumps(initial_state, indent=2))
original = copy.deepcopy(before["ue_policies"][0]["ue_policy_associations"][0]["policy"])
first = ue["sessions"][0]
first_slice = next(row for row in scenario["slices"] if row["id"] == first["slice_id"])
restricted = copy.deepcopy(original)
for rule in restricted["rules"]:
    rule["routes"] = [{"precedence": 1, "dnn": first["dnn"], "sst": first_slice["sst"], "sd": first_slice["sd"]}]
current = before
for label, sessions, policy, count in [
    ("revoke", [first["id"]], restricted, 1),
    ("grant", [row["id"] for row in ue["sessions"]], original, 2),
]:
    auth = authorization()
    action = {"run_id": "phase2-isolated", "snapshot_id": current["snapshot_id"],
              "action_type": "subscription_authorization_update", "target": {"supi": ue["supi"]},
              "parameters": {"expected_digest": auth["digest"], "session_ids": sessions, "policy": policy}}
    if label == "revoke":
        denied = client.post("http://127.0.0.1:18080/v1/actions/subscription-authorization", headers=agent, json=action)
        assert denied.status_code == 403
        stale = copy.deepcopy(action)
        stale["parameters"]["expected_digest"] = "0" * 64
        response = client.post("http://127.0.0.1:18080/v1/actions/subscription-authorization", headers=project, json=stale)
        response.raise_for_status()
        assert response.json()["status"] == "rejected"
        assert authorization()["digest"] == auth["digest"]
    (directory / f"{label}-action.json").write_text(json.dumps(action, indent=2))
    response = client.post("http://127.0.0.1:18080/v1/actions/subscription-authorization", headers=project, json=action)
    (directory / f"{label}-response.json").write_text(response.text)
    response.raise_for_status()
    receipt = response.json()
    assert receipt["status"] == "verified", receipt
    assert len(receipt["observed_effect"]["allowed_nssai"]) == count
    current = snapshot(f"AfterSubscription:{label}")
    nas = json.loads(state_path.read_text())
    assert sum(row["active"] for row in nas["sessions"]) == count
    assert len(current["sessions"]) == count
    assert all(row["data_quality"]["correlation_status"] == "complete" and not row["data_quality"]["stale"] for row in current["flows"])
    (directory / f"{label}-nas.json").write_text(json.dumps(nas, indent=2))
    (directory / f"{label}-snapshot.json").write_text(json.dumps(current, indent=2))
    if label == "revoke":
        association = current["ue_policies"][0]["ue_policy_associations"][0]
        forbidden = {"run_id": "phase2-isolated", "snapshot_id": current["snapshot_id"], "action_type": "ursp_apply",
                     "target": {"supi": ue["supi"], "flow_id": "video-4k-control-2"},
                     "parameters": {"associationId": association["id"], "expectedVersion": association["version"], "policy": original}}
        rejected = client.post("http://127.0.0.1:18080/v1/actions/policy", headers=agent, json=forbidden)
        rejected.raise_for_status()
        assert rejected.json()["status"] == "rejected"
        (directory / "revoked-ursp-rejected.json").write_text(rejected.text)
    print(json.dumps({"stage": label, "status": "verified", "active_pdus": count}), flush=True)
logs = subprocess.check_output(["docker", "logs", "p2-oai-nrue-5"], stderr=subprocess.STDOUT).decode()
assert "UE_POLICY PDU_REQUEST id=2 dnn=urllc" in logs
(directory / "ue-policy-events.log").write_text("\n".join(line for line in logs.splitlines() if "UE_POLICY" in line))
summary = {"subscription_revoke_grant": "verified", "initial_pdus": 1, "after_demand_pdus": 2,
           "ue_nas_allowed_nssai": "verified", "unauthorized_agent_and_revoked_ursp": "rejected",
           "evidence": str(directory)}
(directory / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary))
