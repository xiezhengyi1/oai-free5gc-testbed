"""Create an isolated one-UE/two-PDU test run; never touches the source run."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
from pathlib import Path

import yaml
from enable_ue_policy import enable

from testbed.rendering.compose_renderer import render_run


def render(source: Path, run_id: str, ue_id: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    scenario = yaml.safe_load(source.read_text())
    ue = next(row for row in scenario["ues"] if row["id"] == ue_id)
    if len(ue["sessions"]) != 2:
        raise ValueError("isolated profile requires exactly two configured PDU sessions")
    scenario["scenario_id"] = run_id
    scenario["ues"] = [ue]
    scenario["ran"]["gnbs"] = [
        row for row in scenario["ran"]["gnbs"] if row["id"] == ue["serving_gnb"]
    ]
    scenario["flows"] = [row for row in scenario["flows"] if row["ue_id"] == ue_id]
    service_ids = {row["service_instance_id"] for row in scenario["flows"]}
    scenario["services"] = [row for row in scenario["services"] if row["id"] in service_ids]
    dnns = {row["dnn"] for row in ue["sessions"]}
    scenario["core"]["upfs"] = [row for row in scenario["core"]["upfs"] if row["dnn"] in dnns]
    slice_ids = {row["slice_id"] for row in ue["sessions"]}
    scenario["slices"] = [row for row in scenario["slices"] if row["id"] in slice_ids]
    for row in scenario["slices"]:
        row["initial_state"] = "running"
    containers = {
        ue["container"],
        *(row["container"] for row in scenario["ran"]["gnbs"]),
        *(row["container"] for row in scenario["core"]["upfs"]),
        *(row["container"] for row in scenario["services"]),
    }
    scenario["resources"]["containers"] = {
        key: value
        for key, value in scenario["resources"]["containers"].items()
        if key in containers
    }
    scenario["resources"].pop("system_cpuset_cpus", None)
    for row in scenario["resources"]["containers"].values():
        row.pop("cpuset_cpus", None)
    renamed = {
        name: "p2-" + name
        for name in containers
        | {ue["traffic_sidecar"]}
        | {row["container"] for row in scenario["links"]}
    }

    def rewrite(value):
        if isinstance(value, dict):
            return {renamed.get(key, key): rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str):
            value = re.sub(r"^172\.(3[0-8])\.0\.", r"10.230.\1.", value)
            value = re.sub(r"^10\.(6[0-9])\.0\.", r"10.231.\1.", value)
            return renamed.get(value, value)
        return value

    scenario = rewrite(scenario)
    for item in scenario["networks"].values():
        item["bridge_name"] = "p2-" + item["bridge_name"]
    input_path = root / "artifacts" / f"{run_id}-scenario.yaml"
    if input_path.exists():
        raise FileExistsError(input_path)
    input_path.write_text(yaml.safe_dump(scenario, sort_keys=False))
    run_dir = render_run(root, input_path, run_id).root
    token = secrets.token_hex(32)
    os.environ["UE_POLICY_ADMIN_TOKEN"] = token
    enable(run_dir)
    path = run_dir / "generated" / "compose.yaml"
    compose = yaml.safe_load(path.read_text())
    for service in compose["services"].values():
        if not service["container_name"].startswith("p2-"):
            service["container_name"] = "p2-" + service["container_name"]
        if "ports" in service:
            service["ports"] = [
                f"127.0.0.1:{int(port.split(':')[0]) + 10000}:{port.split(':')[1]}"
                for port in service["ports"]
            ]
        service["logging"] = {"driver": "local", "options": {"max-size": "10m", "max-file": "2"}}
        service.setdefault("environment", {})["NO_PROXY"] = "*"
        service["environment"]["no_proxy"] = "*"
    api_key = secrets.token_hex(32)
    project_key = secrets.token_hex(32)
    db_password = secrets.token_hex(32)
    for name in ("action-gateway", "snapshot-builder"):
        compose["services"][name]["environment"]["MULTIAGENTS_DATABASE_URL"] = (
            f"postgresql://testbed:{db_password}@policy-postgres:5432/testbed"
        )
    compose["services"]["action-gateway"]["environment"].update(
        ACTION_GATEWAY_CONTAINER="p2-action-gateway",
        ACTION_GATEWAY_API_KEYS=f"multiagents:{api_key},project:{project_key}",
    )
    compose["services"]["policy-postgres"] = {
        "image": "pgvector/pgvector:pg16",
        "container_name": "p2-policy-postgres",
        "environment": {
            "POSTGRES_USER": "testbed",
            "POSTGRES_PASSWORD": db_password,
            "POSTGRES_DB": "testbed",
        },
        "volumes": [
            "../ue-policy/databases/postgres:/var/lib/postgresql/data",
            "./policy-init.sql:/docker-entrypoint-initdb.d/01-policy.sql:ro",
        ],
        "networks": {"control-net": {}},
    }
    compose["services"]["mongodb"]["volumes"] = [
        "../ue-policy/databases/mongo:/data/db",
        "../ue-policy/databases/mongo-config:/data/configdb",
    ]
    compose["services"]["prometheus"]["volumes"][1] = (
        "../ue-policy/databases/prometheus:/prometheus"
    )
    compose["services"]["cadvisor"]["command"] = [
        "--docker_only=true",
        "--enable_metrics=cpu,memory",
        "--store_container_labels=false",
    ]
    compose["services"]["cadvisor"]["healthcheck"] = {
        "test": [
            "CMD",
            "wget",
            "-Y",
            "off",
            "-q",
            "-O",
            "/dev/null",
            "http://127.0.0.1:8080/healthz",
        ],
        "interval": "30s",
        "timeout": "3s",
    }
    (run_dir / "generated" / "policy-init.sql").write_text(
        "CREATE TABLE network_graph_snapshot (snapshot_id text PRIMARY KEY, "
        "base_network_snapshot_id text, trigger_event text, graph_summary jsonb, "
        "created_at timestamptz);\n"
    )
    path.write_text(yaml.safe_dump(compose, sort_keys=False))
    credentials = run_dir / "ue-policy" / "credentials.json"
    credentials.write_text(
        json.dumps({"admin_token": token, "multiagents_key": api_key, "project_key": project_key})
    )
    credentials.chmod(0o600)
    print(run_dir)
    return run_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ue", default="ue-5")
    args = parser.parse_args()
    render(args.source, args.run_id, args.ue)
