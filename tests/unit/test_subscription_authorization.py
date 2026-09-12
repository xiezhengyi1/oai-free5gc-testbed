import copy
from types import SimpleNamespace

import pytest

from testbed.gateway.subscription_authorization import AuthorizationParameters, authorization_digest, project_authorization
from testbed.rendering.free5gc_renderer import _subscriber_payload


@pytest.fixture
def catalog():
    # Only fields used by provisioning are required by this focused fixture.
    class UE(SimpleNamespace):
        def model_copy(self, *, update):
            return UE(**(vars(self) | update))
    sessions = [SimpleNamespace(id="initial", slice_id="s1", dnn="embb"),
                SimpleNamespace(id="on-demand", slice_id="s2", dnn="urllc")]
    ue = UE(id="ue-1", supi="imsi-208930000000009", key="0" * 32, opc="1" * 32, sessions=sessions)
    scenario = SimpleNamespace(plmn=SimpleNamespace(mcc="208", mnc="93"), flows=[],
                               services=[], slices=[SimpleNamespace(id="s1", sst=1, sd="000001"),
                                                    SimpleNamespace(id="s2", sst=2, sd="000001")])
    return scenario, ue, _subscriber_payload(scenario, ue)


def parameters(current, sessions):
    return AuthorizationParameters(expected_digest=authorization_digest(current), session_ids=sessions,
        policy={"plmn": "20893", "upsc": 1, "rules": [{"precedence": 1, "routes": [
            {"precedence": 1, "dnn": "embb", "sst": 1, "sd": "000001"}]}]})


def test_revoke_and_grant_all_four_authorization_views(catalog):
    scenario, ue, current = catalog
    original = copy.deepcopy(current)
    reduced = project_authorization(scenario, ue, current, parameters(current, ["initial"]))
    assert current == original
    assert len(reduced["AccessAndMobilitySubscriptionData"]["nssai"]["defaultSingleNssais"]) == 1
    assert len(reduced["SessionManagementSubscriptionData"]) == 1
    assert set(reduced["SmfSelectionSubscriptionData"]["subscribedSnssaiInfos"]) == {"01000001"}
    assert set(reduced["SmPolicyData"]["smPolicySnssaiData"]) == {"01000001"}
    granted = project_authorization(scenario, ue, reduced, parameters(reduced, ["initial", "on-demand"]))
    assert granted == current


def test_stale_subscription_and_unknown_catalog_are_rejected(catalog):
    scenario, ue, current = catalog
    action = parameters(current, ["initial"])
    current["SessionManagementSubscriptionData"][0]["dnnConfigurations"]["embb"]["sessionAmbr"]["uplink"] = "2 Gbps"
    with pytest.raises(ValueError, match="changed since"):
        project_authorization(scenario, ue, current, action)
    with pytest.raises(ValueError, match="catalog"):
        project_authorization(scenario, ue, current, parameters(current, ["initial", "not-deployed"]))
    with pytest.raises(ValueError, match="initial connectivity"):
        project_authorization(scenario, ue, current, parameters(current, ["on-demand"]))


def test_revoked_route_cannot_be_rebound(catalog):
    scenario, ue, current = catalog
    action = parameters(current, ["initial"])
    data = action.model_dump(mode="json")
    data["policy"]["rules"][0]["routes"][0].update(dnn="urllc", sst=2)
    action = AuthorizationParameters.model_validate(data)
    with pytest.raises(ValueError, match="not subscribed"):
        project_authorization(scenario, ue, current, action)


def test_retained_subscription_metadata_is_preserved(catalog):
    scenario, ue, current = catalog
    current["AccessAndMobilitySubscriptionData"]["nssai"]["supportedFeatures"] = "1"
    current["SessionManagementSubscriptionData"][0]["sharedVnGroupDataIds"] = {"group": "retained"}
    current["SmfSelectionSubscriptionData"]["supportedFeatures"] = "2"
    current["SmfSelectionSubscriptionData"]["subscribedSnssaiInfos"]["01000001"]["dnnInfos"][0]["defaultDnnIndicator"] = True
    current["SmPolicyData"]["smPolicySnssaiData"]["01000001"]["smPolicyDnnData"]["embb"]["offline"] = True
    reduced = project_authorization(scenario, ue, current, parameters(current, ["initial"]))
    assert reduced["AccessAndMobilitySubscriptionData"]["nssai"]["supportedFeatures"] == "1"
    assert reduced["SessionManagementSubscriptionData"][0]["sharedVnGroupDataIds"] == {"group": "retained"}
    assert reduced["SmfSelectionSubscriptionData"]["supportedFeatures"] == "2"
    assert reduced["SmfSelectionSubscriptionData"]["subscribedSnssaiInfos"]["01000001"]["dnnInfos"][0]["defaultDnnIndicator"]
    assert reduced["SmPolicyData"]["smPolicySnssaiData"]["01000001"]["smPolicyDnnData"]["embb"]["offline"]
