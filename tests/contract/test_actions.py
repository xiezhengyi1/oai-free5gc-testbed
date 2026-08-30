from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from testbed.gateway.action_arbiter import ActionArbiter
from testbed.gateway.contracts import PolicyAction, ResourceAction
from testbed.gateway.policy_translator import translate_policy
from testbed.scenario.loader import load_scenario
from testbed.state.lock_store import TargetLock

ROOT = Path(__file__).resolve().parents[2]


def policy_action() -> PolicyAction:
    return PolicyAction.model_validate(
        {
            "run_id": "run-001",
            "snapshot_id": "snapshot-100",
            "action_type": "sm_policy_update",
            "target": {
                "supi": "imsi-208930000000001",
                "flow_id": "inference-edge-flow",
            },
            "parameters": {"five_qi": 2, "gbr_ul_mbps": 15, "mbr_ul_mbps": 20},
        }
    )


def test_action_contract_rejects_unknown_fields_and_invalid_bandwidth() -> None:
    payload = policy_action().model_dump(mode="json")
    payload["parameters"]["gbr_ul_mbps"] = 25
    payload["parameters"]["hidden_default"] = True
    with pytest.raises(ValidationError):
        PolicyAction.model_validate(payload)


def test_principal_ownership_is_exclusive(tmp_path: Path) -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    arbiter = ActionArbiter(tmp_path, scenario)
    with pytest.raises(PermissionError, match="multiagents"):
        arbiter.authorize("project", policy_action())
    resource = ResourceAction.model_validate(
        {
            "run_id": "run-001",
            "snapshot_id": "snapshot-100",
            "action_type": "update_container_resources",
            "target": {"container": "free5gc-upf-edge"},
            "parameters": {"cpus": 3, "memory_mb": 1536},
        }
    )
    with pytest.raises(PermissionError, match="project"):
        arbiter.authorize("multiagents", resource)


def test_policy_translation_is_explicit_and_stable() -> None:
    scenario = load_scenario(ROOT / "scenarios/validation/s4_policy_change.yaml")
    translated = translate_policy(scenario, policy_action())
    assert translated.ue_container == "oai-nrue-1"
    assert translated.plmn_id == "20893"
    assert translated.flow_rule["dnn"] == "mec"
    assert translated.flow_rule["filter"] == ("permit out udp from any 41001 to 172.34.0.100 5202")
    assert translated.qos_flow["5qi"] == 2
    assert translated.qos_flow["gbrUL"] == "15000 Kbps"


def test_target_lock_rejects_a_concurrent_writer(tmp_path: Path) -> None:
    with (
        TargetLock(tmp_path, "container:free5gc-upf-edge"),
        pytest.raises(FileExistsError),
        TargetLock(tmp_path, "container:free5gc-upf-edge"),
    ):
        pass
