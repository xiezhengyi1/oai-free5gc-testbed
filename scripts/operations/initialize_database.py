"""Initialize the telemetry schema using the run's service account; keep existing data."""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from testbed.telemetry.state_projection import StateProjection


def initialize_database(database_url: str) -> None:
    url = make_url(database_url)
    if url.host == "host.docker.internal" and url.port == 15434:
        url = url.set(host="127.0.0.1", port=5432)
    with create_engine(url).begin() as connection:
        connection.execute(
            text("""CREATE TABLE IF NOT EXISTS network_graph_snapshot (
            snapshot_id TEXT PRIMARY KEY, base_network_snapshot_id TEXT,
            trigger_event TEXT NOT NULL, graph_summary JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL)""")
        )
        StateProjection().initialize(connection)


if __name__ == "__main__":
    initialize_database(os.environ["MULTIAGENTS_DATABASE_URL"])
    print("telemetry history and state projection schema initialized")
