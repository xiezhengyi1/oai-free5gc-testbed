from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from testbed.scenario.ids import stable_digest, validate_run_id
from testbed.scenario.schema import Scenario, StrictModel
from testbed.scenario.topology import build_topology


class CompiledScenario(StrictModel):
    run_id: str
    scenario_id: str
    schema_version: str
    compiled_at: datetime
    scenario_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_path: str
    scenario: dict[str, Any]
    topology: dict[str, list[dict[str, Any]]]


def compile_scenario(scenario: Scenario, source_path: str | Path, run_id: str) -> CompiledScenario:
    normalized_run_id = validate_run_id(run_id)
    payload = scenario.model_dump(mode="json", by_alias=True)
    return CompiledScenario(
        run_id=normalized_run_id,
        scenario_id=scenario.scenario_id,
        schema_version=scenario.schema_version,
        compiled_at=datetime.now(UTC),
        scenario_sha256=stable_digest(payload),
        source_path=str(Path(source_path).resolve(strict=True)),
        scenario=payload,
        topology=build_topology(scenario),
    )
