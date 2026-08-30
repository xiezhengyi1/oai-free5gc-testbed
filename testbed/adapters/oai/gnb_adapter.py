from __future__ import annotations

from testbed.adapters.docker_adapter import DockerAdapter


class GnbAdapter:
    def __init__(self, docker: DockerAdapter, container: str) -> None:
        self.docker = docker
        self.container = container

    def logs(self) -> str:
        return self.docker.container_logs(self.container)
