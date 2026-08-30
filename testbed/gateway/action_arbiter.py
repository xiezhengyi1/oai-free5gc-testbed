from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from testbed.gateway.contracts import LifecycleAction, PolicyAction, ResourceAction
from testbed.scenario.schema import Scenario
from testbed.telemetry.models import UnifiedSnapshot
from testbed.telemetry.snapshot_writer import SnapshotStore


class ActionArbiter:
    def __init__(self, run_dir: Path, scenario: Scenario) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.scenario = scenario
        self.snapshots = SnapshotStore(self.run_dir)

    def authorize(self, principal: str, action: object) -> None:
        if isinstance(action, PolicyAction) and principal != "multiagents":
            raise PermissionError("PolicyAction requires the multiagents principal")
        if isinstance(action, (ResourceAction, LifecycleAction)) and principal != "project":
            raise PermissionError(
                "ResourceAction and LifecycleAction require the project principal"
            )

    def validate_snapshot(self, run_id: str, snapshot_id: str) -> UnifiedSnapshot:
        if run_id != self.run_dir.name:
            raise ValueError(f"action run_id does not match active run: {run_id}")
        snapshot = self.snapshots.get(snapshot_id)
        if snapshot.run_id != run_id:
            raise ValueError("snapshot belongs to another run")
        age = datetime.now(UTC) - snapshot.observed_to
        if age.total_seconds() > self.scenario.runtime.action_timeout_seconds:
            raise ValueError(f"snapshot is stale: {snapshot_id}")
        return snapshot

    def validate_policy_target(self, action: PolicyAction, snapshot: UnifiedSnapshot) -> None:
        ue = next((item for item in self.scenario.ues if item.supi == action.target.supi), None)
        flow = next(
            (item for item in self.scenario.flows if item.id == action.target.flow_id), None
        )
        if ue is None or flow is None or flow.ue_id != ue.id:
            raise ValueError("policy target is not a declared UE/flow pair")
        observed = next(
            (item for item in snapshot.flows if item["flow_id"] == action.target.flow_id), None
        )
        if observed is None or observed["supi"] != action.target.supi:
            raise ValueError("policy target is absent from the referenced snapshot")
        if observed["data_quality"]["correlation_status"] != "complete":
            raise ValueError("policy target correlation is incomplete")

    def validate_container(self, container: str) -> None:
        if container not in self.scenario.resources.containers:
            raise ValueError(f"container is not resource-action allowlisted: {container}")
