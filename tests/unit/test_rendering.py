from __future__ import annotations

from pathlib import Path

import yaml

from testbed.artifacts.manifest_writer import RunLayout
from testbed.rendering.compose_renderer import _render_compose
from testbed.rendering.oai_gnb_renderer import render_gnb_config
from testbed.scenario.loader import load_scenario

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
    assert compose["services"]["free5gc-smf"]["depends_on"] == [
        "free5gc-nrf",
        "free5gc-upf-edge",
        "free5gc-upf-cloud",
    ]
    assert compose["services"]["free5gc-amf"]["image"] == "free5gc/amf:v4.1.0"
    assert compose["services"]["free5gc-upf-edge"]["image"] == "free5gc/upf:v4.1.0"
    assert compose["services"]["oai-gnb-1"]["image"] == (
        "oaisoftwarealliance/oai-gnb:2026.w35"
    )
    assert compose["services"]["oai-nrue-1"]["image"] == (
        "oaisoftwarealliance/oai-nr-ue:2026.w35"
    )
    nrue_options = compose["services"]["oai-nrue-1"]["environment"][
        "USE_ADDITIONAL_OPTIONS"
    ]
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
    assert compose["services"]["action-gateway"]["environment"]["RUN_ID"] == "render-001"


def test_oai_2026_w35_gnb_rfsimulator_config_is_a_list(tmp_path: Path) -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    destination = tmp_path / "gnb.conf"
    render_gnb_config(scenario, scenario.ran.gnbs[0], destination)
    rendered = destination.read_text(encoding="utf-8")
    assert "rfsimulator = (" in rendered
    assert "rfsimulator = {" not in rendered
