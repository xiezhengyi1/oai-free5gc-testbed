from __future__ import annotations

import json
import os
import re
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from prometheus_client import Gauge, start_http_server

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.adapters.oai.ue_adapter import session_interface
from testbed.telemetry.free5gc_event_parser import (
    SESSION_DL_TEID,
    SESSION_QOS,
    SESSION_QOS_RELEASE,
    SESSION_UL_TEID,
    parse_session_fields,
)
from testbed.telemetry.ran_exporter import UE_STATUS, parse_ran_ues, parse_ue_rnti

SESSION_COMPLETE = Gauge(
    "testbed_session_correlation_complete",
    "Whether all authoritative session keys were found",
    ("supi", "dnn"),
)


class SessionLogHistory:
    """Keep native events across overlapping reads, never across container restarts."""

    def __init__(self, max_events: int = 100_000) -> None:
        self.identity = None
        self.since = None
        self.events = {}
        self.bindings = {}
        self.last_read = {}
        self.max_events = max_events

    @staticmethod
    def _identity(docker, container):
        inspected = docker.inspect(container)
        return inspected["Id"], inspected["State"]["StartedAt"]

    def read(self, docker, container):
        identity = self._identity(docker, container)
        if identity != self.identity:
            self.identity, self.since, self.events, self.bindings = identity, None, {}, {}
        started_at = datetime.now(UTC).isoformat()
        began = time.monotonic()
        text = docker.container_logs(container, tail="all", since=self.since, timestamps=True)
        if self._identity(docker, container) != identity:
            self.identity, self.since, self.events, self.bindings = None, None, {}, {}
            raise RuntimeError("gNB restarted during session history collection")
        for line in text.splitlines():
            timestamp, separator, body = line.partition(" ")
            if not separator or not timestamp.endswith("Z"):
                continue
            status = UE_STATUS.search(body)
            creation = re.search(r"UE ID (\d+) RNTI ([0-9a-fA-F]+)\)", body)
            if status or creation:
                rnti = int(status.group(1) if status else creation.group(2), 16)
                current = self.bindings.get(rnti)
                if current is None or timestamp >= current[0]:
                    self.bindings[rnti] = timestamp, body
            if any(
                pattern.search(body)
                for pattern in (SESSION_QOS, SESSION_QOS_RELEASE, SESSION_UL_TEID, SESSION_DL_TEID)
            ):
                self.events[timestamp, body] = body
        if len(self.events) > self.max_events:
            raise RuntimeError(
                "session history capacity exceeded; archive evidence before restarting"
            )
        previous_since, self.since = self.since, started_at
        self.last_read = dict(
            since=previous_since,
            input_bytes=len(text.encode()),
            retained_events=len(self.events),
            seconds=time.monotonic() - began,
        )
        return "\n".join(
            [body for _, body in self.bindings.values()]
            + [body for _, body in sorted(self.events.items(), key=lambda item: item[0][0])]
        )


def _session_gnb_history(docker, container):
    if not hasattr(docker, "_session_histories"):
        docker._session_histories = {}
    history = docker._session_histories.setdefault(container, SessionLogHistory())
    return history.read(docker, container)


def _current_ue_rnti(docker, container):
    # Connected stats are periodic. Fall back to full native history only if absent.
    recent = docker.container_logs(container, tail="200")
    try:
        return parse_ue_rnti(recent)
    except ValueError:
        return parse_ue_rnti(docker.container_logs(container, tail="all"))


def collect_sessions(run_dir: Path, docker: DockerAdapter) -> list[dict[str, object]]:
    compiled = json.loads((run_dir / "compiled-scenario.json").read_text(encoding="utf-8"))
    scenario = compiled["scenario"]
    dynamic = (run_dir / "ue-policy/dynamic-pdu.json").exists()
    slices = {item["id"]: item for item in scenario["slices"]}

    def observe_ue(ue):
        rnti = _current_ue_rnti(docker, ue["container"])
        interfaces = json.loads(docker.exec(ue["container"], ["ip", "-j", "addr", "show"]))
        interface_by_name = {item["ifname"]: item for item in interfaces}
        selected = list(enumerate(ue["sessions"], start=1))
        if dynamic:
            state = json.loads(
                (
                    run_dir
                    / "ue-policy"
                    / ue["id"]
                    / f"{ue['supi'].removeprefix('imsi-')}.policy.state.json"
                ).read_text()
            )
            selected = [
                (
                    pdu["id"],
                    next(
                        session
                        for session in ue["sessions"]
                        if session["dnn"] == pdu["dnn"]
                        and slices[session["slice_id"]]["sst"] == pdu["sst"]
                        and slices[session["slice_id"]]["sd"] == pdu["sd"]
                    ),
                )
                for pdu in state["sessions"]
                if pdu["active"]
            ]
        return ue, rnti, interface_by_name, selected

    with ThreadPoolExecutor(max_workers=4) as pool:
        inputs = list(pool.map(observe_ue, scenario["ues"]))
    gnb_logs = {
        gnb["id"]: _session_gnb_history(docker, gnb["container"]) for gnb in scenario["ran"]["gnbs"]
    }
    ran_by_gnb = {gnb_id: parse_ran_ues(log_text) for gnb_id, log_text in gnb_logs.items()}
    records: list[dict[str, object]] = []
    for ue, rnti, interface_by_name, selected in inputs:
        cu_ue_id = int(ran_by_gnb[ue["serving_gnb"]][rnti]["cu_ue_id"])
        for index, session in selected:
            record = parse_session_fields(
                gnb_logs[ue["serving_gnb"]],
                ue["supi"],
                session["dnn"],
                index,
                cu_ue_id,
            )
            interface_name = session_interface(index)
            address_info = interface_by_name[interface_name]["addr_info"]
            ipv4 = next(item["local"] for item in address_info if item["family"] == "inet")
            record.update(
                {
                    "ue_id": ue["id"],
                    "session_id": session["id"],
                    "slice_id": session["slice_id"],
                    "pdu_session_id": index,
                    "ue_ip": ipv4,
                    "rnti": f"0x{rnti:04x}",
                    "cu_ue_id": cu_ue_id,
                }
            )
            complete = all(name in record for name in ("qfi", "five_qi", "ul_teid", "dl_teid"))
            record["correlation_status"] = "complete" if complete else "incomplete"
            SESSION_COMPLETE.labels(ue["supi"], session["dnn"]).set(int(complete))
            records.append(record)
    return records


def refresh_sessions(run_dir: Path, docker: DockerAdapter) -> list[dict[str, object]]:
    records = collect_sessions(run_dir, docker)
    if not all(record["correlation_status"] == "complete" for record in records):
        raise RuntimeError("session refresh requires complete UE/NGAP correlation")
    output = run_dir / "session-observations.json"
    temporary = output.with_suffix(".refresh.tmp")
    temporary.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output)
    return records


def main() -> None:
    run_dir = Path(os.environ["RUN_DIR"])
    output = run_dir / "session-observations.json"
    live_policy = (run_dir / "ue-policy/profile.json").exists()
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
        if (
            not live_policy
            and not (run_dir / "ue-policy/dynamic-pdu.json").exists()
            and all(record["correlation_status"] == "complete" for record in records)
        ):
            stop.wait()
        stop.wait(1)


if __name__ == "__main__":
    main()
