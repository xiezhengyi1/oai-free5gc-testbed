from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.artifacts.log_collector import collect_compose_logs
from testbed.gateway.slice_manager import SliceManager
from testbed.orchestration.readiness import Readiness
from testbed.orchestration.subscriber_bootstrap import provision_subscribers
from testbed.scenario.loader import load_scenario
from testbed.state.models import RunPhase, RunState
from testbed.state.run_store import RunStore
from testbed.state.slice_store import SliceStore


class LaunchPhaseError(RuntimeError):
    def __init__(self, phase: RunPhase, cause: Exception) -> None:
        super().__init__(f"{phase}: {type(cause).__name__}: {cause}")
        self.phase = phase
        self.cause = cause


class Launcher:
    def __init__(self, run_dir: Path, compose_env_file: Path | None = None) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.compose_env_file = compose_env_file
        self.scenario = load_scenario(self.run_dir / "source-scenario.yaml")
        self.compose_file = self.run_dir / "generated" / "compose.yaml"
        self.docker = DockerAdapter(
            self.compose_file,
            timeout_seconds=self.scenario.runtime.action_timeout_seconds,
            compose_env_file=self.compose_env_file,
        )
        self.readiness = Readiness(self.docker, self.scenario)
        self.store = RunStore(self.run_dir)
        self.slice_store = SliceStore(self.run_dir)
        self.slice_manager = SliceManager(
            self.scenario,
            self.docker,
            self.readiness,
            self.slice_store,
        )

    def _bring_up(
        self,
        on_ready: Callable[[RunPhase, dict[str, Any]], None],
    ) -> None:
        core_services = [
            "mongodb",
            "free5gc-nrf",
            "free5gc-ausf",
            "free5gc-nssf",
            "free5gc-pcf",
            "free5gc-udm",
            "free5gc-udr",
            "free5gc-nef",
            "free5gc-amf",
            *(item.container for item in self.scenario.core.upfs),
            "free5gc-smf",
            "free5gc-webui",
            "free5gc-chf",
        ]
        application_services = [item.container for item in self.scenario.services]
        application_services.extend(item.container for item in self.scenario.links)
        expected_phase = RunPhase.CORE_READY
        try:
            self.docker.compose_config()
            self.docker.compose_up(core_services)
            on_ready(RunPhase.CORE_READY, self.readiness.wait(self.readiness.core))

            expected_phase = RunPhase.PFCP_READY
            on_ready(RunPhase.PFCP_READY, self.readiness.wait(self.readiness.pfcp))
            subscribers = provision_subscribers(
                self.run_dir / "generated" / "subscribers.json",
                "http://127.0.0.1:5000",
                self.scenario.runtime.startup_timeout_seconds,
                self.scenario.runtime.readiness_poll_seconds,
            )

            expected_phase = RunPhase.GNB_READY
            gnb_evidence: dict[str, Any] = {}
            for gnb in self.scenario.ran.gnbs:
                self.docker.compose_up([gnb.container])
                gnb_evidence[gnb.id] = self.readiness.wait(
                    lambda gnb=gnb: self.readiness.gnb_connected(gnb)
                )
            gnb_evidence["subscriber_count"] = len(subscribers)
            on_ready(RunPhase.GNB_READY, gnb_evidence)

            self.docker.compose_up(application_services)
            registered_supis: list[str] = []
            tunnels: dict[str, object] = {}
            for ue in self.scenario.ues:
                expected_phase = RunPhase.UE_REGISTERED
                self.docker.compose_up([ue.container])
                registration = self.readiness.wait(lambda ue=ue: self.readiness.ue_registered(ue))
                registered_supis.append(registration["supi"])

                expected_phase = RunPhase.PDU_READY
                tunnels[ue.id] = self.readiness.wait(lambda ue=ue: self.readiness.pdu(ue))
            on_ready(RunPhase.UE_REGISTERED, {"registered_supis": registered_supis})
            on_ready(RunPhase.PDU_READY, tunnels)

            expected_phase = RunPhase.TRAFFIC_READY
            self.docker.compose_up([item.traffic_sidecar for item in self.scenario.ues])
            on_ready(RunPhase.TRAFFIC_READY, self.readiness.wait(self.readiness.traffic))
            self.slice_manager.reconcile_initial()

            expected_phase = RunPhase.TELEMETRY_READY
            self.docker.compose_up(
                [
                    "prometheus",
                    "cadvisor",
                    "grafana",
                    "ran-exporter",
                    "session-tracker",
                    "snapshot-builder",
                    "action-gateway",
                ]
            )
            on_ready(
                RunPhase.TELEMETRY_READY, self.readiness.wait(self.readiness.telemetry)
            )
        except Exception as error:
            raise LaunchPhaseError(expected_phase, error) from error

    def _record_failure(self, failure: LaunchPhaseError, log_name: str) -> None:
        log_path = collect_compose_logs(
            self.compose_file,
            self.run_dir / "logs" / log_name,
            compose_env_file=self.compose_env_file,
        )
        self.store.fail(failure.phase, failure.cause, {"logs": str(log_path)})

    def start(self) -> RunState:
        if self.store.current().phase != RunPhase.CREATED:
            raise ValueError("start requires the run to be in CREATED phase")
        try:
            self._bring_up(self.store.advance)
        except LaunchPhaseError as failure:
            self._record_failure(failure, "startup.log")
            raise failure.cause from failure
        return self.store.advance(RunPhase.RUNNING, {"ready": True})

    def resume(self) -> RunState:
        current_phase = self.store.current().phase
        if current_phase not in (RunPhase.RUNNING, RunPhase.FAILED):
            raise ValueError("resume requires the run to be in RUNNING or FAILED phase")
        recovered: dict[str, Any] = {}

        def observe(phase: RunPhase, evidence: dict[str, Any]) -> None:
            recovered[phase.value] = evidence

        try:
            self._bring_up(observe)
        except LaunchPhaseError as failure:
            self._record_failure(failure, "recovery.log")
            raise failure.cause from failure
        return self.store.recover(
            {
                "ready": True,
                "recovered_from": current_phase,
                "recovered": recovered,
            }
        )

    def stop(self) -> RunState:
        log_path = collect_compose_logs(
            self.compose_file,
            self.run_dir / "logs" / "compose.log",
            compose_env_file=self.compose_env_file,
        )
        self.docker.compose_stop()
        return self.store.stop({"compose_stopped": True, "logs": str(log_path)})

    def reset(self) -> RunState:
        self.docker.compose_down(remove_volumes=True)
        self.store.reset()
        return self.start()
