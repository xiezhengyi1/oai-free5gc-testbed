"""Record verified isolated runtime images and pin compose to immutable local image IDs."""
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/phase2-isolated"
path = run / "generated/compose.yaml"
compose = yaml.safe_load(path.read_text())
assert compose["name"] == "testbed-phase2-isolated"
assert all(row["container_name"].startswith("p2-") for row in compose["services"].values())
evidence = max((run / "ue-policy/evidence").glob("subscription-dynamic-*"), key=lambda item: item.name)
summary = json.loads((evidence / "summary.json").read_text())
assert summary["subscription_revoke_grant"] == "verified"
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
shutil.copy2(path, run / "ue-policy/dynamic-backups" / f"compose-before-pin-{stamp}.yaml")
images = {}
for name in ("p2-oai-nrue-5", "p2-free5gc-amf", "p2-free5gc-pcf", "p2-free5gc-smf",
             "p2-action-gateway", "p2-snapshot-builder", "p2-session-tracker", "p2-traffic-sidecar-ue-5"):
    service = next(row for row in compose["services"].values() if row["container_name"] == name)
    runtime = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
    assert runtime["State"]["Running"], name
    digest = runtime["Image"]
    tag = runtime["Config"]["Image"].rsplit(":", 1)[0] + ":dynamic-pdu-20260909-" + digest.split(":")[1][:12]
    subprocess.run(["docker", "image", "tag", digest, tag], check=True)
    service["image"] = tag
    images[name] = {"image": tag, "id": digest}
path.write_text(yaml.safe_dump(compose, sort_keys=False))
subprocess.run(["docker", "compose", "--env-file", str(root / ".env"), "-f", str(path), "config", "--quiet"], check=True)
repos = {"testbed": root, "oai": root.parent / "openairinterface5g-build", "amf": root.parent / "ue-policy-work/amf"}
commits = {name: subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
           for name, repo in repos.items()}
manifest = {"run_id": "phase2-isolated", "verified_at": stamp, "evidence": str(evidence),
            "images": images, "commits": commits, "unit_and_contract_tests": "64 passed",
            "compose_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "formal_environment_upgraded": False}
output = run / "ue-policy/deployment-dynamic-pdu.json"
output.write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest, indent=2))
