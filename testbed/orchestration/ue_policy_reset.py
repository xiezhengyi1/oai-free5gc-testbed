"""Clear dynamic UE-policy runtime state before a run reset."""

from __future__ import annotations

import os
from pathlib import Path

from testbed.scenario.loader import load_scenario


def reset_policy_runtime(root: Path) -> None:
    scenario = load_scenario(root / "source-scenario.yaml")
    (root / "ue-policy" / "pcf" / "associations.json").unlink()
    for ue in scenario.ues:
        directory = root / "ue-policy" / ue.id
        prefix = ue.supi.removeprefix("imsi-")
        (directory / f"{prefix}.policy").unlink()
        (directory / f"{prefix}.policy.sock").unlink()
        (directory / f"{prefix}.policy.state.json").unlink()
        for flow in scenario.flows:
            if flow.ue_id == ue.id:
                (directory / f"{flow.id}.route.json").unlink()


if __name__ == "__main__":
    reset_policy_runtime(Path(os.environ["RUN_DIR"]))
