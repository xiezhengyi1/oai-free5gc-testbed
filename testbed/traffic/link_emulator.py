from __future__ import annotations

import os
import signal
import subprocess
import threading


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main() -> None:
    delay = float(os.environ["DELAY_MS"])
    jitter = float(os.environ["JITTER_MS"])
    loss_percent = float(os.environ["LOSS_RATE"]) * 100
    bandwidth = float(os.environ["BANDWIDTH_MBPS"])
    for interface in ("n6", "app"):
        _run(
            [
                "tc",
                "qdisc",
                "replace",
                "dev",
                interface,
                "root",
                "netem",
                "delay",
                f"{delay}ms",
                f"{jitter}ms",
                "loss",
                f"{loss_percent}%",
                "rate",
                f"{bandwidth}mbit",
            ]
        )
    _run(["iptables", "-A", "FORWARD", "-i", "n6", "-o", "app", "-j", "ACCEPT"])
    _run(["iptables", "-A", "FORWARD", "-i", "app", "-o", "n6", "-j", "ACCEPT"])
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signal, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signal, _frame: stop.set())
    stop.wait()


if __name__ == "__main__":
    main()
