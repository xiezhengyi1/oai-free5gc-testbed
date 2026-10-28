"""Transactional read model for observed network state, independent of actors.

This module is also deployed byte-for-byte beside the testbed telemetry writer.
It never executes policies or treats a control-plane acknowledgement as an SLA.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import text

PROJECTION_VERSION = "network-state-1"
POLICY_FIELDS = {
    "AM": "am_policy_associations",
    "SM": "sm_policy_associations",
    "URSP": "ue_policy_associations",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def observed_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("snapshot observed_to must include a timezone")
    return parsed


def policy_rows(native: dict[str, Any]) -> list[dict[str, Any]]:
    """An empty list is authoritative absence; an omitted field is unknown."""
    if not isinstance(native.get("ue_policies"), list):
        raise ValueError("complete native ue_policies evidence is required")
    result = []
    seen = set()
    for ue in native["ue_policies"]:
        supi = ue["supi"]
        if not isinstance(supi, str) or not supi:
            raise ValueError("policy SUPI is required")
        for family, field in POLICY_FIELDS.items():
            if not isinstance(ue.get(field), list):
                raise ValueError(f"missing complete {field} evidence for {supi}")
            for association in ue[field]:
                identifier = association.get("id", association.get("association_id"))
                if "id" in association and "association_id" in association and association["id"] != association["association_id"]:
                    raise ValueError("conflicting policy association identities")
                if not isinstance(identifier, str) or not identifier:
                    raise ValueError("policy association_id is required")
                key = (supi, family, identifier)
                if key in seen:
                    raise ValueError("duplicate policy association identity")
                seen.add(key)
                result.append({"supi": supi, "family": family, "association_id": identifier,
                               "payload": canonical_json(association)})
    return result


class StateProjection:
    def __init__(self, *, schema: str = "public", checkpoint_every: int = 100) -> None:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
            raise ValueError("invalid database schema identifier")
        if checkpoint_every < 1:
            raise ValueError("checkpoint_every must be positive")
        self.schema = schema
        self.checkpoint_every = checkpoint_every

    def table(self, name: str) -> str:
        return f'"{self.schema}".{name}'

    def initialize(self, connection: Any) -> None:
        current = self.table("network_state_current")
        policies = self.table("network_policy_current")
        checkpoints = self.table("network_graph_checkpoint")
        statements = [f"""
            CREATE TABLE IF NOT EXISTS {current} (
                run_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL, baseline_epoch TEXT NOT NULL,
                source_sha256 TEXT NOT NULL, projection_version TEXT NOT NULL,
                applied_count BIGINT NOT NULL, graph JSONB NOT NULL,
                native_snapshot JSONB NOT NULL,
                projected_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
            f"""CREATE TABLE IF NOT EXISTS {policies} (
                run_id TEXT NOT NULL REFERENCES {current}(run_id), supi TEXT NOT NULL,
                family TEXT NOT NULL CHECK (family IN ('AM','SM','URSP')),
                association_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL,
                PRIMARY KEY(run_id,supi,family,association_id))""",
            f"""CREATE TABLE IF NOT EXISTS {checkpoints} (
                run_id TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL, source_sha256 TEXT NOT NULL,
                projection_version TEXT NOT NULL, graph JSONB NOT NULL,
                native_snapshot JSONB NOT NULL,
                PRIMARY KEY(run_id,snapshot_id))""",
            f"CREATE INDEX IF NOT EXISTS network_checkpoint_time_idx ON {checkpoints}(run_id,observed_at DESC)",
            f"""CREATE OR REPLACE VIEW {self.table('network_current_flow')} AS
                SELECT c.run_id,c.snapshot_id,c.observed_at,c.baseline_epoch,
                       f->>'supi' AS supi, f->>'app_id' AS app_id,
                       f->>'flow_id' AS flow_id, f AS properties
                FROM {current} c CROSS JOIN LATERAL
                     jsonb_array_elements(c.native_snapshot->'flows') f""",
            f"""CREATE OR REPLACE VIEW {self.table('network_current_session')} AS
                SELECT c.run_id,c.snapshot_id,c.observed_at,c.baseline_epoch,
                       s->>'supi' AS supi, s->>'pdu_session_id' AS pdu_session_id,
                       s->>'dnn' AS dnn,s->>'snssai' AS snssai,s AS properties
                FROM {current} c CROSS JOIN LATERAL
                     jsonb_array_elements(c.native_snapshot->'sessions') s""",
            f"""CREATE OR REPLACE VIEW {self.table('network_current_ue')} AS
                SELECT DISTINCT c.run_id,c.snapshot_id,c.observed_at,c.baseline_epoch,
                       e->>'supi' AS supi
                FROM {current} c CROSS JOIN LATERAL jsonb_array_elements(
                    (c.native_snapshot->'flows') || (c.native_snapshot->'sessions') ||
                    (c.native_snapshot->'ue_policies')) e""",
            f"""CREATE OR REPLACE VIEW {self.table('network_current_node')} AS
                SELECT c.run_id,c.snapshot_id,c.observed_at,
                       n->>'node_key' AS node_key,n->>'node_type' AS node_type,
                       n->'properties' AS properties
                FROM {current} c CROSS JOIN LATERAL jsonb_array_elements(c.graph->'nodes') n""",
            f"""CREATE OR REPLACE VIEW {self.table('network_current_edge')} AS
                SELECT c.run_id,c.snapshot_id,c.observed_at,e->>'edge_key' AS edge_key,
                       e->>'edge_type' AS edge_type,e->>'source_key' AS source_key,
                       e->>'target_key' AS target_key,e->'properties' AS properties
                FROM {current} c CROSS JOIN LATERAL jsonb_array_elements(c.graph->'edges') e""",
            f"""CREATE OR REPLACE VIEW {self.table('network_current_status')} AS
                SELECT run_id,snapshot_id,observed_at,baseline_epoch,projection_version,
                       applied_count,source_sha256,projected_at,
                       now()-observed_at AS evidence_age
                FROM {current}""",
        ]
        for statement in statements:
            connection.execute(text(statement))

    def apply(self, connection: Any, *, summary: dict[str, Any], native: dict[str, Any]) -> bool:
        """Apply a complete observation in the caller's history-write transaction.

        Older observations never replace the head. Reused IDs with different
        bytes and ambiguous equal-time ordering are rejected, not guessed.
        """
        for field in ("run_id", "snapshot_id"):
            if summary[field] != native[field]:
                raise ValueError(f"graph/native {field} mismatch")
        for field in ("flows", "sessions"):
            if not isinstance(native.get(field), list):
                raise ValueError(f"complete native {field} evidence is required")
        run_id, snapshot_id = native["run_id"], native["snapshot_id"]
        if not run_id or not snapshot_id or "baseline_epoch" not in native:
            raise ValueError("run, snapshot and baseline provenance are required")
        rows = policy_rows(native)
        at = observed_time(native["observed_to"])
        if observed_time(summary["observed_to"]) != at:
            raise ValueError("graph/native observed_to mismatch")
        graph = {k: v for k, v in summary.items() if k != "testbed_snapshot"}
        for field in ("nodes", "edges", "metrics"):
            if not isinstance(graph.get(field), list):
                raise ValueError(f"full graph {field} required for projection")
        checksum = hashlib.sha256(canonical_json({"graph": graph, "native": native}).encode()).hexdigest()
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:lock,0))"),
                           {"lock": "multiagents-state:" + run_id})
        current = self.table("network_state_current")
        previous = connection.execute(text(f"SELECT * FROM {current} WHERE run_id=:run FOR UPDATE"),
                                      {"run": run_id}).mappings().first()
        if previous:
            if previous["snapshot_id"] == snapshot_id:
                if previous["source_sha256"] != checksum:
                    raise ValueError("snapshot identity reused with different source content")
                return False
            if at < previous["observed_at"]:
                return False
            if at == previous["observed_at"]:
                raise ValueError("ambiguous equal-time snapshot ordering")
        count = previous["applied_count"] + 1 if previous else 1
        parameters = {"run": run_id, "snapshot": snapshot_id, "at": at,
                      "epoch": str(native["baseline_epoch"]), "sha": checksum,
                      "version": PROJECTION_VERSION, "count": count,
                      "graph": canonical_json(graph), "native": canonical_json(native)}
        connection.execute(text(f"""
            INSERT INTO {current}(run_id,snapshot_id,observed_at,baseline_epoch,
                source_sha256,projection_version,applied_count,graph,native_snapshot)
            VALUES (:run,:snapshot,:at,:epoch,:sha,:version,:count,
                    CAST(:graph AS jsonb),CAST(:native AS jsonb))
            ON CONFLICT(run_id) DO UPDATE SET snapshot_id=EXCLUDED.snapshot_id,
                observed_at=EXCLUDED.observed_at,baseline_epoch=EXCLUDED.baseline_epoch,
                source_sha256=EXCLUDED.source_sha256,projection_version=EXCLUDED.projection_version,
                applied_count=EXCLUDED.applied_count,graph=EXCLUDED.graph,
                native_snapshot=EXCLUDED.native_snapshot,projected_at=now()
            """), parameters)
        policies = self.table("network_policy_current")
        connection.execute(text(f"DELETE FROM {policies} WHERE run_id=:run"), {"run": run_id})
        if rows:
            connection.execute(text(f"""INSERT INTO {policies}
                (run_id,supi,family,association_id,snapshot_id,observed_at,payload)
                VALUES (:run,:supi,:family,:association_id,:snapshot,:at,CAST(:payload AS jsonb))"""),
                [{"run": run_id, "snapshot": snapshot_id, "at": at, **row} for row in rows])
        if not previous or previous["baseline_epoch"] != str(native["baseline_epoch"]) or count % self.checkpoint_every == 0:
            connection.execute(text(f"""INSERT INTO {self.table('network_graph_checkpoint')}
                (run_id,snapshot_id,observed_at,source_sha256,projection_version,graph,native_snapshot)
                VALUES (:run,:snapshot,:at,:sha,:version,CAST(:graph AS jsonb),CAST(:native AS jsonb))"""), parameters)
        return True
