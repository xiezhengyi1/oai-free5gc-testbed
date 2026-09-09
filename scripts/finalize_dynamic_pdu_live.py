"""Verify preserved live state, pin runtime images, and record the completed upgrade."""
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from testbed.gateway.subscription_authorization import authorization_digest
from testbed.state.run_store import RunStore

root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/s2-live-auto"
compose_path = run / "generated/compose.yaml"
compose = yaml.safe_load(compose_path.read_text())
assert compose["name"] == "testbed-s2-live-auto"
scenario = yaml.safe_load((run / "source-scenario.yaml").read_text())
before = json.loads((run / "ue-policy/dynamic-live-before.json").read_text())
migration = json.loads((run / "ue-policy/dynamic-live-migration.json").read_text())
evidence_root = run / "ue-policy/evidence"
subscription_dir = max(evidence_root.glob("subscription-dynamic-*"), key=lambda item: item.name)
subscription = json.loads((subscription_dir / "summary.json").read_text())
assert subscription["subscription_revoke_grant"] == "verified"
soak_dir = max(evidence_root.glob("pfcp-soak-*"), key=lambda item: item.name)
assert json.loads((soak_dir / "summary.json").read_text())["status"] == "verified"
policy_dir = max(evidence_root.glob("live-*"), key=lambda item: item.name)
assert json.loads((policy_dir / "summary.json").read_text())["ursp_roundtrip"] == "verified"
agents_dir = max(evidence_root.glob("multiagents-live-*"), key=lambda item: item.name)
assert len(json.loads((agents_dir / "observations.json").read_text())) == 18
smf_config = yaml.safe_load((run / "generated/free5gc-config/smfcfg.yaml").read_text())
assert smf_config["configuration"]["urrThreshold"] == 0 and smf_config["configuration"]["urrPeriod"] == 10
credentials = json.loads((run / "ue-policy/credentials.json").read_text())
http = httpx.Client(timeout=180, trust_env=False, headers={"X-API-Key": credentials["project_key"]})
response = http.post("http://127.0.0.1:8081/v1/snapshots", params={"trigger_event": "DynamicLiveFinal"})
response.raise_for_status()
snapshot = response.json()
assert len(snapshot["sessions"]) == sum(len(ue["sessions"]) for ue in scenario["ues"]) == 11
assert len(snapshot["flows"]) == len(scenario["flows"]) == 11
for flow in snapshot["flows"]:
    assert flow["data_quality"]["correlation_status"] == "complete" and not flow["data_quality"]["stale"], flow["id"]
    assert flow["telemetry"]["throughput_ul"] + flow["telemetry"]["throughput_dl"] > 0, flow["id"]
    assert flow["telemetry"]["availability"] > 0, flow["id"]
for ue in scenario["ues"]:
    actual = next(row for row in snapshot["ue_policies"] if row["supi"] == ue["supi"])
    old = before["policies"][ue["supi"]]
    assert len(actual["ue_policy_associations"]) == len(actual["am_policy_associations"]) == 1
    assert actual["ue_policy_associations"][0]["status"] == "complete"
    assert actual["ue_policy_associations"][0]["policy"] == old["ue_policy_associations"][0]["policy"]
    assert actual["am_policy_associations"][0]["rfsp"] == old["am_policy_associations"][0]["rfsp"]
    auth = http.get(f"http://127.0.0.1:8080/v1/subscription-authorizations/{ue['supi']}")
    auth.raise_for_status()
    assert auth.json()["digest"] == authorization_digest(before["subscribers"][ue["supi"]]), ue["id"]
    nas = json.loads((run / "ue-policy" / ue["id"] / f"{ue['supi'].removeprefix('imsi-')}.policy.state.json").read_text())
    assert sum(row["active"] for row in nas["sessions"]) == len(ue["sessions"])
    expected_nssai = before["subscribers"][ue["supi"]]["AccessAndMobilitySubscriptionData"]["nssai"]["defaultSingleNssais"]
    assert {(r["sst"], r["sd"]) for r in nas["allowed_nssai"]} == {(r["sst"], r["sd"]) for r in expected_nssai}
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
directory = evidence_root / f"dynamic-live-final-{stamp}"
directory.mkdir()
(directory / "snapshot.json").write_text(json.dumps(snapshot, indent=2))
images = {}
for service, spec in compose["services"].items():
    runtime = json.loads(subprocess.check_output(["docker", "inspect", spec["container_name"]]))[0]
    assert runtime["State"]["Running"], service
    if spec["container_name"].startswith("oai-"):
        assert runtime["State"]["Health"]["Status"] == "healthy", service
    if "dynamic" in spec["image"]:
        image_id = runtime["Image"]
        tag = spec["image"].rsplit(":", 1)[0] + ":s2-dynamic-20260909-" + image_id.split(":")[1][:12]
        subprocess.run(["docker", "tag", image_id, tag], check=True)
        spec["image"] = tag
    images[service] = {"image": spec["image"], "id": runtime["Image"]}
compose_path.write_text(yaml.safe_dump(compose, sort_keys=False))
compose_path.chmod(0o600)
subprocess.run(["docker", "compose", "--env-file", str(root / ".env"), "-f", str(compose_path), "config", "--quiet"], check=True)
repositories = {name: subprocess.check_output(["git", "-C", str(root.parent / relative), "rev-parse", "HEAD"], text=True).strip()
                for name, relative in {"testbed": "oai-free5gc-testbed", "OAI": "openairinterface5g-build", "AMF": "ue-policy-work/amf"}.items()}
summary = {"run_id": "s2-live-auto", "ues": 6, "sessions": 11, "flows": 11, "initial_pdus": 6,
           "subscription_revoke_grant": "verified", "original_authorization_ursp_rfsp": "preserved",
           "evidence": str(directory), "subscription_evidence": str(subscription_dir), "snapshot_id": snapshot["snapshot_id"],
           "soak_evidence": str(soak_dir), "policy_evidence": str(policy_dir), "agents_evidence": str(agents_dir),
           "urr_reporting": {"period_seconds": 10, "volume_threshold_bytes": 0}}
(directory / "summary.json").write_text(json.dumps(summary, indent=2))
manifest = {**summary, "verified_at": stamp, "images": images, "repositories": repositories,
            "backup": migration["backup"], "compose_sha256": hashlib.sha256(compose_path.read_bytes()).hexdigest()}
(run / "ue-policy/deployment-dynamic-pdu.json").write_text(json.dumps(manifest, indent=2))
migration.update(stage="verified", evidence=str(directory), verified_at=stamp)
(run / "ue-policy/dynamic-live-migration.json").write_text(json.dumps(migration, indent=2))
RunStore(run).recover(summary)
print(json.dumps(summary))
