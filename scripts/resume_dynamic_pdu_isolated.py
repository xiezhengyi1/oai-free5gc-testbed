"""Explicitly resume an interrupted isolated deployment after repairing initial connectivity."""
import json
import subprocess
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/phase2-isolated"
compose_path = run / "generated/compose.yaml"
compose = yaml.safe_load(compose_path.read_text())
assert compose["name"] == "testbed-phase2-isolated"
assert all(row["container_name"].startswith("p2-") for row in compose["services"].values())
keys = {row["container_name"]: key for key, row in compose["services"].items()}
state = json.loads((run / "ue-policy/ue-5/208930000000009.policy.state.json").read_text())
assert sum(row["active"] for row in state["sessions"]) == 1
assert not any(row["pending"] for row in state["sessions"])
ue = json.loads(subprocess.check_output(["docker", "inspect", "p2-oai-nrue-5"]))[0]
assert ue["State"]["Running"]
assert ue["State"]["Health"]["Status"] == "healthy"
marker = json.loads((run / "ue-policy/dynamic-pdu.json").read_text())
(Path(marker["backup"]) / "before-demand-nas-state.json").write_text(json.dumps(state, indent=2))
dc = ["docker", "compose", "--env-file", str(root / ".env"), "-f", str(compose_path)]
subprocess.run([*dc, "run", "--rm", "--no-deps", "--entrypoint", "python", keys["p2-action-gateway"],
                "-m", "testbed.orchestration.ue_policy_bootstrap"], check=True)
subprocess.run([*dc, "up", "-d", "--no-deps", *(keys[name] for name in
                ("p2-traffic-sidecar-ue-5", "p2-session-tracker", "p2-snapshot-builder", "p2-action-gateway"))], check=True)
print("Isolated deployment resumed; end-to-end verification is still required")
