from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from testbed.adapters.docker_adapter import DockerAdapter


def test_container_logs_merges_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **arguments: object) -> subprocess.CompletedProcess[str]:
        observed.update(arguments)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="Received PFCP Association Setup Accepted Response\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    logs = DockerAdapter().container_logs("free5gc-smf")

    assert "PFCP Association" in logs


def test_compose_command_uses_explicit_env_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text("ACTION_GATEWAY_API_KEYS=test\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **arguments: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="services: {}\n")

    monkeypatch.setattr(subprocess, "run", fake_run)

    DockerAdapter(compose_file, compose_env_file=env_file).compose_config()

    assert observed["command"] == [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-f",
        str(compose_file),
        "config",
    ]


def test_compose_logs_are_timestamped_and_bounded(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **arguments: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["timeout"] = arguments["timeout"]
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    DockerAdapter(compose_file).compose_logs()

    assert observed["command"] == [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "logs",
        "--no-color",
        "--timestamps",
        "--tail",
        "10000",
    ]
    assert observed["timeout"] == 300


def test_command_failure_surfaces_stderr(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    def fake_run(command: list[str], **_arguments: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            output="",
            stderr="required variable is missing",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="required variable is missing"):
        DockerAdapter(compose_file).compose_config()


def test_compose_create_uses_host_project_directory(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_run(command: list[str], **_arguments: object) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    project_directory = Path("/host/run/generated")
    DockerAdapter(
        compose_file,
        compose_project_directory=project_directory,
    ).compose_create(["free5gc-upf-urllc"])

    assert observed["command"] == [
        "docker",
        "compose",
        "--project-directory",
        str(project_directory),
        "-f",
        str(compose_file),
        "create",
        "--no-build",
        "free5gc-upf-urllc",
    ]
