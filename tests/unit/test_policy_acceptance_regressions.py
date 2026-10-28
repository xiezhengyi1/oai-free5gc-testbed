from copy import deepcopy
from pathlib import Path

import pytest

from testbed.telemetry.snapshot_builder import _flow_session_qos, _maximum_observed, _slice_qos
from testbed.telemetry.free5gc_event_parser import parse_session_fields


def test_idle_slice_has_no_invented_qos_or_measurement():
    assert _slice_qos([]) == dict(latency=None, processing_delay=None, jitter=None, loss_rate=None)
    assert _maximum_observed([]) is None


def test_slice_qos_uses_business_requirements_when_a_flow_is_routed_into_it():
    flows = [
        {"sla": dict(latency=20, jitter=5, loss_rate=0.001)},
        {"sla": dict(latency=10, jitter=2, loss_rate=0.002)},
    ]
    assert _slice_qos(flows) == dict(latency=10, processing_delay=0, jitter=2, loss_rate=0.001)


def test_live_pdu_qos_update_does_not_relabel_other_business_flows():
    # Same native event sequence as the two-PDU acceptance: default DRBs 1/2,
    # dedicated QFI 2 in PDU 1, modified in place, then released.
    history = "\n".join([
        "UE 1: assigned DRB 1 to QFI 1 (5QI 9) in PDU session 1",
        "UE 1: assigned DRB 2 to QFI 1 (5QI 9) in PDU session 2",
        "UE 1: assigned DRB 3 to QFI 2 (5QI 1) in PDU session 1",
        "UE 1: updated DRB 3 to QFI 2 (5QI 2) in PDU session 1",
    ])
    policy = {
        "sessRules": {"default": {"authDefQos": {"5qi": 9}}},
        "pccRules": {"udp": {"precedence": 1, "refQosData": ["udp-qos"]}},
        "qosDecs": {"udp-qos": {"qosId": "udp-qos", "5qi": 2,
            "gbrUl": "500 Kbps", "gbrDl": "500 Kbps", "maxbrUl": "2000 Kbps", "maxbrDl": "2000 Kbps"}},
    }
    native = parse_session_fields(history, "s", "mec", 1, 1)
    for ref in (3, 5):
        flow = _flow_session_qos(native, policy, ref)
        assert (flow["qfi"], flow["five_qi"], flow["drb_id"]) == (1, 9, 1)
    flow = _flow_session_qos(native, policy, 1)
    assert (flow["qfi"], flow["five_qi"], flow["drb_id"]) == (2, 2, 3)
    history += "\nUE 1: removed QoS flow with QFI=2"
    native = parse_session_fields(history, "s", "mec", 1, 1)
    flow = _flow_session_qos(native, policy, 1)
    assert flow["correlation_status"] == "incomplete" and "qfi" not in flow
    assert _flow_session_qos(native, policy, 3)["qfi"] == 1


def test_ambiguous_or_missing_native_qfi_is_never_guessed():
    policy = {"sessRules": {"default": {"authDefQos": {"5qi": 9}}}}
    for observed in ([], [dict(qfi=1, five_qi=9, drb_id=1), dict(qfi=3, five_qi=9, drb_id=3)]):
        native = dict(qfi=3, five_qi=9, drb_id=3, qos_flows=observed)
        flow = _flow_session_qos(native, policy, 3)
        assert flow["correlation_status"] == "incomplete"
        assert not {"qfi", "five_qi", "drb_id"} & flow.keys()


def test_policy_watchdog_waits_for_native_drb_after_pcf_has_already_changed():
    from types import SimpleNamespace

    from testbed.gateway.contracts import PolicyAction
    from testbed.gateway.policy_watchdog import PolicyWatchdog

    action = PolicyAction.model_validate({
        "run_id": "acceptance", "snapshot_id": "before", "action_type": "sm_policy_update",
        "target": {"supi": "imsi-208930000180001", "flow_id": "udp"},
        "parameters": {"five_qi": 1, "gbr_ul_mbps": 0.5, "gbr_dl_mbps": 0.5,
                       "mbr_ul_mbps": 2, "mbr_dl_mbps": 2},
    })
    incomplete = dict(flow_id="udp", supi=action.target.supi, ran={},
                      session=dict(five_qi=None, qfi=None, active_sm_qos=action.parameters.model_dump()))
    complete = deepcopy(incomplete)
    complete["session"].update(five_qi=1, qfi=2)
    complete["ran"]["drb_id"] = 3
    observations = iter([SimpleNamespace(flows=[incomplete]), SimpleNamespace(flows=[complete])])
    actual, effect = PolicyWatchdog(1, 0).wait(action, lambda: next(observations))
    assert actual.flows == [complete] and effect["qfi"] == 2
    assert effect["drb_id"] == 3 and effect["data_plane_verified"] is False


def test_bootstrap_resume_reuses_only_the_completed_initial_policy(tmp_path, monkeypatch):
    from testbed.orchestration import ue_policy_bootstrap as module
    from testbed.rendering.free5gc_renderer import _subscriber_payload
    from testbed.scenario.loader import load_scenario

    source = Path(__file__).resolve().parents[2] / "scenarios/mvp/s1_single_ue_single_upf.yaml"
    (tmp_path / "source-scenario.yaml").write_bytes(source.read_bytes())
    scenario = load_scenario(source)
    association = {"id": "association-1", "version": 0, "status": "new"}
    deliveries = []

    class Pcf:
        def ue_policy(self, _supi):
            return {"ue_policy_associations": [deepcopy(association)]}

        def apply_ue_policy(self, supi, domain, parameters):
            deliveries.append((supi, domain, parameters))
            association.update(version=1, status="complete", policy=parameters["policy"])

    class Subscriber:
        def __init__(self, _url):
            pass

        def get(self, _supi, _plmn):
            return _subscriber_payload(scenario, scenario.ues[0])

    monkeypatch.setattr(module, "PcfAdapter", Pcf)
    monkeypatch.setattr(module, "SubscriberAdapter", Subscriber)
    module.bootstrap(tmp_path)
    module.bootstrap(tmp_path)
    assert len(deliveries) == 1
    association["policy"]["rules"][0]["routes"][0]["precedence"] = 2
    protected = deepcopy(association)
    with pytest.raises(RuntimeError, match="preserve it"):
        module.bootstrap(tmp_path)
    assert association == protected and len(deliveries) == 1
