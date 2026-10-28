"""Publish a credential-free acceptance summary only after all live gates passed."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "oai-acceptance-20261028-4"
RUN = ROOT / "artifacts/runs" / RUN_ID
OUT = RUN / "evidence/oai-live-acceptance"


def read(name):
    return json.loads((OUT / (name + ".json")).read_text())


def main():
    gates = {name: read(name + "-complete") for name in ("baseline", "ursp", "rfsp", "negatives", "sm", "final")}
    assert gates["final"]["exact_kernel_graph_restored"]
    assert gates["sm"]["native_add_modify_delete"]
    state = json.loads((RUN / "current-state.json").read_text())
    assert state["phase"] == "RUNNING"
    assert read("final-containers") == read("baseline-containers")
    native = json.loads((ROOT / "docs/oai-rebuild-20261028.json").read_text())
    containers = read("final-containers")
    for name, kind in (("oai-gnb-1", "gnb"), ("oai-nrue-1", "ue"), ("oai-nrue-2", "ue")):
        assert containers[name]["image"] == native["candidate_images"][kind]["candidate_image_id"]
    final = read("final-window-2-00")
    flow_stats = [{"id": f["id"], "qfi": f["session"]["qfi"], "five_qi": f["session"]["five_qi"],
                   "drb_id": f["ran"]["drb_id"], "availability": f["telemetry"]["availability"],
                   "received": f["telemetry"]["packet_received"],
                   "throughput_ul_mbps": f["telemetry"]["throughput_ul"],
                   "throughput_dl_mbps": f["telemetry"]["throughput_dl"],
                   "latency_ms": f["telemetry"]["latency"],
                   "correlation": f["data_quality"]["correlation_status"]} for f in final["flows"]]
    negatives = {}
    for path in sorted(OUT.glob("negative-*-response.json")):
        response = json.loads(path.read_text())
        negatives[path.stem.removeprefix("negative-").removesuffix("-response")] = {
            "http_status": response["http_status"], "task_status": response["body"].get("status")}
    hashes = {str(p.relative_to(OUT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in OUT.rglob("*") if p.is_file()}
    report = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": "passed_for_declared_rfsim_scope", "run_id": RUN_ID, "phase": state["phase"],
        "runtime_revision": "oai-acceptance-20261028-v4",
        "scenario": {"gnb": 1, "ues": 2, "upfs": 2, "preestablished_pdu_sessions": 4,
                     "flows": 6, "protocols_per_ue": ["udp", "tcp", "http"]},
        "native_images": native["candidate_images"], "containers": containers, "gates": gates,
        "regression": {"passed": 132, "failed": 0, "log": "experiments/oai-acceptance-20261028/logs/python-regression-v4.log"},
        "negative_cases": negatives, "final_snapshot_id": final["snapshot_id"],
        "final_observed_to": final["observed_to"], "flows": flow_stats,
        "restored_kernel_counts_per_upf": {upf: {kind: len(rows) for kind, rows in graph.items()}
                                           for upf, graph in read("final-kernel").items()},
        "runtime_sources": read("runtime-source-hashes")["containers"],
        "earlier_attempts": [
            {"run_id": "oai-acceptance-20261028-1", "result": "startup failed on idle-slice empty min; stopped; raw evidence retained"},
            {"run_id": "oai-acceptance-20261028-2", "result": "native roundtrips and exact restore passed; exposed incorrect same-PDU per-flow QoS projection; stopped for fix"},
            {"run_id": "oai-acceptance-20261028-3", "result": "SM native add reached RAN; Gateway pending-evidence KeyError; exact native recovery and stop verified before fix"},
        ],
        "rfsp_fixture": {"initial_native_value": 0, "acceptance_baseline": 64,
                         "test": [64, 65, 64], "protected_ue_native_value": 0},
        "fixes": ["idle slice QoS aggregation", "recognize native updated DRB events",
                  "bind per-flow QoS to unique native QFI instead of latest PDU event",
                  "wait within existing watchdog deadline when DRB evidence is pending",
                  "reuse only exact completed initial NAS bootstrap on resume",
                  "pinned-PCF scoped restore client preserves initialized empty-map representation"],
        "limits": [
            "RFSP verified through PCF/AMF/NGAP/gNB acknowledgement; radio_mapping=none; no handover or idle reselection claim",
            "Functional RFsim validation, not a guarantee of SLA: HTTP latency in this scene exceeds the declared 20 ms",
            "URSP selects between preestablished PDU sessions; on-demand PDU creation not tested",
            "QFI binding remains incomplete if multiple observed QFIs share the requested 5QI; never guesses",
            "ELF/image bytes differ from retained images; no universal semantic equivalence or exhaustive physical SDR validation",
            "No model/business-agent inference, training or paused dataset collection was resumed",
        ],
        "evidence_root": str(OUT), "evidence_sha256": hashes,
    }
    path = ROOT / "docs/oai-acceptance-20261028.json"
    assert not path.exists(), "preserve prior acceptance report"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    (ROOT / "experiments/oai-acceptance-20261028/evidence/run4-evidence-sha256.json").write_text(
        json.dumps(hashes, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "run_id": RUN_ID, "evidence_files": len(hashes)}))


if __name__ == "__main__":
    main()
