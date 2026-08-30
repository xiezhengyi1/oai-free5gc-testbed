from __future__ import annotations

from testbed.telemetry.ran_exporter import parse_ran_log


def metrics_from_log(log_text: str) -> dict[str, float | int | str]:
    return parse_ran_log(log_text)
