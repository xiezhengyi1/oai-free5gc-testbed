from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FiveTuple(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_ip: str
    source_port: int
    destination_ip: str
    destination_port: int
    protocol: str


class TrafficProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    flow_id: str
    ue_id: str
    supi: str
    session_id: str
    interface: str
    service_instance_id: str
    five_tuple: FiveTuple
    rate_mbps: float = Field(gt=0)
    packet_size_bytes: int = Field(gt=0)
    sla: dict[str, Any]


def load_profiles(path: Path, ue_id: str) -> list[TrafficProfile]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("traffic profiles must be a list")
    profiles = [TrafficProfile.model_validate(item) for item in payload]
    selected = [item for item in profiles if item.ue_id == ue_id]
    if not selected:
        raise ValueError(f"no traffic profiles declared for {ue_id}")
    return selected
