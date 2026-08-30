from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from testbed.scenario.loader import load_scenario
from testbed.state.models import RunPhase
from testbed.state.run_store import RunStore
from testbed.telemetry.flow_correlator import correlate_flow
from testbed.telemetry.models import UnifiedSnapshot
from testbed.telemetry.snapshot_writer import graph_summary

ROOT = Path(__file__).resolve().parents[2]


def test_run_state_machine_requires_ordered_transitions(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.initialize()
    with pytest.raises(ValueError, match="invalid phase transition"):
        store.advance(RunPhase.PFCP_READY, {})
    state = store.advance(RunPhase.CORE_READY, {"containers": 11})
    assert state.phase == RunPhase.CORE_READY
    assert state.sequence == 1


def test_flow_correlation_never_invents_session_or_ran_values() -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    now = datetime.now(UTC)
    flow = correlate_flow(scenario, scenario.flows[0], None, {}, {}, now, now, 0)
    assert flow["data_quality"]["correlation_status"] == "incomplete"
    assert flow["session"]["qfi"] is None
    assert "mcs_ul" not in flow["ran"]


def test_graph_summary_preserves_agent_flow_contract() -> None:
    now = datetime.now(UTC)
    flow = {
        "flow_id": "flow-1",
        "supi": "imsi-208930000000001",
        "app_id": "inference",
        "app_name": "inference",
        "session": {"snssai": "01010203", "qfi": 7, "five_qi": 2},
        "ran": {"drb_id": 2},
        "telemetry": {"latency": 4.5},
    }
    snapshot = UnifiedSnapshot(
        snapshot_id="snapshot-1",
        run_id="run-1",
        observed_from=now,
        observed_to=now,
        topology={},
        sessions=(),
        flows=(flow,),
        ran_nodes=(),
        core_nodes=(),
        containers=(),
        mec_sites=(),
        mobility=(),
        active_actions=(),
        trigger_event="ContractTest",
    )
    summary = graph_summary(snapshot)
    types = {node["node_type"] for node in summary["nodes"]}
    assert {"ue", "app", "flow", "slice"} <= types
    assert summary["testbed_snapshot"]["snapshot_id"] == "snapshot-1"
    assert any(metric["metric_name"] == "session.qfi" for metric in summary["metrics"])
