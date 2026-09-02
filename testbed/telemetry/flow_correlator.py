from __future__ import annotations

from datetime import datetime
from typing import Any

from testbed.scenario.schema import FlowSpec, Scenario


def correlate_flow(
    scenario: Scenario,
    flow: FlowSpec,
    session: dict[str, Any] | None,
    ran: dict[str, Any],
    telemetry: dict[str, Any],
    allocation_state: dict[str, Any] | None,
    observed_from: datetime,
    observed_to: datetime,
    sample_count: int,
) -> dict[str, Any]:
    ues = {item.id: item for item in scenario.ues}
    services = {item.id: item for item in scenario.services}
    slices = {item.id: item for item in scenario.slices}
    upfs = {item.dnn: item for item in scenario.core.upfs}
    ue = ues[flow.ue_id]
    pdu = {item.id: item for item in ue.sessions}[flow.session_id]
    service = services[flow.service_instance_id]
    slice_item = slices[pdu.slice_id]
    upf = upfs[pdu.dnn]
    flow_ran = dict(ran)
    if session is not None and "drb_id" in session:
        flow_ran["drb_id"] = session["drb_id"]
    required_session = {"qfi", "five_qi", "ue_ip", "ul_teid", "dl_teid"}
    required_ran = {"rnti", "drb_id"}
    complete = (
        session is not None
        and required_session <= session.keys()
        and required_ran <= flow_ran.keys()
        and sample_count > 0
    )
    allocated_bandwidth_ul = (
        allocation_state["allocated_bandwidth_ul_mbps"]
        if allocation_state is not None
        else flow.allocation.allocated_bandwidth_ul_mbps
    )
    allocated_bandwidth_dl = (
        allocation_state["allocated_bandwidth_dl_mbps"]
        if allocation_state is not None
        else flow.allocation.allocated_bandwidth_dl_mbps
    )
    transport_protocol = "tcp" if flow.protocol == "http" else flow.protocol
    ue_ip = session.get("ue_ip") if session else None
    return {
        "id": flow.id,
        "name": flow.id,
        "flow_id": flow.id,
        "supi": ue.supi,
        "app_id": service.service_id,
        "app_name": service.service_id,
        "sla": {
            "latency": flow.sla.latency_ms,
            "jitter": flow.sla.jitter_ms,
            "loss_rate": flow.sla.loss_rate,
            "bandwidth_ul": flow.sla.bandwidth_ul_mbps,
            "bandwidth_dl": flow.sla.bandwidth_dl_mbps,
            "guaranteed_bandwidth_ul": flow.sla.guaranteed_bandwidth_ul_mbps,
            "guaranteed_bandwidth_dl": flow.sla.guaranteed_bandwidth_dl_mbps,
            "priority": flow.sla.priority,
        },
        "allocation": {
            "current_slice_snssai": f"{slice_item.sst:02d}{slice_item.sd}",
            "allocated_bandwidth_ul": allocated_bandwidth_ul,
            "allocated_bandwidth_dl": allocated_bandwidth_dl,
            "source_action_id": (
                allocation_state["source_action_id"] if allocation_state is not None else None
            ),
        },
        "traffic": {
            "five_tuple": [
                ue_ip,
                service.ip,
                flow.src_port,
                flow.dst_port,
                transport_protocol,
            ],
            "packet_size": flow.packet_size_bytes * 8,
            "packet_size_unit": "bits",
            "packet_size_bytes": flow.packet_size_bytes,
            "arrival_rate": (
                flow.rate_mbps * 1_000_000 / (flow.packet_size_bytes * 8)
            ),
            "arrival_rate_unit": "packets_per_second",
            "offered_rate_mbps": flow.rate_mbps,
        },
        "telemetry": telemetry,
        "ran": {
            "serving_cell_id": next(
                gnb.cells[0].id for gnb in scenario.ran.gnbs if gnb.id == ue.serving_gnb
            ),
            "gnb_id": ue.serving_gnb,
            **flow_ran,
        },
        "session": {
            "pdu_session_id": session.get("pdu_session_id") if session else None,
            "dnn": pdu.dnn,
            "snssai": f"{slice_item.sst:02d}{slice_item.sd}",
            "qfi": session.get("qfi") if session else None,
            "five_qi": session.get("five_qi") if session else None,
            "upf_id": upf.container,
            "ue_ip": ue_ip,
            "ul_teid": session.get("ul_teid") if session else None,
            "dl_teid": session.get("dl_teid") if session else None,
            "sm_policy_uri": session.get("sm_policy_uri") if session else None,
        },
        "path": {
            "site_id": service.site_id,
            "service_instance_id": service.id,
            "upf_path": [upf.container],
            "app_endpoint": f"{service.ip}:{flow.dst_port}",
        },
        "data_quality": {
            "window_start": observed_from.isoformat(),
            "window_end": observed_to.isoformat(),
            "sample_count": sample_count,
            "stale": sample_count == 0,
            "correlation_status": "complete" if complete else "incomplete",
        },
    }
