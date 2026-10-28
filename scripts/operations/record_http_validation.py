"""Record server-side NODELAY deployment and its original-metric live validation."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "http-nodelay-20261028-1"


def main():
    run = ROOT / "artifacts/runs" / RUN_ID
    evidence = run / "evidence"
    activity = ROOT / "experiments/http-nodelay-20261028"
    summary = json.loads((evidence / "http-latency-validation/summary.json").read_text())
    assert summary["passed"] and summary["window_count"] == 12
    assert summary["scenario_byte_identical_to_previous"]
    functional = {name: json.loads((evidence / "oai-live-acceptance" / (name + "-complete.json")).read_text())
                  for name in ("baseline", "ursp", "rfsp", "negatives", "sm", "final")}
    source = json.loads((activity / "evidence/runtime-delta.json").read_text())
    assert source["changed_runtime_files"] == ["traffic/app_server.py"]
    tests = (activity / "logs/python-regression.log").read_text()
    assert re.search(r"133 passed", tests) and "failed" not in tests
    old = json.loads((activity / "evidence/previous-run-stopped.json").read_text())
    assert old["phase"] == "STOPPED"
    state = json.loads((run / "current-state.json").read_text())
    assert state["phase"] == "RUNNING"
    containers = json.loads((evidence / "oai-live-acceptance/final-containers.json").read_text())
    old_containers = json.loads((ROOT / "artifacts/runs/oai-acceptance-20261028-4/evidence/oai-live-acceptance/final-containers.json").read_text())
    native = ("oai-gnb-1", "oai-nrue-1", "oai-nrue-2", "free5gc-amf", "free5gc-pcf", "free5gc-smf", "free5gc-upf-edge", "free5gc-upf-alternate")
    assert all(containers[name]["image"] == old_containers[name]["image"] for name in native)
    ranges = {}
    for name, flow in summary["http"].items():
        latency = [w["telemetry"]["latency"] for w in flow["after_windows"]]
        before = flow["before_window_latency_ms"]
        assert max(latency) <= flow["original_sla_latency_ms"] == 20
        ranges[name] = {
            "before_window_ms": {"min": min(before), "max": max(before)},
            "after_window_ms": {"min": min(latency), "max": max(latency), "mean": sum(latency) / len(latency)},
            "throughput_dl_mbps": [w["telemetry"]["throughput_dl"] for w in flow["after_windows"]],
            "jitter_ms": [w["telemetry"]["jitter"] for w in flow["after_windows"]],
            "loss_rate": [w["telemetry"]["loss_rate"] for w in flow["after_windows"]],
        }
    hashes = {str(p.relative_to(evidence)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in evidence.rglob("*") if p.is_file()}
    report = {
        "recorded_at": datetime.now(UTC).isoformat(), "run_id": RUN_ID, "phase": state["phase"],
        "status": "passed_original_20ms_http_latency_clause", "runtime_revision": "http-nodelay-20261028",
        "implementation": "Handler.disable_nagle_algorithm=True on accepted HTTP server sockets",
        "runtime_source_change": source, "scenario_unchanged": True,
        "native_images_unchanged": True, "scenario_sha256": summary["business_scenario_sha256"],
        "regression": {"passed": 133, "failed": 0}, "functional_checks": functional,
        "formal_metric": "existing snapshot's mean of exported full HTTP transaction latency samples",
        "latency_threshold_ms": 20, "nonoverlapping_windows": 12,
        "observation_seconds": summary["measured_seconds"], "http": ranges,
        "normal_client_probe_summary": summary["probe_summary"],
        "containers": containers, "previous_run_id": "oai-acceptance-20261028-4",
        "previous_run_stopped_after_exact_recovery": True,
        "runtime_sources": json.loads((evidence / "oai-live-acceptance/runtime-source-hashes.json").read_text())["containers"],
        "full_business_sla_accepted": None,
        "limits": summary["limits"], "evidence_root": str(evidence), "evidence_sha256": hashes,
    }
    path = ROOT / "docs/http-latency-validation-20261028.json"
    assert not path.exists(), "preserve the original report"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    (activity / "evidence/final-artifact-sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"run_id": RUN_ID, "status": report["status"], "http": ranges, "files": len(hashes)}))


if __name__ == "__main__":
    main()
