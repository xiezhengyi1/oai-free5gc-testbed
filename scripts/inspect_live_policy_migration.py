"""Read-only, credential-free inventory of the exact live migration target."""

import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

run = Path(__file__).resolve().parents[1] / "artifacts/runs/s2-live-auto"
compose = yaml.safe_load((run / "generated/compose.yaml").read_text())
scenario = yaml.safe_load((run / "source-scenario.yaml").read_text())
print(
    json.dumps(
        {
            "run": str(run),
            "project": compose["name"],
            "ues": [
                {key: ue[key] for key in ("id", "supi", "container", "serving_gnb", "sessions")}
                for ue in scenario["ues"]
            ],
            "gnbs": scenario["ran"]["gnbs"],
            "flows": [
                {key: flow[key] for key in ("id", "ue_id", "session_id", "protocol")}
                for flow in scenario["flows"]
            ],
            "runtime": scenario["runtime"],
        },
        indent=2,
    )
)
for name in (
    "free5gc-pcf",
    "free5gc-amf",
    "free5gc-smf",
    "snapshot-builder",
    "action-gateway",
    "session-tracker",
    "prometheus",
    "mongodb",
):
    service = compose["services"][name]
    print(
        json.dumps(
            {
                "service": name,
                "image": service["image"],
                "volumes": service.get("volumes", []),
                "ports": service.get("ports", []),
                "networks": service["networks"],
                "command": service.get("command"),
                "environment_keys": list(service.get("environment", {})),
                "db_host": urlsplit(
                    service.get("environment", {}).get("MULTIAGENTS_DATABASE_URL", "")
                ).hostname,
            }
        )
    )
