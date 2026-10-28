from __future__ import annotations

import os
from typing import Any

import httpx


class PcfAdapter:
    def __init__(self, timeout_seconds: float = 10) -> None:
        self.timeout_seconds = timeout_seconds

    def ue_policy(self, supi: str) -> dict[str, Any]:
        response = httpx.get(
            f"http://pcf.free5gc.org:8000/testbed-policy/v1/ues/{supi}",
            headers={"Authorization": f"Bearer {os.environ['UE_POLICY_ADMIN_TOKEN']}"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def apply_ue_policy(self, supi: str, domain: str, parameters: dict) -> dict:
        if domain not in {"am", "ursp"}:
            raise ValueError("unknown policy domain")
        response = httpx.post(
            f"http://pcf.free5gc.org:8000/testbed-policy/v1/ues/{supi}/{domain}",
            headers={"Authorization": f"Bearer {os.environ['UE_POLICY_ADMIN_TOKEN']}"},
            json=parameters,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def apply_sm_policy(self, supi: str, parameters: dict[str, Any]) -> dict[str, Any]:
        response = httpx.post(
            f"http://pcf.free5gc.org:8000/testbed-policy/v1/ues/{supi}/sm",
            headers={"Authorization": f"Bearer {os.environ['UE_POLICY_ADMIN_TOKEN']}"},
            json=parameters,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def read_sm_policy_association(self, policy_uri: str) -> dict[str, Any]:
        if not policy_uri.startswith("http://pcf.free5gc.org:8000/"):
            raise ValueError("policy_uri must target the run-scoped free5GC PCF")
        response = httpx.get(policy_uri, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("PCF policy response must be an object")
        return payload
