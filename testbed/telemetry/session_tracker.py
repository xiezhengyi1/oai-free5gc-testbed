from __future__ import annotations

import json
import os
import signal
import threading
from pathlib import Path

from prometheus_client import Gauge, start_http_server

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.telemetry.free5gc_event_parser import parse_session_fields

SESSION_COMPLETE = Gauge(
    "testbed_session_correlation_complete",
    "Whether all authoritative session keys were found",
    ("supi", "dnn"),
)


def collect_sessions(run_dir: Path, docker: DockerAdapter) -> list[dict[str, object]]:
    compiled = json.loads((run_dir / "compiled-scenario.json").read_text(encoding="utf-8"))
    scenario = compiled["scenario"]
    smf_logs = docker.container_logs("free5gc-smf")
    records: list[dict[str, object]] = []
    for ue in scenario["ues"]:
        interfaces = json.loads(docker.exec(ue["container"], ["ip", "-j", "addr", "show"]))
        interface_by_name = {item["ifname"]: item for item in interfaces}
        for index, session in enumerate(ue["sessions"], start=1):
            record = parse_session_fields(smf_logs, ue["supi"], session["dnn"])
            interface_name = f"oaitun_ue{index}"
            address_info = interface_by_name[interface_name]["addr_info"]
            ipv4 = next(item["local"] for item in address_info if item["family"] == "inet")
            record.update(
                {
                    "ue_id": ue["id"],
                    "session_id": session["id"],
                    "slice_id": session["slice_id"],
                    "pdu_session_id": index,
                    "ue_ip": ipv4,
                }
            )
            complete = all(name in record for name in ("qfi", "five_qi", "ul_teid", "dl_teid"))
            record["correlation_status"] = "complete" if complete else "incomplete"
            SESSION_COMPLETE.labels(ue["supi"], session["dnn"]).set(int(complete))
            records.append(record)
    return records


def main() -> None:
    run_dir = Path(os.environ["RUN_DIR"])
    output = run_dir / "session-observations.json"
    docker = DockerAdapter()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signal, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signal, _frame: stop.set())
    start_http_server(9103)
    while not stop.is_set():
        records = collect_sessions(run_dir, docker)
        temporary = output.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        temporary.replace(output)
        stop.wait(1)


if __name__ == "__main__":
    main()
