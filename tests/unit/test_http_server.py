"""Exercise actual accepted HTTP sockets and persistent response framing."""
from __future__ import annotations

import json
import socket
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from testbed.traffic.app_server import Handler


def test_http_accepted_connection_disables_nagle_and_preserves_keepalive_framing():
    options = []

    class ObservedHandler(Handler):
        service_instance_id = "http-regression"

        def setup(self):
            super().setup()
            options.append(self.connection.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))

    server = ThreadingHTTPServer(("127.0.0.1", 0), ObservedHandler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        for size in (1200, 1, 4096):
            connection.request("GET", f"/payload?bytes={size}")
            response = connection.getresponse()
            assert response.status == 200 and response.read() == b"x" * size
            assert response.getheader("Content-Length") == str(size)
        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"service_instance_id": "http-regression", "status": "ok"}
        # Enabled options are nonzero (Darwin returns its flag bit rather than 1).
        assert len(options) == 1 and options[0] != 0
    finally:
        connection.close()
        server.shutdown()
        thread.join(2)
        server.server_close()
