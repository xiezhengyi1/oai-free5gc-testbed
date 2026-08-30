from __future__ import annotations

from testbed.adapters.docker_adapter import DockerAdapter


class SmfAdapter:
    def __init__(self, docker: DockerAdapter, container: str = "free5gc-smf") -> None:
        self.docker = docker
        self.container = container

    def logs(self) -> str:
        return self.docker.container_logs(self.container)
