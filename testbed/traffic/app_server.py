from __future__ import annotations

import json
import os
import signal
import socket
import socketserver
import struct
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse


class TcpSinkHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while self.request.recv(65536):
            pass


class TcpSinkServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    service_instance_id: str
    protocol_version = "HTTP/1.1"
    # Headers and small bodies are separate writes; do not hold the body for a delayed ACK.
    disable_nagle_algorithm = True

    def do_GET(self) -> None:
        request = urlparse(self.path)
        if request.path == "/payload":
            size = int(parse_qs(request.query)["bytes"][0])
            body = b"x" * size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if request.path not in ("/", "/health"):
            self.send_error(404)
            return
        body = json.dumps(
            {"service_instance_id": self.service_instance_id, "status": "ok"}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    service_id = os.environ["SERVICE_INSTANCE_ID"]
    http_port = int(os.environ["HTTP_PORT"])
    iperf_port = int(os.environ["IPERF_PORT"])
    udp_port = int(os.environ["UDP_PORT"])
    if "RETURN_ROUTE_CIDR" in os.environ:
        subprocess.run(
            [
                "ip",
                "route",
                "replace",
                os.environ["RETURN_ROUTE_CIDR"],
                "via",
                os.environ["RETURN_ROUTE_GATEWAY"],
            ],
            check=True,
        )
    tcp_server = TcpSinkServer(("0.0.0.0", iperf_port), TcpSinkHandler)
    Handler.service_instance_id = service_id
    server = ThreadingHTTPServer(("0.0.0.0", http_port), Handler)
    server.timeout = 0.2
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind(("0.0.0.0", udp_port))
    udp_socket.settimeout(0.2)
    stop = threading.Event()

    def shutdown(_signal: int, _frame: object) -> None:
        stop.set()

    def echo_udp() -> None:
        while not stop.is_set():
            try:
                payload, address = udp_socket.recvfrom(65535)
            except TimeoutError:
                continue
            if payload[16:20] == b"LCT1":
                if len(payload) < 22:
                    continue
                size = struct.unpack("!H", payload[20:22])[0]
                if not 16 <= size <= 65507:
                    continue
                payload = payload[:16] + b"x" * (size - 16)
            udp_socket.sendto(payload, address)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    with ThreadPoolExecutor(max_workers=2) as executor:
        udp_future = executor.submit(echo_udp)
        tcp_future = executor.submit(tcp_server.serve_forever)
        try:
            while not stop.is_set():
                server.handle_request()
                if udp_future.done():
                    udp_future.result()
                if tcp_future.done():
                    tcp_future.result()
        finally:
            stop.set()
            server.server_close()
            tcp_server.shutdown()
            tcp_server.server_close()
            udp_future.result()
            tcp_future.result()
            udp_socket.close()


if __name__ == "__main__":
    main()
