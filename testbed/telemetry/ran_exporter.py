from __future__ import annotations

import os
import re
import signal
import threading

from prometheus_client import Gauge, start_http_server

from testbed.adapters.docker_adapter import DockerAdapter

PATTERNS: dict[str, re.Pattern[str]] = {
    "rnti": re.compile(r"RNTI\s*(?:=|:|\[)\s*(0x[0-9a-fA-F]+|[0-9a-fA-F]+)", re.IGNORECASE),
    "mcs_dl": re.compile(r"(?:dl[_ ]?mcs|MCS DL)\s*(?:=|:)\s*(\d+)", re.IGNORECASE),
    "mcs_ul": re.compile(r"(?:ul[_ ]?mcs|MCS UL)\s*(?:=|:)\s*(\d+)", re.IGNORECASE),
    "bler_dl": re.compile(r"(?:dl[_ ]?bler|BLER DL)\s*(?:=|:)\s*([0-9.]+)", re.IGNORECASE),
    "bler_ul": re.compile(r"(?:ul[_ ]?bler|BLER UL)\s*(?:=|:)\s*([0-9.]+)", re.IGNORECASE),
    "prb_dl": re.compile(r"(?:dl[_ ]?prb|PRB DL)\s*(?:=|:)\s*(\d+)", re.IGNORECASE),
    "prb_ul": re.compile(r"(?:ul[_ ]?prb|PRB UL)\s*(?:=|:)\s*(\d+)", re.IGNORECASE),
    "rlc_buffer_bytes": re.compile(r"RLC.*buffer\s*(?:=|:)\s*(\d+)", re.IGNORECASE),
    "drb_id": re.compile(r"DRB(?: ID)?\s*(?:=|:)\s*(\d+)", re.IGNORECASE),
}


def parse_ran_log(log_text: str) -> dict[str, float | int | str]:
    result: dict[str, float | int | str] = {}
    for name, pattern in PATTERNS.items():
        matches = pattern.findall(log_text)
        if not matches:
            continue
        raw = matches[-1]
        if name == "rnti":
            result[name] = int(raw, 16)
        elif name.startswith("bler"):
            result[name] = float(raw)
        else:
            result[name] = int(raw)
    result["handover_event"] = "handover" if "Handover" in log_text else "stable"
    return result


RAN_METRIC = Gauge("testbed_ran_metric", "Parsed OAI RAN metric", ("gnb", "metric"))


def main() -> None:
    run_dir = os.environ["RUN_DIR"]
    import json
    from pathlib import Path

    compiled = json.loads((Path(run_dir) / "compiled-scenario.json").read_text(encoding="utf-8"))
    gnbs = compiled["scenario"]["ran"]["gnbs"]
    docker = DockerAdapter()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signal, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signal, _frame: stop.set())
    start_http_server(9102)
    while not stop.is_set():
        for gnb in gnbs:
            metrics = parse_ran_log(docker.container_logs(gnb["container"]))
            for name, value in metrics.items():
                if isinstance(value, (int, float)):
                    RAN_METRIC.labels(gnb["id"], name).set(value)
        stop.wait(1)


if __name__ == "__main__":
    main()
