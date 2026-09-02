from __future__ import annotations

from dataclasses import dataclass

from testbed.gateway.contracts import PolicyAction
from testbed.scenario.schema import Scenario


@dataclass(frozen=True)
class TranslatedPolicy:
    ue_container: str
    traffic_sidecar: str
    plmn_id: str
    flow_rule: dict[str, object]
    qos_flow: dict[str, object]
    charging_data: dict[str, object]


def _bandwidth(value_mbps: float) -> str:
    return f"{round(value_mbps * 1000)} Kbps"


def translate_policy(scenario: Scenario, action: PolicyAction) -> TranslatedPolicy:
    ue = next(item for item in scenario.ues if item.supi == action.target.supi)
    flow = next(item for item in scenario.flows if item.id == action.target.flow_id)
    session = next(item for item in ue.sessions if item.id == flow.session_id)
    slice_spec = next(item for item in scenario.slices if item.id == session.slice_id)
    service = next(item for item in scenario.services if item.id == flow.service_instance_id)
    qos_ref = 1 + next(index for index, item in enumerate(scenario.flows) if item.id == flow.id)
    flow_rule: dict[str, object] = {
        "snssai": f"{slice_spec.sst:02d}{slice_spec.sd}",
        "dnn": session.dnn,
        "qosRef": qos_ref,
        "precedence": qos_ref,
        "filter": f"{service.ip} {flow.dst_port}-{flow.dst_port}",
    }
    qos_flow: dict[str, object] = {
        "snssai": f"{slice_spec.sst:02d}{slice_spec.sd}",
        "dnn": session.dnn,
        "qosRef": qos_ref,
        "5qi": action.parameters.five_qi,
        "mbrUL": _bandwidth(action.parameters.mbr_ul_mbps),
        "gbrUL": _bandwidth(action.parameters.gbr_ul_mbps),
        "mbrDL": _bandwidth(action.parameters.mbr_dl_mbps),
        "gbrDL": _bandwidth(action.parameters.gbr_dl_mbps),
    }
    charging_data: dict[str, object] = {
        "snssai": flow_rule["snssai"],
        "dnn": session.dnn,
        "qosRef": qos_ref,
        "filter": flow_rule["filter"],
        "chargingMethod": "Offline",
        "quota": "0",
        "ueId": action.target.supi,
    }
    return TranslatedPolicy(
        ue_container=ue.container,
        traffic_sidecar=ue.traffic_sidecar,
        plmn_id=f"{scenario.plmn.mcc}{scenario.plmn.mnc}",
        flow_rule=flow_rule,
        qos_flow=qos_flow,
        charging_data=charging_data,
    )
