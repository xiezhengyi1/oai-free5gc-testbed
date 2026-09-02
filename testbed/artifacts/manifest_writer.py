from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from testbed.scenario.compiler import CompiledScenario
from testbed.scenario.schema import Scenario


@dataclass(frozen=True, slots=True)
class RunLayout:
    root: Path
    generated: Path
    logs: Path
    metrics: Path
    pcaps: Path

    @classmethod
    def create(cls, repository_root: Path, run_id: str) -> RunLayout:
        root = repository_root / "artifacts" / "runs" / run_id
        root.mkdir(parents=True, exist_ok=False)
        generated = root / "generated"
        logs = root / "logs"
        metrics = root / "metrics"
        pcaps = root / "pcaps"
        for path in (generated, logs, metrics, pcaps):
            path.mkdir()
        for name in ("actions.jsonl", "receipts.jsonl", "snapshots.jsonl", "state.jsonl"):
            (root / name).touch()
        (metrics / "snapshots.jsonl").hardlink_to(root / "snapshots.jsonl")
        return cls(root=root, generated=generated, logs=logs, metrics=metrics, pcaps=pcaps)


def _git_revision(path: str) -> dict[str, str]:
    root = Path(path).resolve(strict=True)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()
    tag = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
    ).stdout
    if status:
        raise ValueError(f"upstream source tree must be clean: {root}")
    return {"path": str(root), "revision": revision, "tag": tag}


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def initialize_run_artifacts(
    repository_root: Path,
    source_scenario: Path,
    scenario: Scenario,
    compiled: CompiledScenario,
) -> RunLayout:
    layout = RunLayout.create(repository_root, compiled.run_id)
    shutil.copy2(source_scenario, layout.root / "source-scenario.yaml")
    (layout.root / "compiled-scenario.json").write_text(
        compiled.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (layout.generated / "oai-config").mkdir()
    return layout


def write_manifest(
    repository_root: Path,
    layout: RunLayout,
    scenario: Scenario,
    compiled: CompiledScenario,
) -> dict[str, Any]:
    lock_path = repository_root / "deployment" / "images.lock.json"
    manifest = {
        "manifest_version": "1.0",
        "run_id": compiled.run_id,
        "scenario_id": compiled.scenario_id,
        "scenario_sha256": compiled.scenario_sha256,
        "created_at": datetime.now(UTC).isoformat(),
        "versions": scenario.versions.model_dump(mode="json"),
        "sources": {
            "oai": _git_revision(scenario.sources.oai),
            "free5gc_compose": _git_revision(scenario.sources.free5gc_compose),
        },
        "images_lock_sha256": _file_sha256(lock_path),
        "generated_compose_sha256": _file_sha256(layout.generated / "compose.yaml"),
        "state": "CREATED",
    }
    body = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    (layout.root / "run-manifest.json").write_text(body, encoding="utf-8")
    (layout.generated / "run-manifest.json").write_text(body, encoding="utf-8")
    return manifest
