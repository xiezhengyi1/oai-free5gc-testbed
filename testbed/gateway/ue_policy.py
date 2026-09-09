from __future__ import annotations

from ipaddress import IPv4Address, IPv4Network
from typing import Literal

from pydantic import Field, model_validator

from testbed.gateway.contracts import PolicyTarget
from testbed.scenario.schema import StrictModel


class URSPRoute(StrictModel):
    precedence: int = Field(ge=0, le=255)
    dnn: str = Field(min_length=1, max_length=100)
    sst: int = Field(ge=0, le=255)
    sd: str = Field(pattern=r"^[0-9a-f]{6}$")


class URSPRule(StrictModel):
    precedence: int = Field(ge=0, le=255)
    remoteIpv4: IPv4Network | None = None
    protocol: Literal[0, 6, 17] = 0
    remotePort: int = Field(default=0, ge=0, le=65535)
    routes: list[URSPRoute] = Field(min_length=1, max_length=8)


class URSPPolicy(StrictModel):
    plmn: str = Field(pattern=r"^\d{5,6}$")
    upsc: int = Field(ge=0, le=65535)
    rules: list[URSPRule] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_precedence(self):
        if len({rule.precedence for rule in self.rules}) != len(self.rules):
            raise ValueError("URSP rule precedence must be unique")
        for rule in self.rules:
            if len({route.precedence for route in rule.routes}) != len(rule.routes):
                raise ValueError("route descriptor precedence must be unique")
        return self


class URSPParameters(StrictModel):
    associationId: str = Field(min_length=1)
    expectedVersion: int = Field(ge=0)
    policy: URSPPolicy


class URSPAction(StrictModel):
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action_type: Literal["ursp_apply"]
    target: PolicyTarget
    parameters: URSPParameters


class AMParameters(StrictModel):
    associationId: str = Field(min_length=1)
    rfsp: int = Field(ge=1, le=256)


class UETarget(StrictModel):
    supi: str = Field(pattern=r"^imsi-\d{5,15}$")


class AMAction(StrictModel):
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action_type: Literal["am_policy_apply"]
    target: UETarget
    parameters: AMParameters


def validate_subscription(policy: URSPPolicy, subscriber: dict) -> None:
    nssai = subscriber["AccessAndMobilitySubscriptionData"]["nssai"]
    subscribed = {(row["sst"], row["sd"].lower()) for row in nssai["singleNssais"]}
    subscribed |= {(row["sst"], row["sd"].lower()) for row in nssai["defaultSingleNssais"]}
    sm_data = subscriber["SessionManagementSubscriptionData"]
    for rule in policy.rules:
        for route in rule.routes:
            if (route.sst, route.sd) not in subscribed:
                raise ValueError(f"S-NSSAI {route.sst}/{route.sd} is not subscribed")
            allowed = any(
                row["singleNssai"]["sst"] == route.sst
                and row["singleNssai"]["sd"].lower() == route.sd
                and route.dnn in row["dnnConfigurations"]
                for row in sm_data
            )
            if not allowed:
                raise ValueError(f"DNN {route.dnn} is not subscribed for {route.sst}/{route.sd}")


def expected_rule(policy: URSPPolicy, remote_ip: str, protocol: int, port: int) -> URSPRule:
    """Independent verification oracle; never controls the UE or sidecar route."""
    address = IPv4Address(remote_ip)
    matches = [
        rule
        for rule in policy.rules
        if (rule.remoteIpv4 is None or address in rule.remoteIpv4)
        and rule.protocol in (0, protocol)
        and rule.remotePort in (0, port)
    ]
    if not matches:
        raise ValueError("URSP does not cover the verification flow")
    return min(matches, key=lambda rule: rule.precedence)
