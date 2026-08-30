from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from testbed.scenario.compiler import compile_scenario
from testbed.scenario.loader import load_scenario
from testbed.scenario.schema import NetworkPlan, NetworkSpec, Scenario
from testbed.scenario.validator import validate_scenario

ROOT = Path(__file__).resolve().parents[2]


def scenario_paths() -> list[Path]:
    return sorted((ROOT / "scenarios").rglob("*.yaml"))


@pytest.mark.parametrize("path", scenario_paths())
def test_all_declared_scenarios_validate(path: Path) -> None:
    scenario = load_scenario(path)
    assert scenario.versions.oai == "2026.w35"


def test_schema_rejects_undeclared_fields() -> None:
    scenario = load_scenario(scenario_paths()[0])
    payload = scenario.model_dump(mode="json", by_alias=True)
    payload["implicit_default"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Scenario.model_validate(payload)


def test_validator_rejects_cidr_overlap() -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    payload = scenario.networks.model_dump(mode="json", by_alias=True)
    payload["n2-net"] = NetworkSpec(cidr="172.30.0.0/24", bridge_name="bad-n2")
    overlapping = scenario.model_copy(update={"networks": NetworkPlan.model_validate(payload)})
    with pytest.raises(ValueError, match="CIDR overlap"):
        validate_scenario(overlapping)


def test_compilation_has_stable_identity_and_topology() -> None:
    path = ROOT / "scenarios/mvp/s2_single_ue_edge_cloud.yaml"
    scenario = load_scenario(path)
    first = compile_scenario(scenario, path, "run-001")
    second = compile_scenario(scenario, path, "run-001")
    assert first.scenario_sha256 == second.scenario_sha256
    assert first.topology == second.topology
    assert {item["id"] for item in first.topology["nodes"]} >= {
        "edge-upf",
        "cloud-upf",
        "inference-edge",
        "inference-cloud",
    }


def test_validator_rejects_a_protocol_port_mismatch() -> None:
    scenario = load_scenario(ROOT / "scenarios/mvp/s1_single_ue_single_upf.yaml")
    invalid_flow = scenario.flows[0].model_copy(update={"dst_port": 5201})
    invalid = scenario.model_copy(update={"flows": (invalid_flow,)})
    with pytest.raises(ValueError, match="udp requires destination port 5202"):
        validate_scenario(invalid)
