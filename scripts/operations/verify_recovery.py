"""Validate real RFsim telemetry and an authorized, reversible resource action."""

import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[2]
run_id = os.environ["TESTBED_RUN_ID"]
run = root / "artifacts/runs" / run_id
label = os.environ.get(
    "TESTBED_VALIDATION_LABEL", datetime.now(UTC).strftime("recovery-validation-%Y%m%dT%H%M%S%fZ")
)
if Path(label).name != label or label in (".", ".."):
    raise ValueError("TESTBED_VALIDATION_LABEL must be one directory name")
out = run / "evidence" / label
out.mkdir(parents=True, exist_ok=False)
scenario = json.loads((run / "compiled-scenario.json").read_text())["scenario"]
protocols = {flow["id"]: flow["protocol"] for flow in scenario["flows"]}
client = httpx.Client(timeout=90, trust_env=False)
project = {"X-API-Key": os.environ["TESTBED_PROJECT_API_KEY"]}
policy = {"X-API-Key": os.environ["TESTBED_API_KEY"]}
report = {
    "run_id": run_id,
    "checked_at": datetime.now(UTC).isoformat(),
    "scope": "real RFsim startup, telemetry, resource action and restoration; no SLA claim",
}


def save(name, value):
    (out / name).write_text(json.dumps(value, indent=2, default=str) + "\n")


def snapshot(name):
    r = client.post("http://127.0.0.1:8081/v1/snapshots", params={"trigger_event": name})
    r.raise_for_status()
    x = r.json()
    assert x["run_id"] == run_id
    save(name + ".json", x)
    return x


def healthy(x):
    assert len(x["sessions"]) == sum(len(ue["sessions"]) for ue in scenario["ues"])
    assert {f["flow_id"] for f in x["flows"]} == set(protocols)
    for f in x["flows"]:
        assert (
            f["data_quality"]["correlation_status"] == "complete" and not f["data_quality"]["stale"]
        ), f["data_quality"]
        t = f["telemetry"]
        assert t["availability"] == 1
        proto = protocols[f["flow_id"]]
        if proto in ("tcp", "udp"):
            assert t["throughput_ul"] > 0
        if proto in ("http", "udp"):
            assert t["throughput_dl"] > 0
        assert t["packet_received"] > 0
    assert all(n["telemetry"]["prb_utilization"] is not None for n in x["ran_nodes"])
    assert any(n["telemetry"]["prb_utilization"] > 0 for n in x["ran_nodes"])


def limits():
    c = json.loads(subprocess.check_output(["docker", "inspect", "mec-app-edge"]))[0]["HostConfig"]
    return {"cpus": c["NanoCpus"] / 1e9, "memory_mb": c["Memory"] // (1024 * 1024)}


def resource(s, parameters, headers):
    body = dict(
        run_id=run_id,
        snapshot_id=s["snapshot_id"],
        action_type="update_container_resources",
        target={"container": "mec-app-edge"},
        parameters=parameters,
    )
    return client.post("http://127.0.0.1:8080/v1/actions/resource", headers=headers, json=body)


try:
    deadline = time.monotonic() + 30
    while True:
        try:
            ready = client.get("http://127.0.0.1:8081/health")
            ready.raise_for_status()
            break
        except httpx.HTTPError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)
    base = snapshot("RecoveryEntry")
    healthy(base)
    before = limits()
    rejected = resource(base, before, policy)
    assert rejected.status_code == 403 and limits() == before
    report["wrong_principal_rejected_before_write"] = True
    attempted = False
    try:
        attempted = True
        r = resource(
            snapshot("RecoveryResourceBefore"),
            dict(cpus=before["cpus"] + 0.25, memory_mb=before["memory_mb"]),
            project,
        )
        r.raise_for_status()
        receipt = r.json()
        save("resource-apply-receipt.json", receipt)
        assert receipt["status"] == "verified"
        assert limits()["cpus"] == before["cpus"] + 0.25
        report["resource_apply_verified"] = True
    finally:
        if attempted:
            r = resource(snapshot("RecoveryRestoreBefore"), before, project)
            r.raise_for_status()
            restored = r.json()
            save("resource-restore-receipt.json", restored)
            assert restored["status"] == "verified" and limits() == before
            report["resource_restored_exactly"] = True
    observations = []

    def tcp_received():
        if "tcp" not in protocols.values():
            return None
        raw = subprocess.check_output(
            ["docker", "exec", "mec-app-edge", "ss", "-tin", "sport = :5201"], text=True
        )
        return sum(map(int, re.findall(r"bytes_received:(\d+)", raw)))

    for index in range(3):
        if index:
            time.sleep(5)
        x = snapshot("RecoveryStable" + str(index))
        healthy(x)
        assert x["sessions"] == base["sessions"] and x["ue_policies"] == base["ue_policies"]
        observations.append(
            {
                "snapshot_id": x["snapshot_id"],
                "tcp_sink_received_bytes": tcp_received(),
                "flows": {
                    f["flow_id"]: {
                        "protocol": protocols[f["flow_id"]],
                        "received": f["telemetry"]["packet_received"],
                        "throughput_ul": f["telemetry"]["throughput_ul"],
                        "throughput_dl": f["telemetry"]["throughput_dl"],
                    }
                    for f in x["flows"]
                },
            }
        )
    for flow_id in protocols:
        assert (
            observations[-1]["flows"][flow_id]["received"]
            > observations[0]["flows"][flow_id]["received"]
        )
    if "tcp" in protocols.values():
        assert (
            observations[-1]["tcp_sink_received_bytes"]
            > observations[0]["tcp_sink_received_bytes"]
            > 0
        )
    report["stable_actual_traffic"] = observations
    report["sessions_and_policies_preserved"] = True
    url = make_url(os.environ["MULTIAGENTS_DATABASE_URL"]).set(host="127.0.0.1", port=5432)
    with create_engine(url).connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT snapshot_id,projection_version,applied_count FROM network_state_current WHERE run_id=:r"
                ),
                {"r": run_id},
            )
            .mappings()
            .one()
        )
        count = connection.execute(text("SELECT count(*) FROM network_graph_snapshot")).scalar_one()
        assert row["applied_count"] >= 3 and count >= 3
        report["database_projection"] = {**dict(row), "history_rows": count}
    report["cpu_isolation_recorded"] = (run / "cpu-isolation.json").exists()
    assert report["cpu_isolation_recorded"]
    report["passed"] = True
except Exception as error:
    report["passed"] = False
    report["error_type"] = type(error).__name__
    save("summary.json", report)
    raise
finally:
    client.close()
    save("summary.json", report)
print(json.dumps(report, indent=2))
