"""Serial live acceptance; immutable raw checkpoints and explicit native inverses.

Run on ibn3090 with with-testbed.sh. No model or training is launched.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
import struct
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from read_gtp_resources import attributes

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = os.environ.get("TESTBED_RUN_ID", "")
RUN = ROOT / "artifacts/runs" / RUN_ID
OUT = RUN / "evidence/oai-live-acceptance"
SUPI = "imsi-208930000180001"
PROTECTED = "imsi-208930000180002"
FLOW = "inference-edge-flow"
HEADERS = {"X-API-Key": os.environ["TESTBED_API_KEY"]}
CLIENT = httpx.Client(timeout=180, limits=httpx.Limits(max_keepalive_connections=0))


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / (name + ".json")).open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(name, flush=True)
    return value


def read(name):
    return json.loads((OUT / (name + ".json")).read_text())


def snapshot(name):
    response = CLIENT.post("http://127.0.0.1:8081/v1/snapshots", params={"trigger_event": name})
    response.raise_for_status()
    result = save(name, response.json())
    assert result["run_id"] == RUN_ID
    return result


def policy(supi=SUPI):
    response = CLIENT.get(f"http://127.0.0.1:8080/v1/ue-policies/{supi}", headers=HEADERS)
    response.raise_for_status()
    return response.json()


def canonical_policy(value):
    value = copy.deepcopy(value)
    # PCF serializes Go maps as association arrays in unspecified order.
    # Keep all records/fields, sorting only these ID-keyed collections.
    for key in ("am_policy_associations", "sm_policy_associations", "ue_policy_associations"):
        value[key] = sorted(value[key], key=lambda row: row["id"])
    return value


def native(code, value=None):
    result = subprocess.run(["docker", "exec", "-i", "action-gateway", "python", "-c", code],
                            input=json.dumps(value), text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def graphs():
    result = {}
    reader = ROOT / "scripts/operations/read_gtp_resources.py"
    for upf in ("edge", "alternate"):
        raw = subprocess.check_output([
            "docker", "run", "--rm", "--user", "0:0", "--network", f"container:free5gc-upf-{upf}",
            "--cap-drop", "ALL", "--cap-add", "NET_ADMIN", "-v", f"{reader}:/reader.py:ro",
            "--entrypoint", "python", "mergedsystem/testbed-control:oai-acceptance-20261028-v2", "/reader.py",
        ], text=True)
        result[upf] = json.loads(raw)
    return result


def containers():
    names = ["oai-gnb-1", "oai-nrue-1", "oai-nrue-2", "free5gc-upf-edge", "free5gc-upf-alternate",
             "free5gc-pcf", "free5gc-smf", "free5gc-amf", "action-gateway", "snapshot-builder",
             "session-tracker", "traffic-sidecar-ue-1", "traffic-sidecar-ue-2", "mec-app-edge"]
    inspected = json.loads(subprocess.check_output(["docker", "inspect", *names], text=True))
    result = {row["Name"].lstrip("/"): {
        "id": row["Id"], "image": row["Image"], "started_at": row["State"]["StartedAt"],
        "running": row["State"]["Running"], "restart_count": row["RestartCount"],
        "health": row["State"].get("Health", {}).get("Status"),
        "nano_cpus": row["HostConfig"]["NanoCpus"],
    } for row in inspected}
    assert all(row["running"] for row in result.values())
    assert all(result[n]["health"] == "healthy" for n in names[:3])
    assert result["mec-app-edge"]["nano_cpus"] == 1_000_000_000
    return result


def healthy(snap):
    assert len(snap["sessions"]) == 4 and len(snap["flows"]) == 6
    for f in snap["flows"]:
        assert f["data_quality"]["correlation_status"] == "complete", f["id"]
        assert not f["data_quality"]["stale"], f["id"]
        t = f["telemetry"]
        assert t["availability"] == 1 and t["packet_received"] > 0, f["id"]
        if f["id"].endswith("http"):
            assert t["throughput_dl"] > 0, f["id"]
        else:
            assert t["throughput_ul"] > 0, f["id"]
            if f["id"].endswith("flow"):
                assert t["throughput_dl"] > 0, f["id"]
        assert f["ran"]["prb_ul"] > 0, f["id"]


def stable(name):
    for attempt in range(12):
        snap = snapshot(f"{name}-{attempt:02}")
        try:
            healthy(snap)
        except AssertionError:
            if attempt == 11:
                raise
            time.sleep(5)
        else:
            return snap


def action(name, kind, parameters, *, supi=SUPI, negative=False, project=False):
    before = snapshot(name + "-before")
    target = {"supi": supi}
    if kind != "am_policy_apply":
        target["flow_id"] = FLOW
    body = {"run_id": RUN_ID, "snapshot_id": before["snapshot_id"], "action_type": kind,
            "target": target, "parameters": parameters}
    save(name + "-request", body)
    response = CLIENT.post("http://127.0.0.1:8080/v1/actions/policy", json=body,
                           headers={"X-API-Key": os.environ["TESTBED_PROJECT_API_KEY"]} if project else HEADERS)
    result = save(name + "-response", {"http_status": response.status_code, "body": response.json()})
    if negative:
        assert response.status_code in {403, 404, 409, 422} or (
            response.status_code == 200 and result["body"]["status"] == "rejected"), result
    else:
        response.raise_for_status()
        assert result["body"]["status"] == "verified", result
    return result


def protected(snap):
    baseline = read("baseline")
    assert [s for s in snap["sessions"] if s["supi"] == PROTECTED] == [
        s for s in baseline["sessions"] if s["supi"] == PROTECTED]
    assert canonical_policy(policy(PROTECTED)) == canonical_policy(read("protected-policy"))


def ursp_parameters(p):
    assoc = p["ue_policy_associations"][0]
    return {"associationId": assoc["id"], "expectedVersion": assoc["version"],
            "policy": copy.deepcopy(assoc["policy"])}


def baseline():
    assert RUN_ID in {"oai-acceptance-20261028-2", "oai-acceptance-20261028-3", "oai-acceptance-20261028-4", "http-nodelay-20261028-1"}, "explicit frozen acceptance run required"
    assert not (OUT / "baseline.json").exists()
    save("baseline-containers", containers())
    save("pre-fixture-policy", policy())
    assoc = policy()["am_policy_associations"][0]
    action("rfsp-fixture-64", "am_policy_apply", {"associationId": assoc["id"], "rfsp": 64})
    snap = stable("initial-stable")
    save("baseline", snap)
    save("baseline-policy", policy())
    save("protected-policy", policy(PROTECTED))
    save("baseline-kernel", graphs())
    path = RUN / "flow-allocations.json"
    save("baseline-allocations", json.loads(path.read_text()) if path.exists() else {})
    save("baseline-complete", {"time": datetime.now(UTC).isoformat(), "rfsp_fixture": 64})


def ursp():
    params = ursp_parameters(policy())
    original = copy.deepcopy(params["policy"])
    rule = next(r for r in params["policy"]["rules"] if r["protocol"] == 17 and r["remotePort"] == 5202)
    rule["routes"] = [{"precedence": 1, "dnn": "mecalt", "sst": 2, "sd": "010203"}]
    try:
        action("ursp-to-alternate", "ursp_apply", params)
        snap = stable("alternate-stable")
        f = next(f for f in snap["flows"] if f["id"] == FLOW)
        assert (f["session"]["pdu_session_id"], f["session"]["dnn"], f["session"]["snssai"],
                f["session"]["upf_id"]) == (2, "mecalt", "02010203", "free5gc-upf-alternate")
        assert snap["sessions"] == read("baseline")["sessions"]
        protected(snap)
        graph = save("alternate-kernel", graphs())
        assert graph == read("baseline-kernel")
    finally:
        current = policy()
        if current["ue_policy_associations"][0]["policy"] != original:
            inverse = ursp_parameters(current)
            inverse["policy"] = original
            action("ursp-restore", "ursp_apply", inverse)
    snap = stable("ursp-restored-stable")
    protected(snap)
    assert policy()["ue_policy_associations"][0]["policy"] == original
    assert all(f["session"]["pdu_session_id"] == 1 for f in snap["flows"])
    save("ursp-complete", {"native_NAS_roundtrip": True, "preestablished_PDU_count": 4})


def rfsp():
    assoc = policy()["am_policy_associations"][0]
    assert assoc["rfsp"] == 64
    try:
        action("rfsp-to-65", "am_policy_apply", {"associationId": assoc["id"], "rfsp": 65})
        assert policy()["am_policy_associations"][0]["rfsp"] == 65
        protected(stable("rfsp-65-stable"))
    finally:
        if policy()["am_policy_associations"][0]["rfsp"] != 64:
            action("rfsp-restore-64", "am_policy_apply", {"associationId": assoc["id"], "rfsp": 64})
    assert policy()["am_policy_associations"][0]["rfsp"] == 64
    save("rfsp-complete", {"roundtrip": [64, 65, 64], "scope": "NGAP control plane; no radio mapping"})


def negatives():
    for name in ("unsubscribed-dnn", "unsubscribed-slice", "stale-version", "duplicate-precedence", "wrong-principal", "unknown-ue"):
        checkpoint = OUT / ("negative-" + name + "-response.json")
        if checkpoint.exists():
            response = read("negative-" + name + "-response")
            assert response["http_status"] in {403,404,409,422} or response["body"]["status"] == "rejected"
            before = next(p for p in read("negative-" + name + "-before")["ue_policies"] if p["supi"] == SUPI)
            before = {k:v for k,v in before.items() if k != "supi"}  # Snapshot envelope only; target checked above.
            assert canonical_policy(policy()) == canonical_policy(before), name
            continue
        initial = policy()
        params = ursp_parameters(policy())
        if name == "unsubscribed-dnn":
            params["policy"]["rules"][0]["routes"][0]["dnn"] = "not-subscribed"
        elif name == "unsubscribed-slice":
            params["policy"]["rules"][0]["routes"][0]["sst"] = 99
        elif name == "stale-version":
            params["expectedVersion"] -= 1
        elif name == "duplicate-precedence":
            params["policy"]["rules"][1]["precedence"] = params["policy"]["rules"][0]["precedence"]
        action("negative-" + name, "ursp_apply", params, negative=True,
               project=name == "wrong-principal", supi="imsi-208930009999999" if name == "unknown-ue" else SUPI)
        after = save("negative-" + name + "-readback", policy())
        assert canonical_policy(after) == canonical_policy(initial), name
        assert canonical_policy(policy(PROTECTED)) == canonical_policy(read("protected-policy")), name
    save("negatives-complete", {"rejected_without_native_mutation": 6})


def sm_decision():
    return next(a for a in policy()["sm_policy_associations"] if a["pdu_session_id"] == 1)


def radio_evidence(name, since):
    result = {}
    for container in ("oai-gnb-1", "oai-nrue-1", "oai-nrue-2", "free5gc-smf"):
        proc = subprocess.run(["docker", "logs", "--since", since, container],
                              capture_output=True, text=True, check=True)
        result[container] = proc.stdout + proc.stderr
    result["rrc_stats"] = subprocess.check_output(
        ["docker", "exec", "oai-gnb-1", "cat", "nrRRC_stats.log"], text=True)
    return save(name, result)


def sm():
    maps = ("pccRules", "qosDecs", "chgDecs", "traffContDecs")
    initial = save("sm-initial-policy", sm_decision())
    kernel = save("sm-initial-kernel", graphs())
    start = datetime.now(UTC).isoformat()
    save("sm-start", {"time": start})
    try:
        for name, fiveqi in (("add", 1), ("modify", 2)):
            action("sm-" + name, "sm_policy_update", {
                "five_qi": fiveqi, "gbr_ul_mbps": 0.5, "gbr_dl_mbps": 0.5,
                "mbr_ul_mbps": 2, "mbr_dl_mbps": 2,
            })
            snap = stable("sm-" + name + "-stable")
            protected(snap)
            f = next(f for f in snap["flows"] if f["id"] == FLOW)
            assert f["session"]["five_qi"] == fiveqi
            assert f["session"]["qfi"] != 1
            for other in snap["flows"]:
                if other["id"] != FLOW:
                    old = next(b for b in read("baseline")["flows"] if b["id"] == other["id"])
                    assert other["session"] == old["session"], other["id"]
                    assert other["ran"]["drb_id"] == old["ran"]["drb_id"], other["id"]
            graph = save("sm-" + name + "-kernel", graphs())
            assert graph["alternate"] == kernel["alternate"]
            # Both SEIDs belong to different UEs: every protected-UE resource must be byte-exact.
            protected_seids = {r["seid"] for r in kernel["edge"]["pdr"]
                               if "0a3c0002" in r["attrs"]["5"]}
            assert len(protected_seids) == 1
            for kind in ("pdr", "far", "qer", "urr"):
                assert [r for r in graph["edge"][kind] if r["seid"] in protected_seids] == [
                    r for r in kernel["edge"][kind] if r["seid"] in protected_seids]
            new_qers = [r for r in graph["edge"]["qer"] if r not in kernel["edge"]["qer"]
                        and int.from_bytes(bytes.fromhex(r["attrs"]["9"]), "little") == f["session"]["qfi"]]
            assert new_qers, "no native UPF QER for assigned QFI"
            for qer in new_qers:
                for field, expected_rate in (("5", 2), ("6", 0.5)):
                    rates = attributes(bytes.fromhex(qer["attrs"][field]))
                    for high, low in (("1", "2"), ("3", "4")):
                        observed = ((int.from_bytes(bytes.fromhex(rates[high]), "little") << 8)
                                    | int.from_bytes(bytes.fromhex(rates[low]), "little")) / 1000
                        assert observed == expected_rate
            new_ids = {(r["seid"], r["id"]) for r in new_qers}
            selected_pdrs = []
            for pdr in graph["edge"]["pdr"]:
                refs = pdr["attrs"].get("10", [])
                refs = [refs] if isinstance(refs, str) else refs
                if any((pdr["seid"], int.from_bytes(bytes.fromhex(ref), "little")) in new_ids for ref in refs):
                    pdi = attributes(bytes.fromhex(pdr["attrs"]["5"]))
                    sdf = attributes(bytes.fromhex(pdi["3"]))
                    description = attributes(bytes.fromhex(sdf["1"]))
                    assert "ac220064" in (description.get("4"), description.get("6"))
                    assert struct.pack("<HH", 5202, 5202).hex() in (description.get("8"), description.get("9"))
                    selected_pdrs.append(pdr)
            assert len(selected_pdrs) == 2, "both UL/DL SDF rules must reference the assigned QER"
            save("sm-" + name + "-policy", sm_decision())
            radio_evidence("sm-" + name + "-radio", start)
    finally:
        current = sm_decision()
        if current["decision"] != initial["decision"]:
            owned = {kind: sorted(k for k in set(current["decision"].get(kind, {})) |
                                  set(initial["decision"].get(kind, {}))
                                  if current["decision"].get(kind, {}).get(k) !=
                                  initial["decision"].get(kind, {}).get(k)) for kind in maps}
            # This fixture starts without PCC/QoS/charging decisions. Never authorize removal of an existing rule.
            assert all(not initial["decision"].get(kind) for kind in maps)
            request = {"supi": SUPI, "associationId": initial["id"], "dnn": initial["dnn"],
                       "snssai": initial["snssai"], "expected": current["decision"],
                       "restore": initial["decision"], "owned": owned}
            # Pinned PCF compares Go structs with reflect.DeepEqual, but its GET omits
            # initialized empty maps. Confirmed from this image's DWARF + create path:
            # initial SessRules/PccRules/TraffContDecs are allocated; QosDecs is lazy.
            request["expected"] = copy.deepcopy(request["expected"])
            request["restore"] = copy.deepcopy(request["restore"])
            request["expected"].setdefault("traffContDecs", {})
            request["restore"].setdefault("traffContDecs", {})
            request["restore"].setdefault("pccRules", {})
            save("sm-restore-request", request)
            result = native('''import json,sys,os,httpx
p=json.load(sys.stdin)
r=httpx.post("http://pcf.free5gc.org:8000/testbed-policy/v1/ues/"+p["supi"]+"/sm/restore",
    json=p,headers={"Authorization":"Bearer "+os.environ["UE_POLICY_ADMIN_TOKEN"]},timeout=60)
print(json.dumps({"status":r.status_code,"body":r.json()}))
''', request)
            save("sm-restore-response", result)
            assert result["status"] in (200, 201, 204), result
        assert sm_decision()["decision"] == initial["decision"]
    sm_verify_restored()


def sm_verify_restored():
    initial = read("sm-initial-policy")
    kernel = read("sm-initial-kernel")
    start = read("sm-start")["time"]
    assert sm_decision()["decision"] == initial["decision"]
    for attempt in range(15):
        if (OUT / f"sm-restore-readback-{attempt:02}.json").exists():
            continue
        snap = snapshot(f"sm-restore-readback-{attempt:02}")
        if snap["sessions"] == read("baseline")["sessions"]:
            break
        time.sleep(3)
    else:
        raise AssertionError("native SM restore did not converge to original session observations")
    protected(snap)
    path = RUN / "flow-allocations.json"
    allocation = json.loads(path.read_text()) if path.exists() else {}
    initial_alloc = read("baseline-allocations")
    assert {k:v for k,v in allocation.items() if k != FLOW} == {k:v for k,v in initial_alloc.items() if k != FLOW}
    if FLOW in initial_alloc:
        allocation[FLOW] = initial_alloc[FLOW]
    else:
        allocation.pop(FLOW, None)
    native('''import json,sys
from pathlib import Path
p=json.load(sys.stdin);f=Path("/run/flow-allocations.json")
assert json.loads(f.read_text())==p["expected"]
f.write_text(json.dumps(p["restore"],indent=2)+"\\n")
print(json.dumps({"restored":True}))
''', {"expected": json.loads(path.read_text()), "restore": allocation})
    save("sm-restored-allocations", allocation)
    restored = save("sm-restored-kernel", graphs())
    logs = radio_evidence("sm-restored-radio", start)
    assert "updated DRB" in logs["oai-gnb-1"] and "(5QI 2)" in logs["oai-gnb-1"]
    assert "removed QoS flow with QFI=" in logs["oai-gnb-1"]
    drb = read("sm-add-response")["body"]["observed_effect"]["drb_id"]
    assert f"release DRB {drb} of UE 0" in logs["oai-nrue-1"]
    gnb_release = logs["oai-gnb-1"].index(f"release DRB {drb} of UE 1")
    assert "Received RRCReconfigurationComplete" in logs["oai-gnb-1"][gnb_release:]
    assert restored == kernel, "SM resource graph differs after native delete"
    healthy(stable("sm-restored-stable"))
    save("sm-complete", {"native_add_modify_delete": True, "exact_kernel_restore": True})


def final():
    snaps = []
    for index in range(3):
        snaps.append(stable(f"final-window-{index}"))
        if index < 2:
            time.sleep(12)
    for old, new in zip(snaps, snaps[1:]):
        for a, b in zip(old["flows"], new["flows"]):
            assert a["id"] == b["id"]
            assert b["telemetry"]["packet_received"] > a["telemetry"]["packet_received"], a["id"]
    protected(snaps[-1])
    graph = save("final-kernel", graphs())
    assert graph == read("baseline-kernel"), "kernel resource restoration is not exact"
    assert snaps[-1]["sessions"] == read("baseline")["sessions"]
    actual = save("final-containers", containers())
    assert actual == read("baseline-containers"), "acceptance must not restart or replace the native processes"
    host = {str(p.relative_to(ROOT / "testbed")): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "testbed").rglob("*.py")}
    code = "import pathlib,hashlib,json;p=pathlib.Path('/opt/testbed/testbed');print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*.py')}))"
    sources = {}
    for name in ("action-gateway", "snapshot-builder", "session-tracker", "traffic-sidecar-ue-1", "traffic-sidecar-ue-2", "mec-app-edge"):
        hashes = json.loads(subprocess.check_output(["docker", "exec", name, "python", "-c", code], text=True))
        assert hashes == host, name
        sources[name] = {"files": len(hashes), "equal": True}
    save("runtime-source-hashes", {"host": host, "containers": sources})
    save("final-complete", {"stable_windows": 3, "all_six_receiver_counters_increased": True,
                            "exact_kernel_graph_restored": True, "no_container_restarts": True,
                            "application_cpus": 1, "runtime_source_files": len(host)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["baseline", "ursp", "rfsp", "negatives", "sm", "sm_verify_restored", "final"])
    args = parser.parse_args()
    globals()[args.stage]()
