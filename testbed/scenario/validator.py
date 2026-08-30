from __future__ import annotations

from collections.abc import Iterable
from ipaddress import IPv4Address, IPv4Network

from testbed.scenario.schema import Scenario


def _unique(values: Iterable[str], label: str) -> None:
    items = list(values)
    duplicates = sorted({item for item in items if items.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label}: {', '.join(duplicates)}")


def _network(cidr: str, label: str) -> IPv4Network:
    network = IPv4Network(cidr, strict=True)
    if network.version != 4:
        raise ValueError(f"{label} must be IPv4")
    return network


def _host_in(ip: str, network: IPv4Network, label: str) -> None:
    address = IPv4Address(ip)
    if address not in network or address in {network.network_address, network.broadcast_address}:
        raise ValueError(f"{label}={ip} is not a usable host in {network}")


def validate_scenario(scenario: Scenario) -> None:
    slices = {item.id: item for item in scenario.slices}
    sites = {item.id: item for item in scenario.sites}
    gnbs = {item.id: item for item in scenario.ran.gnbs}
    ues = {item.id: item for item in scenario.ues}
    services = {item.id: item for item in scenario.services}
    upfs = {item.id: item for item in scenario.core.upfs}

    _unique(slices, "slice id")
    _unique(sites, "site id")
    _unique(gnbs, "gNB id")
    _unique((cell.id for gnb in scenario.ran.gnbs for cell in gnb.cells), "cell id")
    _unique(ues, "UE id")
    _unique((ue.supi for ue in scenario.ues), "SUPI")
    _unique(services, "service id")
    _unique(upfs, "UPF id")
    _unique((upf.dnn for upf in scenario.core.upfs), "UPF DNN")
    _unique((flow.id for flow in scenario.flows), "flow id")
    _unique((link.id for link in scenario.links), "link id")
    _unique(
        (
            *(upf.container for upf in scenario.core.upfs),
            *(gnb.container for gnb in scenario.ran.gnbs),
            *(ue.container for ue in scenario.ues),
            *(ue.traffic_sidecar for ue in scenario.ues),
            *(service.container for service in scenario.services),
            *(link.container for link in scenario.links),
        ),
        "container name",
    )

    docker_networks = {
        "sbi-net": _network(scenario.networks.sbi.cidr, "sbi-net"),
        "n2-net": _network(scenario.networks.n2.cidr, "n2-net"),
        "n3-net": _network(scenario.networks.n3.cidr, "n3-net"),
        "n4-net": _network(scenario.networks.n4.cidr, "n4-net"),
        "edge-n6-net": _network(scenario.networks.edge_n6.cidr, "edge-n6-net"),
        "cloud-n6-net": _network(scenario.networks.cloud_n6.cidr, "cloud-n6-net"),
        "cloud-app-net": _network(scenario.networks.cloud_app.cidr, "cloud-app-net"),
        "monitoring-net": _network(scenario.networks.monitoring.cidr, "monitoring-net"),
        "control-net": _network(scenario.networks.control.cidr, "control-net"),
    }
    ue_pools = {upf.id: _network(upf.ue_pool, f"UPF {upf.id} UE pool") for upf in upfs.values()}
    all_networks = [*docker_networks.items(), *((f"ue-pool:{k}", v) for k, v in ue_pools.items())]
    for index, (left_name, left) in enumerate(all_networks):
        for right_name, right in all_networks[index + 1 :]:
            if left.overlaps(right):
                raise ValueError(f"CIDR overlap: {left_name}={left} and {right_name}={right}")

    _host_in(scenario.core.amf.sbi_ip, docker_networks["sbi-net"], "AMF SBI")
    _host_in(scenario.core.amf.n2_ip, docker_networks["n2-net"], "AMF N2")
    _host_in(scenario.core.smf.sbi_ip, docker_networks["sbi-net"], "SMF SBI")
    _host_in(scenario.core.smf.n4_ip, docker_networks["n4-net"], "SMF N4")

    for upf in upfs.values():
        if upf.site_id not in sites:
            raise ValueError(f"UPF {upf.id} references unknown site {upf.site_id}")
        _host_in(upf.n3_ip, docker_networks["n3-net"], f"UPF {upf.id} N3")
        _host_in(upf.n4_ip, docker_networks["n4-net"], f"UPF {upf.id} N4")
        n6_name = "edge-n6-net" if sites[upf.site_id].type == "edge" else "cloud-n6-net"
        _host_in(upf.n6_ip, docker_networks[n6_name], f"UPF {upf.id} N6")

    for gnb in gnbs.values():
        if gnb.site_id not in sites:
            raise ValueError(f"gNB {gnb.id} references unknown site {gnb.site_id}")
        _host_in(gnb.n2_ip, docker_networks["n2-net"], f"gNB {gnb.id} N2")
        _host_in(gnb.n3_ip, docker_networks["n3-net"], f"gNB {gnb.id} N3")

    dnn_to_upf = {item.dnn: item for item in upfs.values()}
    for ue in ues.values():
        if ue.serving_gnb not in gnbs:
            raise ValueError(f"UE {ue.id} references unknown gNB {ue.serving_gnb}")
        _unique((session.id for session in ue.sessions), f"session id for {ue.id}")
        for session in ue.sessions:
            if session.slice_id not in slices:
                raise ValueError(
                    f"session {session.id} references unknown slice {session.slice_id}"
                )
            if session.dnn not in dnn_to_upf:
                raise ValueError(f"session {session.id} references unknown DNN {session.dnn}")

    for service in services.values():
        if service.site_id not in sites:
            raise ValueError(f"service {service.id} references unknown site {service.site_id}")
        expected_network = (
            "edge-n6-net" if sites[service.site_id].type == "edge" else "cloud-app-net"
        )
        if service.network != expected_network:
            raise ValueError(f"service {service.id} must use {expected_network}")
        _host_in(service.ip, docker_networks[service.network], f"service {service.id}")
        if scenario.resources.containers.get(service.container) != service.resources:
            raise ValueError(f"service {service.id} resources must match the central resource plan")

    for link in scenario.links:
        _host_in(link.n6_ip, docker_networks["cloud-n6-net"], f"link {link.id} N6")
        _host_in(link.app_side_ip, docker_networks["cloud-app-net"], f"link {link.id} app side")

    cloud_sites = {site.id for site in scenario.sites if site.type == "cloud"}
    cloud_path_required = any(upf.site_id in cloud_sites for upf in upfs.values()) or any(
        service.site_id in cloud_sites for service in services.values()
    )
    if cloud_path_required and len(scenario.links) != 1:
        raise ValueError("a cloud path requires exactly one declared cloud link")
    if not cloud_path_required and scenario.links:
        raise ValueError("cloud links cannot be declared without a cloud UPF or service")

    previous_event_time = 0
    for event in scenario.mobility:
        if event.ue_id not in ues:
            raise ValueError(f"mobility event references unknown UE {event.ue_id}")
        if event.target_gnb not in gnbs:
            raise ValueError(f"mobility event references unknown gNB {event.target_gnb}")
        if event.at_seconds <= previous_event_time:
            raise ValueError("mobility events must be strictly time ordered")
        previous_event_time = event.at_seconds

    five_tuples: set[tuple[str, str, int, int]] = set()
    for flow in scenario.flows:
        if flow.ue_id not in ues:
            raise ValueError(f"flow {flow.id} references unknown UE {flow.ue_id}")
        if flow.service_instance_id not in services:
            raise ValueError(
                f"flow {flow.id} references unknown service {flow.service_instance_id}"
            )
        session_map = {item.id: item for item in ues[flow.ue_id].sessions}
        if flow.session_id not in session_map:
            raise ValueError(f"flow {flow.id} references unknown session {flow.session_id}")
        session = session_map[flow.session_id]
        service = services[flow.service_instance_id]
        if dnn_to_upf[session.dnn].site_id != service.site_id:
            raise ValueError(f"flow {flow.id} session DNN and service resolve to different sites")
        expected_port = {"tcp": 5201, "udp": 5202, "http": service.port}[flow.protocol]
        if flow.dst_port != expected_port:
            raise ValueError(
                f"flow {flow.id} protocol {flow.protocol} requires destination port {expected_port}"
            )
        key = (flow.ue_id, flow.protocol, flow.src_port, flow.dst_port)
        if key in five_tuples:
            raise ValueError(f"flow {flow.id} duplicates a declared five-tuple")
        five_tuples.add(key)

    expected_containers = {
        *(upf.container for upf in upfs.values()),
        *(gnb.container for gnb in gnbs.values()),
        *(ue.container for ue in ues.values()),
        *(service.container for service in services.values()),
    }
    unknown_resource_targets = set(scenario.resources.containers) - expected_containers
    if unknown_resource_targets:
        raise ValueError(
            f"resource plan contains unknown containers: {sorted(unknown_resource_targets)}"
        )
    missing_resource_targets = expected_containers - set(scenario.resources.containers)
    if missing_resource_targets:
        raise ValueError(f"resource plan is missing containers: {sorted(missing_resource_targets)}")

    assigned = [
        scenario.core.amf.sbi_ip,
        scenario.core.amf.n2_ip,
        scenario.core.smf.sbi_ip,
        scenario.core.smf.n4_ip,
        *(upf.n3_ip for upf in upfs.values()),
        *(upf.n4_ip for upf in upfs.values()),
        *(upf.n6_ip for upf in upfs.values()),
        *(gnb.n2_ip for gnb in gnbs.values()),
        *(gnb.n3_ip for gnb in gnbs.values()),
        *(service.ip for service in services.values()),
        *(link.n6_ip for link in scenario.links),
        *(link.app_side_ip for link in scenario.links),
    ]
    _unique(assigned, "static IP")
