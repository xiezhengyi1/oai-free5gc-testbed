from __future__ import annotations

import pytest
from pydantic import ValidationError

from testbed.gateway.sm_restore_plan import plan_restore, verify_restore
from testbed.telemetry.free5gc_event_parser import parse_session_fields
from testbed.telemetry.session_tracker import SessionLogHistory
from testbed.traffic.profiles import TrafficProfile
from testbed.traffic.timing import TrafficTiming


def assignment(session, qfi, five_qi=9, ue=1):
    return f"UE {ue}: assigned DRB {qfi} to QFI {qfi} (5QI {five_qi}) in PDU session {session}"


def parse(lines, session=1):
    return parse_session_fields("\n".join(lines), "imsi-example", "mec", session, 1)


def test_qos_update_selects_latest_assignment_and_release_restores_previous():
    lines = [assignment(1, 1), assignment(1, 2, 1), assignment(1, 1, 2)]
    assert parse(lines)["five_qi"] == 2
    assert parse(lines)["qfi"] == 1
    lines.append("UE 1: removed QoS flow with QFI=1")
    assert parse(lines)["qfi"] == 2
    lines.append("UE 1: removed QoS flow with QFI=2")
    assert "qfi" not in parse(lines)


def test_unscoped_release_never_guesses_between_pdu_sessions():
    lines = [assignment(1, 1), assignment(2, 1), "UE 1: removed QoS flow with QFI=1"]
    for session in (1, 2):
        result = parse(lines, session)
        assert "qfi" not in result
        assert "ambiguous" in result["correlation_error"]


def test_native_qos_update_observation_replaces_old_five_qi_and_is_cached():
    docker = Logs()
    history = SessionLogHistory()
    docker.text = stamped(0, assignment(1, 1, 1))
    history.read(docker, "gnb")
    docker.text = stamped(1, "UE 1: updated DRB 1 to QFI 1 (5QI 2) in PDU session 1")
    records = history.read(docker, "gnb")
    result = parse_session_fields(records, "s", "d", 1, 1)
    assert result["five_qi"] == 2
    assert result["qfi"] == 1
    assert len(history.events) == 2


def test_scoped_release_and_other_ue_do_not_remove_protected_session():
    lines = [
        assignment(1, 1),
        assignment(2, 1),
        assignment(1, 1, ue=2),
        "UE 2: removed QoS flow with QFI=1",
        "UE 1: removed QoS flow with QFI=1 in PDU session 2",
    ]
    assert parse(lines, 1)["qfi"] == 1
    assert "qfi" not in parse(lines, 2)


class Logs:
    def __init__(self):
        self.started = "start-1"
        self.text = ""
        self.reads = []
        self.restart_during_read = False

    def inspect(self, _container):
        return {"Id": "id-1", "State": {"StartedAt": self.started}}

    def container_logs(self, _container, **kwargs):
        self.reads.append(kwargs)
        if self.restart_during_read:
            self.started = "start-2"
        return self.text


def stamped(index, body):
    return f"2026-10-27T00:00:{index:02d}.000000000Z {body}"


def test_session_history_deduplicates_overlap_and_invalidates_on_restart():
    docker = Logs()
    history = SessionLogHistory()
    first = stamped(0, assignment(1, 1))
    second = stamped(1, assignment(1, 2, 1))
    docker.text = first + "\n" + second
    history.read(docker, "gnb")
    docker.text = second + "\n" + stamped(2, "UE 1: removed QoS flow with QFI=2")
    text = history.read(docker, "gnb")
    assert len(history.events) == 3
    assert parse_session_fields(text, "s", "d", 1, 1)["qfi"] == 1
    assert docker.reads[-1]["since"] is not None
    docker.started = "start-2"
    docker.text = first
    history.read(docker, "gnb")
    assert len(history.events) == 1 and docker.reads[-1]["since"] is None


def test_session_history_rejects_restart_mid_read_and_capacity_overflow():
    docker = Logs()
    history = SessionLogHistory(max_events=1)
    docker.restart_during_read = True
    with pytest.raises(RuntimeError, match="restarted"):
        history.read(docker, "gnb")
    assert not history.events
    docker.restart_during_read = False
    docker.text = stamped(0, assignment(1, 1)) + "\n" + stamped(1, assignment(1, 2))
    with pytest.raises(RuntimeError, match="capacity"):
        history.read(docker, "gnb")


def test_timing_defaults_and_burst_boundaries_preserve_explicit_contract():
    assert TrafficTiming().packet_interval(1200, 1) == pytest.approx(0.0096)
    t = TrafficTiming(interval_ms=20, burst_on_ms=100, burst_off_ms=100, start_offset_ms=50)
    assert t.packet_interval(1200, 1) == 0.02
    assert t.packet_rate(1200, 1) == 25
    assert t.scheduled_rate_mbps(1200, 1) == pytest.approx(0.24)
    assert TrafficTiming().scheduled_rate_mbps(1200, 1) == 1
    assert t.next_active(0, 0) == 0.05
    assert t.next_active(0.16, 0) == pytest.approx(0.25)
    with pytest.raises(ValidationError):
        TrafficTiming(burst_on_ms=100)


def test_udp_response_contract_rejects_other_protocol_and_short_request():
    payload = dict(
        flow_id="f",
        ue_id="u",
        supi="s",
        session_id="p",
        interface="lo",
        service_instance_id="a",
        rate_mbps=1,
        packet_size_bytes=20,
        sla={},
        udp_response_bytes=100,
        five_tuple=dict(
            source_ip="127.0.0.1",
            source_port=41000,
            destination_ip="127.0.0.1",
            destination_port=5202,
            protocol="udp",
        ),
    )
    with pytest.raises(ValidationError):
        TrafficProfile.model_validate(payload)
    payload["packet_size_bytes"] = 100
    payload["five_tuple"]["protocol"] = "tcp"
    with pytest.raises(ValidationError):
        TrafficProfile.model_validate(payload)


def test_sm_inverse_requires_exact_identity_and_protects_unowned_entries():
    import copy

    before = dict(
        supi="s",
        flow_id="f",
        association_id="a",
        session=1,
        protected_state={},
        decision={k: {} for k in ("pccRules", "qosDecs", "chgDecs", "traffContDecs")},
    )
    after = copy.deepcopy(before)
    after["decision"]["qosDecs"]["owned"] = {"5qi": 2}
    owned = {k: (["owned"] if k == "qosDecs" else []) for k in before["decision"]}
    plan = plan_restore(before, after, owned)
    assert plan["notification_delta"] == {"qosDecs": {"owned": None}}
    verify_restore(before, plan)
    with pytest.raises(ValueError):
        verify_restore(after, plan)
    after["protected_state"] = {"another-flow": "changed"}
    with pytest.raises(ValueError, match="protected"):
        plan_restore(before, after, owned)
