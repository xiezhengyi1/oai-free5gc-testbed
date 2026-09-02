from __future__ import annotations

from pathlib import Path

import yaml

from testbed.scenario.schema import Scenario


def render_prometheus(scenario: Scenario, destination: Path) -> None:
    traffic_targets = [f"{ue.container}:9101" for ue in scenario.ues]
    scrape_timeout_milliseconds = scenario.observability.scrape_interval_seconds * 800
    payload = {
        "global": {
            "scrape_interval": f"{scenario.observability.scrape_interval_seconds}s",
            "scrape_timeout": f"{scrape_timeout_milliseconds}ms",
            "evaluation_interval": f"{scenario.observability.scrape_interval_seconds}s",
        },
        "scrape_configs": [
            {"job_name": "prometheus", "static_configs": [{"targets": ["prometheus:9090"]}]},
            {"job_name": "cadvisor", "static_configs": [{"targets": ["cadvisor:8080"]}]},
            {
                "job_name": "traffic-exporter",
                "static_configs": [{"targets": traffic_targets}],
            },
            {"job_name": "ran-exporter", "static_configs": [{"targets": ["ran-exporter:9102"]}]},
            {
                "job_name": "testbed-control",
                "static_configs": [
                    {
                        "targets": [
                            "session-tracker:9103",
                            "snapshot-builder:9104",
                            "action-gateway:9105",
                        ]
                    }
                ],
            },
        ],
    }
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
