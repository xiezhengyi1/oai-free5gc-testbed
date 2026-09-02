from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from testbed.orchestration.launcher import Launcher
from testbed.scenario.loader import load_scenario
from testbed.state.models import RunPhase

ROOT = Path(__file__).resolve().parents[2]


class FakeDocker:
    def __init__(self) -> None:
        self.up_calls: list[list[str]] = []
        self.stopped = False

    def compose_config(self) -> None:
        return

    def compose_up(self, services: list[str]) -> None:
        self.up_calls.append(services)

    def compose_stop(self) -> None:
        self.stopped = True


class FakeReadiness:
    def __init__(self) -> None:
        self.gnb_events: list[str] = []
        self.ue_events: list[tuple[str, str]] = []

    def wait(self, probe: Any) -> Any:
        return probe()

    def core(self) -> dict[str, object]:
        return {"containers": []}

    def pfcp(self) -> dict[str, int]:
        return {"accepted_associations": 2}

    def gnb_connected(self, gnb: Any) -> dict[str, str]:
        self.gnb_events.append(gnb.id)
        return {"n2_ip": gnb.n2_ip}

    def ue_registered(self, ue: Any) -> dict[str, str]:
        self.ue_events.append(("registered", ue.id))
        return {"supi": ue.supi}

    def pdu(self, ue: Any) -> list[dict[str, str]]:
        self.ue_events.append(("pdu", ue.id))
        return [{"ue_id": ue.id}]

    def traffic(self) -> dict[str, object]:
        return {}

    def telemetry(self) -> dict[str, object]:
        return {}


class FakeStore:
    def __init__(self, phase: RunPhase = RunPhase.CREATED) -> None:
        self.phase = phase
        self.advances: list[tuple[RunPhase, object]] = []
        self.recoveries: list[dict[str, Any]] = []
        self.stops: list[dict[str, Any]] = []

    def current(self) -> SimpleNamespace:
        return SimpleNamespace(phase=self.phase)

    def advance(self, phase: RunPhase, evidence: object) -> SimpleNamespace:
        self.advances.append((phase, evidence))
        self.phase = phase
        return SimpleNamespace(phase=phase)

    def recover(self, evidence: dict[str, Any]) -> SimpleNamespace:
        self.recoveries.append(evidence)
        return SimpleNamespace(phase=RunPhase.RUNNING)

    def stop(self, evidence: dict[str, Any]) -> SimpleNamespace:
        self.stops.append(evidence)
        return SimpleNamespace(phase=RunPhase.STOPPED)


class FakeSliceManager:
    def __init__(self) -> None:
        self.reconciled = False

    def reconcile_initial(self) -> dict[str, object]:
        self.reconciled = True
        return {}


def test_launcher_brings_multi_ue_pdu_sessions_up_sequentially(
    tmp_path: Path, monkeypatch: Any
) -> None:
    launcher = object.__new__(Launcher)
    launcher.run_dir = tmp_path
    launcher.compose_file = tmp_path / "compose.yaml"
    launcher.compose_env_file = tmp_path / ".env"
    launcher.scenario = load_scenario(
        ROOT / "scenarios/advanced/s6_multi_gnb_multi_upf_multi_ue.yaml"
    )
    launcher.docker = FakeDocker()
    launcher.readiness = FakeReadiness()
    launcher.store = FakeStore()
    launcher.slice_manager = FakeSliceManager()
    monkeypatch.setattr(
        "testbed.orchestration.launcher.provision_subscribers",
        lambda *_args: [ue.supi for ue in launcher.scenario.ues],
    )

    launcher.start()

    assert launcher.readiness.gnb_events == ["gnb-1", "gnb-2"]
    assert ["oai-gnb-1"] in launcher.docker.up_calls
    assert ["oai-gnb-2"] in launcher.docker.up_calls
    assert launcher.readiness.ue_events == [
        ("registered", "ue-1"),
        ("pdu", "ue-1"),
        ("registered", "ue-2"),
        ("pdu", "ue-2"),
    ]
    assert ["oai-nrue-1"] in launcher.docker.up_calls
    assert ["oai-nrue-2"] in launcher.docker.up_calls
    assert ["oai-nrue-1", "oai-nrue-2"] not in launcher.docker.up_calls
    assert launcher.slice_manager.reconciled is True


def test_launcher_resumes_running_run_and_records_recovery(
    tmp_path: Path, monkeypatch: Any
) -> None:
    launcher = object.__new__(Launcher)
    launcher.run_dir = tmp_path
    launcher.compose_file = tmp_path / "compose.yaml"
    launcher.compose_env_file = tmp_path / ".env"
    launcher.scenario = load_scenario(
        ROOT / "scenarios/advanced/s6_multi_gnb_multi_upf_multi_ue.yaml"
    )
    launcher.docker = FakeDocker()
    launcher.readiness = FakeReadiness()
    launcher.store = FakeStore(RunPhase.RUNNING)
    launcher.slice_manager = FakeSliceManager()
    monkeypatch.setattr(
        "testbed.orchestration.launcher.provision_subscribers",
        lambda *_args: [ue.supi for ue in launcher.scenario.ues],
    )

    state = launcher.resume()

    assert state.phase == RunPhase.RUNNING
    assert launcher.store.advances == []
    assert launcher.store.recoveries[0]["ready"] is True
    assert launcher.store.recoveries[0]["recovered_from"] == RunPhase.RUNNING
    assert RunPhase.TELEMETRY_READY.value in launcher.store.recoveries[0]["recovered"]
    assert launcher.readiness.ue_events == [
        ("registered", "ue-1"),
        ("pdu", "ue-1"),
        ("registered", "ue-2"),
        ("pdu", "ue-2"),
    ]
    assert launcher.slice_manager.reconciled is True


def test_launcher_retries_a_failed_recovery(tmp_path: Path, monkeypatch: Any) -> None:
    launcher = object.__new__(Launcher)
    launcher.run_dir = tmp_path
    launcher.compose_file = tmp_path / "compose.yaml"
    launcher.compose_env_file = tmp_path / ".env"
    launcher.scenario = load_scenario(
        ROOT / "scenarios/advanced/s6_multi_gnb_multi_upf_multi_ue.yaml"
    )
    launcher.docker = FakeDocker()
    launcher.readiness = FakeReadiness()
    launcher.store = FakeStore(RunPhase.FAILED)
    launcher.slice_manager = FakeSliceManager()
    monkeypatch.setattr(
        "testbed.orchestration.launcher.provision_subscribers",
        lambda *_args: [ue.supi for ue in launcher.scenario.ues],
    )

    state = launcher.resume()

    assert state.phase == RunPhase.RUNNING
    assert launcher.store.recoveries[0]["recovered_from"] == RunPhase.FAILED


def test_launcher_collects_logs_before_stopping(tmp_path: Path, monkeypatch: Any) -> None:
    launcher = object.__new__(Launcher)
    launcher.run_dir = tmp_path
    launcher.compose_file = tmp_path / "compose.yaml"
    launcher.compose_env_file = tmp_path / ".env"
    launcher.docker = FakeDocker()
    launcher.store = FakeStore(RunPhase.RUNNING)
    collected: list[tuple[Path, Path, Path | None]] = []

    def collect(
        compose_file: Path,
        destination: Path,
        compose_env_file: Path | None = None,
    ) -> Path:
        collected.append((compose_file, destination, compose_env_file))
        return destination

    monkeypatch.setattr("testbed.orchestration.launcher.collect_compose_logs", collect)

    state = launcher.stop()

    assert state.phase == RunPhase.STOPPED
    assert launcher.docker.stopped is True
    assert collected == [
        (tmp_path / "compose.yaml", tmp_path / "logs" / "compose.log", tmp_path / ".env")
    ]
    assert launcher.store.stops == [
        {"compose_stopped": True, "logs": str(tmp_path / "logs" / "compose.log")}
    ]
