from __future__ import annotations

import json
from pathlib import Path

from testbed.traffic.profiles import TrafficProfile


def write_registry(path: Path, profiles: list[TrafficProfile]) -> None:
    records = [
        {
            "flow_id": item.flow_id,
            "supi": item.supi,
            "ue_id": item.ue_id,
            "session_id": item.session_id,
            "service_instance_id": item.service_instance_id,
            "interface": item.interface,
            "five_tuple": item.five_tuple.model_dump(mode="json"),
        }
        for item in profiles
    ]
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
