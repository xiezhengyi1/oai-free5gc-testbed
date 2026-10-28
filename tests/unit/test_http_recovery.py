"""Real loopback sockets exercise the recovered HTTP worker's failure boundaries."""

from __future__ import annotations

import socket
import struct
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from testbed.traffic import exporter

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="SO_BINDTODEVICE requires Linux")


@pytest.mark.parametrize(
    "mode",
    [
        "timeout_header",
        "timeout_body",
        "stop_header",
        "stop_body",
        "truncated",
        "reset",
        "status500",
    ],
)
def test_http_recovers_transport_errors_and_preserves_status_failure(monkeypatch, mode):
    stop, ready, done = threading.Event(), threading.Event(), threading.Event()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)
    source = socket.socket()
    source.bind(("127.0.0.1", 0))
    port = source.getsockname()[1]
    source.close()
    held, errors, counts = [], [], []

    def serve():
        attempt = 0
        while not done.is_set():
            try:
                connection, _ = listener.accept()
            except TimeoutError:
                continue
            attempt += 1
            held.append(connection)
            connection.settimeout(0.1)
            try:
                connection.recv(4096)
                if mode == "stop_header":
                    ready.set()
                    continue
                if mode == "stop_body":
                    connection.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 100\r\n\r\nx")
                    ready.set()
                    continue
                if mode == "timeout_header" and attempt == 1:
                    continue
                if mode in ("timeout_body", "truncated") and attempt == 1:
                    connection.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 100\r\n\r\nx")
                    if mode == "truncated":
                        connection.close()
                    continue
                if mode == "reset" and attempt == 1:
                    connection.setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                    connection.close()
                    continue
                if mode == "status500":
                    connection.sendall(b"HTTP/1.0 500 Error\r\nContent-Length: 0\r\n\r\n")
                    continue
                connection.sendall(b"HTTP/1.0 200 OK\r\nContent-Length: 3\r\n\r\nabc")
                connection.close()
            except OSError:
                pass

    class Metric:
        def labels(self, *_args):
            return self

        def set(self, _value):
            pass

        def inc(self):
            counts.append(1)
            stop.set()

    for name in (
        "RUNNING",
        "COMPAT_TRAFFIC_RUNNING",
        "HTTP_LATENCY",
        "HTTP_REQUESTS",
        "JITTER",
        "THROUGHPUT",
        "THROUGHPUT_DL",
    ):
        monkeypatch.setattr(exporter, name, Metric())
    monkeypatch.setattr(exporter, "_labels", lambda _profile: ())
    original = exporter.BoundHTTPConnection

    def connect(profile):
        connection = original(profile)
        connection.timeout = 0.15
        return connection

    monkeypatch.setattr(exporter, "BoundHTTPConnection", connect)
    profile = SimpleNamespace(
        five_tuple=SimpleNamespace(
            destination_ip="127.0.0.1", destination_port=listener.getsockname()[1], source_port=port
        ),
        interface="lo",
        packet_size_bytes=3,
        rate_mbps=1,
        timing=SimpleNamespace(
            packet_interval=lambda *_: 0.01, next_active=lambda deadline, _origin: deadline
        ),
    )

    def work():
        try:
            exporter._http_worker(profile, stop)
        except Exception as exc:
            errors.append(exc)

    server, worker = threading.Thread(target=serve), threading.Thread(target=work)
    server.start()
    worker.start()
    try:
        if mode.startswith("stop_"):
            assert ready.wait(2)
            began = time.monotonic()
            stop.set()
        else:
            began = time.monotonic()
        worker.join(3)
        assert not worker.is_alive()
        if mode == "status500":
            assert errors and isinstance(errors[0], RuntimeError) and not counts
        elif mode.startswith("stop_"):
            assert not errors and not counts and time.monotonic() - began < 1
        else:
            assert not errors and len(counts) == 1
    finally:
        stop.set()
        done.set()
        for connection in held:
            connection.close()
        worker.join(1)
        server.join(1)
        listener.close()
