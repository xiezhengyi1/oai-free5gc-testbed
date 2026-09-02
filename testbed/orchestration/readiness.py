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


class Readiness:
    def __init__(self, docker: DockerAdapter, scenario: Scenario) -> None:
        self.docker = docker
        self.scenario = scenario

    def wait(self, probe: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        deadline = time.monotonic() + self.scenario.runtime.startup_timeout_seconds
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
            raise RuntimeError(
                f"expected {expected} PFCP associations, found {accepted}"
            )
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
        services = {item.id: item for item in self.scenario.services}
        ues = {item.id: item for item in self.scenario.ues}
        evidence: dict[str, str] = {}
        for flow in (item for item in self.scenario.flows if item.id in flow_ids):
            ue = ues[flow.ue_id]
            session_index = [item.id for item in ue.sessions].index(flow.session_id) + 1
            service = services[flow.service_instance_id]
            evidence[flow.id] = UeAdapter(self.docker, ue.container).ping(
                service.ip, session_interface(session_index)
            )
        return evidence

    def telemetry(self) -> dict[str, Any]:
        prometheus = PrometheusAdapter("http://127.0.0.1:29090")
        prometheus.ready()
        up = prometheus.instant_query("up")
        expected_targets = 6 + len(self.scenario.ues)
        if len(up) != expected_targets:
            raise RuntimeError(
                f"expected {expected_targets} Prometheus targets, found {len(up)}"
            )
        down = [item["metric"] for item in up if float(item["value"][1]) != 1.0]
        if down:
            raise RuntimeError(f"Prometheus targets are down: {down}")
        snapshot_health = httpx.get("http://127.0.0.1:8081/health", timeout=5)
        snapshot_health.raise_for_status()
        gateway_health = httpx.get("http://127.0.0.1:8080/health", timeout=5)
        gateway_health.raise_for_status()
        return {
            "targets": len(up),
            "snapshot_builder": snapshot_health.json(),
            "action_gateway": gateway_health.json(),
        }
