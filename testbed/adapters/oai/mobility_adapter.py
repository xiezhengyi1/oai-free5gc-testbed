from __future__ import annotations

from typing import Any

import httpx


class MobilityAdapter:
    def __init__(self, endpoint: str, timeout_seconds: float = 10) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def set_channel(self, channel_name: str, parameters: dict[str, float]) -> dict[str, Any]:
        response = httpx.patch(
            f"{self.endpoint}/rfsimulator/channel/{channel_name}",
            json=parameters,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("OAI mobility response must be an object")
        return payload
