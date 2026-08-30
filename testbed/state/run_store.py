from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from testbed.state.models import RunPhase, RunState

PHASE_ORDER = (
    RunPhase.CREATED,
    RunPhase.CORE_READY,
    RunPhase.PFCP_READY,
    RunPhase.GNB_READY,
    RunPhase.UE_REGISTERED,
    RunPhase.PDU_READY,
    RunPhase.TRAFFIC_READY,
    RunPhase.TELEMETRY_READY,
    RunPhase.RUNNING,
)


class RunStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.current_path = self.run_dir / "current-state.json"
        self.history_path = self.run_dir / "state.jsonl"

    def initialize(self) -> RunState:
        if self.current_path.exists():
            raise FileExistsError(f"run state already exists: {self.current_path}")
        return self._write(RunState.created(self.run_dir.name))

    def current(self) -> RunState:
        return RunState.model_validate_json(self.current_path.read_text(encoding="utf-8"))

    def advance(self, phase: RunPhase, evidence: dict[str, Any]) -> RunState:
        current = self.current()
        if current.phase not in PHASE_ORDER:
            raise ValueError(f"cannot advance terminal phase {current.phase}")
        expected_index = PHASE_ORDER.index(current.phase) + 1
        if expected_index >= len(PHASE_ORDER) or PHASE_ORDER[expected_index] != phase:
            raise ValueError(f"invalid phase transition {current.phase} -> {phase}")
        state = RunState(
            run_id=current.run_id,
            phase=phase,
            sequence=current.sequence + 1,
            reset_generation=current.reset_generation,
            observed_at=datetime.now(UTC),
            evidence=evidence,
        )
        return self._write(state)

    def fail(self, failed_phase: RunPhase, error: Exception, evidence: dict[str, Any]) -> RunState:
        current = self.current()
        state = RunState(
            run_id=current.run_id,
            phase=RunPhase.FAILED,
            sequence=current.sequence + 1,
            reset_generation=current.reset_generation,
            observed_at=datetime.now(UTC),
            evidence=evidence,
            failed_phase=failed_phase,
            error=f"{type(error).__name__}: {error}",
        )
        return self._write(state)

    def stop(self, evidence: dict[str, Any]) -> RunState:
        current = self.current()
        return self._write(
            RunState(
                run_id=current.run_id,
                phase=RunPhase.STOPPED,
                sequence=current.sequence + 1,
                reset_generation=current.reset_generation,
                observed_at=datetime.now(UTC),
                evidence=evidence,
            )
        )

    def reset(self) -> RunState:
        current = self.current()
        state = RunState.created(current.run_id, current.reset_generation + 1).model_copy(
            update={"sequence": current.sequence + 1}
        )
        return self._write(state)

    def _write(self, state: RunState) -> RunState:
        body = state.model_dump_json() + "\n"
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(body)
        self.current_path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return state
