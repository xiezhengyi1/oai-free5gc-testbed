import httpx

from testbed.adapters.prometheus_adapter import PrometheusAdapter


def test_queries_reuse_one_client(monkeypatch):
    requests = []
    clients = []

    def respond(request):
        requests.append(request)
        if request.url.path == "/-/ready":
            return httpx.Response(200)
        kind = "matrix" if request.url.path.endswith("query_range") else "vector"
        return httpx.Response(200, json={"status": "success", "data": {"resultType": kind, "result": []}})

    client_type = httpx.Client

    def create(**kwargs):
        client = client_type(transport=httpx.MockTransport(respond), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", create)
    adapter = PrometheusAdapter("http://prometheus:9090")
    adapter.ready()
    assert adapter.instant_query("up", 100) == []
    assert adapter.range_query("up", 90, 100, 1) == []
    assert len(clients) == 1
    assert len(requests) == 3
    assert requests[1].url.params["time"] == "100"
    assert requests[2].url.params["start"] == "90"
    clients[0].close()
