from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import Field

from testbed.scenario.schema import Scenario, SliceCapacitySpec, StrictModel


class SlicePhase(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    DELETED = "deleted"


class SliceState(StrictModel):
    slice_id: str
    snssai: str
    phase: SlicePhase
    sequence: int = Field(ge=0)
    observed_at: datetime
    upf_containers: tuple[str, ...]
    ue_ids: tuple[str, ...]
    flow_ids: tuple[str, ...]
    capacity: SliceCapacitySpec


class SliceCatalogState(StrictModel):
    run_id: str
    sequence: int = Field(ge=0)
    observed_at: datetime
    slices: tuple[SliceState, ...]


@dataclass(frozen=True, slots=True)
class SliceBindings:
    slice_id: str
    upf_containers: tuple[str, ...]
    ue_ids: tuple[str, ...]
    ue_containers: tuple[str, ...]
    traffic_sidecars: tuple[str, ...]
    flow_ids: tuple[str, ...]


def slice_bindings(scenario: Scenario, slice_id: str) -> SliceBindings:
    upf_by_dnn = {item.dnn: item for item in scenario.core.upfs}
    ue_sessions = {
        ue.id: tuple(session for session in ue.sessions if session.slice_id == slice_id)
        for ue in scenario.ues
    }
    ue_ids = tuple(ue.id for ue in scenario.ues if ue_sessions[ue.id])
    return SliceBindings(
        slice_id=slice_id,
        upf_containers=tuple(
            sorted(
                {
                    upf_by_dnn[session.dnn].container
                    for sessions in ue_sessions.values()
                    for session in sessions
                }
            )
        ),
        ue_ids=ue_ids,
        ue_containers=tuple(ue.container for ue in scenario.ues if ue.id in ue_ids),
        traffic_sidecars=tuple(
            ue.traffic_sidecar for ue in scenario.ues if ue.id in ue_ids
        ),
        flow_ids=tuple(
            flow.id
            for flow in scenario.flows
            if flow.ue_id in ue_sessions
            and any(
                session.id == flow.session_id for session in ue_sessions[flow.ue_id]
            )
        ),
    )


class SliceStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.current_path = self.run_dir / "slice-state.json"
        self.history_path = self.run_dir / "slice-state.jsonl"

    def initialize(self, scenario: Scenario) -> SliceCatalogState:
        if self.current_path.exists():
            raise FileExistsError(f"slice state already exists: {self.current_path}")
        observed_at = datetime.now(UTC)
        slices = []
        for slice_item in scenario.slices:
            bindings = slice_bindings(scenario, slice_item.id)
            slices.append(
                SliceState(
                    slice_id=slice_item.id,
                    snssai=f"{slice_item.sst:02d}{slice_item.sd}",
                    phase=SlicePhase(slice_item.initial_state),
                    sequence=0,
                    observed_at=observed_at,
                    upf_containers=bindings.upf_containers,
                    ue_ids=bindings.ue_ids,
                    flow_ids=bindings.flow_ids,
                    capacity=slice_item.capacity,
                )
            )
        return self._write(
            SliceCatalogState(
                run_id=self.run_dir.name,
                sequence=0,
                observed_at=observed_at,
                slices=tuple(slices),
            )
        )

    def current(self) -> SliceCatalogState:
        return SliceCatalogState.model_validate_json(
            self.current_path.read_text(encoding="utf-8")
        )

    def list(self) -> tuple[SliceState, ...]:
        return self.current().slices

    def get(self, slice_id: str) -> SliceState:
        return next(item for item in self.list() if item.slice_id == slice_id)

    def advance(self, slice_id: str, phase: SlicePhase) -> SliceState:
        catalog = self.current()
        current = next(item for item in catalog.slices if item.slice_id == slice_id)
        allowed = {
            SlicePhase.RUNNING: {SlicePhase.STOPPED},
            SlicePhase.STOPPED: {SlicePhase.RUNNING, SlicePhase.DELETED},
            SlicePhase.DELETED: {SlicePhase.STOPPED},
        }
        if phase not in allowed[current.phase]:
            raise ValueError(f"invalid slice transition {current.phase} -> {phase}")
        observed_at = datetime.now(UTC)
        updated = current.model_copy(
            update={
                "phase": phase,
                "sequence": current.sequence + 1,
                "observed_at": observed_at,
            }
        )
        slices = tuple(
            updated if item.slice_id == slice_id else item for item in catalog.slices
        )
        self._write(
            SliceCatalogState(
                run_id=catalog.run_id,
                sequence=catalog.sequence + 1,
                observed_at=observed_at,
                slices=slices,
            )
        )
        return updated

    def _write(self, state: SliceCatalogState) -> SliceCatalogState:
        body = state.model_dump_json() + "\n"
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(body)
        self.current_path.write_text(
            state.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        return state
