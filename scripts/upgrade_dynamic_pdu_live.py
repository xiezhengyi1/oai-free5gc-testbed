"""Explicit stages for upgrading the existing live NAS-policy run; never touches p2 containers."""
import argparse
import json
import os
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import yaml

root = Path(__file__).resolve().parents[1]
run = root / "artifacts/runs/s2-live-auto"
path = run / "generated/compose.yaml"
compose = yaml.safe_load(path.read_text())
scenario = yaml.safe_load((run / "source-scenario.yaml").read_text())
assert compose["name"] == "testbed-s2-live-auto"
assert all(not row["container_name"].startswith("p2-") for row in compose["services"].values())
keys = {row["container_name"]: key for key, row in compose["services"].items()}
dc = ["docker", "compose", "--env-file", str(root / ".env"), "-f", str(path)]
marker = run / "ue-policy/dynamic-live-migration.json"


def execute(command, *names):
    subprocess.run([*dc, *command, *(keys[name] for name in names)], check=True)


def inspect(name):
    return json.loads(subprocess.check_output(["docker", "inspect", name]))[0]


def prepare():
    assert not marker.exists(), "already prepared; select the next explicit stage"
    os.umask(0o077)
    backup = run / "migration-backups" / datetime.now(UTC).strftime("dynamic-%Y%m%dT%H%M%SZ")
    backup.mkdir(mode=0o700)
    shutil.copytree(run / "generated", backup / "generated")
    for name in ("source-scenario.yaml", "compiled-scenario.json", "current-state.json", "session-observations.json"):
        shutil.copy2(run / name, backup / name)
    containers = [inspect(name) for name in keys]
    (backup / "containers.json").write_text(json.dumps(containers, indent=2))
    with (backup / "free5gc.archive").open("wb") as output:
        subprocess.run(["docker", "exec", "mongodb", "mongodump", "--db", "free5gc", "--archive"], stdout=output, check=True)
    subprocess.run(["docker", "cp", "free5gc-pcf:/ue-policy/associations.json", str(backup / "associations.json")], check=True)
    code = """
import json, os
from pathlib import Path
from testbed.scenario.loader import load_scenario
from testbed.adapters.free5gc.pcf_adapter import PcfAdapter
from testbed.adapters.free5gc.subscriber_adapter import SubscriberAdapter
s=load_scenario(Path(os.environ['RUN_DIR'])/'source-scenario.yaml')
p=PcfAdapter(); a=SubscriberAdapter('http://free5gc-webui:5000')
print(json.dumps({'policies':{u.supi:p.ue_policy(u.supi) for u in s.ues},
 'subscribers':{u.supi:a.get(u.supi,s.plmn.mcc+s.plmn.mnc) for u in s.ues}}))
"""
    state = json.loads(subprocess.check_output(["docker", "exec", "-e", "PYTHONPATH=/opt/testbed", "action-gateway", "python", "-c", code]))
    for supi, policy in state["policies"].items():
        assert len(policy["ue_policy_associations"]) == 1, supi
        assert policy["ue_policy_associations"][0]["status"] == "complete", supi
    (backup / "policy-subscriber-state.json").write_text(json.dumps(state, indent=2))
    marker.write_text(json.dumps({"backup": str(backup), "stage": "prepared"}, indent=2))
    # In-container paths are /run, not the host path. Keep the private copy on the same run mount.
    (run / "ue-policy/dynamic-live-before.json").write_text(json.dumps(state, indent=2))
    print(json.dumps({"backup": str(backup), "preserved_ues": len(state["policies"])}), flush=True)


def deploy():
    migration = json.loads(marker.read_text())
    execute(["stop"], "action-gateway", "snapshot-builder", "session-tracker", *(u["traffic_sidecar"] for u in scenario["ues"]))
    execute(["stop"], *(u["container"] for u in scenario["ues"]))
    execute(["stop"], *(g["container"] for g in scenario["ran"]["gnbs"]))
    execute(["stop"], "free5gc-amf", "free5gc-smf", "free5gc-pcf", *(u["container"] for u in scenario["core"]["upfs"]))
    execute(["stop"], "free5gc-chf")
    for name in ("action-gateway", "snapshot-builder", "session-tracker"):
        compose["services"][keys[name]]["image"] = "oai-free5gc-testbed/control:dynamic-live"
    compose["services"][keys["free5gc-amf"]]["image"] = "free5gc/amf:dynamic-pdu-20260909-9fb5b8206206"
    for ue in scenario["ues"]:
        service = compose["services"][keys[ue["container"]]]
        service["image"] = "oaisoftwarealliance/oai-nr-ue:dynamic-pdu-20260909-63cd82f0bfba"
        service["environment"]["OAI_UE_DYNAMIC_PDU"] = "1"
        compose["services"][keys[ue["traffic_sidecar"]]]["image"] = "oai-free5gc-testbed/traffic-sidecar:dynamic-pdu-20260909-743ef10573e9"
    smf_path = run / "generated/free5gc-config/smfcfg.yaml"
    config = yaml.safe_load(smf_path.read_text())
    # gtp5g tests nonzero volume thresholds before firing VOLTH. Keep periodic
    # measurement and charging; do not generate a packet-rate threshold storm.
    config["configuration"].update(urrThreshold=0, urrPeriod=10)
    smf_path.write_text(yaml.safe_dump(config, sort_keys=False))
    path.write_text(yaml.safe_dump(compose, sort_keys=False))
    path.chmod(0o600)
    (run / "ue-policy/dynamic-pdu.json").write_text(json.dumps({"version": 1, "mode": "nas_dynamic_pdu", "backup": migration["backup"]}))
    execute(["config", "--quiet"])
    subprocess.run([*dc, "run", "--rm", "--no-deps", "--entrypoint", "python", keys["action-gateway"], "-m", "testbed.orchestration.ue_policy_storage"], check=True)
    execute(["up", "-d", "--no-deps"], "free5gc-chf", "free5gc-pcf", "free5gc-amf", "free5gc-smf", *(u["container"] for u in scenario["core"]["upfs"]))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        for upf in scenario["core"]["upfs"]:
            assert inspect(upf["container"])["State"]["Running"], upf["container"]
        logs = subprocess.check_output(["docker", "logs", "--since", inspect("free5gc-smf")["State"]["StartedAt"], "free5gc-smf"], stderr=subprocess.STDOUT).decode()
        if all(f"UPF({u['n4_ip']}) setup association" in logs for u in scenario["core"]["upfs"]):
            break
        time.sleep(2)
    else:
        raise TimeoutError("live PFCP associations did not complete")
    execute(["up", "-d", "--no-deps"], *(g["container"] for g in scenario["ran"]["gnbs"]))
    migration["stage"] = "core_started"
    marker.write_text(json.dumps(migration, indent=2))


def ues():
    for ue in scenario["ues"]:
        execute(["up", "-d", "--no-deps"], ue["container"])
        deadline = time.monotonic() + 120
        state_path = run / "ue-policy" / ue["id"] / f"{ue['supi'].removeprefix('imsi-')}.policy.state.json"
        while time.monotonic() < deadline:
            runtime = inspect(ue["container"])
            assert runtime["State"]["Running"], ue["container"]
            started = datetime.fromisoformat(runtime["State"]["StartedAt"].replace("Z", "+00:00")).timestamp()
            if state_path.exists() and state_path.stat().st_mtime > started:
                state = json.loads(state_path.read_text())
                if sum(row["active"] for row in state["sessions"]) == 1:
                    print(f"{ue['id']}: initial PDU established", flush=True)
                    break
            time.sleep(2)
        else:
            raise TimeoutError(f"{ue['id']}: initial PDU missing")
    migration = json.loads(marker.read_text())
    states = {u["supi"]: json.loads((run / "ue-policy" / u["id"] / f"{u['supi'].removeprefix('imsi-')}.policy.state.json").read_text()) for u in scenario["ues"]}
    (Path(migration["backup"]) / "initial-only.json").write_text(json.dumps(states, indent=2))


def policies():
    code = """
import json
from pathlib import Path
from testbed.adapters.free5gc.pcf_adapter import PcfAdapter
from testbed.gateway.policy_rebind import rebind_policy
p=PcfAdapter()
previous=json.loads(Path('/run/ue-policy/dynamic-live-before.json').read_text())['policies']
for supi, state in previous.items():
 print(json.dumps({'supi':supi, **rebind_policy(p,supi,state,90,1)}),flush=True)
"""
    subprocess.run([*dc, "run", "--rm", "--no-deps", "--entrypoint", "python", keys["action-gateway"], "-c", code], check=True)


def traffic():
    execute(["up", "-d", "--no-deps"], *(u["traffic_sidecar"] for u in scenario["ues"]))
    execute(["up", "-d", "--no-deps"], "session-tracker", "snapshot-builder", "action-gateway", "ran-exporter")
    print("Live runtime upgraded; verification is still required", flush=True)


parser = argparse.ArgumentParser()
parser.add_argument("stage", choices=["prepare", "deploy", "ues", "policies", "traffic"])
globals()[parser.parse_args().stage]()
