from __future__ import annotations

import json
from pathlib import Path

import yaml

from testbed.artifacts.manifest_writer import RunLayout
from testbed.rendering.compose_renderer import _render_compose
from testbed.rendering.free5gc_renderer import _patch_smf, _subscriber_payload
from testbed.rendering.oai_gnb_renderer import render_gnb_config
from testbed.rendering.observability_renderer import render_prometheus
from testbed.rendering.traffic_renderer import render_traffic_profiles
from testbed.scenario.loader import load_scenario
from testbed.scenario.topology import build_topology

ROOT = Path(__file__).resolve().parents[2]


def test_compose_fragments_render_to_one_valid_model(tmp_path: Path) -> None:
    generated = tmp_path / "generated"
    generated.mkdir()
    layout = RunLayout(
        root=tmp_path,
        generated=generated,
        logs=tmp_path / "logs",
        metrics=tmp_path / "metrics",
        pcaps=tmp_path / "pcaps",
    )
    scenario = load_scenario(ROOT / "scenarios/mvp/s2_single_ue_edge_cloud.yaml")
    _render_compose(ROOT, layout, scenario, "render-001")
    compose = yaml.safe_load((generated / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["name"] == "testbed-render-001"
    assert compose["networks"]["sbi-net"]["ipam"]["config"][0]["ip_range"] == "172.30.0.128/25"
    assert compose["services"]["free5gc-smf"]["depends_on"] == [
        "free5gc-nrf",
        "free5gc-upf-edge",
        "free5gc-upf-cloud",
    ]
    assert compose["services"]["free5gc-amf"]["image"] == "free5gc/amf:v4.1.0"
    assert "./free5gc-config/cert:/free5gc/cert" in (compose["services"]["free5gc-nrf"]["volumes"])
    assert compose["services"]["free5gc-upf-edge"]["image"] == "free5gc/upf:v4.1.0"
    assert compose["services"]["oai-gnb-1"]["image"] == ("oaisoftwarealliance/oai-gnb:2026.w35")
    assert compose["services"]["oai-nrue-1"]["image"] == ("oaisoftwarealliance/oai-nr-ue:2026.w35")
    nrue_options = compose["services"]["oai-nrue-1"]["environment"]["USE_ADDITIONAL_OPTIONS"]
    assert "--rfsimulator.[0].serveraddr oai-gnb-1" in nrue_options
    assert "--rfsimulator.serveraddr" not in nrue_options
    assert "--sa" not in nrue_options
    assert "--ssb" not in nrue_options
    assert (
        compose["services"]["cloud-app"]["networks"]["cloud-app-net"]["ipv4_address"]
        == "172.38.0.100"
    )
    assert compose["services"]["cloud-app"]["environment"]["RETURN_ROUTE_CIDR"] == ("172.35.0.0/24")
    assert compose["services"]["mec-app-edge"]["environment"]["UDP_PORT"] == "5202"
    assert compose["services"]["free5gc-chf"]["depends_on"] == [
        "mongodb",
        "free5gc-nrf",
        "free5gc-webui",
    ]
    assert compose["services"]["snapshot-builder"]["extra_hosts"] == [
        "host.docker.internal:host-gateway"
    ]
    assert compose["services"]["prometheus"]["ports"] == ["29090:9090"]
    assert compose["services"]["action-gateway"]["environment"]["RUN_ID"] == "render-001"
    render_traffic_profiles(scenario, generated / "traffic-profiles.json")
    traffic_profiles = json.loads((generated / "traffic-profiles.json").read_text(encoding="utf-8"))
    assert [profile["interface"] for profile in traffic_profiles] == [
        "oaitun_ue1",
        "oaitun_ue1p2",
        "oaitun_ue1p2",
    ]


def test_oai_2026_w35_gnb_rfsimulator_config_is_a_list(tmp_path: Path) -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    payload = _subscriber_payload(scenario, scenario.ues[0])
    arp = payload["SessionManagementSubscriptionData"][0]["dnnConfigurations"]["mec"][
        "5gQosProfile"
    ]["arp"]
    assert arp == {"priorityLevel": 8, "preemptCap": "", "preemptVuln": ""}
    destination = tmp_path / "gnb.conf"
    render_gnb_config(scenario, scenario.ran.gnbs[0], destination)
    rendered = destination.read_text(encoding="utf-8")
    assert "rfsimulator = (" in rendered
    assert "rfsimulator = {" not in rendered


def test_multi_ran_multi_core_scenario_renders_distinct_instances(tmp_path: Path) -> None:
    scenario = load_scenario(ROOT / "scenarios/advanced/s6_multi_gnb_multi_upf_multi_ue.yaml")
    assert len(scenario.ran.gnbs) == 2
    assert len(scenario.core.upfs) == 2
    assert len(scenario.ues) == 2
    assert sum(len(gnb.cells) for gnb in scenario.ran.gnbs) == 2
    assert all(len(ue.sessions) == 2 for ue in scenario.ues)

    generated = tmp_path / "generated"
    generated.mkdir()
    layout = RunLayout(
        root=tmp_path,
        generated=generated,
        logs=tmp_path / "logs",
        metrics=tmp_path / "metrics",
        pcaps=tmp_path / "pcaps",
    )
    _render_compose(ROOT, layout, scenario, "multi-render-001")
    compose = yaml.safe_load((generated / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {
        "free5gc-upf-edge",
        "free5gc-upf-cloud",
        "oai-gnb-1",
        "oai-gnb-2",
        "oai-nrue-1",
        "oai-nrue-2",
        "traffic-sidecar-ue-1",
        "traffic-sidecar-ue-2",
    } <= services.keys()
    assert (
        "--rfsimulator.[0].serveraddr oai-gnb-1"
        in services["oai-nrue-1"]["environment"]["USE_ADDITIONAL_OPTIONS"]
    )
    assert (
        "--rfsimulator.[0].serveraddr oai-gnb-2"
        in services["oai-nrue-2"]["environment"]["USE_ADDITIONAL_OPTIONS"]
    )

    first_config = tmp_path / "gnb-1.conf"
    second_config = tmp_path / "gnb-2.conf"
    render_gnb_config(scenario, scenario.ran.gnbs[0], first_config)
    render_gnb_config(scenario, scenario.ran.gnbs[1], second_config)
    assert "physCellId = 1;" in first_config.read_text(encoding="utf-8")
    assert "nr_cellid = 12345678L;" in first_config.read_text(encoding="utf-8")
    assert "physCellId = 2;" in second_config.read_text(encoding="utf-8")
    assert "nr_cellid = 12345679L;" in second_config.read_text(encoding="utf-8")

    render_traffic_profiles(scenario, generated / "traffic-profiles.json")
    traffic_profiles = json.loads((generated / "traffic-profiles.json").read_text(encoding="utf-8"))
    assert len(traffic_profiles) == 4
    assert {profile["ue_id"] for profile in traffic_profiles} == {"ue-1", "ue-2"}
    assert {profile["interface"] for profile in traffic_profiles} == {
        "oaitun_ue1",
        "oaitun_ue1p2",
    }

    smf_config = {"configuration": {"sbi": {}}}
    _patch_smf(scenario, smf_config)
    userplane = smf_config["configuration"]["userplaneInformation"]
    assert userplane["upNodes"]["access-network"] == {"type": "AN"}
    assert not {gnb.id for gnb in scenario.ran.gnbs} & userplane["upNodes"].keys()
    assert userplane["links"] == [
        {"A": "access-network", "B": "edge-upf"},
        {"A": "access-network", "B": "cloud-upf"},
    ]

    render_prometheus(scenario, generated / "prometheus.yml")
    prometheus = yaml.safe_load((generated / "prometheus.yml").read_text(encoding="utf-8"))
    assert prometheus["global"]["scrape_interval"] == "2s"
    assert prometheus["global"]["scrape_timeout"] == "1600ms"


def test_managed_multi_slice_scenario_renders_slice_specific_upfs(tmp_path: Path) -> None:
    scenario = load_scenario(ROOT / "scenarios/advanced/s7_managed_multi_slice.yaml")
    assert [item.id for item in scenario.slices] == ["embb", "urllc", "mmtc"]
    assert all(item.initial_state == "running" for item in scenario.slices)
    assert {item.dnn for item in scenario.core.upfs} == {"embb", "urllc", "mmtc"}
    assert [len(ue.sessions) for ue in scenario.ues] == [3, 3, 2, 2]
    assert len(scenario.flows) == 10

    smf_config = {"configuration": {"sbi": {}}}
    _patch_smf(scenario, smf_config)
    userplane = smf_config["configuration"]["userplaneInformation"]
    assert userplane["upNodes"]["embb-upf"]["sNssaiUpfInfos"][0]["sNssai"] == {
        "sst": 1,
        "sd": "010203",
    }
    assert userplane["upNodes"]["urllc-upf"]["sNssaiUpfInfos"][0]["sNssai"] == {
        "sst": 2,
        "sd": "020304",
    }
    assert userplane["upNodes"]["mmtc-upf"]["sNssaiUpfInfos"][0]["sNssai"] == {
        "sst": 3,
        "sd": "030405",
    }

    subscriber = _subscriber_payload(scenario, scenario.ues[0])
    assert len(subscriber["SessionManagementSubscriptionData"]) == 3
    topology = build_topology(scenario)
    slice_nodes = [item for item in topology["nodes"] if item["type"] == "slice"]
    assert {item["id"] for item in slice_nodes} == {"embb", "urllc", "mmtc"}
    assert {
        (item["source"], item["target"]) for item in topology["edges"] if item["type"] == "uses_upf"
    } == {
        ("embb", "embb-upf"),
        ("urllc", "urllc-upf"),
        ("mmtc", "mmtc-upf"),
    }

    generated = tmp_path / "generated"
    generated.mkdir()
    layout = RunLayout(
        root=tmp_path,
        generated=generated,
        logs=tmp_path / "logs",
        metrics=tmp_path / "metrics",
        pcaps=tmp_path / "pcaps",
    )
    _render_compose(ROOT, layout, scenario, "managed-render-001")
    compose = yaml.safe_load((generated / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert services["free5gc-smf"]["cpuset"] == "0-1,16-17"
    assert services["traffic-sidecar-ue-3"]["cpuset"] == "0-1,16-17"
    assert services["oai-gnb-1"]["cpuset"] == "2-4,18-20"
    assert services["oai-gnb-2"]["cpuset"] == "5-7,21-23"
    assert services["oai-nrue-3"]["cpuset"] == "12-13,28-29"
    assert services["oai-nrue-4"]["cpuset"] == "14-15,30-31"
