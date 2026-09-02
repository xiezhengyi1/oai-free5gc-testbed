from __future__ import annotations

import json
from ipaddress import ip_network
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from testbed.artifacts.manifest_writer import (
    RunLayout,
    initialize_run_artifacts,
    write_manifest,
)
from testbed.rendering.free5gc_renderer import render_free5gc
from testbed.rendering.oai_gnb_renderer import render_gnb_config
from testbed.rendering.oai_ue_renderer import render_ue_config
from testbed.rendering.observability_renderer import render_prometheus
from testbed.rendering.traffic_renderer import render_traffic_profiles
from testbed.scenario.compiler import compile_scenario
from testbed.scenario.loader import load_scenario
from testbed.state.run_store import RunStore
from testbed.state.slice_store import SliceStore

TEMPLATES = (
    "base.compose.yaml.j2",
    "free5gc.compose.yaml.j2",
    "oai.compose.yaml.j2",
    "mec-cloud.compose.yaml.j2",
    "observability.compose.yaml.j2",
)


def _merge(left: dict[str, Any], right: dict[str, Any], path: str = "root") -> dict[str, Any]:
    result = dict(left)
    for key, value in right.items():
        key_path = f"{path}.{key}"
        if key not in result:
            result[key] = value
        elif isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge(result[key], value, key_path)
        elif result[key] != value:
            raise ValueError(f"compose fragment conflict at {key_path}")
    return result


def _apply_cpu_affinity(compose: dict[str, Any], scenario: Any) -> None:
    system_cpuset = scenario.resources.system_cpuset_cpus
    if system_cpuset is not None:
        for service in compose["services"].values():
            service["cpuset"] = system_cpuset
    for container, resources in scenario.resources.containers.items():
        if resources.cpuset_cpus is not None:
            compose["services"][container]["cpuset"] = resources.cpuset_cpus


def _render_compose(repository_root: Path, layout: RunLayout, scenario: Any, run_id: str) -> None:
    environment = Environment(
        loader=FileSystemLoader(repository_root / "deployment" / "compose"),
        undefined=StrictUndefined,
        autoescape=False,
        keep_trailing_newline=True,
    )
    sbi_dynamic_range = str(
        tuple(ip_network(scenario.networks.sbi.cidr).subnets(prefixlen_diff=1))[1]
    )
    context = {
        "scenario": scenario,
        "run_id": run_id,
        "project_name": f"testbed-{run_id}",
        "sbi_dynamic_range": sbi_dynamic_range,
    }
    compose: dict[str, Any] = {}
    for name in TEMPLATES:
        rendered = environment.get_template(name).render(**context)
        fragment = yaml.safe_load(rendered)
        if not isinstance(fragment, dict):
            raise ValueError(f"compose template did not render a mapping: {name}")
        compose = _merge(compose, fragment)
    _apply_cpu_affinity(compose, scenario)
    (layout.generated / "compose.yaml").write_text(
        yaml.safe_dump(compose, sort_keys=False), encoding="utf-8"
    )


def render_run(repository_root: Path, scenario_path: Path, run_id: str) -> RunLayout:
    repository_root = repository_root.resolve(strict=True)
    source_path = scenario_path.resolve(strict=True)
    scenario = load_scenario(source_path)
    compiled = compile_scenario(scenario, source_path, run_id)
    layout = initialize_run_artifacts(repository_root, source_path, scenario, compiled)
    render_free5gc(scenario, layout.generated)
    for gnb in scenario.ran.gnbs:
        render_gnb_config(scenario, gnb, layout.generated / "oai-config" / f"{gnb.id}.conf")
    for ue in scenario.ues:
        render_ue_config(scenario, ue, layout.generated / "oai-config" / f"{ue.id}.conf")
    render_traffic_profiles(scenario, layout.generated / "traffic-profiles.json")
    render_prometheus(scenario, layout.generated / "prometheus.yml")
    _render_compose(repository_root, layout, scenario, run_id)
    write_manifest(repository_root, layout, scenario, compiled)
    RunStore(layout.root).initialize()
    SliceStore(layout.root).initialize(scenario)
    (layout.generated / "compiled-scenario.json").write_text(
        json.dumps(compiled.model_dump(mode="json"), indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    return layout
