from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

from testbed.state.models import RunState
from testbed.state.run_store import baseline_epoch
from testbed.traffic.profiles import TrafficProfile


def query_ue_route(profile: TrafficProfile, policy_dir: Path) -> dict | None:
    state = RunState.model_validate_json(
        (policy_dir / "current-state.json").read_text(encoding="utf-8")
    )
    protocol = {"udp": 17, "tcp": 6, "http": 6}[profile.five_tuple.protocol]
    path = policy_dir / f"{profile.supi.removeprefix('imsi-')}.policy.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect(str(path))
        client.sendall(
            (f"{profile.five_tuple.destination_ip} {protocol} "
             f"{profile.five_tuple.destination_port}\n").encode()
        )
        response = client.makefile("r").readline().split()
    if response[0] in {"NO_ROUTE", "PENDING", "FAILED"}:
        return None
    if len(response) != 6 or response[0] != "ROUTE":
        raise RuntimeError(f"UE policy query failed: {response}")
    return {
        "flow_id": profile.flow_id,
        "supi": profile.supi,
        "interface": response[1],
        "pdu_session_id": int(response[2]),
        "rule_precedence": int(response[3]),
        "upsc": int(response[4]),
        "pti": int(response[5]),
        "source": "oai_ue_nas_policy",
        "baseline_epoch": baseline_epoch(state.run_id, state.reset_generation),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def publish_route(policy_dir: Path, route: dict) -> None:
    destination = policy_dir / f"{route['flow_id']}.route.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(route), encoding="utf-8")
    temporary.replace(destination)
