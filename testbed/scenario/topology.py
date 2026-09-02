from __future__ import annotations

from typing import Any

from testbed.scenario.schema import Scenario


def build_topology(scenario: Scenario) -> dict[str, list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    upf_by_dnn = {item.dnn: item for item in scenario.core.upfs}
    service_by_id = {item.id: item for item in scenario.services}

    for slice_item in scenario.slices:
        nodes.append(
            {
                "id": slice_item.id,
                "type": "slice",
                "attributes": {
                    "sst": slice_item.sst,
                    "sd": slice_item.sd,
                    "initial_state": slice_item.initial_state,
                },
            }
        )
    for site in scenario.sites:
        nodes.append({"id": site.id, "type": "site", "attributes": {"site_type": site.type}})
    for gnb in scenario.ran.gnbs:
        nodes.append({"id": gnb.id, "type": "gnb", "attributes": {"site_id": gnb.site_id}})
        edges.append({"source": gnb.site_id, "target": gnb.id, "type": "hosts"})
        for cell in gnb.cells:
            nodes.append({"id": cell.id, "type": "cell", "attributes": {"pci": cell.pci}})
            edges.append({"source": gnb.id, "target": cell.id, "type": "serves"})
    for upf in scenario.core.upfs:
        nodes.append({"id": upf.id, "type": "upf", "attributes": {"dnn": upf.dnn}})
        edges.append({"source": upf.site_id, "target": upf.id, "type": "hosts"})
    slice_upf_edges = {
        (session.slice_id, upf_by_dnn[session.dnn].id)
        for ue in scenario.ues
        for session in ue.sessions
    }
    edges.extend(
        {"source": slice_id, "target": upf_id, "type": "uses_upf"}
        for slice_id, upf_id in sorted(slice_upf_edges)
    )
    for service in scenario.services:
        nodes.append(
            {
                "id": service.id,
                "type": "service_instance",
                "attributes": {
                    "service_id": service.service_id,
                    "endpoint": f"{service.ip}:{service.port}",
                },
            }
        )
        edges.append({"source": service.site_id, "target": service.id, "type": "hosts"})
    for ue in scenario.ues:
        nodes.append({"id": ue.id, "type": "ue", "attributes": {"supi": ue.supi}})
        edges.append({"source": ue.id, "target": ue.serving_gnb, "type": "attached_to"})
        session_by_id = {item.id: item for item in ue.sessions}
        for flow in (item for item in scenario.flows if item.ue_id == ue.id):
            session = session_by_id[flow.session_id]
            upf = upf_by_dnn[session.dnn]
            service = service_by_id[flow.service_instance_id]
            nodes.append(
                {
                    "id": flow.id,
                    "type": "flow",
                    "attributes": {"protocol": flow.protocol, "session_id": session.id},
                }
            )
            edges.extend(
                [
                    {"source": ue.id, "target": flow.id, "type": "originates"},
                    {"source": session.slice_id, "target": flow.id, "type": "carries"},
                    {"source": flow.id, "target": upf.id, "type": "traverses"},
                    {"source": flow.id, "target": service.id, "type": "terminates_at"},
                ]
            )
    return {"nodes": nodes, "edges": edges}
