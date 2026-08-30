from __future__ import annotations

import json
import subprocess
from ipaddress import IPv4Network

from testbed.scenario.schema import Scenario


def host_route_conflicts(scenario: Scenario) -> list[dict[str, str]]:
    output = subprocess.run(
        ["ip", "-j", "-4", "route", "show"], check=True, capture_output=True, text=True
    ).stdout
    routes = json.loads(output)
    declared = {
        "sbi-net": IPv4Network(scenario.networks.sbi.cidr),
        "n2-net": IPv4Network(scenario.networks.n2.cidr),
        "n3-net": IPv4Network(scenario.networks.n3.cidr),
        "n4-net": IPv4Network(scenario.networks.n4.cidr),
        "edge-n6-net": IPv4Network(scenario.networks.edge_n6.cidr),
        "cloud-n6-net": IPv4Network(scenario.networks.cloud_n6.cidr),
        "cloud-app-net": IPv4Network(scenario.networks.cloud_app.cidr),
        "monitoring-net": IPv4Network(scenario.networks.monitoring.cidr),
        "control-net": IPv4Network(scenario.networks.control.cidr),
        **{f"ue-pool:{upf.id}": IPv4Network(upf.ue_pool) for upf in scenario.core.upfs},
    }
    conflicts: list[dict[str, str]] = []
    for route in routes:
        destination = route.get("dst")
        if destination in (None, "default"):
            continue
        route_network = IPv4Network(destination, strict=False)
        for name, network in declared.items():
            if route_network.overlaps(network):
                conflicts.append(
                    {"declared": name, "cidr": str(network), "host_route": str(route_network)}
                )
    return conflicts
