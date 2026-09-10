from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from math import ceil, cos, pi, sin, sqrt
from pathlib import Path
from typing import Literal

import yaml

from testbed.scenario.loader import load_scenario

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
S2_BASE = REPOSITORY_ROOT / "scenarios" / "experiments" / "s2_original_live.yaml"
S6_BASE = REPOSITORY_ROOT / "scenarios" / "advanced" / "s6_multi_gnb_multi_upf_multi_ue.yaml"
OUTPUT_ROOT = REPOSITORY_ROOT / "scenarios" / "experiments"


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    base: Literal["s2", "s6"]
    gnb_count: int
    ue_count: int
    traffic_mode: str
    rate_scale: float
    capacity_scale: float
    shape: str
    layout_scale: float
    assignment_offset: int = 0
    mobility: bool = False
    link_delay_ms: float | None = None
    link_jitter_ms: float | None = None
    link_loss_rate: float | None = None
    link_bandwidth_mbps: float | None = None


SPECS = (
    ScenarioSpec("s2k-01-rural-roadside-control", "s2", 1, 4, "control", 0.75, 1.10, "star", 1.00),
    ScenarioSpec(
        "s2k-02-factory-cell-control", "s2", 2, 12, "control", 1.00, 1.00, "compact", 0.80
    ),
    ScenarioSpec(
        "s2k-03-smart-factory-mixed", "s2", 4, 24, "mixed", 1.00, 1.05, "compact", 0.90, 1
    ),
    ScenarioSpec("s2k-04-campus-iot", "s2", 4, 48, "telemetry", 1.00, 1.00, "grid", 1.10),
    ScenarioSpec(
        "s2k-05-district-massive-iot", "s2", 8, 120, "telemetry", 1.20, 0.90, "grid", 1.25, 1
    ),
    ScenarioSpec(
        "s2k-06-stadium-event-broadband", "s2", 12, 180, "broadband", 1.35, 0.85, "ring", 1.00
    ),
    ScenarioSpec(
        "s2k-07-hospital-campus-mixed", "s2", 3, 18, "mixed", 0.85, 1.15, "triangle", 0.75
    ),
    ScenarioSpec(
        "s2k-08-emergency-corridor", "s2", 6, 24, "control", 1.20, 1.10, "line", 1.60, 1, True
    ),
    ScenarioSpec("s2k-09-warehouse-robots", "s2", 4, 32, "control", 0.90, 1.00, "grid", 0.55),
    ScenarioSpec("s2k-10-university-campus", "s2", 6, 60, "mixed", 1.00, 1.00, "grid", 1.20, 1),
    ScenarioSpec(
        "s2k-11-highway-mobility", "s2", 8, 40, "control", 1.00, 1.10, "line", 2.00, 0, True
    ),
    ScenarioSpec("s2k-12-urban-mobility", "s2", 12, 96, "mixed", 1.10, 1.00, "grid", 0.85, 1, True),
    ScenarioSpec("s2k-13-suburban-balanced", "s2", 4, 30, "mixed", 0.80, 1.20, "ring", 1.35),
    ScenarioSpec(
        "s2k-14-dense-video-hotspot", "s2", 10, 150, "broadband", 1.50, 0.80, "compact", 0.60, 1
    ),
    ScenarioSpec(
        "s2k-15-edge-cloud-small", "s6", 2, 8, "mixed", 1.00, 1.00, "line", 1.00, link_delay_ms=25
    ),
    ScenarioSpec(
        "s2k-16-edge-cloud-campus", "s6", 4, 32, "mixed", 1.00, 1.05, "grid", 1.00, link_delay_ms=25
    ),
    ScenarioSpec(
        "s2k-17-edge-inference-dense",
        "s6",
        6,
        72,
        "edge",
        1.30,
        0.95,
        "compact",
        0.70,
        1,
        link_delay_ms=20,
    ),
    ScenarioSpec(
        "s2k-18-cloud-inference-regional",
        "s6",
        8,
        96,
        "cloud",
        1.30,
        1.00,
        "ring",
        1.40,
        1,
        link_delay_ms=30,
    ),
    ScenarioSpec(
        "s2k-19-cloud-backhaul-degraded",
        "s6",
        10,
        120,
        "mixed",
        1.00,
        0.90,
        "grid",
        1.50,
        link_delay_ms=80,
        link_jitter_ms=10,
        link_bandwidth_mbps=100,
    ),
    ScenarioSpec(
        "s2k-20-disaster-backhaul-loss",
        "s6",
        12,
        144,
        "mixed",
        0.90,
        0.80,
        "compact",
        0.65,
        1,
        True,
        link_delay_ms=35,
        link_jitter_ms=5,
        link_loss_rate=0.02,
        link_bandwidth_mbps=50,
    ),
)

S2_PROFILES = {
    "control": ("ue-1", "ue-2", "ue-3", "ue-4", "ue-5"),
    "broadband": ("ue-3", "ue-4", "ue-5", "ue-6"),
    "telemetry": ("ue-2", "ue-6"),
    "mixed": ("ue-1", "ue-2", "ue-3", "ue-4", "ue-5", "ue-6"),
}
S6_PROFILES = {
    "edge": ("ue-1", "ue-2"),
    "cloud": ("ue-1", "ue-2"),
    "mixed": ("ue-1", "ue-2"),
}


def _load(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"scenario root must be a mapping: {path}")
    return payload


def _positions(shape: str, count: int, scale: float) -> list[dict[str, float]]:
    if shape == "line":
        source = [(260.0 * index, 0.0) for index in range(count)]
    elif shape in {"star", "ring"}:
        source = [(0.0, 0.0)] if shape == "star" else []
        ring_count = count - len(source)
        source.extend(
            (
                320.0 * cos(2 * pi * index / ring_count),
                320.0 * sin(2 * pi * index / ring_count),
            )
            for index in range(ring_count)
        )
    elif shape == "triangle":
        source = [(0.0, 0.0), (300.0, 0.0), (150.0, 260.0)]
    else:
        width = ceil(sqrt(count))
        spacing = 120.0 if shape == "compact" else 260.0
        source = [(spacing * (index % width), spacing * (index // width)) for index in range(count)]
    return [{"x": x * scale, "y": y * scale, "z": 10.0} for x, y in source]


def _matches_traffic(flow: dict, mode: str) -> bool:
    if mode == "mixed":
        return True
    if mode == "control":
        return flow["protocol"] == "udp"
    if mode == "broadband":
        return flow["protocol"] == "http"
    if mode == "telemetry":
        return flow["protocol"] == "tcp"
    if mode == "edge":
        return flow["service_instance_id"] == "inference-edge"
    if mode == "cloud":
        return flow["service_instance_id"] == "inference-cloud"
    raise ValueError(f"unknown traffic mode: {mode}")


def _scale_bandwidth(flow: dict, scale: float) -> None:
    flow["rate_mbps"] = round(flow["rate_mbps"] * scale, 4)
    for key in (
        "bandwidth_ul_mbps",
        "bandwidth_dl_mbps",
        "guaranteed_bandwidth_ul_mbps",
        "guaranteed_bandwidth_dl_mbps",
    ):
        flow["sla"][key] = round(flow["sla"][key] * scale, 4)
    for key in ("allocated_bandwidth_ul_mbps", "allocated_bandwidth_dl_mbps"):
        flow["allocation"][key] = round(flow["allocation"][key] * scale, 4)


def _clone_gnbs(payload: dict, spec: ScenarioSpec) -> list[dict]:
    templates = payload["ran"]["gnbs"]
    positions = _positions(spec.shape, spec.gnb_count, spec.layout_scale)
    gnbs = []
    for index in range(1, spec.gnb_count + 1):
        gnb = deepcopy(templates[(index - 1) % len(templates)])
        gnb["id"] = f"gnb-{index}"
        gnb["container"] = f"oai-gnb-{index}"
        gnb["n2_ip"] = f"172.31.0.{49 + index}"
        gnb["n3_ip"] = f"172.32.0.{49 + index}"
        gnb["cells"] = [
            {
                "id": f"cell-{index}",
                "pci": index,
                "position": positions[index - 1],
            }
        ]
        gnbs.append(gnb)
    return gnbs


def _clone_ues_and_flows(
    payload: dict,
    spec: ScenarioSpec,
    gnbs: list[dict],
    scenario_number: int,
) -> tuple[list[dict], list[dict]]:
    profiles = (
        S2_PROFILES[spec.traffic_mode] if spec.base == "s2" else S6_PROFILES[spec.traffic_mode]
    )
    source_ues = {ue["id"]: ue for ue in payload["ues"]}
    source_flows = {
        ue_id: [
            flow
            for flow in payload["flows"]
            if flow["ue_id"] == ue_id and _matches_traffic(flow, spec.traffic_mode)
        ]
        for ue_id in profiles
    }
    ues = []
    flows = []
    for index in range(1, spec.ue_count + 1):
        source_id = profiles[(index - 1) % len(profiles)]
        ue_id = f"ue-{index}"
        selected_flows = source_flows[source_id]

        ue = deepcopy(source_ues[source_id])
        ue["id"] = ue_id
        ue["container"] = f"oai-nrue-{index}"
        ue["traffic_sidecar"] = f"traffic-sidecar-ue-{index}"
        ue["supi"] = f"imsi-{208930000000000 + scenario_number * 1000 + index}"
        ue["serving_gnb"] = gnbs[(index - 1 + spec.assignment_offset) % len(gnbs)]["id"]
        ues.append(ue)

        for source_flow in selected_flows:
            flow = deepcopy(source_flow)
            suffix = source_flow["id"].removeprefix(f"{source_id}-")
            flow["id"] = f"{ue_id}-{suffix}"
            flow["ue_id"] = ue_id
            _scale_bandwidth(flow, spec.rate_scale)
            flows.append(flow)
    return ues, flows


def _resize_slice_capacities(payload: dict, spec: ScenarioSpec) -> None:
    session_slices = {
        (ue["id"], session["id"]): session["slice_id"]
        for ue in payload["ues"]
        for session in ue["sessions"]
    }
    baseline_gnbs = 3 if spec.base == "s2" else 2
    cell_scale = max(1.0, spec.gnb_count / baseline_gnbs) * spec.capacity_scale
    for slice_item in payload["slices"]:
        slice_id = slice_item["id"]
        slice_flows = [
            flow
            for flow in payload["flows"]
            if session_slices[(flow["ue_id"], flow["session_id"])] == slice_id
        ]
        capacity = slice_item["capacity"]
        for direction in ("ul", "dl"):
            guaranteed = sum(
                flow["sla"][f"guaranteed_bandwidth_{direction}_mbps"] for flow in slice_flows
            )
            guaranteed_key = f"guaranteed_bandwidth_{direction}_mbps"
            total_key = f"total_bandwidth_{direction}_mbps"
            capacity[guaranteed_key] = round(
                max(capacity[guaranteed_key] * cell_scale, guaranteed * 1.05),
                4,
            )
            capacity[total_key] = round(
                max(capacity[total_key] * cell_scale, capacity[guaranteed_key]),
                4,
            )


def _resource_plan(
    payload: dict,
    base_resources: dict[str, dict],
    gnbs: list[dict],
    ues: list[dict],
) -> dict:
    gnb_template = deepcopy(
        next(resources for name, resources in base_resources.items() if name.startswith("oai-gnb"))
    )
    ue_template = deepcopy(
        next(resources for name, resources in base_resources.items() if name.startswith("oai-nrue"))
    )
    gnb_template.pop("cpuset_cpus", None)
    ue_template.pop("cpuset_cpus", None)
    containers = {
        upf["container"]: deepcopy(base_resources[upf["container"]])
        for upf in payload["core"]["upfs"]
    }
    containers.update({gnb["container"]: deepcopy(gnb_template) for gnb in gnbs})
    containers.update({ue["container"]: deepcopy(ue_template) for ue in ues})
    containers.update(
        {service["container"]: deepcopy(service["resources"]) for service in payload["services"]}
    )
    return {"containers": containers}


def _build_payload(spec: ScenarioSpec) -> dict:
    base_path = S2_BASE if spec.base == "s2" else S6_BASE
    payload = deepcopy(_load(base_path))
    base_resources = deepcopy(payload["resources"]["containers"])
    payload["scenario_id"] = spec.scenario_id
    payload["sources"] = deepcopy(_load(S2_BASE)["sources"])
    scenario_number = int(spec.scenario_id.split("-")[1])

    gnbs = _clone_gnbs(payload, spec)
    payload["ran"]["gnbs"] = gnbs
    ues, flows = _clone_ues_and_flows(payload, spec, gnbs, scenario_number)
    payload["ues"] = ues
    payload["flows"] = flows

    service_ids = {flow["service_instance_id"] for flow in flows}
    payload["services"] = [
        service for service in payload["services"] if service["id"] in service_ids
    ]

    used_slice_ids = {session["slice_id"] for ue in ues for session in ue["sessions"]}
    used_dnns = {session["dnn"] for ue in ues for session in ue["sessions"]}
    payload["slices"] = [
        slice_item for slice_item in payload["slices"] if slice_item["id"] in used_slice_ids
    ]
    payload["core"]["upfs"] = [upf for upf in payload["core"]["upfs"] if upf["dnn"] in used_dnns]
    _resize_slice_capacities(payload, spec)

    used_site_ids = {
        *(gnb["site_id"] for gnb in gnbs),
        *(upf["site_id"] for upf in payload["core"]["upfs"]),
        *(service["site_id"] for service in payload["services"]),
    }
    payload["sites"] = [site for site in payload["sites"] if site["id"] in used_site_ids]

    cloud_required = any(site["type"] == "cloud" for site in payload["sites"])
    payload["links"] = payload["links"] if cloud_required else []
    if payload["links"]:
        link = payload["links"][0]
        if spec.link_delay_ms is not None:
            link["delay_ms"] = spec.link_delay_ms
        if spec.link_jitter_ms is not None:
            link["jitter_ms"] = spec.link_jitter_ms
        if spec.link_loss_rate is not None:
            link["loss_rate"] = spec.link_loss_rate
        if spec.link_bandwidth_mbps is not None:
            link["bandwidth_mbps"] = spec.link_bandwidth_mbps

    payload["resources"] = _resource_plan(payload, base_resources, gnbs, ues)

    payload["mobility"] = []
    if spec.mobility:
        event_count = min(10, max(1, spec.ue_count // 12))
        gnb_index = {gnb["id"]: index for index, gnb in enumerate(gnbs)}
        for index, ue in enumerate(ues[:event_count]):
            current_index = gnb_index[ue["serving_gnb"]]
            target = gnbs[(current_index + 1) % len(gnbs)]
            position = target["cells"][0]["position"]
            payload["mobility"].append(
                {
                    "at_seconds": 45 + 15 * index,
                    "ue_id": ue["id"],
                    "target_gnb": target["id"],
                    "position": {
                        "x": position["x"] + 20.0,
                        "y": position["y"] + 10.0,
                        "z": 1.5,
                    },
                }
            )
    return payload


def build_scenarios(output_root: Path = OUTPUT_ROOT) -> list[Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for spec in SPECS:
        path = output_root / f"{spec.scenario_id}.yaml"
        path.write_text(
            yaml.safe_dump(_build_payload(spec), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        load_scenario(path)
        paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    paths = build_scenarios(args.output_root)
    print(f"Wrote and validated {len(paths)} topology-first scenarios in {args.output_root}")


if __name__ == "__main__":
    main()


__all__ = ["OUTPUT_ROOT", "SPECS", "ScenarioSpec", "build_scenarios"]
