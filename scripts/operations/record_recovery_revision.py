"""Record a source/image revision only at a stopped, container-free run boundary."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from testbed.orchestration.host_check import _verify_images
from testbed.orchestration.host_profile import configured_profile
from testbed.rendering.compose_renderer import set_generated_permissions
from testbed.state.run_store import RunStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    run = (root / "artifacts/runs" / args.run_id).resolve(strict=True)
    if run.parent != (root / "artifacts/runs").resolve():
        raise ValueError("run must be a direct child of artifacts/runs")
    assert RunStore(run).current().phase.value == "STOPPED"
    running = subprocess.check_output(
        [
            "docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=testbed-" + run.name,
            "--format",
            "{{.ID}}",
        ],
        text=True,
    )
    if running.strip():
        raise RuntimeError("run containers must be stopped before revising code or images")
    profile = configured_profile()
    assert profile is not None
    _verify_images(root / "deployment/images.lock.json")
    previous = run / "host-profile.json"
    old = previous.read_bytes()
    old_hash = hashlib.sha256(old).hexdigest()
    history = run / "runtime-profiles"
    history.mkdir(exist_ok=True)
    saved = history / (old_hash + ".json")
    if not saved.exists():
        saved.write_bytes(old)
    previous.write_text(profile.model_dump_json(indent=2) + "\n")
    set_generated_permissions(SimpleNamespace(root=run, generated=run / "generated"))
    event = dict(
        at=datetime.now(UTC).isoformat(),
        reason=args.reason,
        old_profile_sha256=old_hash,
        new_profile_sha256=hashlib.sha256(previous.read_bytes()).hexdigest(),
        source_sha256={
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (root / "testbed").rglob("*.py")
        },
    )
    with (run / "runtime-revisions.jsonl").open("a") as out:
        out.write(json.dumps(event) + "\n")
    print("recorded stopped-boundary runtime revision")


if __name__ == "__main__":
    main()
