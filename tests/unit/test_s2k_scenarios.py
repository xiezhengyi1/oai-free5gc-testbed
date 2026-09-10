from __future__ import annotations

import hashlib
import json

from scripts.build_s2k_scenarios import SPECS, build_scenarios
from testbed.scenario.compiler import compile_scenario
from testbed.scenario.loader import load_scenario


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def test_build_s2k_scenarios_are_valid_compilable_and_topologically_distinct(tmp_path) -> None:
    paths = build_scenarios(tmp_path)
    loaded = [load_scenario(path) for path in paths]
    scenarios = [scenario.model_dump(mode="json", by_alias=True) for scenario in loaded]
    compiled = [
        compile_scenario(scenario, path, f"preflight-{index:02d}")
        for index, (scenario, path) in enumerate(zip(loaded, paths, strict=True), 1)
    ]

    assert len(paths) == 20
    assert set(tmp_path.glob("*.yaml")) == set(paths)
    assert len({scenario["scenario_id"] for scenario in scenarios}) == 20
    assert [(len(scenario["ran"]["gnbs"]), len(scenario["ues"])) for scenario in scenarios] == [
        (spec.gnb_count, spec.ue_count) for spec in SPECS
    ]
    assert max(spec.gnb_count for spec in SPECS) >= 10
    assert max(spec.ue_count for spec in SPECS) >= 100
    assert all(item.topology["nodes"] and item.topology["edges"] for item in compiled)

    network_digests = {
        _digest(
            {
                key: scenario[key]
                for key in ("networks", "slices", "sites", "core", "ran", "ues", "mobility")
            }
        )
        for scenario in scenarios
    }
    traffic_digests = {
        _digest({key: scenario[key] for key in ("services", "links", "flows")})
        for scenario in scenarios
    }
    assert len(network_digests) == len(SPECS)
    assert len(traffic_digests) == len(SPECS)
