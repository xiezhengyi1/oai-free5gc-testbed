from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx


class SubscriberAdapter:
    def __init__(self, base_url: str, timeout_seconds: float = 10) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _url(self, ue_id: str, plmn_id: str) -> str:
        return f"{self.base_url}/api/subscriber/{quote(ue_id, safe='')}/{quote(plmn_id, safe='')}"

    def upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        ue_id = str(payload["ueId"])
        plmn_id = str(payload["plmnID"])
        response = httpx.put(self._url(ue_id, plmn_id), json=payload, timeout=self.timeout_seconds)
        response.raise_for_status()
        observed = self.get(ue_id, plmn_id)
        for field in (
            "AuthenticationSubscription",
            "SessionManagementSubscriptionData",
            "SmfSelectionSubscriptionData",
            "SmPolicyData",
        ):
            if observed.get(field) != payload.get(field):
                raise RuntimeError(f"subscriber readback mismatch for {ue_id}: {field}")
        return observed

    def update_policy(
        self,
        ue_id: str,
        plmn_id: str,
        flow_rule: dict[str, Any],
        qos_flow: dict[str, Any],
        charging_data: dict[str, Any],
    ) -> dict[str, Any]:
        subscriber = self.get(ue_id, plmn_id)
        policy_key = (
            flow_rule["snssai"],
            flow_rule["dnn"],
            flow_rule["qosRef"],
        )

        def matches(item: dict[str, Any]) -> bool:
            return (item.get("snssai"), item.get("dnn"), item.get("qosRef")) == policy_key

        flow_rules = [item for item in subscriber.get("FlowRules", []) if not matches(item)]
        qos_flows = [item for item in subscriber.get("QosFlows", []) if not matches(item)]
        charging_key = (
            charging_data["snssai"],
            charging_data["dnn"],
            charging_data["qosRef"],
            charging_data["filter"],
        )

        def charging_matches(item: dict[str, Any]) -> bool:
            return (
                item.get("snssai"),
                item.get("dnn"),
                item.get("qosRef"),
                item.get("filter"),
            ) == charging_key

        charging_rows = [
            item
            for item in subscriber.get("ChargingDatas", [])
            if not charging_matches(item)
        ]
        subscriber["FlowRules"] = [*flow_rules, flow_rule]
        subscriber["QosFlows"] = [*qos_flows, qos_flow]
        subscriber["ChargingDatas"] = [*charging_rows, charging_data]
        response = httpx.put(
            self._url(ue_id, plmn_id), json=subscriber, timeout=self.timeout_seconds
        )
        response.raise_for_status()
        observed = self.get(ue_id, plmn_id)
        observed_rule = next(item for item in observed.get("FlowRules", []) if matches(item))
        observed_qos = next(item for item in observed.get("QosFlows", []) if matches(item))
        observed_charging = next(
            item
            for item in observed.get("ChargingDatas", [])
            if charging_matches(item)
        )
        if (
            observed_rule != flow_rule
            or observed_qos != qos_flow
            or observed_charging != charging_data
        ):
            raise RuntimeError(f"policy readback mismatch for {ue_id}/{policy_key}")
        return observed

    def get(self, ue_id: str, plmn_id: str) -> dict[str, Any]:
        response = httpx.get(self._url(ue_id, plmn_id), timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("subscriber readback must be an object")
        return payload
