from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class FlowAllocationStore:
    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "flow-allocations.json"

    def list(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("flow allocations must be an object keyed by flow ID")
        return payload

    def update(
        self,
        flow_id: str,
        allocated_bandwidth_ul_mbps: float,
        allocated_bandwidth_dl_mbps: float,
        source_action_id: str,
    ) -> dict[str, Any]:
        allocations = self.list()
        state = {
            "flow_id": flow_id,
            "allocated_bandwidth_ul_mbps": allocated_bandwidth_ul_mbps,
            "allocated_bandwidth_dl_mbps": allocated_bandwidth_dl_mbps,
            "source_action_id": source_action_id,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        allocations[flow_id] = state
        self.path.write_text(
            json.dumps(allocations, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return state
