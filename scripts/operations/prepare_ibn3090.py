"""Prepare a new recovery run using retained, pinned images and a separate test database."""

from __future__ import annotations

import argparse
import copy
import json
import os
import secrets
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "merged-recovery-s1-20261027-1"


def call(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def configure_private_environment(run_id):
    env_file = ROOT / ".env"
    if env_file.exists():
        return
    inspected = json.loads(call(["docker", "inspect", "ibn3090-multiagents-postgres"]))[0]
    original = dict(row.split("=", 1) for row in inspected["Config"]["Env"] if "=" in row)
    admin = original.get("POSTGRES_USER", "postgres")
    database, role = "mergedsystem_testbed", "mergedsystem_testbed"
    query = [
        "docker",
        "exec",
        "-i",
        "ibn3090-multiagents-postgres",
        "psql",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        admin,
    ]
    if call(
        [*query, "-d", "postgres", "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{database}'"]
    ):
        raise RuntimeError(
            "test database already exists; recover its private configuration before reuse"
        )
    password = secrets.token_urlsafe(40)
    sql = f"CREATE ROLE {role} LOGIN PASSWORD '{password}';\nCREATE DATABASE {database} OWNER {role};\n"
    subprocess.run(
        [*query, "-d", "postgres"], input=sql, text=True, capture_output=True, check=True
    )
    schema = f"""SET ROLE {role};
CREATE TABLE network_graph_snapshot (
 snapshot_id TEXT PRIMARY KEY, base_network_snapshot_id TEXT,
 trigger_event TEXT NOT NULL, graph_summary JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL);
"""
    subprocess.run(
        [*query, "-d", database], input=schema, text=True, capture_output=True, check=True
    )
    project, multiagents = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    values = dict(
        MULTIAGENTS_DATABASE_URL=f"postgresql+psycopg://{role}:{quote(password)}@host.docker.internal:15434/{database}",
        ACTION_GATEWAY_API_KEYS=f"multiagents:{multiagents},project:{project}",
        TESTBED_API_KEY=multiagents,
        TESTBED_PROJECT_API_KEY=project,
        TESTBED_RUN_ID=run_id,
        TESTBED_BASE_URL="http://127.0.0.1:8081",
        TESTBED_GATEWAY_URL="http://127.0.0.1:8080",
        TESTBED_HOST_PROFILE=str(ROOT / "deployment/hosts/ibn3090/profile.json"),
    )
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write("".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items()))
    private = ROOT / "configs/hosts"
    private.mkdir(parents=True, exist_ok=True)
    (private / "ibn3090.env").symlink_to("../../.env")


def main():
    from testbed.scenario.ids import validate_run_id
    from testbed.scenario.schema import Scenario

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--protocols", action="store_true")
    parser.add_argument("--activate-run", action="store_true")
    args = parser.parse_args()
    args.run_id = validate_run_id(args.run_id)
    running = call(["docker", "ps", "--format", "{{.Names}}"])
    if any(name.startswith(("oai-gnb-", "oai-nrue-")) for name in running.splitlines()):
        raise RuntimeError("stop the current simulation before preparing a new run")
    from testbed.orchestration.host_profile import HostProfile

    replacements = {
        "oaisoftwarealliance/oai-gnb:2026.w35": "oai-free5gc-testbed/oai-gnb:lifecycle-drb-release-20261019",
        "oaisoftwarealliance/oai-nr-ue:2026.w35": "oai-free5gc-testbed/oai-nr-ue:lifecycle-dci-admission-20261019",
        "free5gc/amf:v4.1.0": "free5gc/amf:v4.1.0-uepolicy",
        "free5gc/pcf:v4.1.0": "free5gc/pcf:lifecycle-20261017",
        "free5gc/smf:v4.1.0": "free5gc/smf:lifecycle-sdf-20261017",
        "free5gc/upf:v4.1.0": "free5gc/upf:lifecycle-urr-period-20261018",
        "oai-free5gc-testbed/control:0.1.0": "mergedsystem/testbed-control:recovery-20261028",
        "oai-free5gc-testbed/traffic-sidecar:0.1.0": "mergedsystem/testbed-traffic:recovery-20261028",
        "oai-free5gc-testbed/app:0.1.0": "mergedsystem/testbed-app:recovery-20261028",
    }
    # The default lock contains unused historical aliases; only rendered template images are required.
    import re

    template_images = set()
    for p in (ROOT / "deployment/compose").glob("*.j2"):
        template_images.update(re.findall(r"image:\s*([^\s{]+)", p.read_text()))
    template_images = {x for x in template_images if "{{" not in x and not x.endswith("/")}
    selected = {replacements.get(x, x) for x in template_images}
    # free5gc's Jinja loop emits these role-specific images.
    selected.update("free5gc/" + role + ":v4.1.0" for role in ("ausf", "nssf", "udm", "udr", "nef"))
    selected.add(replacements["free5gc/pcf:v4.1.0"])
    digests = {}
    for image in sorted(selected):
        info = json.loads(call(["docker", "image", "inspect", image]))[0]
        digests[image] = (
            info["RepoDigests"][0].split("@", 1)[1] if info["RepoDigests"] else info["Id"]
        )
    profile = HostProfile(
        name="ibn3090",
        images=replacements,
        digests=digests,
        control_cpus=[0, 1, 2, 3, 16, 17, 18, 19],
        radio_cpus=list(range(4, 16)) + list(range(20, 32)),
    )
    (ROOT / "deployment/hosts/ibn3090/profile.json").write_text(
        profile.model_dump_json(indent=2) + "\n"
    )
    configure_private_environment(args.run_id)
    from initialize_database import initialize_database

    private_values = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            private_values[key] = shlex.split(value)[0]
    initialize_database(private_values["MULTIAGENTS_DATABASE_URL"])
    payload = yaml.safe_load((ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml").read_text())
    payload["scenario_id"] = "merged-recovery-single-ue"
    payload["sources"] = dict(
        oai=str(ROOT.parent / ".dependencies/oai-reference"),
        free5gc_compose=str(ROOT.parent / ".dependencies/free5gc-compose"),
    )
    if args.protocols:
        payload["scenario_id"] = "merged-recovery-three-protocols"
        payload["flows"][0]["udp_response_bytes"] = 1200
        for protocol, port, source_port in [("tcp", 5201, 41002), ("http", 8080, 41003)]:
            flow = copy.deepcopy(payload["flows"][0])
            flow.pop("udp_response_bytes")
            flow.update(
                id="inference-edge-" + protocol,
                protocol=protocol,
                src_port=source_port,
                dst_port=port,
                rate_mbps=1,
            )
            for name in ["bandwidth_ul_mbps", "bandwidth_dl_mbps"]:
                flow["sla"][name] = 1
            for name in ["guaranteed_bandwidth_ul_mbps", "guaranteed_bandwidth_dl_mbps"]:
                flow["sla"][name] = 0.5
            flow["allocation"] = dict(allocated_bandwidth_ul_mbps=1, allocated_bandwidth_dl_mbps=1)
            payload["flows"].append(flow)
    Scenario.model_validate(payload)
    if args.activate_run:
        lines = (ROOT / ".env").read_text().splitlines()
        lines = [
            "TESTBED_RUN_ID=" + shlex.quote(args.run_id)
            if line.startswith("TESTBED_RUN_ID=")
            else line
            for line in lines
        ]
        with tempfile.NamedTemporaryFile(
            mode="w", dir=ROOT / "configs/hosts", suffix=".env", delete=False
        ) as handle:
            handle.write("\n".join(lines) + "\n")
            temp = Path(handle.name)
        os.replace(temp, ROOT / ".env")
    filename = "ibn3090-protocols.yaml" if args.protocols else "ibn3090-recovery.yaml"
    path = ROOT / "scenarios/validation" / filename
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    print(
        json.dumps(
            dict(
                run_id=args.run_id,
                image_pins=len(digests),
                scenario=str(path),
                private_environment="ready",
            )
        )
    )


if __name__ == "__main__":
    main()
