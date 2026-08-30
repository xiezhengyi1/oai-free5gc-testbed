from __future__ import annotations

import json
import os
import re
import select
import signal
import socket
import struct
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from http.client import HTTPConnection
from pathlib import Path

from prometheus_client import Counter, Gauge, start_http_server

from testbed.traffic.commands import ping_command, traffic_command
from testbed.traffic.profiles import TrafficProfile, load_profiles

LABELS = ("flow_id", "supi", "ue_id", "protocol", "service_instance_id")
RUNNING = Gauge("testbed_flow_running", "Whether the traffic process is running", LABELS)
THROUGHPUT = Gauge("testbed_flow_throughput_mbps", "Measured traffic throughput", LABELS)
JITTER = Gauge("testbed_flow_jitter_ms", "UDP jitter", LABELS)
LOSS = Gauge("testbed_flow_loss_ratio", "UDP loss ratio from zero to one", LABELS)
RETRANSMITS = Counter("testbed_flow_tcp_retransmits_total", "TCP retransmissions", LABELS)
PING_RTT = Gauge("testbed_flow_ping_rtt_ms", "Latest ICMP RTT", LABELS)
PING_RECEIVED = Counter("testbed_flow_ping_received_total", "Received ICMP replies", LABELS)
HTTP_LATENCY = Gauge("testbed_flow_http_latency_ms", "HTTP transaction latency", LABELS)
HTTP_REQUESTS = Counter("testbed_flow_http_requests_total", "Completed HTTP requests", LABELS)
UDP_LATENCY = Gauge("testbed_flow_udp_latency_ms", "UDP echo round-trip latency", LABELS)
UDP_SENT = Counter("testbed_flow_udp_sent_total", "Sent UDP echo datagrams", LABELS)
UDP_RECEIVED = Counter("testbed_flow_udp_received_total", "Received UDP echo datagrams", LABELS)

COMPAT_TRAFFIC_RUNNING = Gauge(
    "container_agent_traffic_running", "Project-compatible traffic state"
)
COMPAT_PING_RUNNING = Gauge("container_agent_ping_running", "Project-compatible ping state")
COMPAT_STREAM_ERRORS = Counter(
    "container_agent_traffic_stream_errors_total", "Project-compatible stream failures"
)
COMPAT_PING_SENT = Counter("container_agent_ping_sent_total", "Project-compatible ping sent")
COMPAT_PING_RECEIVED = Counter(
    "container_agent_ping_received_total", "Project-compatible ping received"
)
COMPAT_PING_LOST = Counter("container_agent_ping_lost_total", "Project-compatible ping lost")
COMPAT_PING_RTT = Gauge(
    "container_agent_ping_rtt_milliseconds", "Project-compatible latest ping RTT"
)
COMPAT_PING_RTT_SUM = Gauge(
    "container_agent_ping_rtt_milliseconds_sum", "Project-compatible cumulative ping RTT"
)
COMPAT_PING_RTT_COUNT = Gauge(
    "container_agent_ping_rtt_milliseconds_count", "Project-compatible ping sample count"
)
COMPAT_TCP_SENT_BYTES = Counter(
    "container_agent_tcp_sent_bytes_total", "Project-compatible TCP bytes"
)
COMPAT_TCP_RETRANSMITS = Counter(
    "container_agent_tcp_retransmits_total", "Project-compatible TCP retransmissions"
)
COMPAT_TCP_BPS = Gauge(
    "container_agent_tcp_interval_sender_bits_per_second", "Project-compatible TCP rate"
)
COMPAT_TCP_INTERVAL_RETRANSMITS = Gauge(
    "container_agent_tcp_interval_retransmits", "Project-compatible interval retransmissions"
)
COMPAT_TCP_RTT_AVERAGE = Gauge(
    "container_agent_tcp_interval_rtt_milliseconds_average", "Project-compatible mean TCP RTT"
)
COMPAT_TCP_RTT_MAXIMUM = Gauge(
    "container_agent_tcp_interval_rtt_milliseconds_maximum", "Project-compatible max TCP RTT"
)
COMPAT_TCP_PARALLEL = Gauge(
    "container_agent_tcp_parallel_streams", "Project-compatible TCP stream count"
)
COMPAT_TCP_SEQUENCE = Gauge(
    "container_agent_tcp_interval_sequence", "Project-compatible TCP interval sequence"
)
COMPAT_UDP_RECEIVED_BYTES = Counter(
    "container_agent_udp_received_bytes_total", "Project-compatible UDP bytes"
)
COMPAT_UDP_DATAGRAMS = Counter(
    "container_agent_udp_datagrams_total", "Project-compatible UDP datagrams"
)
COMPAT_UDP_LOST = Counter(
    "container_agent_udp_lost_packets_total", "Project-compatible UDP lost packets"
)
COMPAT_UDP_JITTER = Gauge(
    "container_agent_udp_interval_jitter_milliseconds", "Project-compatible UDP jitter"
)
COMPAT_UDP_BPS = Gauge(
    "container_agent_udp_interval_bits_per_second", "Project-compatible UDP rate"
)
COMPAT_UDP_TARGET_BPS = Gauge(
    "container_agent_udp_target_bits_per_second", "Project-compatible UDP target rate"
)
COMPAT_UDP_LENGTH = Gauge(
    "container_agent_udp_length_bytes", "Project-compatible UDP datagram length"
)
COMPAT_UDP_PARALLEL = Gauge(
    "container_agent_udp_parallel_streams", "Project-compatible UDP stream count"
)

PING_PATTERN = re.compile(r"icmp_seq=(\d+).*time=([0-9.]+)\s*ms")


class BoundHTTPConnection(HTTPConnection):
    def __init__(self, profile: TrafficProfile) -> None:
        super().__init__(
            profile.five_tuple.destination_ip,
            profile.five_tuple.destination_port,
            timeout=5,
        )
        self.interface = profile.interface
        self.source_port = profile.five_tuple.source_port

    def connect(self) -> None:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.setsockopt(
            socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode() + b"\0"
        )
        connection.bind(("", self.source_port))
        connection.connect((self.host, self.port))
        self.sock = connection


def _labels(profile: TrafficProfile) -> tuple[str, ...]:
    return (
        profile.flow_id,
        profile.supi,
        profile.ue_id,
        profile.five_tuple.protocol,
        profile.service_instance_id,
    )


def _traffic_worker(profile: TrafficProfile, stop: threading.Event) -> None:
    labels = _labels(profile)
    process = subprocess.Popen(
        traffic_command(profile),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    RUNNING.labels(*labels).set(1)
    COMPAT_TRAFFIC_RUNNING.set(1)
    try:
        if process.stdout is None:
            raise RuntimeError("iperf3 stdout pipe was not created")
        for line in process.stdout:
            if stop.is_set():
                break
            event = json.loads(line)
            if event.get("event") == "interval":
                data = event["data"]
                interval = data.get("sum") or data.get("sum_sent")
                THROUGHPUT.labels(*labels).set(float(interval["bits_per_second"]) / 1_000_000)
                RETRANSMITS.labels(*labels).inc(float(interval["retransmits"]))
                COMPAT_TCP_SENT_BYTES.inc(float(interval["bytes"]))
                COMPAT_TCP_RETRANSMITS.inc(float(interval["retransmits"]))
                COMPAT_TCP_BPS.set(float(interval["bits_per_second"]))
                streams = data.get("streams", [])
                rtts_ms = [
                    float(item["rtt"]) / 1000 for item in streams if "rtt" in item
                ]
                COMPAT_TCP_INTERVAL_RETRANSMITS.set(float(interval["retransmits"]))
                COMPAT_TCP_RTT_AVERAGE.set(
                    sum(rtts_ms) / len(rtts_ms) if rtts_ms else 0
                )
                COMPAT_TCP_RTT_MAXIMUM.set(max(rtts_ms) if rtts_ms else 0)
                COMPAT_TCP_PARALLEL.set(max(1, len(streams)))
                COMPAT_TCP_SEQUENCE.inc()
        return_code = process.wait(timeout=5)
        if not stop.is_set() and return_code != 0:
            stderr = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"iperf3 failed for {profile.flow_id}: {stderr}")
    finally:
        RUNNING.labels(*labels).set(0)
        COMPAT_TRAFFIC_RUNNING.set(0)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def _udp_worker(profile: TrafficProfile, stop: threading.Event) -> None:
    labels = _labels(profile)
    header = struct.Struct("!Qd")
    payload = b"x" * (profile.packet_size_bytes - header.size)
    interval = profile.packet_size_bytes * 8 / (profile.rate_mbps * 1_000_000)
    expiry_seconds = max(1.0, float(profile.sla["latency_ms"]) * 4 / 1000)
    destination = (
        profile.five_tuple.destination_ip,
        profile.five_tuple.destination_port,
    )
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_BINDTODEVICE,
        profile.interface.encode() + b"\0",
    )
    udp_socket.bind(("", profile.five_tuple.source_port))
    udp_socket.connect(destination)
    udp_socket.setblocking(False)
    pending: dict[int, float] = {}
    sent_order: deque[tuple[int, float]] = deque()
    sequence = 0
    jitter_ms = 0.0
    previous_rtt_ms: float | None = None
    received_bytes_window = 0
    received_window = 0
    lost_window = 0
    next_send = time.monotonic()
    last_report = next_send
    RUNNING.labels(*labels).set(1)
    COMPAT_TRAFFIC_RUNNING.set(1)
    COMPAT_UDP_TARGET_BPS.set(profile.rate_mbps * 1_000_000)
    COMPAT_UDP_LENGTH.set(profile.packet_size_bytes)
    COMPAT_UDP_PARALLEL.set(1)
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_send:
                sequence += 1
                packet = header.pack(sequence, now) + payload
                udp_socket.send(packet)
                pending[sequence] = now
                sent_order.append((sequence, now))
                UDP_SENT.labels(*labels).inc()
                next_send += interval

            timeout = min(max(0.0, next_send - now), 0.05)
            readable, _, _ = select.select([udp_socket], [], [], timeout)
            if readable:
                response = udp_socket.recv(profile.packet_size_bytes)
                received_at = time.monotonic()
                received_sequence, sent_at = header.unpack_from(response)
                if received_sequence in pending:
                    del pending[received_sequence]
                    rtt_ms = (received_at - sent_at) * 1000
                    if previous_rtt_ms is not None:
                        jitter_ms += (abs(rtt_ms - previous_rtt_ms) - jitter_ms) / 16
                    previous_rtt_ms = rtt_ms
                    received_bytes_window += len(response)
                    received_window += 1
                    UDP_RECEIVED.labels(*labels).inc()
                    UDP_LATENCY.labels(*labels).set(rtt_ms)
                    COMPAT_UDP_RECEIVED_BYTES.inc(len(response))
                    COMPAT_UDP_DATAGRAMS.inc()

            now = time.monotonic()
            cutoff = now - expiry_seconds
            while sent_order and sent_order[0][1] < cutoff:
                expired_sequence, _sent_at = sent_order.popleft()
                if expired_sequence in pending:
                    del pending[expired_sequence]
                    lost_window += 1
                    COMPAT_UDP_LOST.inc()

            elapsed = now - last_report
            if elapsed >= 1.0:
                bits_per_second = received_bytes_window * 8 / elapsed
                resolved = received_window + lost_window
                loss_ratio = lost_window / resolved if resolved else 0.0
                THROUGHPUT.labels(*labels).set(bits_per_second / 1_000_000)
                JITTER.labels(*labels).set(jitter_ms)
                LOSS.labels(*labels).set(loss_ratio)
                COMPAT_UDP_JITTER.set(jitter_ms)
                COMPAT_UDP_BPS.set(bits_per_second)
                received_bytes_window = 0
                received_window = 0
                lost_window = 0
                last_report = now
    finally:
        udp_socket.close()
        RUNNING.labels(*labels).set(0)
        COMPAT_TRAFFIC_RUNNING.set(0)


def _ping_worker(profile: TrafficProfile, stop: threading.Event) -> None:
    labels = _labels(profile)
    process = subprocess.Popen(
        ping_command(profile), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    previous_sequence: int | None = None
    rtt_sum = 0.0
    rtt_count = 0
    COMPAT_PING_RUNNING.set(1)
    try:
        if process.stdout is None:
            raise RuntimeError("ping stdout pipe was not created")
        for line in process.stdout:
            if stop.is_set():
                break
            match = PING_PATTERN.search(line)
            if match:
                sequence = int(match.group(1))
                rtt_ms = float(match.group(2))
                sent = 1 if previous_sequence is None else max(1, sequence - previous_sequence)
                lost = sent - 1
                previous_sequence = sequence
                rtt_sum += rtt_ms
                rtt_count += 1
                PING_RTT.labels(*labels).set(rtt_ms)
                PING_RECEIVED.labels(*labels).inc()
                COMPAT_PING_SENT.inc(sent)
                COMPAT_PING_RECEIVED.inc()
                COMPAT_PING_LOST.inc(lost)
                COMPAT_PING_RTT.set(rtt_ms)
                COMPAT_PING_RTT_SUM.set(rtt_sum)
                COMPAT_PING_RTT_COUNT.set(rtt_count)
        return_code = process.wait(timeout=5)
        if not stop.is_set() and return_code != 0:
            stderr = process.stderr.read() if process.stderr else ""
            raise RuntimeError(f"ping failed for {profile.flow_id}: {stderr}")
    finally:
        COMPAT_PING_RUNNING.set(0)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def _http_worker(profile: TrafficProfile, stop: threading.Event) -> None:
    labels = _labels(profile)
    interval = profile.packet_size_bytes * 8 / (profile.rate_mbps * 1_000_000)
    RUNNING.labels(*labels).set(1)
    COMPAT_TRAFFIC_RUNNING.set(1)
    connection = BoundHTTPConnection(profile)
    try:
        while not stop.is_set():
            started = time.monotonic()
            connection.request("GET", f"/payload?bytes={profile.packet_size_bytes}")
            response = connection.getresponse()
            body = response.read()
            if response.status != 200:
                raise RuntimeError(f"HTTP flow received status {response.status}")
            elapsed = time.monotonic() - started
            HTTP_LATENCY.labels(*labels).set(elapsed * 1000)
            HTTP_REQUESTS.labels(*labels).inc()
            THROUGHPUT.labels(*labels).set(len(body) * 8 / elapsed / 1_000_000)
            stop.wait(max(0.0, interval - elapsed))
    finally:
        connection.close()
        RUNNING.labels(*labels).set(0)
        COMPAT_TRAFFIC_RUNNING.set(0)


def main() -> None:
    ue_id = os.environ["UE_ID"]
    profiles = load_profiles(Path(os.environ["TRAFFIC_PROFILE_PATH"]), ue_id)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signal, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signal, _frame: stop.set())
    start_http_server(9101)
    with ThreadPoolExecutor(max_workers=len(profiles) * 2) as executor:
        futures = []
        for profile in profiles:
            if profile.five_tuple.protocol == "http":
                worker = _http_worker
            elif profile.five_tuple.protocol == "udp":
                worker = _udp_worker
            else:
                worker = _traffic_worker
            futures.append(executor.submit(worker, profile, stop))
            futures.append(executor.submit(_ping_worker, profile, stop))
        done, _pending = wait(futures, return_when=FIRST_EXCEPTION)
        failures = [future.exception() for future in done if future.exception() is not None]
        if failures:
            COMPAT_STREAM_ERRORS.inc(len(failures))
            stop.set()
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
