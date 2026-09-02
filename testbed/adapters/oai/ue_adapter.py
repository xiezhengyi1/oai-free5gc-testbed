from __future__ import annotations

import json
from typing import Any

from testbed.adapters.docker_adapter import DockerAdapter


def session_interface(session_index: int) -> str:
    return "oaitun_ue1" if session_index == 1 else f"oaitun_ue1p{session_index}"


class UeAdapter:
    def __init__(self, docker: DockerAdapter, container: str) -> None:
        self.docker = docker
        self.container = container

    def tunnel(self, interface: str = "oaitun_ue1") -> dict[str, Any]:
        payload = json.loads(
            self.docker.exec(self.container, ["ip", "-j", "addr", "show", interface])
        )
        if not isinstance(payload, list) or len(payload) != 1:
            raise RuntimeError(f"UE tunnel is absent: {self.container}/{interface}")
        return payload[0]

    def ping(self, target: str, interface: str = "oaitun_ue1") -> str:
        return self.docker.exec(
            self.container, ["ping", "-I", interface, "-c", "3", "-W", "2", target]
        )
