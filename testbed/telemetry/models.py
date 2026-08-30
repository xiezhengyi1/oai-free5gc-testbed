from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from testbed.scenario.schema import StrictModel


class UnifiedSnapshot(StrictModel):
    snapshot_id: str
    run_id: str
    observed_from: datetime
    observed_to: datetime
    topology: dict[str, Any]
    sessions: tuple[dict[str, Any], ...]
    flows: tuple[dict[str, Any], ...]
    ran_nodes: tuple[dict[str, Any], ...]
    core_nodes: tuple[dict[str, Any], ...]
    containers: tuple[dict[str, Any], ...]
    mec_sites: tuple[dict[str, Any], ...]
    mobility: tuple[dict[str, Any], ...]
    active_actions: tuple[dict[str, Any], ...]
    trigger_event: str = Field(min_length=1)
