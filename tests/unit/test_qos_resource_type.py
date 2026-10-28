import pytest
from pydantic import ValidationError
from testbed.gateway.contracts import PolicyParameters
from testbed.gateway.policy_translator import _bandwidth
from testbed.telemetry.snapshot_builder import _active_sm_qos
from testbed.gateway.contracts import PolicyAction
from testbed.gateway.postcondition_verifier import verify_policy
from types import SimpleNamespace

def test_gbr_requires_supported_resource_type():
    rates = dict(gbr_ul_mbps=2.34, mbr_ul_mbps=2.85, gbr_dl_mbps=1.8, mbr_dl_mbps=2.25)
    for five_qi in (5, 6, 7, 8, 9, 255):
        with pytest.raises(ValidationError, match="supported GBR 5QI"):
            PolicyParameters(five_qi=five_qi, **rates)
    assert PolicyParameters(five_qi=2, **rates).gbr_ul_mbps == 2.34

def test_exact_rate_and_current_readback():
    assert _bandwidth(2.34) == "2340 Kbps"
    with pytest.raises(ValueError, match="implicit rounding"):
        _bandwidth(2.3868)
    policy = {"pccRules": {"rule": {"precedence": 1, "refQosData": ["q"]}}, "qosDecs": {"q": {"5qi": 2, "gbrUl": "2340 Kbps", "gbrDl": "1800 Kbps", "maxbrUl": "2850 Kbps", "maxbrDl": "2250 Kbps"}}}
    assert _active_sm_qos(policy, 1)["gbr_ul_mbps"] == 2.34
    assert _active_sm_qos(policy, 2) is None
    policy["qosDecs"]["q"]["gbrUl"] = "2400 Kbps"
    assert _active_sm_qos(policy, 1)["gbr_ul_mbps"] == 2.4

def test_receipt_requires_exact_policy_and_does_not_claim_data_plane():
    rates = dict(five_qi=2, gbr_ul_mbps=2.34, mbr_ul_mbps=2.85, gbr_dl_mbps=1.8, mbr_dl_mbps=2.25)
    action = PolicyAction(run_id="test", snapshot_id="before", action_type="sm_policy_update", target={"supi":"imsi-208930000001001", "flow_id":"test-flow"}, parameters=rates)
    session = {"five_qi":2,"qfi":2,"active_sm_qos":dict(rates)}
    snap = SimpleNamespace(flows=[{"flow_id":"test-flow","supi":action.target.supi,"session":session,"ran":{"drb_id":2}}])
    assert verify_policy(action,snap)["data_plane_verified"] is False
    session["active_sm_qos"]["gbr_ul_mbps"]=2.25
    with pytest.raises(RuntimeError,match="readback mismatch"):
        verify_policy(action,snap)
