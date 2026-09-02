from __future__ import annotations

from unittest.mock import MagicMock

from testbed.gateway.contracts import SliceLifecycleAction, SliceResourceAction
from testbed.gateway.slice_manager import SliceManager
from testbed.scenario.loader import load_scenario
from testbed.state.slice_store import SlicePhase, SliceStore


def _lifecycle(action_type: str, slice_id: str = "embb") -> SliceLifecycleAction:
    return SliceLifecycleAction.model_validate(
        {
            "run_id": "slice-run",
            "snapshot_id": "snapshot-1",
            "action_type": action_type,
            "target": {"slice_id": slice_id},
        }
    )


def test_configured_slice_runs_full_lifecycle_and_resource_update(tmp_path) -> None:
    scenario = load_scenario("scenarios/mvp/s1_single_ue_single_upf.yaml")
    store = SliceStore(tmp_path)
    store.initialize(scenario)
    docker = MagicMock()
    readiness = MagicMock()
    readiness.pfcp_associations.return_value = {"accepted_associations": 1}
    readiness.ue_registered.return_value = {"supi": scenario.ues[0].supi}
    readiness.pdu.return_value = [{"interface": "oaitun_ue1"}]
    readiness.traffic_for_slice.return_value = {"inference-edge-flow": "ok"}
    readiness.wait.side_effect = lambda probe: probe()
    docker.container_running.return_value = False
    manager = SliceManager(scenario, docker, readiness, store)

    stop_effect, stopped = manager.lifecycle(_lifecycle("stop_slice"))
    assert stopped.phase == SlicePhase.STOPPED
    assert stop_effect["upf_containers"] == ["free5gc-upf-edge"]
    docker.stop.assert_called_once_with("free5gc-upf-edge")

    _delete_effect, deleted = manager.lifecycle(_lifecycle("delete_slice"))
    assert deleted.phase == SlicePhase.DELETED
    docker.compose_remove.assert_called_once_with(["free5gc-upf-edge"])

    _create_effect, created = manager.lifecycle(_lifecycle("create_slice"))
    assert created.phase == SlicePhase.STOPPED
    docker.compose_create.assert_called_once_with(["free5gc-upf-edge"])

    _start_effect, running = manager.lifecycle(_lifecycle("start_slice"))
    assert running.phase == SlicePhase.RUNNING
    docker.start.assert_called_once_with("free5gc-upf-edge")
    docker.restart.assert_any_call("free5gc-upf-edge")
    docker.restart.assert_any_call("free5gc-smf")
    docker.restart.assert_any_call("oai-nrue-1")
    docker.restart.assert_any_call("traffic-sidecar-ue-1")
    readiness.pfcp_associations.assert_called_once_with(1)

    resource = SliceResourceAction.model_validate(
        {
            "run_id": "slice-run",
            "snapshot_id": "snapshot-2",
            "action_type": "update_slice_resources",
            "target": {"slice_id": "embb"},
            "parameters": {"cpus": 3, "memory_mb": 1536},
        }
    )
    manager.resources(resource)
    docker.update_resources.assert_called_once_with("free5gc-upf-edge", 3.0, 1536)


def test_start_slice_rebuilds_all_active_pfcp_and_ue_sessions(tmp_path) -> None:
    scenario = load_scenario("scenarios/advanced/s7_managed_multi_slice.yaml")
    store = SliceStore(tmp_path)
    store.initialize(scenario)
    store.advance("urllc", SlicePhase.STOPPED)
    docker = MagicMock()
    readiness = MagicMock()
    readiness.pfcp_associations.return_value = {"accepted_associations": 3}
    readiness.ue_registered.side_effect = lambda ue: {"supi": ue.supi}
    readiness.pdu.side_effect = lambda ue: [{"ue_id": ue.id}]
    readiness.traffic_for_slice.return_value = {
        "ue-1-urllc-flow": "ok",
        "ue-2-urllc-flow": "ok",
        "ue-3-urllc-flow": "ok",
        "ue-4-urllc-flow": "ok",
    }
    readiness.wait.side_effect = lambda probe: probe()
    manager = SliceManager(scenario, docker, readiness, store)

    effect, running = manager.lifecycle(_lifecycle("start_slice", "urllc"))

    assert running.phase == SlicePhase.RUNNING
    docker.start.assert_called_once_with("free5gc-upf-urllc")
    assert effect["operation"]["upf_restarts"] == {
        "free5gc-upf-embb": docker.restart.return_value,
        "free5gc-upf-urllc": docker.restart.return_value,
        "free5gc-upf-mmtc": docker.restart.return_value,
    }
    readiness.pfcp_associations.assert_called_once_with(3)
    assert readiness.ue_registered.call_count == 4
    assert readiness.pdu.call_count == 4
    docker.restart.assert_any_call("free5gc-smf")
    docker.restart.assert_any_call("oai-nrue-1")
    docker.restart.assert_any_call("oai-nrue-2")
    docker.restart.assert_any_call("oai-nrue-3")
    docker.restart.assert_any_call("oai-nrue-4")
    docker.restart.assert_any_call("traffic-sidecar-ue-1")
    docker.restart.assert_any_call("traffic-sidecar-ue-2")
    docker.restart.assert_any_call("traffic-sidecar-ue-3")
    docker.restart.assert_any_call("traffic-sidecar-ue-4")
