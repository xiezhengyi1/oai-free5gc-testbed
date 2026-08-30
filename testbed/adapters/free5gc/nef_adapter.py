from __future__ import annotations

from typing import Any

import httpx


class NefAdapter:
    def __init__(
        self, base_url: str = "http://nef.free5gc.org:8000", timeout_seconds: float = 10
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def create_traffic_influence(self, af_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}/3gpp-traffic-influence/v1/{af_id}/subscriptions",
            json=payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("NEF response must be an object")
        return result
