from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from prometheus_client import Gauge, start_http_server

from testbed.adapters.prometheus_adapter import PrometheusAdapter
from testbed.scenario.ids import stable_digest
from testbed.scenario.loader import load_scenario
from testbed.telemetry.flow_correlator import correlate_flow
from testbed.telemetry.models import UnifiedSnapshot
from testbed.telemetry.snapshot_writer import PostgresGraphWriter, SnapshotStore
from testbed.telemetry.window_manager import WindowManager

SNAPSHOTS_WRITTEN = Gauge("testbed_snapshot_sequence", "Number of snapshots written", ("run_id",))


def _label_selector(labels: dict[str, str]) -> str:
    return ",".join(f'{key}="{value}"' for key, value in labels.items())


class SnapshotBuilder:
    def __init__(
        self,
        run_dir: Path,
        prometheus_url: str,
        database_url: str,
    ) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.scenario = load_scenario(self.run_dir / "source-scenario.yaml")
        self.run_id = self.run_dir.name
        self.prometheus = PrometheusAdapter(prometheus_url)
        self.store = SnapshotStore(self.run_dir)
        self.graph_writer = PostgresGraphWriter(database_url)
        self.sequence = 0
        self.build_lock = threading.Lock()

    def _sessions(self) -> list[dict[str, Any]]:
        path = self.run_dir / "session-observations.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError("session observations must be a list of objects")
        return payload

    def _flow_telemetry(
        self,
        window: WindowManager,
        flow_id: str,
        supi: str,
        ue_id: str,
        protocol: str,
        service_id: str,
    ) -> tuple[dict[str, Any], int]:
        selector = _label_selector(
            {
                "flow_id": flow_id,
                "supi": supi,
                "ue_id": ue_id,
                "protocol": protocol,
                "service_instance_id": service_id,
            }
        )
        throughput, throughput_samples = window.mean(f"testbed_flow_throughput_mbps{{{selector}}}")
        if protocol == "http":
            latency_metric = "testbed_flow_http_latency_ms"
            sent_metric = "testbed_flow_http_requests_total"
            received_metric = "testbed_flow_http_requests_total"
        elif protocol == "udp":
            latency_metric = "testbed_flow_udp_latency_ms"
            sent_metric = "testbed_flow_udp_sent_total"
            received_metric = "testbed_flow_udp_received_total"
        else:
            latency_metric = "testbed_flow_ping_rtt_ms"
            sent_metric = None
            received_metric = "testbed_flow_ping_received_total"
        latency, latency_samples = window.mean(f"{latency_metric}{{{selector}}}")
        running, running_samples = window.mean(f"testbed_flow_running{{{selector}}}")
        jitter, _ = window.mean(f"testbed_flow_jitter_ms{{{selector}}}")
        loss, _ = window.mean(f"testbed_flow_loss_ratio{{{selector}}}")
        retransmits = window.latest(f"testbed_flow_tcp_retransmits_total{{{selector}}}")
        return (
            {
                "throughput_ul": throughput,
                "throughput_dl": 0.0,
                "latency": latency,
                "jitter": jitter,
                "loss_rate": loss,
                "packet_sent": (
                    window.latest(f"{sent_metric}{{{selector}}}") if sent_metric else None
                ),
                "packet_received": window.latest(f"{received_metric}{{{selector}}}"),
                "tcp_retransmits": retransmits,
                "tcp_retransmits_per_second": None,
                "tcp_rtt_ms_average": latency,
                "availability": running,
                "observed_at": datetime.fromtimestamp(window.end, UTC).isoformat(),
            },
            min(throughput_samples, latency_samples, running_samples),
        )

    def _ran_metrics(self, window: WindowManager, gnb_id: str) -> dict[str, Any]:
        mapping = {
            "rnti": "rnti",
            "drb_id": "drb_id",
            "mcs_ul": "mcs_ul",
            "mcs_dl": "mcs_dl",
            "bler_ul": "bler_ul",
            "bler_dl": "bler_dl",
            "prb_ul": "prb_ul",
            "prb_dl": "prb_dl",
            "rlc_buffer_bytes": "rlc_buffer_bytes",
        }
        result: dict[str, Any] = {}
        for output_name, metric_name in mapping.items():
            if metric_name is not None:
                result[output_name] = window.latest(
                    f'testbed_ran_metric{{gnb="{gnb_id}",metric="{metric_name}"}}'
                )
        compact = {key: value for key, value in result.items() if value is not None}
        if "rnti" in compact:
            compact["rnti"] = f"0x{int(compact['rnti']):04x}"
        return compact

    def _containers(self, window: WindowManager) -> tuple[dict[str, Any], ...]:
        names = [
            *(item.container for item in self.scenario.core.upfs),
            *(item.container for item in self.scenario.ran.gnbs),
            *(item.container for item in self.scenario.ues),
            *(item.container for item in self.scenario.services),
        ]
        records = []
        for name in names:
            cpu, _ = window.mean(f'rate(container_cpu_usage_seconds_total{{name="{name}"}}[1m])')
            memory, _ = window.mean(f'container_memory_working_set_bytes{{name="{name}"}}')
            cpu_limit = window.latest(
                f'container_spec_cpu_quota{{name="{name}"}} / '
                f'container_spec_cpu_period{{name="{name}"}}'
            )
            memory_limit = window.latest(f'container_spec_memory_limit_bytes{{name="{name}"}}')
            records.append(
                {
                    "id": name,
                    "cpu_cores": cpu,
                    "cpu_limit_cores": cpu_limit,
                    "memory_working_set_bytes": memory,
                    "memory_limit_bytes": memory_limit,
                }
            )
        return tuple(records)

    def build(self, trigger_event: str = "PeriodicMonitor") -> UnifiedSnapshot:
        with self.build_lock:
            return self._build(trigger_event)

    def _build(self, trigger_event: str) -> UnifiedSnapshot:
        observed_to = datetime.now(UTC)
        observed_from = observed_to - timedelta(
            seconds=self.scenario.observability.snapshot_window_seconds
        )
        window = WindowManager(
            self.prometheus, observed_from.timestamp(), observed_to.timestamp(), 1
        )
        sessions = self._sessions()
        session_map = {(item["supi"], item["session_id"]): item for item in sessions}
        ues = {item.id: item for item in self.scenario.ues}
        ran_by_gnb = {gnb.id: self._ran_metrics(window, gnb.id) for gnb in self.scenario.ran.gnbs}
        flows = []
        for flow in self.scenario.flows:
            ue = ues[flow.ue_id]
            telemetry, sample_count = self._flow_telemetry(
                window,
                flow.id,
                ue.supi,
                ue.id,
                flow.protocol,
                flow.service_instance_id,
            )
            flows.append(
                correlate_flow(
                    self.scenario,
                    flow,
                    session_map.get((ue.supi, flow.session_id)),
                    ran_by_gnb[ue.serving_gnb],
                    telemetry,
                    observed_from,
                    observed_to,
                    sample_count,
                )
            )
        self.sequence += 1
        snapshot_id = (
            "snapshot-"
            + stable_digest(
                {
                    "run_id": self.run_id,
                    "sequence": self.sequence,
                    "observed_to": observed_to.isoformat(),
                }
            )[:20]
        )
        snapshot = UnifiedSnapshot(
            snapshot_id=snapshot_id,
            run_id=self.run_id,
            observed_from=observed_from,
            observed_to=observed_to,
            topology=json.loads(
                (self.run_dir / "compiled-scenario.json").read_text(encoding="utf-8")
            )["topology"],
            sessions=tuple(sessions),
            flows=tuple(flows),
            ran_nodes=tuple(
                {
                    "id": gnb.id,
                    "name": gnb.container,
                    "node_type": "AN",
                    "hosted_slice_snssais": [
                        f"{item.sst:02d}{item.sd}" for item in self.scenario.slices
                    ],
                    "telemetry": ran_by_gnb[gnb.id],
                }
                for gnb in self.scenario.ran.gnbs
            ),
            core_nodes=tuple(
                {
                    "id": upf.id,
                    "name": upf.container,
                    "node_type": "CN",
                    "hosted_slice_snssais": [
                        f"{item.sst:02d}{item.sd}" for item in self.scenario.slices
                    ],
                    "dnn": upf.dnn,
                }
                for upf in self.scenario.core.upfs
            ),
            containers=self._containers(window),
            mec_sites=tuple(item.model_dump(mode="json") for item in self.scenario.sites),
            mobility=(),
            active_actions=(),
            trigger_event=trigger_event,
        )
        self.store.append(snapshot)
        self.graph_writer.write(snapshot)
        SNAPSHOTS_WRITTEN.labels(self.run_id).set(self.sequence)
        return snapshot


builder: SnapshotBuilder | None = None
periodic_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global builder, periodic_task
    run_dir = Path(os.environ["RUN_DIR"])
    while not (run_dir / "session-observations.json").exists():
        await asyncio.sleep(1)
    builder = SnapshotBuilder(
        run_dir,
        os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"),
        os.environ["MULTIAGENTS_DATABASE_URL"],
    )
    start_http_server(9104)

    async def periodic() -> None:
        while True:
            await asyncio.to_thread(builder.build)
            await asyncio.sleep(builder.scenario.observability.snapshot_interval_seconds)

    periodic_task = asyncio.create_task(periodic())
    yield
    periodic_task.cancel()
    with suppress(asyncio.CancelledError):
        await periodic_task


app = FastAPI(title="Unified Snapshot API", version="1.0", lifespan=lifespan)


def _builder() -> SnapshotBuilder:
    if builder is None:
        raise HTTPException(status_code=503, detail="snapshot builder is not ready")
    return builder


@app.get("/health")
def health() -> dict[str, str]:
    _builder()
    if periodic_task is None or periodic_task.done():
        raise HTTPException(status_code=503, detail="periodic snapshot task is not running")
    return {"status": "ok"}


@app.get("/v1/snapshots/latest")
def latest(run_id: str = Query(...)) -> UnifiedSnapshot:
    service = _builder()
    if run_id != service.run_id:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return service.store.latest()


@app.get("/v1/snapshots/{snapshot_id}")
def by_id(snapshot_id: str) -> UnifiedSnapshot:
    try:
        return _builder().store.get(snapshot_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="unknown snapshot_id") from error


@app.post("/v1/snapshots", status_code=201)
def create_event_snapshot(trigger_event: str = Query(..., min_length=1)) -> UnifiedSnapshot:
    return _builder().build(trigger_event)
