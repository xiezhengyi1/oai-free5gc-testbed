import copy

import pytest

from testbed.gateway.ue_policy import AMAction, URSPPolicy, expected_rule, validate_subscription


def policy():
    return URSPPolicy.model_validate(
        {
            "plmn": "20893",
            "upsc": 1,
            "rules": [
                {
                    "precedence": 1,
                    "remoteIpv4": "192.0.2.0/24",
                    "protocol": 6,
                    "remotePort": 443,
                    "routes": [{"precedence": 1, "dnn": "embb", "sst": 1, "sd": "000001"}],
                },
                {
                    "precedence": 255,
                    "routes": [{"precedence": 1, "dnn": "urllc", "sst": 2, "sd": "000001"}],
                },
            ],
        }
    )


def subscriber():
    slices = [{"sst": 1, "sd": "000001"}, {"sst": 2, "sd": "000001"}]
    return {
        "AccessAndMobilitySubscriptionData": {
            "nssai": {"defaultSingleNssais": slices, "singleNssais": []}
        },
        "SessionManagementSubscriptionData": [
            {"singleNssai": row, "dnnConfigurations": {dnn: {}}}
            for row, dnn in zip(slices, ["embb", "urllc"], strict=True)
        ],
    }


def test_subscription_is_slice_and_dnn_scoped():
    validate_subscription(policy(), subscriber())
    data = subscriber()
    data["SessionManagementSubscriptionData"][0]["dnnConfigurations"] = {"other": {}}
    with pytest.raises(ValueError, match="DNN embb is not subscribed"):
        validate_subscription(policy(), data)
    data = subscriber()
    data["AccessAndMobilitySubscriptionData"]["nssai"]["defaultSingleNssais"].pop()
    with pytest.raises(ValueError, match="S-NSSAI 2/000001 is not subscribed"):
        validate_subscription(policy(), data)


def test_oracle_matches_prefix_protocol_and_port():
    assert expected_rule(policy(), "192.0.2.1", 6, 443).precedence == 1
    for ip, protocol, port in [
        ("198.51.100.1", 6, 443),
        ("192.0.2.1", 17, 443),
        ("192.0.2.1", 6, 80),
    ]:
        assert expected_rule(policy(), ip, protocol, port).precedence == 255


def test_duplicate_precedence_and_ipv6_are_rejected():
    data = policy().model_dump(mode="json")
    duplicate = copy.deepcopy(data)
    duplicate["rules"][1]["precedence"] = 1
    with pytest.raises(ValueError, match="unique"):
        URSPPolicy.model_validate(duplicate)
    data["rules"][0]["remoteIpv4"] = "::/0"
    with pytest.raises(ValueError):
        URSPPolicy.model_validate(data)


def test_am_is_ue_scoped_and_rfsp_is_not_a_qos_knob():
    data = {
        "run_id": "test",
        "snapshot_id": "s1",
        "action_type": "am_policy_apply",
        "target": {"supi": "imsi-208930000000009"},
        "parameters": {"associationId": "am-1", "rfsp": 256},
    }
    assert AMAction.model_validate(data).parameters.rfsp == 256
    for invalid in (0, 257):
        data["parameters"]["rfsp"] = invalid
        with pytest.raises(ValueError):
            AMAction.model_validate(data)
