from __future__ import annotations

import io
import socket
import subprocess
import threading

import pytest

from testbed.traffic.commands import traffic_command
from testbed.traffic.exporter import (
    BoundHTTPConnection,
    _parse_iperf_interval,
    _ping_worker,
)
from testbed.traffic.profiles import TrafficProfile


class StoppablePing:
    def __init__(self) -> None:
        self.stdout = iter(["64 bytes: icmp_seq=1 time=1.0 ms\n"])
        self.stderr = io.StringIO()
        self.return_code: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.return_code

    def terminate(self) -> None:
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout: int) -> int:
        if not self.terminated:
            raise subprocess.TimeoutExpired("ping", timeout)
        return 0


def test_ping_worker_terminates_process_when_stop_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = StoppablePing()
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: process)
    profile = TrafficProfile.model_validate(
        {
            "flow_id": "flow-1",
            "ue_id": "ue-1",
            "supi": "imsi-208930000000001",
            "session_id": "session-1",
            "interface": "oaitun_ue1",
            "service_instance_id": "service-1",
            "five_tuple": {
                "source_ip": "assigned-after-pdu-session",
                "source_port": 41001,
                "destination_ip": "172.34.0.100",
                "destination_port": 5202,
                "protocol": "udp",
            },
            "rate_mbps": 1,
            "packet_size_bytes": 1200,
            "sla": {"latency_ms": 20},
        }
    )
    stop = threading.Event()
    stop.set()

    _ping_worker(profile, stop)

    assert process.terminated is True


def test_bookworm_iperf_interval_is_parsed_without_json_stream() -> None:
    line = "[  5]   1.00-2.00   sec  5.96 MBytes  50.0 Mbits/sec    2   1.25 MBytes"

    assert _parse_iperf_interval(line) == (1.0, 50.0, 2.0)


def test_traffic_command_uses_supported_streaming_text_output() -> None:
    profile = TrafficProfile.model_validate(
        {
            "flow_id": "flow-1",
            "ue_id": "ue-1",
            "supi": "imsi-208930000000001",
            "session_id": "session-1",
            "interface": "oaitun_ue1",
            "service_instance_id": "service-1",
            "five_tuple": {
                "source_ip": "assigned-after-pdu-session",
                "source_port": 41001,
                "destination_ip": "172.34.0.100",
                "destination_port": 5201,
                "protocol": "tcp",
            },
            "rate_mbps": 1,
            "packet_size_bytes": 1200,
            "sla": {"latency_ms": 20},
        }
    )

    command = traffic_command(profile)

    assert "--json-stream" not in command
    assert command[command.index("--format") + 1] == "m"


def test_bound_http_connection_reuses_declared_source_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.options: list[tuple[int, int, object]] = []

        def settimeout(self, _timeout: float) -> None:
            return

        def setsockopt(self, level: int, option: int, value: object) -> None:
            self.options.append((level, option, value))

        def bind(self, _address: tuple[str, int]) -> None:
            return

        def connect(self, _address: tuple[str, int]) -> None:
            return

    created = FakeSocket()
    monkeypatch.setattr(socket, "socket", lambda *_args: created)
    profile = TrafficProfile.model_validate(
        {
            "flow_id": "flow-1",
            "ue_id": "ue-1",
            "supi": "imsi-208930000000001",
            "session_id": "session-1",
            "interface": "oaitun_ue1",
            "service_instance_id": "service-1",
            "five_tuple": {
                "source_ip": "assigned-after-pdu-session",
                "source_port": 41001,
                "destination_ip": "172.34.0.100",
                "destination_port": 8080,
                "protocol": "http",
            },
            "rate_mbps": 1,
            "packet_size_bytes": 1200,
            "sla": {"latency_ms": 20},
        }
    )

    BoundHTTPConnection(profile).connect()

    assert (socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) in created.options
