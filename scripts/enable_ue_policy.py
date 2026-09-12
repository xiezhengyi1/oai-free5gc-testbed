"""Render the explicit NAS UE-policy profile into an already rendered run.

Run before starting the run. This does not change running containers.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml


def enable(run_dir: Path) -> None:
    token = os.environ["UE_POLICY_ADMIN_TOKEN"]
    if not token:
        raise ValueError("UE_POLICY_ADMIN_TOKEN must be nonempty")
    generated = run_dir / "generated"
    path = generated / "compose.yaml"
    compose = yaml.safe_load(path.read_text())
    scenario = yaml.safe_load((run_dir / "source-scenario.yaml").read_text())
    services = compose["services"]
    for nf in ("pcf", "amf"):
        services[f"free5gc-{nf}"]["image"] = f"free5gc/{nf}:v4.1.0-uepolicy"
    policy_dir = run_dir / "ue-policy"
    (policy_dir / "pcf").mkdir(parents=True, exist_ok=True)
    services["free5gc-pcf"]["environment"].update(
        UE_POLICY_STATE_DIR="/ue-policy", UE_POLICY_ADMIN_TOKEN=token
    )
    services["free5gc-pcf"]["volumes"].append("../ue-policy/pcf:/ue-policy")
    for service in ("action-gateway", "snapshot-builder"):
        services[service]["environment"]["UE_POLICY_ADMIN_TOKEN"] = token
    services["snapshot-builder"]["networks"]["sbi-net"] = {}
    for ue in scenario["ues"]:
        directory = policy_dir / ue["id"]
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o777)
        services[ue["container"]]["image"] = "oaisoftwarealliance/oai-nr-ue:2026.w35-uepolicy"
        for name in (ue["container"], ue["traffic_sidecar"]):
            services[name]["environment"]["OAI_UE_POLICY_DIR"] = "/ue-policy"
            services[name]["volumes"].append(f"../ue-policy/{ue['id']}:/ue-policy")
        services[ue["traffic_sidecar"]]["image"] = "oai-free5gc-testbed/traffic-sidecar:uepolicy"
    for gnb in scenario["ran"]["gnbs"]:
        services[gnb["container"]]["image"] = "oaisoftwarealliance/oai-gnb:2026.w35-uepolicy"
    services["action-gateway"]["image"] = "oai-free5gc-testbed/control:uepolicy"
    services["snapshot-builder"]["image"] = "oai-free5gc-testbed/control:uepolicy"
    path.write_text(yaml.safe_dump(compose, sort_keys=False))
    (policy_dir / "profile.json").write_text(
        json.dumps(
            {
                "mode": "nas_ue_policy",
                "upsc_scope": "one section per HPLMN",
                "rfsp_mode": "ngap_control_plane",
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    enable(parser.parse_args().run_dir.resolve(strict=True))
