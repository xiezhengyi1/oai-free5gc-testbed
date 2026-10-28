"""Pin only the current run's identified gNB threads; no PID/name-wide operations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from testbed.orchestration.host_profile import load_run_profile

PROTOCOL_THREADS = {"PDCP data ind", "RLC queue", "pdcp_timer"}


class ThreadsNotReady(RuntimeError):
    pass


def process_identity(pid: int) -> tuple[int, str]:
    path = Path("/proc") / str(pid)
    return path.stat().st_uid, (path / "stat").read_text().split(") ")[1].split()[19]


def main_gnb_pid(rows: list[str], init_pid: int) -> int:
    """Select the direct child of this container's init, not an OAI fork."""
    pids = [
        int(row.split()[0])
        for row in rows
        if row.split()[2] == "nr-softmodem" and int(row.split()[1]) == init_pid
    ]
    if len(pids) != 1:
        raise RuntimeError("gNB process identity is not unique")
    return pids[0]


def pin_threads(request: dict) -> list[dict]:
    control, radio = set(request["control"]), set(request["radio"])
    if not control or not radio or control & radio:
        raise ValueError("invalid CPU pools")
    if not (control | radio).issubset(set(range(os.cpu_count() or 0))):
        raise ValueError("CPU topology does not match the host")
    rows = []
    for target in request["targets"]:
        pid = target["pid"]
        if process_identity(pid) != (target["uid"], target["ticks"]):
            raise RuntimeError("gNB identity changed before CPU isolation")
        entries = []
        for thread in (Path("/proc") / str(pid) / "task").iterdir():
            try:
                entries.append((thread, (thread / "comm").read_text().strip()))
            except FileNotFoundError:
                continue
        if not PROTOCOL_THREADS.issubset({name for _, name in entries}):
            raise ThreadsNotReady("gNB protocol threads are not all initialized")
        found = set()
        for thread, name in entries:
            pool = control if name in PROTOCOL_THREADS else radio
            try:
                os.sched_setaffinity(int(thread.name), pool)
                observed = os.sched_getaffinity(int(thread.name))
            except ProcessLookupError:
                continue
            if observed != pool:
                raise RuntimeError("thread affinity read-back differs")
            if name in PROTOCOL_THREADS:
                found.add(name)
            rows.append(dict(pid=pid, tid=int(thread.name), name=name, cpus=sorted(pool)))
        if found != PROTOCOL_THREADS:
            raise ThreadsNotReady("gNB protocol threads changed during CPU isolation")
        if process_identity(pid) != (target["uid"], target["ticks"]):
            raise RuntimeError("gNB identity changed during CPU isolation")
    return rows


def isolate_current_run(docker, run_dir: Path, scenario) -> None:
    profile = load_run_profile(run_dir)
    if profile is None or not profile.isolate_protocol_threads:
        return
    targets = []
    for gnb in scenario.ran.gnbs:
        inspected = docker.inspect(gnb.container)
        project = inspected["Config"]["Labels"].get("com.docker.compose.project")
        if project != f"testbed-{run_dir.name}" or not inspected["State"]["Running"]:
            raise RuntimeError("gNB is not running under this run's Compose ownership")
        rows = docker._run(["docker", "top", gnb.container, "-eo", "pid,ppid,comm"]).splitlines()[
            1:
        ]
        pid = main_gnb_pid(rows, inspected["State"]["Pid"])
        uid, ticks = process_identity(pid)
        targets.append(dict(pid=pid, uid=uid, ticks=ticks))
    image = profile.images.get(
        "oai-free5gc-testbed/control:0.1.0", "oai-free5gc-testbed/control:0.1.0"
    )
    payload = dict(targets=targets, control=profile.control_cpus, radio=profile.radio_cpus)
    command = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--privileged",
        "--pid=host",
        "--entrypoint",
        "python",
        image,
        "-m",
        "testbed.orchestration.cpu_isolation",
    ]
    deadline = time.monotonic() + scenario.runtime.startup_timeout_seconds
    while True:
        result = subprocess.run(
            command, input=json.dumps(payload), text=True, capture_output=True, timeout=60
        )
        if result.returncode == 0:
            break
        if result.returncode != 75 or time.monotonic() >= deadline:
            raise RuntimeError(f"CPU isolation failed: {result.stderr.strip()}")
        time.sleep(scenario.runtime.readiness_poll_seconds)
    evidence = dict(targets=targets, threads=json.loads(result.stdout))
    (run_dir / "cpu-isolation.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    try:
        print(json.dumps(pin_threads(json.load(sys.stdin))))
    except ThreadsNotReady as error:
        print(str(error), file=sys.stderr)
        sys.exit(75)
