from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from testbed.orchestration.readiness import Readiness
from testbed.scenario.loader import load_scenario
from testbed.state.models import RunPhase
from testbed.state.run_store import RunStore
from testbed.telemetry.flow_correlator import correlate_flow
from testbed.telemetry.free5gc_event_parser import parse_session_fields
from testbed.telemetry.models import UnifiedSnapshot
from testbed.telemetry.ran_exporter import (
    parse_ran_ues,
    parse_ue_rnti,
    ran_records_ready,
)
from testbed.telemetry.snapshot_builder import _maximum_observed, _prb_utilization
from testbed.telemetry.snapshot_writer import PostgresGraphWriter, SnapshotStore, graph_summary

ROOT = Path(__file__).resolve().parents[2]


def test_snapshot_aggregate_uses_only_observed_flow_metrics() -> None:
    assert _maximum_observed([None, 4.5, 3.0]) == 4.5
    assert _maximum_observed([None, None]) is None


def test_snapshot_prb_utilization_requires_all_ue_measurements() -> None:
    assert _prb_utilization([20.0, 10.0], 100.0) == 0.3
    assert _prb_utilization([20.0, None], 100.0) is None


def test_snapshot_store_writes_history_and_latest_metric_artifacts(tmp_path: Path) -> None:
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    (tmp_path / "snapshots.jsonl").touch()
    now = datetime.now(UTC)
    snapshot = UnifiedSnapshot(
        snapshot_id="snapshot-artifact-1",
        run_id="run-artifact-1",
        observed_from=now,
        observed_to=now,
        topology={},
        slice_states=(),
        sessions=(),
        flows=(),
        ran_nodes=(),
        core_nodes=(),
        containers=(),
        mec_sites=(),
        mobility=(),
        active_actions=(),
        trigger_event="periodic",
    )

    SnapshotStore(tmp_path).append(snapshot)

    assert SnapshotStore(tmp_path).latest() == snapshot
    assert UnifiedSnapshot.model_validate_json(
        (metrics / "latest.json").read_text(encoding="utf-8")
    ) == snapshot


def test_run_state_machine_requires_ordered_transitions(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.initialize()
    with pytest.raises(ValueError, match="invalid phase transition"):
        store.advance(RunPhase.PFCP_READY, {})
    state = store.advance(RunPhase.CORE_READY, {"containers": 11})
    assert state.phase == RunPhase.CORE_READY
    assert state.sequence == 1


def test_running_state_can_record_an_in_place_recovery(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.initialize()
    for phase in (
        RunPhase.CORE_READY,
        RunPhase.PFCP_READY,
        RunPhase.GNB_READY,
        RunPhase.UE_REGISTERED,
        RunPhase.PDU_READY,
        RunPhase.TRAFFIC_READY,
        RunPhase.TELEMETRY_READY,
        RunPhase.RUNNING,
    ):
        store.advance(phase, {})

    state = store.recover({"ready": True, "reason": "host_restart"})

    assert state.phase == RunPhase.RUNNING
    assert state.sequence == 9
    assert state.evidence == {"ready": True, "reason": "host_restart"}


def test_failed_recovery_can_be_retried_without_resetting_the_run(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.initialize()
    for phase in (
        RunPhase.CORE_READY,
        RunPhase.PFCP_READY,
        RunPhase.GNB_READY,
        RunPhase.UE_REGISTERED,
        RunPhase.PDU_READY,
        RunPhase.TRAFFIC_READY,
        RunPhase.TELEMETRY_READY,
        RunPhase.RUNNING,
    ):
        store.advance(phase, {})
    store.fail(RunPhase.PFCP_READY, RuntimeError("PFCP evidence unavailable"), {})

    state = store.recover({"ready": True, "recovered_from": RunPhase.FAILED})

    assert state.phase == RunPhase.RUNNING
    assert state.sequence == 10
    assert state.evidence["recovered_from"] == RunPhase.FAILED


def test_telemetry_readiness_rejects_an_empty_prometheus_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyPrometheus:
        def ready(self) -> None:
            return

        def instant_query(self, _query: str) -> list[dict[str, object]]:
            return []

    monkeypatch.setattr(
        "testbed.orchestration.readiness.PrometheusAdapter",
        lambda _url: EmptyPrometheus(),
    )
    scenario = load_scenario(ROOT / "scenarios/advanced/s7_managed_multi_slice.yaml")
    readiness = Readiness(docker=object(), scenario=scenario)

    with pytest.raises(RuntimeError, match="expected 10 Prometheus targets, found 0"):
        readiness.telemetry()


def test_flow_correlation_never_invents_session_or_ran_values() -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    now = datetime.now(UTC)
    flow = correlate_flow(scenario, scenario.flows[0], None, {}, {}, None, now, now, 0)
    assert flow["data_quality"]["correlation_status"] == "incomplete"
    assert flow["session"]["qfi"] is None
    assert "mcs_ul" not in flow["ran"]
    assert flow["traffic"]["five_tuple"][0] is None


def test_flow_correlation_projects_explicit_optimizer_inputs() -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    now = datetime.now(UTC)
    session = {
        "pdu_session_id": 1,
        "qfi": 1,
        "five_qi": 2,
        "ue_ip": "10.60.0.1",
        "ul_teid": "0x00000001",
        "dl_teid": "0x00000002",
        "drb_id": 1,
    }
    flow = correlate_flow(
        scenario,
        scenario.flows[0],
        session,
        {"rnti": "e404"},
        {},
        {
            "allocated_bandwidth_ul_mbps": 18,
            "allocated_bandwidth_dl_mbps": 19,
            "source_action_id": "action-1",
        },
        now,
        now,
        1,
    )

    assert flow["sla"] == {
        "latency": 20.0,
        "jitter": 5.0,
        "loss_rate": 0.001,
        "bandwidth_ul": 20.0,
        "bandwidth_dl": 20.0,
        "guaranteed_bandwidth_ul": 15.0,
        "guaranteed_bandwidth_dl": 15.0,
        "priority": 1,
    }
    assert flow["allocation"]["allocated_bandwidth_ul"] == 18
    assert flow["allocation"]["allocated_bandwidth_dl"] == 19
    assert flow["traffic"]["five_tuple"] == [
        "10.60.0.1",
        "172.34.0.100",
        41001,
        5202,
        "udp",
    ]
    assert flow["traffic"]["packet_size"] == 9600
    assert flow["traffic"]["arrival_rate"] == pytest.approx(2083.3333333333335)


def test_oai_2026_w35_logs_expose_session_and_ran_correlation_keys() -> None:
    log_text = """
UE RNTI e404 CU-UE-ID 1 in-sync
UE e404: dlsch_rounds 42/0/0/0, BLER 0.00000 MCS (0) 28 (Qm 6)
UE e404: ulsch_rounds 41/0/0/0, BLER 0.01000 MCS (0) 27 (Qm 6) NPRB 57
UE 1: created new DRB 1 for QFI 1 (5QI 9)
UE 1: assigned DRB 1 to QFI 1 (5QI 9) in PDU session 1
PDU Session to Setup: PDU Session ID=1, incoming TEID=0x00000002
N3 GTP-U tunnel: PDUSession=1/UL TEID=0x00000002
PDU Session Setup: ID=1, outgoing TEID=0x6bca34d6
"""
    session = parse_session_fields(log_text, "imsi-208930000000001", "mec", 1, 1)
    assert session["drb_id"] == 1
    assert session["qfi"] == 1
    assert session["five_qi"] == 9
    assert session["ul_teid"] == "0x00000002"
    assert session["dl_teid"] == "0x6bca34d6"
    ran = parse_ran_ues(log_text)[0xE404]
    assert ran == {
        "rnti": 0xE404,
        "cu_ue_id": 1,
        "mcs_dl": 28,
        "mcs_ul": 27,
        "bler_dl": 0.0,
        "bler_ul": 0.01,
        "prb_ul": 57,
        "handover_event": "stable",
    }


def test_multi_ue_ran_and_session_metrics_are_not_cross_correlated() -> None:
    log_text = """
UE RNTI e404 CU-UE-ID 1 in-sync
UE e404: dlsch_rounds 42/0/0/0, BLER 0.01000 MCS (0) 28 (Qm 6)
UE e404: ulsch_rounds 41/0/0/0, BLER 0.02000 MCS (0) 27 (Qm 6) NPRB 57
UE 1: assigned DRB 1 to QFI 7 (5QI 2) in PDU session 1
N3 GTP-U tunnel: PDUSession=1/UL TEID=0x00000002
PDU Session Setup: ID=1, outgoing TEID=0x11111111
UE RNTI a505 CU-UE-ID 2 in-sync
UE a505: dlsch_rounds 40/0/0/0, BLER 0.03000 MCS (0) 18 (Qm 4)
UE a505: ulsch_rounds 39/0/0/0, BLER 0.04000 MCS (0) 17 (Qm 4) NPRB 23
UE 2: assigned DRB 2 to QFI 9 (5QI 7) in PDU session 1
N3 GTP-U tunnel: PDUSession=1/UL TEID=0x00000004
PDU Session Setup: ID=1, outgoing TEID=0x22222222
"""
    ran = parse_ran_ues(log_text)
    assert ran[0xE404]["mcs_ul"] == 27
    assert ran[0xA505]["mcs_ul"] == 17
    first = parse_session_fields(log_text, "imsi-1", "embb", 1, 1)
    second = parse_session_fields(log_text, "imsi-2", "embb", 1, 2)
    assert (first["drb_id"], first["ul_teid"], first["dl_teid"]) == (
        1,
        "0x00000002",
        "0x11111111",
    )
    assert (second["drb_id"], second["ul_teid"], second["dl_teid"]) == (
        2,
        "0x00000004",
        "0x22222222",
    )


def test_nrue_connected_rnti_is_parsed() -> None:
    assert parse_ue_rnti("RNTI 0xe404 State = NR_RRC_CONNECTED") == 0xE404
    assert parse_ue_rnti("UE 0 RNTI ae9e stats sfn: 512.8") == 0xAE9E


def test_ran_exporter_waits_for_each_current_ue_rnti() -> None:
    ues = [
        {"id": "ue-1", "serving_gnb": "gnb-1"},
        {"id": "ue-2", "serving_gnb": "gnb-2"},
    ]
    rntis = {"ue-1": 0xE404, "ue-2": 0xA505}
    records = {"gnb-1": {0xE404: {}}, "gnb-2": {}}

    assert not ran_records_ready(ues, rntis, records)
    records["gnb-2"][0xA505] = {}
    assert ran_records_ready(ues, rntis, records)


def test_postgres_graph_writer_selects_declared_psycopg3_driver() -> None:
    writer = PostgresGraphWriter("postgresql://writer:secret@localhost/testbed")
    assert writer.engine.url.drivername == "postgresql+psycopg"
    writer.engine.dispose()


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
        slice_states=(
            {
                "slice_id": "embb",
                "snssai": "01010203",
                "phase": "running",
            },
        ),
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
