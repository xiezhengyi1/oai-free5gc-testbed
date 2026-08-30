from __future__ import annotations

import json
from pathlib import Path

from testbed.scenario.schema import Scenario


def render_traffic_profiles(scenario: Scenario, destination: Path) -> None:
    services = {item.id: item for item in scenario.services}
    ues = {item.id: item for item in scenario.ues}
    payload = []
    for flow in scenario.flows:
        service = services[flow.service_instance_id]
        ue = ues[flow.ue_id]
        session_index = [item.id for item in ue.sessions].index(flow.session_id) + 1
        payload.append(
            {
                "flow_id": flow.id,
                "ue_id": flow.ue_id,
                "supi": ue.supi,
                "session_id": flow.session_id,
                "interface": f"oaitun_ue{session_index}",
                "service_instance_id": service.id,
                "five_tuple": {
                    "source_ip": "assigned-after-pdu-session",
                    "source_port": flow.src_port,
                    "destination_ip": service.ip,
                    "destination_port": flow.dst_port,
                    "protocol": flow.protocol,
                },
                "rate_mbps": flow.rate_mbps,
                "packet_size_bytes": flow.packet_size_bytes,
                "sla": flow.sla.model_dump(mode="json"),
            }
        )
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
