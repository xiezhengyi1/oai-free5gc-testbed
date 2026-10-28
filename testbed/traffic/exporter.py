from __future__ import annotations

import os
import re
import select
import signal
import socket
import struct
import subprocess
import threading
import time
import errno
from collections import deque
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from http.client import HTTPConnection, IncompleteRead
from pathlib import Path

from prometheus_client import Counter, Gauge, start_http_server

from testbed.traffic.commands import ping_command
from testbed.traffic.profiles import TrafficProfile, load_profiles
from testbed.traffic.ue_policy import publish_route, query_ue_route

LABELS = ("flow_id", "supi", "ue_id", "protocol", "service_instance_id")
RUNNING = Gauge("testbed_flow_running", "Whether the traffic process is running", LABELS)
THROUGHPUT = Gauge("testbed_flow_throughput_mbps", "Measured traffic throughput", LABELS)
THROUGHPUT_UL = Gauge(
    "testbed_flow_throughput_ul_mbps", "Measured uplink application throughput", LABELS
)
THROUGHPUT_DL = Gauge(
    "testbed_flow_throughput_dl_mbps", "Measured downlink application throughput", LABELS
)
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
        self.transport = None

    def connect(self) -> None:
        if self.transport is not None:
            self.interrupt()
            self.transport.close()
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.transport = connection.dup()
        self.sock = connection
        connection.settimeout(self.timeout)
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        connection.setsockopt(
            socket.SOL_SOCKET, socket.SO_BINDTODEVICE, self.interface.encode() + b"\0"
        )
        connection.bind(("", self.source_port))
        connection.connect((self.host, self.port))
        self.sock = connection

    def interrupt(self) -> None:
        # HTTP/1.0 can transfer socket ownership to HTTPResponse before read().
        transport = self.transport
        if transport is not None and transport.fileno() != -1:
            try:
                transport.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                transport.shutdown(socket.SHUT_RDWR)
            except OSError as exc:
                if exc.errno not in (errno.ENOTCONN, errno.EBADF):
                    raise
    def abort(self) -> None:
        self.interrupt()
        self.release()

    def release(self) -> None:
        self.close()
        if self.transport is not None:
            self.transport.close()


def _labels(profile: TrafficProfile) -> tuple[str, ...]:
    return (
        profile.flow_id,
        profile.supi,
        profile.ue_id,
        profile.five_tuple.protocol,
        profile.service_instance_id,
    )


def _initialize_flow_metrics(profile: TrafficProfile) -> None:
    labels = _labels(profile)
    RUNNING.labels(*labels).set(0)
    THROUGHPUT.labels(*labels).set(0)
    THROUGHPUT_UL.labels(*labels).set(0)
    THROUGHPUT_DL.labels(*labels).set(0)
    JITTER.labels(*labels).set(0)
    LOSS.labels(*labels).set(0)
    RETRANSMITS.labels(*labels)
    PING_RTT.labels(*labels).set(0)
    PING_RECEIVED.labels(*labels)
    HTTP_LATENCY.labels(*labels).set(0)
    HTTP_REQUESTS.labels(*labels)
    UDP_LATENCY.labels(*labels).set(0)
    UDP_SENT.labels(*labels)
    UDP_RECEIVED.labels(*labels)


def _tcp_worker(profile: TrafficProfile, stop: threading.Event) -> None:
    labels = _labels(profile)
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(5)
    connection.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    connection.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_BINDTODEVICE,
        profile.interface.encode() + b"\0",
    )
    connection.bind(("", profile.five_tuple.source_port))
    connection.connect(
        (
            profile.five_tuple.destination_ip,
            profile.five_tuple.destination_port,
        )
    )
    connection.setblocking(False)
    payload = b"x" * profile.packet_size_bytes
    interval = profile.timing.packet_interval(profile.packet_size_bytes, profile.rate_mbps)
    sent_bytes_window = 0
    last_report = time.monotonic()
    origin = last_report
    deadline = profile.timing.next_active(origin, origin)
    RUNNING.labels(*labels).set(1)
    COMPAT_TRAFFIC_RUNNING.set(1)
    COMPAT_TCP_PARALLEL.set(1)
    try:
        while not stop.is_set():
            if stop.wait(max(0, deadline - time.monotonic())):
                break
            started = time.monotonic()
            offset = 0
            while offset < len(payload) and not stop.is_set():
                _, writable, _ = select.select([], [connection], [], 0.2)
                if writable:
                    try:
                        written = connection.send(payload[offset:])
                    except BlockingIOError:
                        continue
                    if written == 0:
                        raise ConnectionError("TCP peer closed while sending")
                    offset += written
            if stop.is_set():
                break
            sent_bytes_window += len(payload)
            COMPAT_TCP_SENT_BYTES.inc(len(payload))
            now = time.monotonic()
            elapsed = now - last_report
            if elapsed >= 1.0:
                throughput_mbps = sent_bytes_window * 8 / elapsed / 1_000_000
                THROUGHPUT.labels(*labels).set(throughput_mbps)
                THROUGHPUT_UL.labels(*labels).set(throughput_mbps)
                COMPAT_TCP_BPS.set(throughput_mbps * 1_000_000)
                COMPAT_TCP_SEQUENCE.inc()
                sent_bytes_window = 0
                last_report = now
            deadline = profile.timing.next_active(max(started + interval, now), origin)
    finally:
        RUNNING.labels(*labels).set(0)
        COMPAT_TRAFFIC_RUNNING.set(0)
        if stop.is_set():
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        connection.close()


def _udp_worker(profile: TrafficProfile, stop: threading.Event) -> None:
    labels = _labels(profile)
    header = struct.Struct("!Qd")
    payload = b"x" * (profile.packet_size_bytes - header.size)
    if profile.udp_response_bytes is not None:
        payload = struct.pack("!4sH", b"LCT1", profile.udp_response_bytes) + payload[6:]
    interval = profile.timing.packet_interval(profile.packet_size_bytes, profile.rate_mbps)
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
    sent_bytes_window = 0
    received_window = 0
    lost_window = 0
    origin = time.monotonic()
    next_send = profile.timing.next_active(origin, origin)
    last_report = origin
    RUNNING.labels(*labels).set(1)
    COMPAT_TRAFFIC_RUNNING.set(1)
    COMPAT_UDP_TARGET_BPS.set(
        profile.timing.scheduled_rate_mbps(profile.packet_size_bytes, profile.rate_mbps)
        * 1_000_000
    )
    COMPAT_UDP_LENGTH.set(profile.packet_size_bytes)
    COMPAT_UDP_PARALLEL.set(1)
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_send:
                sequence += 1
                packet = header.pack(sequence, now) + payload
                udp_socket.send(packet)
                sent_bytes_window += len(packet)
                pending[sequence] = now
                sent_order.append((sequence, now))
                UDP_SENT.labels(*labels).inc()
                next_send = profile.timing.next_active(max(next_send + interval, now + interval), origin)

            timeout = min(max(0.0, next_send - now), 0.05)
            readable, _, _ = select.select([udp_socket], [], [], timeout)
            if readable:
                response = udp_socket.recv(65535)
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
                uplink_bits_per_second = sent_bytes_window * 8 / elapsed
                resolved = received_window + lost_window
                loss_ratio = lost_window / resolved if resolved else 0.0
                THROUGHPUT.labels(*labels).set(uplink_bits_per_second / 1_000_000)
                THROUGHPUT_UL.labels(*labels).set(uplink_bits_per_second / 1_000_000)
                THROUGHPUT_DL.labels(*labels).set(bits_per_second / 1_000_000)
                JITTER.labels(*labels).set(jitter_ms)
                LOSS.labels(*labels).set(loss_ratio)
                COMPAT_UDP_JITTER.set(jitter_ms)
                COMPAT_UDP_BPS.set(bits_per_second)
                received_bytes_window = 0
                sent_bytes_window = 0
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
    previous_rtt_ms: float | None = None
    jitter_ms = 0.0
    sent_total = 0
    received_total = 0
    rtt_sum = 0.0
    rtt_count = 0
    COMPAT_PING_RUNNING.set(1)
    try:
        if process.stdout is None:
            raise RuntimeError("ping stdout pipe was not created")
        while not stop.is_set():
            ready, _, _ = select.select([process.stdout], [], [], 0.2)
            if not ready:
                continue
            line = process.stdout.readline()
            if not line:
                break
            match = PING_PATTERN.search(line)
            if match:
                sequence = int(match.group(1))
                rtt_ms = float(match.group(2))
                sent = 1 if previous_sequence is None else max(1, sequence - previous_sequence)
                lost = sent - 1
                previous_sequence = sequence
                sent_total += sent
                received_total += 1
                if previous_rtt_ms is not None:
                    jitter_ms += (abs(rtt_ms - previous_rtt_ms) - jitter_ms) / 16
                previous_rtt_ms = rtt_ms
                rtt_sum += rtt_ms
                rtt_count += 1
                PING_RTT.labels(*labels).set(rtt_ms)
                PING_RECEIVED.labels(*labels).inc()
                if profile.five_tuple.protocol != "udp":
                    JITTER.labels(*labels).set(jitter_ms)
                    LOSS.labels(*labels).set((sent_total - received_total) / sent_total)
                COMPAT_PING_SENT.inc(sent)
                COMPAT_PING_RECEIVED.inc()
                COMPAT_PING_LOST.inc(lost)
                COMPAT_PING_RTT.set(rtt_ms)
                COMPAT_PING_RTT_SUM.set(rtt_sum)
                COMPAT_PING_RTT_COUNT.set(rtt_count)
        if stop.is_set():
            return
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
    interval = profile.timing.packet_interval(profile.packet_size_bytes, profile.rate_mbps)
    RUNNING.labels(*labels).set(1)
    COMPAT_TRAFFIC_RUNNING.set(1)
    connection = BoundHTTPConnection(profile)
    finished = threading.Event()
    def cancel_on_stop():
        while not finished.wait(0.05):
            if stop.is_set():
                connection.interrupt()
                return
    canceller = threading.Thread(target=cancel_on_stop)
    canceller.start()
    previous_latency_ms: float | None = None
    jitter_ms = 0.0
    received_bytes_window = 0
    last_report = time.monotonic()
    origin = last_report
    deadline = profile.timing.next_active(origin, origin)
    try:
        while not stop.is_set():
            if stop.wait(max(0, deadline - time.monotonic())):
                break
            started = time.monotonic()
            try:
                connection.request("GET", f"/payload?bytes={profile.packet_size_bytes}")
                with connection.getresponse() as response:
                    body = response.read()
            except (OSError, IncompleteRead, ValueError) as exc:
                connection.abort()
                RUNNING.labels(*labels).set(0)
                COMPAT_TRAFFIC_RUNNING.set(0)
                if stop.is_set():
                    break
                if not isinstance(exc, (TimeoutError, ConnectionError, IncompleteRead)):
                    raise
                connection = BoundHTTPConnection(profile)
                deadline = profile.timing.next_active(time.monotonic() + interval, origin)
                continue
            RUNNING.labels(*labels).set(1)
            COMPAT_TRAFFIC_RUNNING.set(1)
            if response.status != 200:
                raise RuntimeError(f"HTTP flow received status {response.status}")
            elapsed = time.monotonic() - started
            latency_ms = elapsed * 1000
            if previous_latency_ms is not None:
                jitter_ms += (abs(latency_ms - previous_latency_ms) - jitter_ms) / 16
            previous_latency_ms = latency_ms
            HTTP_LATENCY.labels(*labels).set(latency_ms)
            HTTP_REQUESTS.labels(*labels).inc()
            JITTER.labels(*labels).set(jitter_ms)
            received_bytes_window += len(body)
            now = time.monotonic()
            report_elapsed = now - last_report
            if report_elapsed >= 1.0:
                downlink_mbps = received_bytes_window * 8 / report_elapsed / 1_000_000
                THROUGHPUT.labels(*labels).set(downlink_mbps)
                THROUGHPUT_DL.labels(*labels).set(downlink_mbps)
                received_bytes_window = 0
                last_report = now
            deadline = profile.timing.next_active(max(started + interval, now), origin)
    finally:
        finished.set()
        canceller.join()
        if stop.is_set():
            connection.abort()
        else:
            connection.release()
        RUNNING.labels(*labels).set(0)
        COMPAT_TRAFFIC_RUNNING.set(0)


def _policy_worker(profile: TrafficProfile, stop: threading.Event) -> None:
    policy_dir = Path(os.environ["OAI_UE_POLICY_DIR"])
    worker = {"http": _http_worker, "udp": _udp_worker, "tcp": _tcp_worker}[
        profile.five_tuple.protocol
    ]
    current_interface = None
    local_stop = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = []
        try:
            while not stop.is_set():
                for future in futures:
                    if future.done():
                        future.result()
                        raise RuntimeError(f"flow worker stopped: {profile.flow_id}")
                route = query_ue_route(profile, policy_dir)
                interface = route["interface"] if route is not None else None
                if interface != current_interface:
                    local_stop.set()
                    for future in futures:
                        future.result(timeout=10)
                    futures = []
                    current_interface = interface
                    if route is not None:
                        effective = profile.model_copy(update={"interface": interface})
                        local_stop = threading.Event()
                        futures = [
                            pool.submit(worker, effective, local_stop),
                            pool.submit(_ping_worker, effective, local_stop),
                        ]
                if route is not None:
                    publish_route(policy_dir, route)
                stop.wait(1)
        finally:
            local_stop.set()


def main() -> None:
    ue_id = os.environ["UE_ID"]
    profiles = load_profiles(Path(os.environ["TRAFFIC_PROFILE_PATH"]), ue_id)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda _signal, _frame: stop.set())
    signal.signal(signal.SIGINT, lambda _signal, _frame: stop.set())
    start_http_server(9101)
    for profile in profiles:
        _initialize_flow_metrics(profile)
    with ThreadPoolExecutor(max_workers=len(profiles) * 2) as executor:
        futures = []
        for profile in profiles:
            if "OAI_UE_POLICY_DIR" in os.environ:
                futures.append(executor.submit(_policy_worker, profile, stop))
                continue
            if profile.five_tuple.protocol == "http":
                worker = _http_worker
            elif profile.five_tuple.protocol == "udp":
                worker = _udp_worker
            else:
                worker = _tcp_worker
            futures.append(executor.submit(worker, profile, stop))
            futures.append(executor.submit(_ping_worker, profile, stop))
        done, _pending = wait(futures, return_when=FIRST_EXCEPTION)
        failures = [future.exception() for future in done if future.exception() is not None]
        if failures:
            COMPAT_STREAM_ERRORS.inc(len(failures))
            stop.set()
            wait(futures)
            raise failures[0]
        for future in futures:
            future.result()


if __name__ == "__main__":
    main()
