from __future__ import annotations

from pathlib import Path

from testbed.orchestration.launcher import Launcher
from testbed.state.models import RunState


def reset_run(run_dir: Path) -> RunState:
    return Launcher(run_dir).reset()
