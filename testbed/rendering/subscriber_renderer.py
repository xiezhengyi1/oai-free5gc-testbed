from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_subscriber_payloads(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"subscriber payload must be a list of objects: {path}")
    return payload
