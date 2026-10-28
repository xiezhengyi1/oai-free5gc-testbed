from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from testbed.artifacts.metrics_exporter import export_metrics
from testbed.telemetry.models import UnifiedSnapshot
from testbed.telemetry.state_projection import StateProjection


class SnapshotStore:
    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "snapshots.jsonl"

    def append(self, snapshot: UnifiedSnapshot) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(snapshot.model_dump_json() + "\n")
        export_metrics(self.path.parent, snapshot.model_dump(mode="json"))

    def get(self, snapshot_id: str) -> UnifiedSnapshot:
        needle = json.dumps(snapshot_id, ensure_ascii=False).encode("utf-8")
        with self.path.open("rb") as handle:
            for line in handle:
                if needle in line:
                    snapshot = UnifiedSnapshot.model_validate_json(line)
                    if snapshot.snapshot_id == snapshot_id:
                        return snapshot
        raise KeyError(snapshot_id)

    def latest(self) -> UnifiedSnapshot:
        with self.path.open("rb") as handle:
            lines = deque(handle, maxlen=1)
        if not lines:
            raise LookupError("no snapshots have been written")
        return UnifiedSnapshot.model_validate_json(lines[0])


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


def graph_delta(
    current: dict[str, Any], previous: dict[str, Any]
) -> dict[str, Any]:
    node_changes, deleted_nodes = _collection_delta(
        current["nodes"], previous["nodes"], "node_key"
    )
    edge_changes, deleted_edges = _collection_delta(
        current["edges"], previous["edges"], "edge_key"
    )
    metric_changes, deleted_metrics = _collection_delta(
        current["metrics"], previous["metrics"], "metric_key"
    )
    return {
        "mode": "delta",
        "testbed_state": {
            key: current["testbed_snapshot"][key]
            for key in ("baseline_epoch", "sessions", "ue_policies", "active_actions")
        },
        "snapshot_id": current["snapshot_id"],
        "run_id": current["run_id"],
        "trigger_event": current["trigger_event"],
        "observed_from": current["observed_from"],
        "observed_to": current["observed_to"],
        "upsert": {
            "nodes": node_changes,
            "edges": edge_changes,
            "metrics": metric_changes,
        },
        "delete": {
            "node_keys": deleted_nodes,
            "edge_keys": deleted_edges,
            "metric_keys": deleted_metrics,
        },
    }


def _collection_delta(
    current: list[dict[str, Any]], previous: list[dict[str, Any]], key: str
) -> tuple[list[dict[str, Any]], list[str]]:
    if key == "metric_key":
        current_by_key = {_metric_key(item): item for item in current}
        previous_by_key = {_metric_key(item): item for item in previous}
    else:
        current_by_key = {item[key]: item for item in current}
        previous_by_key = {item[key]: item for item in previous}
    upserts = [
        item
        for item_key, item in current_by_key.items()
        if previous_by_key.get(item_key) != item
    ]
    return upserts, sorted(set(previous_by_key) - set(current_by_key))


def _metric_key(metric: dict[str, Any]) -> str:
    return ":".join(
        (metric["owner_type"], metric["owner_key"], metric["metric_name"])
    )


class PostgresGraphWriter:
    def __init__(self, database_url: str) -> None:
        self.engine = create_engine(
            database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        )
        self.previous_summary: dict[str, Any] | None = None
        self.previous_snapshot_id: str | None = None
        self.projection = StateProjection(checkpoint_every=100)
        self.write_count = 0

    def write(self, snapshot: UnifiedSnapshot) -> None:
        summary = graph_summary(snapshot)
        stored_graph = (
            {"mode": "full", **summary}
            if self.previous_summary is None or self.write_count % 100 == 0
            else graph_delta(summary, self.previous_summary)
        )
        statement = text(
            """
            INSERT INTO network_graph_snapshot
                (snapshot_id, base_network_snapshot_id, trigger_event, graph_summary, created_at)
            VALUES
                (
                    :snapshot_id,
                    :base_network_snapshot_id,
                    :trigger_event,
                    CAST(:graph_summary AS JSONB),
                    :created_at
                )
            """
        )
        with self.engine.begin() as connection:
            connection.execute(
                statement,
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "base_network_snapshot_id": self.previous_snapshot_id if stored_graph["mode"] == "delta" else None,
                    "trigger_event": snapshot.trigger_event,
                    "graph_summary": json.dumps(stored_graph),
                    "created_at": snapshot.observed_to,
                },
            )
            self.projection.apply(connection, summary=summary, native=snapshot.model_dump(mode="json"))
        self.write_count += 1
        self.previous_summary = summary
        self.previous_snapshot_id = snapshot.snapshot_id
