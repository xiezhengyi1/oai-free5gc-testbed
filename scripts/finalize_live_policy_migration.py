"""Pin the verified live images and save a credential-free deployment manifest."""
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/s2-live-auto"
assert not (run / "ue-policy/deployment-manifest.json").exists(), "live migration is already finalized"
state = json.loads((run / "current-state.json").read_text())
assert state["phase"] == "RUNNING" and state["evidence"]["ursp_roundtrip"] == "verified"
path = run / "generated/compose.yaml"
compose = yaml.safe_load(path.read_text())
manifest = {"verified_at": state["observed_at"], "finalized_at": datetime.now(UTC).isoformat(),
            "evidence": state["evidence"], "images": {}, "repositories": {}}
for service, spec in compose["services"].items():
    if "uepolicy" not in spec["image"]:
        continue
    container = json.loads(subprocess.check_output(["docker", "inspect", spec["container_name"]]))[0]
    assert container["State"]["Running"], service
    image_id = container["Image"]
    repository = spec["image"].rsplit(":", 1)[0]
    tag = f"{repository}:s2-live-20260909-{image_id.split(':')[1][:12]}"
    subprocess.run(["docker", "tag", image_id, tag], check=True)
    spec["image"] = tag
    manifest["images"][service] = {"tag": tag, "id": image_id}
for name, relative in {"testbed": ".", "Multiagents": "../Multiagents", "OAI": "../openairinterface5g-build",
                       "PCF": "../ue-policy-work/pcf", "AMF": "../ue-policy-work/amf", "NAS": "../ue-policy-work/nas"}.items():
    manifest["repositories"][name] = subprocess.check_output(["git", "-C", str(root / relative), "rev-parse", "HEAD"], text=True).strip()
path.write_text(yaml.safe_dump(compose, sort_keys=False))
subprocess.run(["docker", "compose", "--env-file", str(root / ".env"), "-f", str(path), "config", "--quiet"], check=True)
(run / "ue-policy/deployment-manifest.json").write_text(json.dumps(manifest, indent=2))
print(json.dumps({"pinned_services": len(manifest["images"]), "manifest": str(run / "ue-policy/deployment-manifest.json")}))
