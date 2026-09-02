from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from testbed.artifacts.metrics_exporter import export_metrics
from testbed.telemetry.models import UnifiedSnapshot


class SnapshotStore:
    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "snapshots.jsonl"

    def append(self, snapshot: UnifiedSnapshot) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(snapshot.model_dump_json() + "\n")
        export_metrics(self.path.parent, snapshot.model_dump(mode="json"))

    def get(self, snapshot_id: str) -> UnifiedSnapshot:
        for line in self.path.read_text(encoding="utf-8").splitlines():
            snapshot = UnifiedSnapshot.model_validate_json(line)
            if snapshot.snapshot_id == snapshot_id:
                return snapshot
        raise KeyError(snapshot_id)

    def latest(self) -> UnifiedSnapshot:
        lines = self.path.read_text(encoding="utf-8").splitlines()
        if not lines:
            raise LookupError("no snapshots have been written")
        return UnifiedSnapshot.model_validate_json(lines[-1])


def graph_summary(snapshot: UnifiedSnapshot) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    metrics: list[dict[str, Any]] = []
    for flow in snapshot.flows:
        supi = flow["supi"]
        app_key = f"app:{supi}:{flow['app_id']}"
        flow_key = f"flow:{supi}:{flow['app_id']}:{flow['flow_id']}"
        ue_key = f"ue:{supi}"
        if not any(item["node_key"] == ue_key for item in nodes):
            nodes.append(
                {"node_key": ue_key, "node_type": "ue", "label": supi, "properties": {"supi": supi}}
            )
        if not any(item["node_key"] == app_key for item in nodes):
            nodes.append(
                {
                    "node_key": app_key,
                    "node_type": "app",
                    "label": flow["app_name"],
                    "properties": {"id": flow["app_id"], "name": flow["app_name"], "supi": supi},
                }
            )
            edges.append(
                {
                    "edge_key": f"{ue_key}->{app_key}",
                    "edge_type": "owns",
                    "source_key": ue_key,
                    "target_key": app_key,
                    "properties": {},
                }
            )
        nodes.append(
            {
                "node_key": flow_key,
                "node_type": "flow",
                "label": flow["flow_id"],
                "properties": flow,
            }
        )
        edges.append(
            {
                "edge_key": f"{app_key}->{flow_key}",
                "edge_type": "contains_flow",
                "source_key": app_key,
                "target_key": flow_key,
                "properties": {},
            }
        )
        snssai = flow["session"]["snssai"]
        edges.append(
            {
                "edge_key": f"{flow_key}->slice:{snssai}",
                "edge_type": "served_by_slice",
                "source_key": flow_key,
                "target_key": f"slice:{snssai}",
                "properties": {},
            }
        )
        for section in ("telemetry", "ran", "session"):
            for name, value in flow.get(section, {}).items():
                if isinstance(value, (int, float)):
                    metrics.append(
                        {
                            "owner_type": "node",
                            "owner_key": flow_key,
                            "metric_name": f"{section}.{name}",
                            "metric_value": value,
                            "observed_at": snapshot.observed_to.isoformat(),
                        }
                    )
    slice_ids = {flow["session"]["snssai"] for flow in snapshot.flows}
    slice_state_by_snssai = {item["snssai"]: item for item in snapshot.slice_states}
    for snssai in slice_ids:
        slice_state = slice_state_by_snssai[snssai]
        nodes.append(
            {
                "node_key": f"slice:{snssai}",
                "node_type": "slice",
                "label": snssai,
                "properties": {
                    "snssai": snssai,
                    "sst": int(snssai[:2]),
                    "sd": snssai[2:],
                    "slice_id": slice_state["slice_id"],
                    "lifecycle_state": slice_state["phase"],
                },
            }
        )
    for node in snapshot.ran_nodes:
        nodes.append(
            {
                "node_key": f"ran_node:{node['id']}",
                "node_type": "ran_node",
                "label": node["id"],
                "properties": node,
            }
        )
    for node in snapshot.core_nodes:
        nodes.append(
            {
                "node_key": f"core_node:{node['id']}",
                "node_type": "core_node",
                "label": node["id"],
                "properties": node,
            }
        )
    return {
        "snapshot_id": snapshot.snapshot_id,
        "run_id": snapshot.run_id,
        "trigger_event": snapshot.trigger_event,
        "observed_from": snapshot.observed_from.isoformat(),
        "observed_to": snapshot.observed_to.isoformat(),
        "nodes": nodes,
        "edges": edges,
        "metrics": metrics,
        "testbed_snapshot": snapshot.model_dump(mode="json"),
    }


class PostgresGraphWriter:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(
            database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        )

    def write(self, snapshot: UnifiedSnapshot) -> None:
        summary = graph_summary(snapshot)
        statement = text(
            """
            INSERT INTO network_graph_snapshot
                (snapshot_id, base_network_snapshot_id, trigger_event, graph_summary, created_at)
            VALUES
                (:snapshot_id, NULL, :trigger_event, CAST(:graph_summary AS JSONB), :created_at)
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "trigger_event": snapshot.trigger_event,
                    "graph_summary": json.dumps(summary),
                    "created_at": snapshot.observed_to.replace(tzinfo=None),
                },
            )
