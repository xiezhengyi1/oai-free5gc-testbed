from __future__ import annotations

from typing import Any

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.gateway.contracts import SliceLifecycleAction, SliceResourceAction
from testbed.orchestration.readiness import Readiness
from testbed.scenario.schema import Scenario
from testbed.state.slice_store import SlicePhase, SliceState, SliceStore, slice_bindings


class SliceManager:
    def __init__(
        self,
        scenario: Scenario,
        docker: DockerAdapter,
        readiness: Readiness,
        store: SliceStore,
    ) -> None:
        self.scenario = scenario
        self.docker = docker
        self.readiness = readiness
        self.store = store

    def reconcile_initial(self) -> dict[str, Any]:
        reconciled: dict[str, Any] = {}
        for state in self.store.list():
            if state.phase == SlicePhase.RUNNING:
                reconciled[state.slice_id] = {"phase": state.phase, "operation": "none"}
                continue
            for container in state.upf_containers:
                self.docker.stop(container)
            if state.phase == SlicePhase.DELETED:
                self.docker.compose_remove(list(state.upf_containers))
            reconciled[state.slice_id] = {
                "phase": state.phase,
                "operation": state.phase,
            }
        return reconciled

    def lifecycle(self, action: SliceLifecycleAction) -> tuple[dict[str, Any], SliceState]:
        current = self.store.get(action.target.slice_id)
        bindings = slice_bindings(self.scenario, current.slice_id)
        expected_phase = {
            "create_slice": SlicePhase.DELETED,
            "start_slice": SlicePhase.STOPPED,
            "stop_slice": SlicePhase.RUNNING,
            "delete_slice": SlicePhase.STOPPED,
        }[action.action_type]
        if current.phase != expected_phase:
            raise ValueError(
                f"{action.action_type} requires {expected_phase}, observed {current.phase}"
            )

        operation: dict[str, Any]
        next_phase: SlicePhase
        if action.action_type == "create_slice":
            self.docker.compose_create(list(bindings.upf_containers))
            operation = {
                container: {"running": self.docker.container_running(container)}
                for container in bindings.upf_containers
            }
            next_phase = SlicePhase.STOPPED
        elif action.action_type == "start_slice":
            started = {
                container: self.docker.start(container) for container in bindings.upf_containers
            }
            active_upfs = [
                container
                for state in self.store.list()
                if state.phase == SlicePhase.RUNNING or state.slice_id == current.slice_id
                for container in state.upf_containers
            ]
            operation = {
                "started": started,
                "upf_restarts": {
                    container: self.docker.restart(container) for container in active_upfs
                },
                "smf_restart": self.docker.restart("free5gc-smf"),
            }
            operation["pfcp"] = self.readiness.wait(
                lambda: self.readiness.pfcp_associations(len(active_upfs))
            )
            operation["ue_restarts"] = {}
            operation["pdu"] = {}
            for ue in self.scenario.ues:
                operation["ue_restarts"][ue.id] = self.docker.restart(ue.container)
                self.readiness.wait(lambda ue=ue: self.readiness.ue_registered(ue))
                operation["pdu"][ue.id] = self.readiness.wait(
                    lambda ue=ue: self.readiness.pdu(ue)
                )
            operation["traffic_sidecar_restarts"] = {
                ue.id: self.docker.restart(ue.traffic_sidecar) for ue in self.scenario.ues
            }
            operation["traffic"] = self.readiness.wait(
                lambda: self.readiness.traffic_for_slice(current.slice_id)
            )
            next_phase = SlicePhase.RUNNING
        elif action.action_type == "stop_slice":
            operation = {
                container: self.docker.stop(container) for container in bindings.upf_containers
            }
            next_phase = SlicePhase.STOPPED
        else:
            self.docker.compose_remove(list(bindings.upf_containers))
            operation = {container: {"removed": True} for container in bindings.upf_containers}
            next_phase = SlicePhase.DELETED

        updated = self.store.advance(current.slice_id, next_phase)
        return (
            {
                "slice_id": current.slice_id,
                "phase_before": current.phase,
                "phase_after": updated.phase,
                "upf_containers": list(bindings.upf_containers),
                "ue_ids": list(bindings.ue_ids),
                "flow_ids": list(bindings.flow_ids),
                "operation": operation,
            },
            updated,
        )

    def resources(self, action: SliceResourceAction) -> dict[str, Any]:
        current = self.store.get(action.target.slice_id)
        if current.phase == SlicePhase.DELETED:
            raise ValueError("slice resources cannot be updated while the slice is deleted")
        bindings = slice_bindings(self.scenario, current.slice_id)
        return {
            container: self.docker.update_resources(
                container,
                action.parameters.cpus,
                action.parameters.memory_mb,
            )
            for container in bindings.upf_containers
        }
