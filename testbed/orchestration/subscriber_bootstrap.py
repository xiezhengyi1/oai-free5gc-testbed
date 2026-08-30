from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from testbed.adapters.free5gc.subscriber_adapter import SubscriberAdapter


def provision_subscribers(
    payload_path: Path,
    base_url: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> list[dict[str, Any]]:
    payloads = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payloads, list) or not all(isinstance(item, dict) for item in payloads):
        raise ValueError("subscribers.json must contain a list of objects")
    adapter = SubscriberAdapter(base_url)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return [adapter.upsert(item) for item in payloads]
        except Exception:
            if time.monotonic() >= deadline:
                raise
            time.sleep(poll_seconds)
