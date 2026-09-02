from __future__ import annotations

import argparse
import json
from pathlib import Path

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.state.run_store import RunStore
from testbed.telemetry.snapshot_writer import SnapshotStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    arguments = parser.parse_args()
    run_dir = arguments.run_dir.resolve(strict=True)
    repository_root = Path(__file__).resolve().parents[1]
    state = RunStore(run_dir).current()
    if state.phase != "RUNNING":
        raise RuntimeError(f"run is not RUNNING: {state.phase}")
    DockerAdapter(
        run_dir / "generated" / "compose.yaml",
        compose_env_file=repository_root / ".env",
    ).compose_config()
    snapshot = SnapshotStore(run_dir).latest()
    incomplete = [
        flow["flow_id"]
        for flow in snapshot.flows
        if flow["data_quality"]["correlation_status"] != "complete"
    ]
    if incomplete:
        raise RuntimeError(f"incomplete flow correlations: {incomplete}")
    print(
        json.dumps(
            {
                "run_id": run_dir.name,
                "phase": state.phase,
                "snapshot_id": snapshot.snapshot_id,
                "flows": [flow["flow_id"] for flow in snapshot.flows],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
