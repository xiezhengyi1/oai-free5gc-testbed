from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import yaml

from testbed.scenario.schema import Scenario, UeSpec

REQUIRED_BASE_CONFIGS = (
    "nrfcfg.yaml",
    "amfcfg.yaml",
    "ausfcfg.yaml",
    "nssfcfg.yaml",
    "pcfcfg.yaml",
    "smfcfg.yaml",
    "udmcfg.yaml",
    "udrcfg.yaml",
    "nefcfg.yaml",
    "chfcfg.yaml",
    "webuicfg.yaml",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping in {path}")
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _s_nssai(scenario: Scenario, slice_id: str) -> dict[str, Any]:
    item = {entry.id: entry for entry in scenario.slices}[slice_id]
    return {"sst": item.sst, "sd": item.sd}


def _subscriber_payload(scenario: Scenario, ue: UeSpec) -> dict[str, Any]:
    session_by_slice: dict[str, list[Any]] = {}
    for session in ue.sessions:
        session_by_slice.setdefault(session.slice_id, []).append(session)
    default_slices = [_s_nssai(scenario, item) for item in session_by_slice]
    sm_data: list[dict[str, Any]] = []
    smf_selection: dict[str, Any] = {}
    sm_policy: dict[str, Any] = {}
    for slice_id, sessions in session_by_slice.items():
        snssai = _s_nssai(scenario, slice_id)
        key = f"{snssai['sst']:02d}{snssai['sd']}"
        dnn_configurations = {
            session.dnn: {
                "pduSessionTypes": {
                    "defaultSessionType": "IPV4",
                    "allowedSessionTypes": ["IPV4"],
                },
                "sscModes": {
                    "defaultSscMode": "SSC_MODE_1",
                    "allowedSscModes": ["SSC_MODE_1"],
                },
                "sessionAmbr": {"uplink": "1 Gbps", "downlink": "1 Gbps"},
                "5gQosProfile": {
                    "5qi": 9,
                    "arp": {"priorityLevel": 8, "preemptCap": "", "preemptVuln": ""},
                    "priorityLevel": 8,
                },
            }
            for session in sessions
        }
        sm_data.append({"singleNssai": snssai, "dnnConfigurations": dnn_configurations})
        smf_selection[key] = {"dnnInfos": [{"dnn": item.dnn} for item in sessions]}
        sm_policy[key] = {
            "snssai": snssai,
            "smPolicyDnnData": {item.dnn: {"dnn": item.dnn} for item in sessions},
        }
    digits = ue.supi.removeprefix("imsi-")
    return {
        "plmnID": f"{scenario.plmn.mcc}{scenario.plmn.mnc}",
        "ueId": ue.supi,
        "AuthenticationSubscription": {
            "authenticationMethod": "5G_AKA",
            "permanentKey": {
                "permanentKeyValue": ue.key,
                "encryptionKey": 0,
                "encryptionAlgorithm": 0,
            },
            "sequenceNumber": "000000000023",
            "authenticationManagementField": "8000",
            "opc": {"opcValue": ue.opc, "encryptionKey": 0, "encryptionAlgorithm": 0},
        },
        "AccessAndMobilitySubscriptionData": {
            "gpsis": [f"msisdn-{digits[-10:].zfill(10)}"],
            "nssai": {"defaultSingleNssais": default_slices, "singleNssais": default_slices},
            "subscribedUeAmbr": {"uplink": "1 Gbps", "downlink": "1 Gbps"},
        },
        "SessionManagementSubscriptionData": sm_data,
        "SmfSelectionSubscriptionData": {"subscribedSnssaiInfos": smf_selection},
        "AmPolicyData": {"subscCats": ["free5gc"]},
        "SmPolicyData": {"smPolicySnssaiData": sm_policy},
        "FlowRules": [],
        "QosFlows": [],
        "ChargingDatas": [],
    }


def _patch_amf(scenario: Scenario, config: dict[str, Any]) -> None:
    body = config["configuration"]
    body["ngapIpList"] = [scenario.core.amf.n2_ip]
    body["sbi"]["registerIPv4"] = scenario.core.amf.sbi_ip
    body["sbi"]["bindingIPv4"] = scenario.core.amf.sbi_ip
    body["servedGuamiList"] = [
        {"plmnId": {"mcc": scenario.plmn.mcc, "mnc": scenario.plmn.mnc}, "amfId": "cafe00"}
    ]
    body["supportTaiList"] = [
        {
            "plmnId": {"mcc": scenario.plmn.mcc, "mnc": scenario.plmn.mnc},
            "tac": f"{scenario.plmn.tac:06x}",
        }
    ]
    body["plmnSupportList"] = [
        {
            "plmnId": {"mcc": scenario.plmn.mcc, "mnc": scenario.plmn.mnc},
            "snssaiList": [{"sst": item.sst, "sd": item.sd} for item in scenario.slices],
        }
    ]
    body["supportDnnList"] = [item.dnn for item in scenario.core.upfs]
    body["nrfUri"] = "http://nrf.free5gc.org:8000"


def _patch_smf(scenario: Scenario, config: dict[str, Any]) -> None:
    body = config["configuration"]
    body["sbi"]["registerIPv4"] = scenario.core.smf.sbi_ip
    body["sbi"]["bindingIPv4"] = scenario.core.smf.sbi_ip
    body["plmnList"] = [{"mcc": scenario.plmn.mcc, "mnc": scenario.plmn.mnc}]
    body["pfcp"] = {
        "nodeID": scenario.core.smf.n4_ip,
        "listenAddr": scenario.core.smf.n4_ip,
        "externalAddr": scenario.core.smf.n4_ip,
    }
    body["snssaiInfos"] = []
    for slice_item in scenario.slices:
        dnns = sorted(
            {
                session.dnn
                for ue in scenario.ues
                for session in ue.sessions
                if session.slice_id == slice_item.id
            }
        )
        body["snssaiInfos"].append(
            {
                "sNssai": {"sst": slice_item.sst, "sd": slice_item.sd},
                "dnnInfos": [
                    {"dnn": dnn, "dns": {"ipv4": "8.8.8.8", "ipv6": "2001:4860:4860::8888"}}
                    for dnn in dnns
                ],
            }
        )
    access_network = "access-network"
    up_nodes: dict[str, Any] = {access_network: {"type": "AN"}}
    links: list[dict[str, str]] = []
    for upf in scenario.core.upfs:
        slice_infos = []
        for slice_item in scenario.slices:
            if any(
                session.dnn == upf.dnn and session.slice_id == slice_item.id
                for ue in scenario.ues
                for session in ue.sessions
            ):
                slice_infos.append(
                    {
                        "sNssai": {"sst": slice_item.sst, "sd": slice_item.sd},
                        "dnnUpfInfoList": [{"dnn": upf.dnn, "pools": [{"cidr": upf.ue_pool}]}],
                    }
                )
        up_nodes[upf.id] = {
            "type": "UPF",
            "nodeID": upf.n4_ip,
            "addr": upf.n4_ip,
            "sNssaiUpfInfos": slice_infos,
            "interfaces": [
                {"interfaceType": "N3", "endpoints": [upf.n3_ip], "networkInstances": [upf.dnn]}
            ],
        }
        links.append({"A": access_network, "B": upf.id})
    body["userplaneInformation"] = {"upNodes": up_nodes, "links": links}


def _upf_config(upf: Any) -> dict[str, Any]:
    return {
        "version": "1.0.3",
        "description": f"Generated configuration for {upf.id}",
        "pfcp": {"addr": upf.n4_ip, "nodeID": upf.n4_ip, "retransTimeout": "1s", "maxRetrans": 3},
        "gtpu": {
            "forwarder": "gtp5g",
            "ifList": [{"addr": upf.n3_ip, "type": "N3", "ifname": "n3"}],
        },
        "dnnList": [{"dnn": upf.dnn, "cidr": upf.ue_pool, "natifname": "n6"}],
        "logger": {"enable": True, "level": "info", "reportCaller": False},
    }


def render_free5gc(scenario: Scenario, generated_dir: Path) -> None:
    source = Path(scenario.sources.free5gc_compose)
    config_source = source / "config"
    cert_source = source / "cert"
    for name in REQUIRED_BASE_CONFIGS:
        (config_source / name).resolve(strict=True)
    cert_source.resolve(strict=True)

    destination = generated_dir / "free5gc-config"
    destination.mkdir(parents=True)
    for name in REQUIRED_BASE_CONFIGS:
        shutil.copy2(config_source / name, destination / name)
    shutil.copytree(cert_source, destination / "cert")

    nrf = _load_yaml(destination / "nrfcfg.yaml")
    nrf["configuration"]["DefaultPlmnId"] = {"mcc": scenario.plmn.mcc, "mnc": scenario.plmn.mnc}
    _write_yaml(destination / "nrfcfg.yaml", nrf)

    amf = _load_yaml(destination / "amfcfg.yaml")
    _patch_amf(scenario, amf)
    _write_yaml(destination / "amfcfg.yaml", amf)

    smf = _load_yaml(destination / "smfcfg.yaml")
    _patch_smf(scenario, smf)
    _write_yaml(destination / "smfcfg.yaml", smf)

    for upf in scenario.core.upfs:
        _write_yaml(destination / f"upfcfg-{upf.id}.yaml", _upf_config(upf))
        site_type = {site.id: site.type for site in scenario.sites}[upf.site_id]
        route_command = ""
        if site_type == "cloud":
            link = scenario.links[0]
            route_command = (
                f"ip route replace {scenario.networks.cloud_app.cidr} via {link.n6_ip} dev n6\n"
            )
        (destination / f"upf-iptables-{upf.id}.sh").write_text(
            "#!/bin/sh\nset -eu\niptables -t nat -A POSTROUTING -o n6 -j MASQUERADE\n"
            "iptables -I FORWARD 1 -j ACCEPT\n" + route_command,
            encoding="utf-8",
            newline="\n",
        )
    _write_yaml(
        destination / "uerouting.yaml",
        {
            "info": {"version": "1.0.7", "description": "Generated UE routing information"},
            "ueRoutingInfo": {},
            "routeProfile": {},
            "pfdDataForApp": [],
        },
    )
    subscribers = [_subscriber_payload(scenario, ue) for ue in scenario.ues]
    (generated_dir / "subscribers.json").write_text(
        json.dumps(subscribers, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
