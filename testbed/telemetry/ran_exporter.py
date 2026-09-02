from __future__ import annotations

import json
import os
import re
import signal
import threading
from pathlib import Path

from prometheus_client import Gauge, start_http_server

from testbed.adapters.docker_adapter import DockerAdapter

UE_STATUS = re.compile(r"UE RNTI\s+([0-9a-fA-F]+)\s+CU-UE-ID\s+(\d+)", re.IGNORECASE)
UE_DLSCH = re.compile(
    r"UE ([0-9a-fA-F]+): dlsch.*?BLER\s+([0-9.]+)\s+MCS\s+\(\d+\)\s+(\d+)",
    re.IGNORECASE,
)
UE_ULSCH = re.compile(
    r"UE ([0-9a-fA-F]+): ulsch.*?BLER\s+([0-9.]+)\s+MCS\s+\(\d+\)\s+"
    r"(\d+).*?NPRB\s+(\d+)",
    re.IGNORECASE,
)
UE_GOODPUT = re.compile(
    r"UE ([0-9a-fA-F]+): LCID .*?goodput DL\s+([0-9.]+)\s+UL\s+([0-9.]+)\s+Mbps",
    re.IGNORECASE,
)
NRUE_CURRENT_RNTI = re.compile(
    r"(?:RNTI\s+0x|UE\s+\d+\s+RNTI\s+)([0-9a-fA-F]+)"
    r"(?:\s+State\s*=\s*NR_RRC_CONNECTED|\s+stats)",
    re.IGNORECASE,
)


def parse_ue_rnti(log_text: str) -> int:
    matches = NRUE_CURRENT_RNTI.findall(log_text)
    if not matches:
        raise ValueError("nrUE log does not contain a connected RNTI")
    return int(matches[-1], 16)


def parse_ran_ues(log_text: str) -> dict[int, dict[str, float | int | str]]:
    records: dict[int, dict[str, float | int | str]] = {}
    for raw_rnti, raw_cu_ue_id in UE_STATUS.findall(log_text):
        rnti = int(raw_rnti, 16)
        records.setdefault(rnti, {}).update(rnti=rnti, cu_ue_id=int(raw_cu_ue_id))
    for raw_rnti, raw_bler, raw_mcs in UE_DLSCH.findall(log_text):
        rnti = int(raw_rnti, 16)
        records.setdefault(rnti, {}).update(bler_dl=float(raw_bler), mcs_dl=int(raw_mcs))
    for raw_rnti, raw_bler, raw_mcs, raw_prb in UE_ULSCH.findall(log_text):
        rnti = int(raw_rnti, 16)
        records.setdefault(rnti, {}).update(
            bler_ul=float(raw_bler), mcs_ul=int(raw_mcs), prb_ul=int(raw_prb)
        )
    for raw_rnti, raw_dl, raw_ul in UE_GOODPUT.findall(log_text):
        rnti = int(raw_rnti, 16)
        records.setdefault(rnti, {}).update(
            goodput_dl_mbps=float(raw_dl), goodput_ul_mbps=float(raw_ul)
        )
    handover_event = "handover" if "Handover" in log_text else "stable"
    for record in records.values():
        record["handover_event"] = handover_event
    return records


def ran_records_ready(
    ues: list[dict[str, object]],
    rnti_by_ue: dict[str, int],
    records_by_gnb: dict[str, dict[int, dict[str, float | int | str]]],
) -> bool:
    return all(
        rnti_by_ue[str(ue["id"])] in records_by_gnb[str(ue["serving_gnb"])]
        for ue in ues
    )


RAN_UE_METRIC = Gauge(
    "testbed_ran_ue_metric",
    "OAI RAN metric correlated to one configured UE",
    ("gnb", "ue_id", "supi", "rnti", "metric"),
)
RAN_METRIC = Gauge("testbed_ran_metric", "Mean OAI RAN metric per gNB", ("gnb", "metric"))


def main() -> None:
    run_dir = Path(os.environ["RUN_DIR"])
    compiled = json.loads((run_dir / "compiled-scenario.json").read_text(encoding="utf-8"))
    scenario = compiled["scenario"]
    gnbs = {item["id"]: item for item in scenario["ran"]["gnbs"]}
    docker = DockerAdapter()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signal, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signal, _frame: stop.set())
    start_http_server(9102)
    while not stop.is_set():
        try:
            rnti_by_ue = {
                ue["id"]: parse_ue_rnti(
                    docker.container_logs(ue["container"], tail="200")
                )
                for ue in scenario["ues"]
            }
        except ValueError:
            stop.wait(1)
            continue
        records_by_gnb = {
            gnb_id: parse_ran_ues(docker.container_logs(gnb["container"]))
            for gnb_id, gnb in gnbs.items()
        }
        if not ran_records_ready(scenario["ues"], rnti_by_ue, records_by_gnb):
            stop.wait(1)
            continue
        aggregate: dict[tuple[str, str], list[float]] = {}
        for ue in scenario["ues"]:
            gnb_id = ue["serving_gnb"]
            rnti = rnti_by_ue[ue["id"]]
            metrics = records_by_gnb[gnb_id][rnti]
            rnti_label = f"0x{rnti:04x}"
            for name, value in metrics.items():
                if name in {"rnti", "cu_ue_id", "handover_event"}:
                    continue
                numeric = float(value)
                RAN_UE_METRIC.labels(gnb_id, ue["id"], ue["supi"], rnti_label, name).set(numeric)
                aggregate.setdefault((gnb_id, name), []).append(numeric)
        for (gnb_id, name), values in aggregate.items():
            RAN_METRIC.labels(gnb_id, name).set(sum(values) / len(values))
        stop.wait(1)


if __name__ == "__main__":
    main()
