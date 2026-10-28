"""Migrate the explicitly prepared live run, preserving its DB and old Prometheus volume."""

import argparse
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument(
    "--resume-chain", action="store_true", help="reuse the already copied Prometheus database"
)
args = parser.parse_args()
run = root / "artifacts/runs/s2-live-auto"
path = run / "generated/compose.yaml"
compose = yaml.safe_load(path.read_text())
scenario = yaml.safe_load((run / "source-scenario.yaml").read_text())
migration = json.loads((run / "ue-policy/migration.json").read_text())
assert compose["name"] == "testbed-s2-live-auto"
assert all(not row["container_name"].startswith("p2-") for row in compose["services"].values())
dc = ["docker", "compose", "--env-file", str(root / ".env"), "-f", str(path)]


def execute(*args):
    subprocess.run([*dc, *args], check=True)


def up(services):
    execute("up", "-d", "--no-deps", *services)


def inventory(name):
    return json.loads(subprocess.check_output(["docker", "inspect", name]))[0]


print("Stopping the live policy/RAN/UE chain; keeping MongoDB, webUI and NRF", flush=True)
execute(
    "stop",
    "action-gateway",
    "snapshot-builder",
    "session-tracker",
    *(ue["traffic_sidecar"] for ue in scenario["ues"]),
)
# UE deregistration must reach PCF before PCF/AMF stop, deleting old associations.
execute("stop", *(ue["container"] for ue in scenario["ues"]))
execute("stop", *(gnb["container"] for gnb in scenario["ran"]["gnbs"]))
execute(
    "stop",
    "free5gc-amf",
    "free5gc-smf",
    "free5gc-pcf",
    *(upf["container"] for upf in scenario["core"]["upfs"]),
)
execute("stop", "prometheus")
saved_containers = json.loads((Path(migration["backup"]) / "containers.json").read_text())
saved_prom = next(row for row in saved_containers if row["Name"] == "/prometheus")
old_prom = next(mount for mount in saved_prom["Mounts"] if mount["Destination"] == "/prometheus")
assert old_prom["Type"] == "volume"
destination = (run / "ue-policy/databases/prometheus").resolve()
assert destination.is_relative_to(run.resolve())
if args.resume_chain:
    assert destination.is_dir()
    assert (
        compose["services"]["prometheus"]["volumes"][1]
        == "../ue-policy/databases/prometheus:/prometheus"
    )
else:
    assert not destination.exists()
    destination.mkdir(parents=True)
    print("Copying stopped Prometheus data to root disk; retaining the original volume", flush=True)
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--user",
            "0",
            "--entrypoint",
            "sh",
            "-v",
            f"{old_prom['Name']}:/source:ro",
            "-v",
            f"{destination}:/target",
            "oai-free5gc-testbed/control:uepolicy",
            "-c",
            "cp -a /source/. /target/",
        ],
        check=True,
    )
compose["services"]["prometheus"]["volumes"][1] = "../ue-policy/databases/prometheus:/prometheus"
compose["services"]["cadvisor"]["command"] = [
    "--docker_only=true",
    "--enable_metrics=cpu,memory",
    "--store_container_labels=false",
]
compose["services"]["cadvisor"]["healthcheck"] = {
    "test": ["CMD", "wget", "-Y", "off", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/healthz"],
    "interval": "30s",
    "timeout": "3s",
}
path.write_text(yaml.safe_dump(compose, sort_keys=False))
execute(
    "run",
    "--rm",
    "--no-deps",
    "--entrypoint",
    "python",
    "action-gateway",
    "-m",
    "testbed.orchestration.ue_policy_storage",
)
up(
    [
        "free5gc-pcf",
        "free5gc-amf",
        "free5gc-smf",
        *(upf["container"] for upf in scenario["core"]["upfs"]),
    ]
)
up([gnb["container"] for gnb in scenario["ran"]["gnbs"]])
for gnb in scenario["ran"]["gnbs"]:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = inventory(gnb["container"])
        assert state["State"]["Running"], f"{gnb['container']} exited"
        logs = subprocess.check_output(
            ["docker", "logs", gnb["container"]], stderr=subprocess.STDOUT
        ).decode()
        if "Received NGSetupResponse" in logs:
            print(f"{gnb['id']}: NG setup complete", flush=True)
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"{gnb['id']}: NG setup timeout")
for ue in scenario["ues"]:
    up([ue["container"]])
    deadline = time.monotonic() + 120
    expected = {"oaitun_ue1"} | {
        f"oaitun_ue1p{index}" for index in range(2, len(ue["sessions"]) + 1)
    }
    while time.monotonic() < deadline:
        assert inventory(ue["container"])["State"]["Running"], f"{ue['container']} exited"
        rows = json.loads(
            subprocess.check_output(["docker", "exec", ue["container"], "ip", "-j", "addr"])
        )
        active = {
            row["ifname"]
            for row in rows
            if any(address["family"] == "inet" for address in row["addr_info"])
        }
        if expected <= active:
            print(f"{ue['id']}: {len(expected)} PDU interfaces ready", flush=True)
            break
        time.sleep(2)
    else:
        raise TimeoutError(f"{ue['id']}: PDU setup timeout")
execute(
    "run",
    "--rm",
    "--no-deps",
    "--entrypoint",
    "python",
    "action-gateway",
    "-m",
    "testbed.orchestration.ue_policy_bootstrap",
)
up([ue["traffic_sidecar"] for ue in scenario["ues"]])
up(["session-tracker", "prometheus", "cadvisor", "ran-exporter"])
up(["snapshot-builder", "action-gateway"])
migration.update(
    deployed_at=datetime.now(UTC).isoformat(),
    old_prometheus_volume=old_prom["Name"],
    new_prometheus_path=str(destination),
)
(run / "ue-policy/migration.json").write_text(json.dumps(migration, indent=2))
print("Live images deployed; end-to-end verification remains required", flush=True)
