from __future__ import annotations

from pathlib import Path

from testbed.adapters.docker_adapter import DockerAdapter
from testbed.artifacts.log_collector import collect_compose_logs
from testbed.orchestration.readiness import Readiness
from testbed.orchestration.subscriber_bootstrap import provision_subscribers
from testbed.scenario.loader import load_scenario
from testbed.state.models import RunPhase, RunState
from testbed.state.run_store import RunStore


class Launcher:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir.resolve(strict=True)
        self.scenario = load_scenario(self.run_dir / "source-scenario.yaml")
        self.compose_file = self.run_dir / "generated" / "compose.yaml"
        self.docker = DockerAdapter(
            self.compose_file, timeout_seconds=self.scenario.runtime.action_timeout_seconds
        )
        self.readiness = Readiness(self.docker, self.scenario)
        self.store = RunStore(self.run_dir)

    def start(self) -> RunState:
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
            if self.store.current().phase != RunPhase.CREATED:
                raise ValueError("start requires the run to be in CREATED phase")
            self.docker.compose_config()
            self.docker.compose_up(core_services)
            self.store.advance(RunPhase.CORE_READY, self.readiness.wait(self.readiness.core))

            expected_phase = RunPhase.PFCP_READY
            self.store.advance(RunPhase.PFCP_READY, self.readiness.wait(self.readiness.pfcp))
            subscribers = provision_subscribers(
                self.run_dir / "generated" / "subscribers.json",
                "http://127.0.0.1:5000",
                self.scenario.runtime.startup_timeout_seconds,
                self.scenario.runtime.readiness_poll_seconds,
            )

            expected_phase = RunPhase.GNB_READY
            self.docker.compose_up([item.container for item in self.scenario.ran.gnbs])
            gnb_evidence = self.readiness.wait(self.readiness.gnb)
            gnb_evidence["subscriber_count"] = len(subscribers)
            self.store.advance(RunPhase.GNB_READY, gnb_evidence)

            expected_phase = RunPhase.UE_REGISTERED
            self.docker.compose_up(
                [*application_services, *(item.container for item in self.scenario.ues)]
            )
            self.store.advance(
                RunPhase.UE_REGISTERED, self.readiness.wait(self.readiness.ue_registered)
            )

            expected_phase = RunPhase.PDU_READY
            self.store.advance(RunPhase.PDU_READY, self.readiness.wait(self.readiness.pdu))

            expected_phase = RunPhase.TRAFFIC_READY
            self.docker.compose_up([item.traffic_sidecar for item in self.scenario.ues])
            self.store.advance(RunPhase.TRAFFIC_READY, self.readiness.wait(self.readiness.traffic))

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
            self.store.advance(
                RunPhase.TELEMETRY_READY, self.readiness.wait(self.readiness.telemetry)
            )
            return self.store.advance(RunPhase.RUNNING, {"ready": True})
        except Exception as error:
            log_path = collect_compose_logs(
                self.compose_file, self.run_dir / "logs" / "startup.log"
            )
            self.store.fail(expected_phase, error, {"logs": str(log_path)})
            raise

    def stop(self) -> RunState:
        self.docker.compose_stop()
        return self.store.stop({"compose_stopped": True})

    def reset(self) -> RunState:
        self.docker.compose_down(remove_volumes=True)
        self.store.reset()
        return self.start()
