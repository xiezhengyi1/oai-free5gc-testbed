from __future__ import annotations

import subprocess
from pathlib import Path


def start_capture(interface: str, destination: Path) -> subprocess.Popen[bytes]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        ["tcpdump", "-i", interface, "-U", "-w", str(destination)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def stop_capture(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    process.wait(timeout=10)
    if process.returncode not in (0, -15):
        stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
        raise RuntimeError(f"tcpdump exited with {process.returncode}: {stderr}")
