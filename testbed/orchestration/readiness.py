from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.adapters.oai.ue_adapter import UeAdapter, session_interface
from testbed.adapters.prometheus_adapter import PrometheusAdapter
from testbed.scenario.schema import GnbSpec, Scenario, UeSpec
from testbed.telemetry.models import UnifiedSnapshot


class Readiness:
    def __init__(
        self,
        docker: DockerAdapter,
        scenario: Scenario,
        prometheus_url: str = "http://127.0.0.1:29090",
    ) -> None:
        self.docker = docker
        self.scenario = scenario
        self.prometheus_url = prometheus_url

    def wait(
        self, probe: Callable[[], dict[str, Any]], timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        timeout = (
            self.scenario.runtime.startup_timeout_seconds
            if timeout_seconds is None
            else timeout_seconds
        )
        deadline = time.monotonic() + timeout
        while True:
            try:
                return probe()
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(self.scenario.runtime.readiness_poll_seconds)

    def core(self) -> dict[str, Any]:
        containers = [
            "mongodb",
            "free5gc-nrf",
            "free5gc-ausf",
            "free5gc-nssf",
            "free5gc-pcf",
            "free5gc-udm",
            "free5gc-udr",
            "free5gc-nef",
            "free5gc-amf",
            "free5gc-smf",
            "free5gc-webui",
            "free5gc-chf",
            *(item.container for item in self.scenario.core.upfs),
        ]
        stopped = [item for item in containers if not self.docker.container_running(item)]
        if stopped:
            raise RuntimeError(f"core containers are not running: {stopped}")
        return {"containers": containers}

    def mongodb(self) -> dict[str, bool]:
        output = self.docker.exec(
            "mongodb", ["mongo", "--quiet", "--eval", "db.adminCommand('ping').ok"]
        )
        if output.strip() != "1":
            raise RuntimeError(f"MongoDB ping returned {output.strip()!r}")
        return {"ready": True}

    def nrf(self) -> dict[str, bool]:
        logs = self.docker.container_logs("free5gc-nrf")
        if "SBI server started" not in logs:
            raise RuntimeError("NRF SBI server is not ready")
        return {"ready": True}

    def nf_registered(self, container: str) -> dict[str, bool]:
        logs = self.docker.container_logs(container)
        if "register to NRF Error" in logs:
            raise RuntimeError(f"{container} did not complete its initial NRF registration")
        if "OAuth2 setting receive from NRF: true" not in logs:
            raise RuntimeError(f"{container} has no successful OAuth2 NRF registration evidence")
        return {"oauth2": True}

    def pfcp(self) -> dict[str, Any]:
        accepted = self.pfcp_count()
        if accepted < len(self.scenario.core.upfs):
            raise RuntimeError(
                f"expected {len(self.scenario.core.upfs)} PFCP associations, found {accepted}"
            )
        return {"accepted_associations": accepted}

    def pfcp_count(self) -> int:
        logs = self.docker.container_logs("free5gc-smf")
        return logs.count("Received PFCP Association Setup Accepted Response")

    def pfcp_associations(self, expected: int) -> dict[str, int]:
        accepted = self.pfcp_count()
        if accepted < expected:
            raise RuntimeError(f"expected {expected} PFCP associations, found {accepted}")
        return {"accepted_associations": accepted}

    def gnb_connected(self, gnb: GnbSpec) -> dict[str, str]:
        amf_logs = self.docker.container_logs("free5gc-amf")
        gnb_logs = self.docker.container_logs(gnb.container)
        if re.search(r"NG.?Setup.*(Response|successful)", gnb_logs, re.IGNORECASE) is None:
            raise RuntimeError(f"gNB {gnb.id} has no successful NG Setup evidence")
        if gnb.id not in amf_logs and gnb.n2_ip not in amf_logs:
            raise RuntimeError(f"AMF has no N2 evidence for {gnb.id}")
        return {"n2_ip": gnb.n2_ip}

    def gnb(self) -> dict[str, Any]:
        return {gnb.id: self.gnb_connected(gnb) for gnb in self.scenario.ran.gnbs}

    def ue_registered(self, ue: UeSpec) -> dict[str, str]:
        amf_logs = self.docker.container_logs("free5gc-amf")
        registration = re.compile(
            rf"\[supi:SUPI:{re.escape(ue.supi)}\].*Handle Registration Complete"
        )
        if registration.search(amf_logs) is None:
            raise RuntimeError(f"AMF has no registration-complete evidence for {ue.id}")
        return {"supi": ue.supi}

    def pdu(self, ue: UeSpec) -> list[dict[str, Any]]:
        adapter = UeAdapter(self.docker, ue.container)
        return [
            adapter.tunnel(session_interface(index)) for index, _ in enumerate(ue.sessions, start=1)
        ]

    def initial_pdu(self, ue: UeSpec) -> list[dict[str, Any]]:
        return [UeAdapter(self.docker, ue.container).tunnel()]

    def pdu_for_slice(self, ue: UeSpec, slice_id: str) -> list[dict[str, Any]]:
        adapter = UeAdapter(self.docker, ue.container)
        return [
            adapter.tunnel(session_interface(index))
            for index, session in enumerate(ue.sessions, start=1)
            if session.slice_id == slice_id
        ]

    def traffic(self) -> dict[str, Any]:
        return self._traffic({flow.id for flow in self.scenario.flows})

    def traffic_for_slice(self, slice_id: str) -> dict[str, Any]:
        session_slice = {
            (ue.id, session.id): session.slice_id
            for ue in self.scenario.ues
            for session in ue.sessions
        }
        return self._traffic(
            {
                flow.id
                for flow in self.scenario.flows
                if session_slice[(flow.ue_id, flow.session_id)] == slice_id
            }
        )

    def _traffic(self, flow_ids: set[str]) -> dict[str, Any]:
        prometheus = PrometheusAdapter(self.prometheus_url)
        prometheus.ready()
        running = {
            row["metric"]["flow_id"]: float(row["value"][1])
            for row in prometheus.instant_query("testbed_flow_running")
        }
        missing = flow_ids - running.keys()
        stopped = {flow_id for flow_id in flow_ids if running.get(flow_id) != 1.0}
        if missing or stopped:
            raise RuntimeError(
                f"traffic workers are not running: missing={sorted(missing)}, stopped={sorted(stopped)}"
            )
        return {flow_id: {"running": True} for flow_id in sorted(flow_ids)}

    def telemetry_sources(self) -> dict[str, Any]:
        prometheus = PrometheusAdapter(self.prometheus_url)
        prometheus.ready()
        up = prometheus.instant_query(
            'up{instance!="snapshot-builder:9104",instance!="action-gateway:9105"}'
        )
        expected_targets = 4 + len(self.scenario.ues)
        if len(up) != expected_targets:
            raise RuntimeError(f"expected {expected_targets} Prometheus targets, found {len(up)}")
        down = [item["metric"] for item in up if float(item["value"][1]) != 1.0]
        if down:
            raise RuntimeError(f"Prometheus targets are down: {down}")
        containers = [
            *(item.container for item in self.scenario.core.upfs),
            *(item.container for item in self.scenario.ran.gnbs),
        ]
        for name in containers:
            for query in [
                f'rate(container_cpu_usage_seconds_total{{name="{name}"}}[1m])',
                f'container_memory_working_set_bytes{{name="{name}"}}',
            ]:
                if not prometheus.instant_query(query):
                    raise RuntimeError(f"resource metric is not sampled yet: {query}")
        return {"targets": len(up), "resource_containers": containers}

    def telemetry(self) -> dict[str, Any]:
        prometheus = PrometheusAdapter(self.prometheus_url)
        prometheus.ready()
        up = prometheus.instant_query("up")
        expected_targets = 6 + len(self.scenario.ues)
        if len(up) != expected_targets:
            raise RuntimeError(f"expected {expected_targets} Prometheus targets, found {len(up)}")
        down = [item["metric"] for item in up if float(item["value"][1]) != 1.0]
        if down:
            raise RuntimeError(f"Prometheus targets are down: {down}")
        snapshot_health = httpx.get("http://127.0.0.1:8081/health", timeout=5)
        snapshot_health.raise_for_status()
        gateway_health = httpx.get("http://127.0.0.1:8080/health", timeout=5)
        gateway_health.raise_for_status()
        response = httpx.post(
            "http://127.0.0.1:8081/v1/snapshots",
            params={"trigger_event": "TelemetryReadiness"},
            timeout=self.scenario.runtime.action_timeout_seconds,
        )
        response.raise_for_status()
        snapshot = UnifiedSnapshot.model_validate(response.json())
        if {flow["flow_id"] for flow in snapshot.flows} != {
            flow.id for flow in self.scenario.flows
        }:
            raise RuntimeError("telemetry snapshot does not cover the declared flows")
        if any(
            flow["data_quality"]["correlation_status"] != "complete"
            or flow["data_quality"]["stale"]
            for flow in snapshot.flows
        ):
            raise RuntimeError("telemetry snapshot has incomplete or stale flow evidence")
        return {
            "targets": len(up),
            "snapshot_builder": snapshot_health.json(),
            "action_gateway": gateway_health.json(),
            "snapshot_id": snapshot.snapshot_id,
            "run_id": snapshot.run_id,
        }
