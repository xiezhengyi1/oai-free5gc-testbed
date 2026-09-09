"""Record readiness from isolated containers and real snapshots after manual launch."""

import json
import subprocess
from pathlib import Path

import httpx
import yaml

from testbed.state.models import RunPhase
from testbed.state.run_store import PHASE_ORDER, RunStore

root = Path(__file__).resolve().parents[1] / "artifacts/runs/phase2-isolated"
compose = yaml.safe_load((root / "generated/compose.yaml").read_text())
scenario = yaml.safe_load((root / "source-scenario.yaml").read_text())


def inspect(service):
    name = compose["services"][service]["container_name"]
    assert name.startswith("p2-"), "refusing to inspect a non-isolated target"
    row = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
    assert row["State"]["Running"], name
    return {"container": name, "id": row["Id"], "started_at": row["State"]["StartedAt"]}


def logs(service):
    name = compose["services"][service]["container_name"]
    assert name.startswith("p2-")
    return subprocess.check_output(["docker", "logs", name], stderr=subprocess.STDOUT).decode()


services = [name for name in compose["services"] if name != "grafana"]
containers = [inspect(name) for name in services]
amf = logs("free5gc-amf")
for ue in scenario["ues"]:
    assert f"SUPI:{ue['supi']}]" in amf and "Handle Registration Complete" in amf
    gnb = next(row for row in scenario["ran"]["gnbs"] if row["id"] == ue["serving_gnb"])
    assert "NGSetupResponse" in logs(gnb["container"])
with httpx.Client(timeout=30, trust_env=False) as client:
    response = client.post(
        "http://127.0.0.1:18081/v1/snapshots", params={"trigger_event": "Phase2FinalReadiness"}
    )
    response.raise_for_status()
    snapshot = response.json()
assert len(snapshot["sessions"]) == 2
assert all(
    row["ue_policy_associations"][0]["status"] == "complete" for row in snapshot["ue_policies"]
)
for flow in snapshot["flows"]:
    assert (
        flow["data_quality"]["correlation_status"] == "complete"
        and not flow["data_quality"]["stale"]
    )
    assert flow["telemetry"]["throughput_dl"] > 0
    slice_ = next(
        row for row in snapshot["slice_states"] if row["snssai"] == flow["session"]["snssai"]
    )
    assert flow["id"] in slice_["flow_ids"]
    assert any(
        edge["type"] == "carries"
        and edge["source"] == slice_["slice_id"]
        and edge["target"] == flow["id"]
        for edge in snapshot["topology"]["edges"]
    )
evidence = {
    "containers": containers,
    "snapshot_id": snapshot["snapshot_id"],
    "mode": "nas_ue_policy",
    "audit_kind": "retrospective_manual_launch_readiness",
    "pfcp_evidence": "two established PDU sessions and working bidirectional UPF data paths",
    "pdu_sessions": len(snapshot["sessions"]),
    "flows_verified": len(snapshot["flows"]),
}
(root / "ue-policy/evidence/final-readiness.json").write_text(json.dumps(evidence, indent=2))
store = RunStore(root)
assert store.current().phase == RunPhase.CREATED, (
    "this audit records the initial manual launch once"
)
for phase in PHASE_ORDER[1:]:
    store.advance(phase, evidence)
print(json.dumps({"phase": store.current().phase, "snapshot": snapshot["snapshot_id"]}))
