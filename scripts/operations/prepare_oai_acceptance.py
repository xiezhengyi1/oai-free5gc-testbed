"""Prepare a fresh, serial two-UE policy acceptance scene after stopping the old scene."""

from __future__ import annotations

import argparse
import copy
import json
import os
import secrets
import shlex
import subprocess
from pathlib import Path

import yaml

from testbed.artifacts.manifest_writer import write_manifest
from testbed.orchestration.host_profile import HostProfile
from testbed.rendering.compose_renderer import render_run, set_generated_permissions
from testbed.scenario.compiler import compile_scenario
from testbed.scenario.loader import load_scenario

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "oai-acceptance-20261028-1"


def main():
    global RUN_ID
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--runtime-revision", default="oai-acceptance-20261028")
    args = parser.parse_args()
    from testbed.scenario.ids import validate_run_id

    RUN_ID = validate_run_id(args.run_id)
    running = subprocess.check_output(["docker", "ps", "--format", "{{.Names}}"], text=True)
    if any(n.startswith(("oai-gnb-", "oai-nrue-")) for n in running.splitlines()):
        raise RuntimeError("stop and archive the previous scene first")
    evidence = ROOT / "experiments/oai-acceptance-20261028"
    assert (evidence / "evidence/previous-run-stopped.json").exists()
    run = ROOT / "artifacts/runs" / RUN_ID
    if run.exists():
        raise FileExistsError("acceptance run exists; preserve it and use its recorded lifecycle")
    old = ROOT / "artifacts/runs/merged-recovery-protocols-20261028-1"
    scenario = yaml.safe_load((old / "source-scenario.yaml").read_text())
    scenario["scenario_id"] = "recovered-oai-policy-acceptance"
    for slice_ in scenario["slices"]:
        slice_["capacity"].update(
            total_bandwidth_ul_mbps=80,
            total_bandwidth_dl_mbps=80,
            guaranteed_bandwidth_ul_mbps=60,
            guaranteed_bandwidth_dl_mbps=60,
        )
    second = copy.deepcopy(scenario["slices"][0])
    second.update(id="urllc", sst=2)
    scenario["slices"].append(second)
    upf = copy.deepcopy(scenario["core"]["upfs"][0])
    upf.update(
        id="alternate-upf",
        container="free5gc-upf-alternate",
        n3_ip="172.32.0.31",
        n4_ip="172.33.0.31",
        n6_ip="172.34.0.31",
        dnn="mecalt",
        ue_pool="10.61.0.0/24",
    )
    scenario["core"]["upfs"].append(upf)
    ue = scenario["ues"][0]
    ue["supi"] = "imsi-208930000180001"
    ue["sessions"].append(dict(id="alternate-session", dnn="mecalt", slice_id="urllc"))
    protected = copy.deepcopy(ue)
    protected.update(
        id="ue-2",
        container="oai-nrue-2",
        traffic_sidecar="traffic-sidecar-ue-2",
        supi="imsi-208930000180002",
    )
    scenario["ues"].append(protected)
    flows = []
    for item in scenario["flows"]:
        item["rate_mbps"] = 2 if item["protocol"] == "udp" else 1
        item["sla"].update(
            bandwidth_ul_mbps=item["rate_mbps"],
            bandwidth_dl_mbps=item["rate_mbps"],
            guaranteed_bandwidth_ul_mbps=0.1,
            guaranteed_bandwidth_dl_mbps=0.1,
        )
        item["allocation"].update(
            allocated_bandwidth_ul_mbps=item["rate_mbps"],
            allocated_bandwidth_dl_mbps=item["rate_mbps"],
        )
        flows.append(item)
        other = copy.deepcopy(item)
        other.update(id="protected-" + item["id"], ue_id="ue-2", src_port=item["src_port"] + 100)
        flows.append(other)
    scenario["flows"] = flows
    limits = scenario["resources"]["containers"]
    limits["oai-nrue-2"] = copy.deepcopy(limits["oai-nrue-1"])
    limits["free5gc-upf-alternate"] = copy.deepcopy(limits["free5gc-upf-edge"])
    scenario_file = ROOT / "scenarios/validation/ibn3090-oai-acceptance.yaml"
    scenario_file.write_text(yaml.safe_dump(scenario, sort_keys=False))
    profile = json.loads((evidence / "evidence/previous-host-profile.json").read_text())
    replacements = {
        "oaisoftwarealliance/oai-gnb:2026.w35": "mergedsystem/oai-gnb:recovered-source-20261028",
        "oaisoftwarealliance/oai-nr-ue:2026.w35": "mergedsystem/oai-nr-ue:recovered-source-20261028",
        "oai-free5gc-testbed/control:0.1.0": f"mergedsystem/testbed-control:{args.runtime_revision}",
        "oai-free5gc-testbed/traffic-sidecar:0.1.0": f"mergedsystem/testbed-traffic:{args.runtime_revision}",
        "oai-free5gc-testbed/app:0.1.0": f"mergedsystem/testbed-app:{args.runtime_revision}",
    }
    profile["images"].update(replacements)
    for image in replacements.values():
        inspected = json.loads(subprocess.check_output(["docker", "image", "inspect", image]))[0]
        profile["digests"][image] = inspected["Id"]
    HostProfile.model_validate(profile)
    profile_file = ROOT / "deployment/hosts/ibn3090/oai-acceptance.json"
    profile_file.write_text(json.dumps(profile, indent=2) + "\n")
    values = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = shlex.split(value)[0]
    values.update(
        TESTBED_RUN_ID=RUN_ID,
        TESTBED_HOST_PROFILE=str(profile_file),
        UE_POLICY_ADMIN_TOKEN=secrets.token_urlsafe(32),
    )
    temp = ROOT / "configs/hosts/acceptance-new.env"
    with temp.open("x") as stream:
        stream.write("".join(k + "=" + shlex.quote(v) + "\n" for k, v in values.items()))
    temp.chmod(0o600)
    os.replace(temp, ROOT / ".env")
    os.environ.update(values)
    layout = render_run(ROOT, scenario_file, RUN_ID)
    compose_file = run / "generated/compose.yaml"
    compose = yaml.safe_load(compose_file.read_text())
    services = compose["services"]
    policy = run / "ue-policy"
    for name in ["pcf", *(u["id"] for u in scenario["ues"])]:
        (policy / name).mkdir(parents=True)
    services["free5gc-pcf"]["environment"].update(
        UE_POLICY_STATE_DIR="/ue-policy", UE_POLICY_ADMIN_TOKEN=values["UE_POLICY_ADMIN_TOKEN"]
    )
    services["free5gc-pcf"]["volumes"].append("../ue-policy/pcf:/ue-policy")
    for name in ["action-gateway", "snapshot-builder"]:
        services[name]["environment"]["UE_POLICY_ADMIN_TOKEN"] = values["UE_POLICY_ADMIN_TOKEN"]
    services["snapshot-builder"]["networks"]["sbi-net"] = {}
    for ue in scenario["ues"]:
        for name in [ue["container"], ue["traffic_sidecar"]]:
            services[name]["environment"]["OAI_UE_POLICY_DIR"] = "/ue-policy"
            services[name]["volumes"].append("../ue-policy/" + ue["id"] + ":/ue-policy")
        services[ue["traffic_sidecar"]]["volumes"].append(
            "../current-state.json:/ue-policy/current-state.json:ro"
        )
    compose_file.write_text(yaml.safe_dump(compose, sort_keys=False))
    (policy / "profile.json").write_text(
        json.dumps(dict(mode="nas_ue_policy", rfsp_mode="ngap_control_plane"))
    )
    smf = run / "generated/free5gc-config/smfcfg.yaml"
    config = yaml.safe_load(smf.read_text())
    config["configuration"].update(urrThreshold=0, urrPeriod=10)
    smf.write_text(yaml.safe_dump(config, sort_keys=False))
    set_generated_permissions(layout)
    checked = load_scenario(scenario_file)
    write_manifest(ROOT, layout, checked, compile_scenario(checked, scenario_file, RUN_ID))
    native = json.loads((ROOT / "docs/oai-rebuild-20261028.json").read_text())
    (run / "oai-recovery-provenance.json").write_text(
        json.dumps(
            dict(
                source=native["historical_source"],
                images=native["candidate_images"],
                patch_chain=native["patch_chain"],
            ),
            indent=2,
        )
    )
    helper = "import os;from pathlib import Path;[(os.chown(p,0,0),p.chmod(0o755)) for p in Path('/run/ue-policy').iterdir() if p.is_dir()]"
    subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "CHOWN",
            "--cap-add",
            "DAC_OVERRIDE",
            "-v",
            str(run) + ":/run",
            "--entrypoint",
            "python",
            replacements["oai-free5gc-testbed/control:0.1.0"],
            "-c",
            helper,
        ],
        check=True,
    )
    print(
        json.dumps(
            dict(run_id=RUN_ID, ues=2, pdu_sessions=4, upfs=2, flows=6, profile=str(profile_file))
        )
    )


if __name__ == "__main__":
    main()
