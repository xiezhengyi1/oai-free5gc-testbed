"""Initialize only the run-scoped policy directories for root/cap-drop OAI."""
import os
from pathlib import Path

from testbed.scenario.loader import load_scenario


def main() -> None:
    root = Path(os.environ["RUN_DIR"])
    scenario = load_scenario(root / "source-scenario.yaml")
    for ue in scenario.ues:
        path = root / "ue-policy" / ue.id
        os.chown(path, 0, 0)
        path.chmod(0o755)
    prometheus = root / "ue-policy/databases/prometheus"
    prometheus.mkdir(parents=True, exist_ok=True)
    os.chown(prometheus, 65534, 65534)


if __name__ == "__main__":
    main()
