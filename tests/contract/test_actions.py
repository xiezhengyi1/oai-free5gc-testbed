from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from testbed.gateway import executor as executor_module
from testbed.gateway.action_arbiter import ActionArbiter
from testbed.gateway.contracts import (
    PolicyAction,
    ResourceAction,
    SliceLifecycleAction,
    SliceResourceAction,
)
from testbed.gateway.executor import ActionExecutor
from testbed.gateway.policy_translator import translate_policy
from testbed.scenario.loader import load_scenario
from testbed.state.lock_store import TargetLock
from testbed.state.run_store import RunStore
from testbed.telemetry.models import UnifiedSnapshot
from testbed.telemetry.snapshot_writer import SnapshotStore

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
            "parameters": {
                "five_qi": 2,
                "gbr_ul_mbps": 15,
                "mbr_ul_mbps": 20,
                "gbr_dl_mbps": 12,
                "mbr_dl_mbps": 18,
            },
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
    arbiter = ActionArbiter(tmp_path, scenario, "run-001")
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
    slice_lifecycle = SliceLifecycleAction.model_validate(
        {
            "run_id": "run-001",
            "snapshot_id": "snapshot-100",
            "action_type": "stop_slice",
            "target": {"slice_id": "embb"},
        }
    )
    slice_resource = SliceResourceAction.model_validate(
        {
            "run_id": "run-001",
            "snapshot_id": "snapshot-100",
            "action_type": "update_slice_resources",
            "target": {"slice_id": "embb"},
            "parameters": {"cpus": 3, "memory_mb": 1536},
        }
    )
    with pytest.raises(PermissionError, match="project"):
        arbiter.authorize("multiagents", slice_lifecycle)
    with pytest.raises(PermissionError, match="project"):
        arbiter.authorize("multiagents", slice_resource)


def test_action_rejects_a_snapshot_from_the_previous_baseline(
    tmp_path: Path,
) -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    metrics = tmp_path / "metrics"
    metrics.mkdir()
    (tmp_path / "snapshots.jsonl").touch()
    runs = RunStore(tmp_path)
    runs.initialize()
    now = datetime.now(UTC)
    snapshot = UnifiedSnapshot(
        snapshot_id="snapshot-before-reset",
        run_id=tmp_path.name,
        baseline_epoch=runs.current_baseline_epoch(),
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
        trigger_event="contract-test",
    )
    SnapshotStore(tmp_path).append(snapshot)
    arbiter = ActionArbiter(tmp_path, scenario, tmp_path.name)

    assert arbiter.validate_snapshot(tmp_path.name, snapshot.snapshot_id) == snapshot
    runs.reset()

    with pytest.raises(ValueError, match="baseline_invalid"):
        arbiter.validate_snapshot(tmp_path.name, snapshot.snapshot_id)


def test_policy_translation_is_explicit_and_stable() -> None:
    scenario = load_scenario(ROOT / "scenarios/validation/s4_policy_change.yaml")
    translated = translate_policy(scenario, policy_action())
    assert translated.ue_container == "oai-nrue-1"
    assert translated.plmn_id == "20893"
    assert translated.flow_rule["dnn"] == "mec"
    assert translated.flow_rule["filter"] == "172.34.0.100 5202-5202"
    assert translated.qos_flow["5qi"] == 2
    assert translated.qos_flow["gbrUL"] == "15000 Kbps"
    assert translated.qos_flow["mbrUL"] == "20000 Kbps"
    assert translated.qos_flow["gbrDL"] == "12000 Kbps"
    assert translated.qos_flow["mbrDL"] == "18000 Kbps"
    assert translated.charging_data == {
        "snssai": "01010203",
        "dnn": "mec",
        "qosRef": 1,
        "filter": "172.34.0.100 5202-5202",
        "chargingMethod": "Offline",
        "quota": "0",
        "ueId": "imsi-208930000000001",
    }


def test_target_lock_rejects_a_concurrent_writer(tmp_path: Path) -> None:
    with (
        TargetLock(tmp_path, "container:free5gc-upf-edge"),
        pytest.raises(FileExistsError),
        TargetLock(tmp_path, "container:free5gc-upf-edge"),
    ):
        pass


def test_sm_policy_update_uses_the_live_pcf_association_without_restarting_the_ue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = load_scenario(ROOT / "scenarios/validation/s4_policy_change.yaml")
    deliveries: list[tuple[str, dict[str, object]]] = []

    class Snapshots:
        def __init__(self, _run_dir: Path) -> None:
            pass

        def get(self, _snapshot_id: str):
            return SimpleNamespace(
                flows=(
                    {
                        "flow_id": "inference-edge-flow",
                        "supi": "imsi-208930000000001",
                        "session": {
                            "dnn": "mec",
                            "snssai": "01010203",
                            "sm_policy_uri": (
                                "http://pcf.free5gc.org:8000/npcf-smpolicycontrol/"
                                "v1/sm-policies/policy-42"
                            ),
                        },
                    },
                )
            )

    class Watchdog:
        def __init__(self, _timeout: float, _poll: float) -> None:
            pass

        def wait(self, _action, _snapshot):
            return SimpleNamespace(snapshot_id="snapshot-after"), {"verified": True}

    executor = object.__new__(ActionExecutor)
    executor.run_dir = ROOT
    executor.scenario = scenario
    executor.pcf = SimpleNamespace(
        apply_sm_policy=lambda supi, parameters: (
            deliveries.append((supi, parameters)) or {"delivery": "smf_callback_accepted"}
        )
    )
    executor.flow_allocations = SimpleNamespace(update=lambda *_args: None)
    executor._snapshot = lambda _trigger: SimpleNamespace(snapshot_id="snapshot-after")
    executor._receipt = lambda *_args: SimpleNamespace(status="verified")
    monkeypatch.setattr(executor_module, "SnapshotStore", Snapshots)
    monkeypatch.setattr(executor_module, "PolicyWatchdog", Watchdog)

    ActionExecutor._apply_policy(executor, policy_action(), datetime.now(UTC))

    assert deliveries == [
        (
            "imsi-208930000000001",
            {
                "associationId": "policy-42",
                "dnn": "mec",
                "snssai": "01010203",
                "qosRef": 1,
                "precedence": 1,
                "filter": "172.34.0.100 5202-5202",
                "5qi": 2,
                "maxbrUl": "20000 Kbps",
                "maxbrDl": "18000 Kbps",
                "gbrUl": "15000 Kbps",
                "gbrDl": "12000 Kbps",
            },
        )
    ]
