from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def write_final_report(run_dir: Path, status: str, evidence: dict[str, Any]) -> Path:
    path = run_dir / "final-report.json"
    payload = {
        "run_id": run_dir.name,
        "status": status,
        "completed_at": datetime.now(UTC).isoformat(),
        "evidence": evidence,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
