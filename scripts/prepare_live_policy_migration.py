"""Checkpoint s2-live-auto, then prepare its tested policy image configuration."""

import json
import os
import secrets
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml
from enable_ue_policy import enable

os.umask(0o077)
root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/s2-live-auto"
assert not (run / "ue-policy").exists(), "migration has already been prepared"
compose_file = run / "generated/compose.yaml"
compose = yaml.safe_load(compose_file.read_text())
assert compose["name"] == "testbed-s2-live-auto"
scenario = yaml.safe_load((run / "source-scenario.yaml").read_text())
names = [row["container_name"] for row in compose["services"].values()]
assert not any(name.startswith("p2-") for name in names)
containers = json.loads(subprocess.check_output(["docker", "inspect", *names]))
runtime = {row["Name"].lstrip("/"): row for row in containers}
backup = run / "migration-backups" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
backup.mkdir(parents=True, mode=0o700)
shutil.copytree(run / "generated", backup / "generated")
shutil.copy2(root / ".env", backup / "compose.env")
for name in (
    "source-scenario.yaml",
    "compiled-scenario.json",
    "current-state.json",
    "state.jsonl",
    "slice-state.json",
    "slice-state.jsonl",
    "session-observations.json",
    "actions.jsonl",
    "receipts.jsonl",
):
    shutil.copy2(run / name, backup / name)
(backup / "containers.json").write_text(json.dumps(containers, indent=2))
with (backup / "free5gc.archive").open("wb") as archive:
    subprocess.run(
        ["docker", "exec", "mongodb", "mongodump", "--db", "free5gc", "--archive"],
        stdout=archive,
        check=True,
    )
for upf in scenario["core"]["upfs"]:
    with (backup / f"{upf['container']}.log").open("wb") as output:
        subprocess.run(
            ["docker", "logs", "--tail", "2000", upf["container"]],
            stdout=output,
            stderr=subprocess.STDOUT,
            check=True,
        )
# Freeze the exact running environment values, not a possibly changed shell/.env.
for service in compose["services"].values():
    actual = dict(
        item.split("=", 1) for item in runtime[service["container_name"]]["Config"]["Env"]
    )
    for key, value in service.get("environment", {}).items():
        if isinstance(value, str) and "${" in value:
            service["environment"][key] = actual[key]
compose_file.write_text(yaml.safe_dump(compose, sort_keys=False))
token = secrets.token_hex(32)
os.environ["UE_POLICY_ADMIN_TOKEN"] = token
enable(run)
compose = yaml.safe_load(compose_file.read_text())
changed = [
    "free5gc-pcf",
    "free5gc-amf",
    "free5gc-smf",
    "session-tracker",
    "snapshot-builder",
    "action-gateway",
]
changed += [ue["container"] for ue in scenario["ues"]]
changed += [ue["traffic_sidecar"] for ue in scenario["ues"]]
changed += [gnb["container"] for gnb in scenario["ran"]["gnbs"]]
changed += [upf["container"] for upf in scenario["core"]["upfs"]]
compose["services"]["session-tracker"]["image"] = "oai-free5gc-testbed/control:uepolicy"
for name in changed:
    service = compose["services"][name]
    service.setdefault("environment", {}).update(NO_PROXY="*", no_proxy="*")
    service["logging"] = {"driver": "local", "options": {"max-size": "20m", "max-file": "3"}}
compose_file.write_text(yaml.safe_dump(compose, sort_keys=False))
compose_file.chmod(0o600)
keys = dict(
    item.split(":", 1)
    for item in compose["services"]["action-gateway"]["environment"][
        "ACTION_GATEWAY_API_KEYS"
    ].split(",")
)
(run / "ue-policy/credentials.json").write_text(
    json.dumps(
        {
            "admin_token": token,
            "multiagents_key": keys["multiagents"],
            "project_key": keys["project"],
        }
    )
)
(run / "ue-policy/migration.json").write_text(
    json.dumps(
        {
            "backup": str(backup),
            "changed_services": changed,
            "prepared_at": datetime.now(UTC).isoformat(),
        },
        indent=2,
    )
)
subprocess.run(
    [
        "docker",
        "compose",
        "--env-file",
        str(root / ".env"),
        "-f",
        str(compose_file),
        "config",
        "--quiet",
    ],
    check=True,
)
print(
    json.dumps({"backup": str(backup), "prepared_services": changed, "containers_restarted": False})
)
