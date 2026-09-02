from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer

from testbed.artifacts.log_collector import collect_compose_logs
from testbed.artifacts.report_writer import write_final_report
from testbed.orchestration.host_check import host_check_payload, lock_images
from testbed.orchestration.launcher import Launcher
from testbed.rendering.compose_renderer import render_run
from testbed.scenario.ids import stable_digest
from testbed.scenario.loader import load_scenario
from testbed.state.run_store import RunStore
from testbed.telemetry.snapshot_writer import SnapshotStore

app = typer.Typer(no_args_is_help=True, pretty_exceptions_show_locals=False)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIO = REPOSITORY_ROOT / "scenarios" / "mvp" / "s1_single_ue_single_upf.yaml"


def _run_dir(run_id: str) -> Path:
    return REPOSITORY_ROOT / "artifacts" / "runs" / run_id


def _print(payload: object) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


@app.command("host-check")
def host_check(
    scenario_path: Annotated[Path, typer.Option("--scenario")] = DEFAULT_SCENARIO,
) -> None:
    payload = host_check_payload(REPOSITORY_ROOT, load_scenario(scenario_path))
    _print(payload)
    if payload["passed"] is not True:
        raise typer.Exit(1)


@app.command()
def validate(scenario_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)]) -> None:
    scenario = load_scenario(scenario_path)
    _print({"valid": True, "scenario_id": scenario.scenario_id})


@app.command()
def render(
    scenario_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    run_id: Annotated[str, typer.Option("--run-id")],
) -> None:
    layout = render_run(REPOSITORY_ROOT, scenario_path, run_id)
    _print({"run_id": run_id, "run_dir": str(layout.root), "state": "CREATED"})


@app.command()
def start(
    scenario_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    run_id: Annotated[str, typer.Option("--run-id")],
) -> None:
    scenario = load_scenario(scenario_path)
    checks = host_check_payload(REPOSITORY_ROOT, scenario)
    if checks["passed"] is not True:
        _print(checks)
        raise typer.Exit(1)
    run_dir = _run_dir(run_id)
    if not run_dir.exists():
        run_dir = render_run(REPOSITORY_ROOT, scenario_path, run_id).root
    else:
        rendered = load_scenario(run_dir / "source-scenario.yaml")
        requested_digest = stable_digest(scenario.model_dump(mode="json", by_alias=True))
        rendered_digest = stable_digest(rendered.model_dump(mode="json", by_alias=True))
        if requested_digest != rendered_digest:
            raise ValueError("existing run was rendered from a different scenario")
    state = Launcher(run_dir, compose_env_file=REPOSITORY_ROOT / ".env").start()
    _print(state.model_dump(mode="json"))


@app.command()
def status(run_id: Annotated[str, typer.Option("--run-id")]) -> None:
    _print(RunStore(_run_dir(run_id)).current().model_dump(mode="json"))


@app.command()
def resume(run_id: Annotated[str, typer.Option("--run-id")]) -> None:
    _print(
        Launcher(_run_dir(run_id), compose_env_file=REPOSITORY_ROOT / ".env")
        .resume()
        .model_dump(mode="json")
    )


@app.command()
def reset(run_id: Annotated[str, typer.Option("--run-id")]) -> None:
    _print(
        Launcher(_run_dir(run_id), compose_env_file=REPOSITORY_ROOT / ".env")
        .reset()
        .model_dump(mode="json")
    )


@app.command()
def stop(run_id: Annotated[str, typer.Option("--run-id")]) -> None:
    _print(
        Launcher(_run_dir(run_id), compose_env_file=REPOSITORY_ROOT / ".env")
        .stop()
        .model_dump(mode="json")
    )


@app.command()
def export(run_id: Annotated[str, typer.Option("--run-id")]) -> None:
    run_dir = _run_dir(run_id).resolve(strict=True)
    state = RunStore(run_dir).current()
    collect_compose_logs(
        run_dir / "generated" / "compose.yaml",
        run_dir / "logs" / "compose.log",
        compose_env_file=REPOSITORY_ROOT / ".env",
    )
    evidence: dict[str, object] = {"state": state.model_dump(mode="json")}
    snapshots_path = run_dir / "snapshots.jsonl"
    if snapshots_path.stat().st_size:
        evidence["latest_snapshot"] = SnapshotStore(run_dir).latest().model_dump(mode="json")
    write_final_report(run_dir, state.phase, evidence)
    archive = shutil.make_archive(str(run_dir), "gztar", root_dir=run_dir)
    _print({"run_id": run_id, "archive": archive})


@app.command("lock-images")
def lock_image_digests() -> None:
    _print(lock_images(REPOSITORY_ROOT / "deployment" / "images.lock.json"))


if __name__ == "__main__":
    app()
