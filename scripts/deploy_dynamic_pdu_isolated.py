"""Deploy dynamic PDU only to the explicitly named existing phase2-isolated lab."""
import json
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/phase2-isolated"
path = run / "generated/compose.yaml"
compose = yaml.safe_load(path.read_text())
assert compose["name"] == "testbed-phase2-isolated"
assert all(row["container_name"].startswith("p2-") for row in compose["services"].values())
service_keys = {row["container_name"].removeprefix("p2-"): key for key, row in compose["services"].items()}
backup = run / "ue-policy/dynamic-backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
backup.mkdir(parents=True, mode=0o700)
shutil.copy2(path, backup / "compose.yaml")
smf_path = run / "generated/free5gc-config/smfcfg.yaml"
shutil.copy2(smf_path, backup / "smfcfg.yaml")
subprocess.run(["docker", "cp", "p2-free5gc-pcf:/ue-policy/associations.json", str(backup / "associations.json")], check=True)
subprocess.run(["docker", "exec", "p2-mongodb", "mongodump", "--db", "free5gc", "--archive=/tmp/dynamic-before.archive"], check=True, capture_output=True)
subprocess.run(["docker", "cp", "p2-mongodb:/tmp/dynamic-before.archive", str(backup / "free5gc.archive")], check=True)
dc = ["docker", "compose", "--env-file", str(root / ".env"), "-f", str(path)]


def execute(*args):
    subprocess.run([*dc, *(service_keys[arg] if arg in service_keys else arg for arg in args)], check=True)


execute("stop", "action-gateway", "snapshot-builder", "session-tracker", "traffic-sidecar-ue-5")
execute("stop", "oai-nrue-5")
execute("stop", "oai-gnb-2", "free5gc-amf", "free5gc-smf", "free5gc-pcf", "free5gc-upf-slice-1", "free5gc-upf-slice-2")
smf_config = yaml.safe_load(smf_path.read_text())
# Video traffic overwhelms CHF at the sample configuration's 1000-byte threshold.
# Keep periodic accounting at 10 seconds, plus volume reports at 64 MiB.
smf_config["configuration"]["urrThreshold"] = 64 * 1024 * 1024
smf_config["configuration"]["urrPeriod"] = 10
smf_path.write_text(yaml.safe_dump(smf_config, sort_keys=False))
compose["services"][service_keys["free5gc-pcf"]]["image"] = "free5gc/pcf:v4.1.0-uepolicy"
compose["services"][service_keys["free5gc-amf"]]["image"] = "free5gc/amf:v4.1.0-dynamic-pdu"
compose["services"][service_keys["free5gc-smf"]]["logging"] = {"driver": "local", "options": {"max-size": "200m", "max-file": "2"}}
compose["services"][service_keys["oai-nrue-5"]]["image"] = "oaisoftwarealliance/oai-nr-ue:2026.w35-dynamic-pdu"
compose["services"][service_keys["oai-nrue-5"]]["environment"]["OAI_UE_DYNAMIC_PDU"] = "1"
for service in ("action-gateway", "snapshot-builder", "session-tracker"):
    compose["services"][service_keys[service]]["image"] = "oai-free5gc-testbed/control:dynamic-pdu"
compose["services"][service_keys["traffic-sidecar-ue-5"]]["image"] = "oai-free5gc-testbed/traffic-sidecar:dynamic-pdu"
path.write_text(yaml.safe_dump(compose, sort_keys=False))
(run / "ue-policy/dynamic-pdu.json").write_text(json.dumps({"version": 1, "mode": "nas_dynamic_pdu", "backup": str(backup)}))
execute("config", "--quiet")
execute("run", "--rm", "--no-deps", "--entrypoint", "python", "action-gateway", "-m", "testbed.orchestration.ue_policy_storage")
execute("up", "-d", "--no-deps", "free5gc-upf-slice-1", "free5gc-upf-slice-2", "free5gc-pcf", "free5gc-amf", "free5gc-smf", "oai-gnb-2")
started_at = time.time()
execute("up", "-d", "--no-deps", "oai-nrue-5")
state_path = run / "ue-policy/ue-5/208930000000009.policy.state.json"
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    if state_path.exists() and state_path.stat().st_mtime > started_at:
        state = json.loads(state_path.read_text())
        if any(row["active"] for row in state["sessions"]):
            assert sum(row["active"] for row in state["sessions"]) == 1
            (backup / "before-demand-nas-state.json").write_text(json.dumps(state, indent=2))
            print("One initial PDU active; no secondary PDU established before traffic", flush=True)
            break
    time.sleep(2)
else:
    raise TimeoutError("initial PDU did not establish")
execute("run", "--rm", "--no-deps", "--entrypoint", "python", "action-gateway", "-m", "testbed.orchestration.ue_policy_bootstrap")
execute("up", "-d", "--no-deps", "traffic-sidecar-ue-5", "session-tracker", "snapshot-builder", "action-gateway")
print(json.dumps({"run": "phase2-isolated", "backup": str(backup), "verification": "required"}))
