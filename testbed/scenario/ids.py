from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def stable_digest(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_run_id(run_id: str) -> str:
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", run_id) is None:
        raise ValueError("run_id must match [a-z0-9][a-z0-9-]{2,62}")
    return run_id


def stable_entity_id(run_id: str, entity_kind: str, entity_id: str) -> str:
    digest = hashlib.sha256(f"{run_id}:{entity_kind}:{entity_id}".encode()).hexdigest()[:16]
    return f"{entity_kind}-{digest}"
