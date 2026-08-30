from __future__ import annotations

from pathlib import Path

import yaml

from testbed.scenario.schema import Scenario
from testbed.scenario.validator import validate_scenario


def load_scenario(path: str | Path) -> Scenario:
    source = Path(path).resolve(strict=True)
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"scenario root must be a mapping: {source}")
    scenario = Scenario.model_validate(payload)
    validate_scenario(scenario)
    return scenario
