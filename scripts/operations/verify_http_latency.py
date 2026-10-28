"""Verify the original HTTP transaction metric after the server-side transport fix.

No QUICKACK/client NODELAY overrides on production workers. Snapshots are immutable;
every one of twelve non-overlapping ten-second observation windows must pass.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import UTC, datetime

import verify_oai_acceptance as acceptance


def main():
    assert acceptance.RUN_ID == "http-nodelay-20261028-1"
    root, run = acceptance.ROOT, acceptance.RUN
    out = run / "evidence/http-latency-validation"
    out.mkdir(parents=True, exist_ok=False)

    def save(name, value):
        with (out / (name + ".json")).open("x") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")

    old_run = root / "artifacts/runs/oai-acceptance-20261028-4"
    old_scenario = (old_run / "source-scenario.yaml").read_bytes()
    new_scenario = (run / "source-scenario.yaml").read_bytes()
    assert old_scenario == new_scenario, "business objects, offered load and original SLA must stay identical"
    assert acceptance.read("final-complete")["exact_kernel_graph_restored"]
    scenario = json.loads((run / "compiled-scenario.json").read_text())["scenario"]
    expected = {f["id"]: f for f in scenario["flows"] if f["protocol"] == "http"}
    assert len(expected) == 2 and all(f["sla"]["latency_ms"] == 20 for f in expected.values())
    windows = []
    previous = None
    previous_end = None
    began = time.monotonic()
    for index in range(12):
        # Wait outside the measured request interval; do not change production pacing.
        if index:
            time.sleep(11)
        response = acceptance.CLIENT.post("http://127.0.0.1:8081/v1/snapshots",
            params={"trigger_event": f"HTTPServerNodelayWindow-{index:02}"})
        response.raise_for_status()
        snap = response.json()
        save(f"window-{index:02}", snap)
        acceptance.healthy(snap)
        acceptance.protected(snap)
        if previous_end is not None:
            assert snap["observed_from"] > previous_end, "formal observation windows must not overlap"
        previous_end = snap["observed_to"]
        for flow in snap["flows"]:
            if previous is not None:
                old = next(f for f in previous["flows"] if f["id"] == flow["id"])
                assert flow["telemetry"]["packet_received"] > old["telemetry"]["packet_received"]
            if flow["id"] in expected:
                threshold = expected[flow["id"]]["sla"]["latency_ms"]
                latency = flow["telemetry"]["latency"]
                assert latency is not None and 0 < latency <= threshold, (index, flow["id"], latency, threshold)
                assert flow["data_quality"]["sample_count"] >= 10
        previous = snap
        windows.append(snap)
        print("HTTP window", index, {f["id"]: round(f["telemetry"]["latency"], 3)
              for f in snap["flows"] if f["id"] in expected}, flush=True)

    # Supplementary real-path request samples: server is fixed, client transport
    # matches the original worker, and never uses TCP_QUICKACK.
    probe = '''import json,socket,time,statistics
from http.client import HTTPConnection
class Probe(HTTPConnection):
 def connect(self):
  s=socket.socket(socket.AF_INET,socket.SOCK_STREAM);s.settimeout(3)
  s.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,b"oaitun_ue1\\0")
  s.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,0)
  s.connect((self.host,self.port));self.sock=s
c=Probe("172.34.0.100",8080,timeout=3);rows=[]
try:
 for i in range(66):
  t0=time.perf_counter();c.request("GET","/payload?bytes=1200");r=c.getresponse();t1=time.perf_counter()
  body=r.read();t2=time.perf_counter();assert r.status==200 and len(body)==1200
  if i>=2:rows.append({"headers_ms":(t1-t0)*1000,"body_wait_ms":(t2-t1)*1000,"total_ms":(t2-t0)*1000})
finally:c.close()
ordered=sorted(r["total_ms"] for r in rows)
print(json.dumps({"raw":rows,"samples":64,"quickack_override":False,"client_nodelay":False,
 "median_ms":statistics.median(ordered),"mean_ms":statistics.mean(ordered),
 "sample_p95_ms":ordered[60],"maximum_ms":ordered[-1]}))
'''
    probes = {}
    for ue in (1, 2):
        result = subprocess.run(["docker", "exec", "-i", f"traffic-sidecar-ue-{ue}", "python", "-"],
                                input=probe, capture_output=True, text=True, check=True)
        probes[str(ue)] = json.loads(result.stdout)
    save("normal-client-probes", probes)
    actual = acceptance.containers()
    assert actual == acceptance.read("baseline-containers"), "native processes must stay unchanged within this run"
    kernel = acceptance.graphs()
    save("kernel-after-soak", kernel)
    assert kernel == acceptance.read("baseline-kernel")
    before_dir = root / "experiments/http-nodelay-20261028/evidence"
    before = [json.loads((before_dir / f"before-window-{i}.json").read_text()) for i in range(3)]
    result = {
        "recorded_at": datetime.now(UTC).isoformat(), "run_id": acceptance.RUN_ID,
        "passed": True, "gate": "original HTTP full-transaction latency; each snapshot window <= declared 20 ms",
        "window_count": 12, "measured_seconds": time.monotonic() - began,
        "business_scenario_sha256": hashlib.sha256(new_scenario).hexdigest(),
        "scenario_byte_identical_to_previous": True, "runtime_revision": "http-nodelay-20261028",
        "http": {flow_id: {
            "original_sla_latency_ms": expected[flow_id]["sla"]["latency_ms"],
            "before_window_latency_ms": [next(f for f in s["flows"] if f["id"] == flow_id)["telemetry"]["latency"] for s in before],
            "after_windows": [{"snapshot_id": s["snapshot_id"],
                "telemetry": next(f for f in s["flows"] if f["id"] == flow_id)["telemetry"]} for s in windows],
        } for flow_id in expected},
        "probe_summary": {ue: {k: v for k, v in values.items() if k != "raw"} for ue, values in probes.items()},
        "containers_unchanged": True, "kernel_exactly_restored": True,
        "limits": ["The formal latency metric is a window average of exported transaction samples, not a production p99 guarantee",
                   "This validates the latency clause; all original bandwidth, jitter and loss measurements are retained separately",
                   "No radio handover, physical SDR or model-inference claim"],
    }
    save("summary", result)
    print("HTTP latency clause PASSED; raw windows and normal-client probes retained", flush=True)


if __name__ == "__main__":
    main()
