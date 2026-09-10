"""Clear dynamic UE-policy runtime state before a run reset."""

from __future__ import annotations

import os
from pathlib import Path

from testbed.scenario.loader import load_scenario


def reset_policy_runtime(root: Path) -> None:
    scenario = load_scenario(root / "source-scenario.yaml")
    for association in (root / "ue-policy" / "pcf").glob("associations.json"):
        association.unlink()
    for ue in scenario.ues:
        directory = root / "ue-policy" / ue.id
        prefix = ue.supi.removeprefix("imsi-")
        for artifact in directory.glob(f"{prefix}.policy*"):
            artifact.unlink()
        for route in directory.glob("*.route.json"):
            route.unlink()


if __name__ == "__main__":
    reset_policy_runtime(Path(os.environ["RUN_DIR"]))
