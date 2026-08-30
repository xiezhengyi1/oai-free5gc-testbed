from __future__ import annotations

from pathlib import Path

from testbed.adapters.docker_adapter import DockerAdapter


def collect_compose_logs(compose_file: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = DockerAdapter(compose_file).compose_logs()
    destination.write_text(output, encoding="utf-8")
    return destination
