from __future__ import annotations

from typing import Any

import httpx


class PrometheusAdapter:
    def __init__(self, base_url: str, timeout_seconds: float = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def ready(self) -> None:
        response = httpx.get(f"{self.base_url}/-/ready", timeout=self.timeout_seconds)
        response.raise_for_status()

    def instant_query(self, query: str, timestamp: float | None = None) -> list[dict[str, Any]]:
        parameters: dict[str, Any] = {"query": query}
        if timestamp is not None:
            parameters["time"] = timestamp
        response = httpx.get(
            f"{self.base_url}/api/v1/query", params=parameters, timeout=self.timeout_seconds
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success" or payload["data"]["resultType"] != "vector":
            raise ValueError(f"unexpected Prometheus response for query {query!r}")
        return payload["data"]["result"]

    def range_query(
        self, query: str, start: float, end: float, step: float
    ) -> list[dict[str, Any]]:
        response = httpx.get(
            f"{self.base_url}/api/v1/query_range",
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success" or payload["data"]["resultType"] != "matrix":
            raise ValueError(f"unexpected Prometheus range response for query {query!r}")
        return payload["data"]["result"]
