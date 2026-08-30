from __future__ import annotations

from typing import Any

import httpx


class PcfAdapter:
    def __init__(self, timeout_seconds: float = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def read_sm_policy_association(self, policy_uri: str) -> dict[str, Any]:
        if not policy_uri.startswith("http://pcf.free5gc.org:8000/"):
            raise ValueError("policy_uri must target the run-scoped free5GC PCF")
        response = httpx.get(policy_uri, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("PCF policy response must be an object")
        return payload
