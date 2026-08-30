from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class DockerAdapter:
    def __init__(self, compose_file: Path | None = None, timeout_seconds: int = 60) -> None:
        self.compose_file = compose_file.resolve(strict=True) if compose_file else None
        self.timeout_seconds = timeout_seconds

    def _run(self, command: list[str], timeout_seconds: int | None = None) -> str:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds or self.timeout_seconds,
        )
        return completed.stdout

    def _compose_command(self, *arguments: str) -> list[str]:
        if self.compose_file is None:
            raise ValueError("compose_file is required for this operation")
        return ["docker", "compose", "-f", str(self.compose_file), *arguments]

    def compose_up(self, services: list[str]) -> None:
        if not services:
            raise ValueError("compose_up requires at least one explicit service")
        self._run(self._compose_command("up", "-d", "--no-build", *services), timeout_seconds=300)

    def compose_stop(self) -> None:
        self._run(self._compose_command("stop"), timeout_seconds=180)

    def compose_down(self, *, remove_volumes: bool) -> None:
        arguments = ["down", "--remove-orphans"]
        if remove_volumes:
            arguments.append("--volumes")
        self._run(self._compose_command(*arguments), timeout_seconds=180)

    def compose_logs(self) -> str:
        return self._run(self._compose_command("logs", "--no-color"), timeout_seconds=120)

    def compose_config(self) -> str:
        return self._run(self._compose_command("config"), timeout_seconds=60)

    def inspect(self, container: str) -> dict[str, Any]:
        payload = json.loads(self._run(["docker", "inspect", container]))
        if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
            raise ValueError(f"docker inspect returned an invalid payload for {container}")
        return payload[0]

    def container_running(self, container: str) -> bool:
        return self.inspect(container)["State"]["Running"] is True

    def container_logs(self, container: str, *, tail: int = 5000) -> str:
        return self._run(["docker", "logs", "--tail", str(tail), container], timeout_seconds=60)

    def exec(self, container: str, command: list[str]) -> str:
        if not command:
            raise ValueError("docker exec requires an explicit command")
        return self._run(["docker", "exec", container, *command])

    def update_resources(self, container: str, cpus: float, memory_mb: int) -> dict[str, Any]:
        self._run(["docker", "update", "--cpus", str(cpus), "--memory", f"{memory_mb}m", container])
        limits = self.read_resource_limits(container)
        if limits != {"cpus": cpus, "memory_mb": memory_mb}:
            raise RuntimeError(f"resource postcondition failed for {container}: {limits}")
        return limits

    def read_resource_limits(self, container: str) -> dict[str, Any]:
        host_config = self.inspect(container)["HostConfig"]
        nano_cpus = int(host_config["NanoCpus"])
        memory = int(host_config["Memory"])
        return {"cpus": nano_cpus / 1_000_000_000, "memory_mb": memory // (1024 * 1024)}

    def restart(self, container: str) -> dict[str, Any]:
        before = self.inspect(container)
        self._run(["docker", "restart", container], timeout_seconds=120)
        after = self.inspect(container)
        if after["State"]["Running"] is not True:
            raise RuntimeError(f"container did not return to running state: {container}")
        if after["State"]["StartedAt"] == before["State"]["StartedAt"]:
            raise RuntimeError(f"container start timestamp did not change: {container}")
        return {
            "running": True,
            "started_at_before": before["State"]["StartedAt"],
            "started_at_after": after["State"]["StartedAt"],
        }
