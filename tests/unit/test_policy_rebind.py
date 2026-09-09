from copy import deepcopy

import pytest

from testbed.gateway.policy_rebind import rebind_policy


class PCF:
    def __init__(self, status="complete"):
        self.applied = []
        self.status = status

    def ue_policy(self, _supi):
        return {
            "ue_policy_associations": [
                {
                    "id": "new-ue",
                    "version": int(bool(self.applied)),
                    "status": self.status if self.applied else "associated",
                }
            ],
            "am_policy_associations": [{"id": "new-am", "rfsp": 0}],
        }

    def apply_ue_policy(self, supi, domain, parameters):
        self.applied.append((supi, domain, deepcopy(parameters)))
        return {"id": "new-ue"}


def previous():
    return {
        "ue_policy_associations": [{"id": "old-ue", "policy": {"upsc": 1, "rules": []}}],
        "am_policy_associations": [{"id": "old-am", "rfsp": 64}],
    }


def test_rebind_preserves_policy_uses_new_associations_and_confirms_ue():
    pcf = PCF()
    result = rebind_policy(pcf, "imsi-1", previous(), timeout=1, poll=0)
    assert result["ue_association_id"] == "new-ue" and result["ursp_status"] == "complete"
    assert pcf.applied == [
        (
            "imsi-1",
            "ursp",
            {"associationId": "new-ue", "expectedVersion": 0, "policy": {"upsc": 1, "rules": []}},
        ),
        ("imsi-1", "am", {"associationId": "new-am", "rfsp": 64}),
    ]


def test_rebind_reject_is_not_reported_as_success():
    pcf = PCF("rejected")
    with pytest.raises(RuntimeError, match="URSP rebind failed"):
        rebind_policy(pcf, "imsi-1", previous(), timeout=1, poll=0)
    assert [item[1] for item in pcf.applied] == ["ursp"]
