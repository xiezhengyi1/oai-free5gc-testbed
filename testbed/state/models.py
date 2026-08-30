from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from testbed.scenario.schema import StrictModel


class RunPhase(StrEnum):
    CREATED = "CREATED"
    CORE_READY = "CORE_READY"
    PFCP_READY = "PFCP_READY"
    GNB_READY = "GNB_READY"
    UE_REGISTERED = "UE_REGISTERED"
    PDU_READY = "PDU_READY"
    TRAFFIC_READY = "TRAFFIC_READY"
    TELEMETRY_READY = "TELEMETRY_READY"
    RUNNING = "RUNNING"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


class RunState(StrictModel):
    run_id: str
    phase: RunPhase
    sequence: int = Field(ge=0)
    reset_generation: int = Field(ge=0)
    observed_at: datetime
    evidence: dict[str, Any]
    failed_phase: RunPhase | None = None
    error: str | None = None

    @classmethod
    def created(cls, run_id: str, reset_generation: int = 0) -> RunState:
        return cls(
            run_id=run_id,
            phase=RunPhase.CREATED,
            sequence=0,
            reset_generation=reset_generation,
            observed_at=datetime.now(UTC),
            evidence={},
        )
