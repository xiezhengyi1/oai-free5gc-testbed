from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_metrics(run_dir: Path, metrics: dict[str, Any]) -> Path:
    path = run_dir / "metrics" / "latest.json"
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
