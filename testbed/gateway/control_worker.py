from __future__ import annotations

import argparse
from pathlib import Path

from testbed.orchestration.launcher import Launcher


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("reset", "stop"))
    parser.add_argument("run_dir", type=Path)
    arguments = parser.parse_args()
    launcher = Launcher(arguments.run_dir)
    if arguments.operation == "reset":
        launcher.reset()
    else:
        launcher.stop()


if __name__ == "__main__":
    main()
