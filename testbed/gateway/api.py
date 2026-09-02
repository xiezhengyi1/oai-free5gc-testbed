from __future__ import annotations

import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from prometheus_client import start_http_server
from pydantic import Field

from testbed.gateway.action_arbiter import ActionArbiter
from testbed.gateway.contracts import (
    ActionReceipt,
    LifecycleAction,
    PolicyAction,
    ResourceAction,
    SliceLifecycleAction,
    SliceResourceAction,
)
from testbed.gateway.executor import ActionExecutor
from testbed.scenario.loader import load_scenario
from testbed.scenario.schema import StrictModel
from testbed.state.lock_store import TargetLock
from testbed.state.run_store import RunStore
from testbed.state.slice_store import SliceState


class RunRequest(StrictModel):
    run_id: str = Field(min_length=1)


class ControlDispatch(StrictModel):
    run_id: str
    operation: str
    worker_container: str
    status: str


run_dir = Path(os.environ["RUN_DIR"]).resolve(strict=True)
active_run_id = os.environ["RUN_ID"]
scenario = load_scenario(run_dir / "source-scenario.yaml")
run_store = RunStore(run_dir)
arbiter = ActionArbiter(run_dir, scenario, active_run_id)
executor = ActionExecutor(run_dir, scenario)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_http_server(9105)
    yield


app = FastAPI(title="Unified Action Gateway", version="1.0", lifespan=lifespan)


def _api_keys() -> dict[str, str]:
    pairs = os.environ["ACTION_GATEWAY_API_KEYS"].split(",")
    parsed = dict(item.split(":", 1) for item in pairs)
    if set(parsed) != {"multiagents", "project"} or any(not value for value in parsed.values()):
        raise RuntimeError(
            "ACTION_GATEWAY_API_KEYS must define non-empty multiagents and project keys"
        )
    return parsed


def principal(x_api_key: Annotated[str, Header(alias="X-API-Key")]) -> str:
    matches = [name for name, key in _api_keys().items() if key == x_api_key]
    if len(matches) != 1:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")
    return matches[0]


def _validate_common(
    action: (
        PolicyAction | ResourceAction | LifecycleAction | SliceLifecycleAction | SliceResourceAction
    ),
    actor: str,
) -> None:
    arbiter.authorize(actor, action)
    snapshot = arbiter.validate_snapshot(action.run_id, action.snapshot_id)
    if isinstance(action, PolicyAction):
        arbiter.validate_policy_target(action, snapshot)
    elif isinstance(action, (SliceLifecycleAction, SliceResourceAction)):
        arbiter.validate_slice_target(action.target.slice_id)
    else:
        arbiter.validate_container(action.target.container)


def _dispatch_control(operation: str) -> ControlDispatch:
    inspected = executor.docker.inspect("action-gateway")
    run_mount = next(item for item in inspected["Mounts"] if item["Destination"] == "/run")
    host_run_dir = Path(run_mount["Source"])
    worker = f"testbed-{operation}-{active_run_id}"
    command = [
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        worker,
        "-v",
        "/var/run/docker.sock:/var/run/docker.sock",
        "-v",
        f"{host_run_dir}:{host_run_dir}",
        "-e",
        f"MULTIAGENTS_DATABASE_URL={os.environ['MULTIAGENTS_DATABASE_URL']}",
        "-e",
        f"ACTION_GATEWAY_API_KEYS={os.environ['ACTION_GATEWAY_API_KEYS']}",
        "oai-free5gc-testbed/control:0.1.0",
        "python",
        "-m",
        "testbed.gateway.control_worker",
        operation,
        str(host_run_dir),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    return ControlDispatch(
        run_id=active_run_id,
        operation=operation,
        worker_container=worker,
        status="accepted",
    )


@app.exception_handler(PermissionError)
async def permission_error(_request: object, error: PermissionError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=403, content={"detail": str(error)})


@app.exception_handler(FileExistsError)
async def lock_conflict(_request: object, error: FileExistsError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"detail": str(error)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "run_id": active_run_id}


@app.post("/v1/runs")
def active_run(request: RunRequest, _actor: Annotated[str, Depends(principal)]):
    if request.run_id != active_run_id:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return run_store.current()


@app.get("/v1/runs/{run_id}")
def run_status(run_id: str, _actor: Annotated[str, Depends(principal)]):
    if run_id != active_run_id:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return run_store.current()


@app.get("/v1/runs/{run_id}/readiness")
def readiness(run_id: str, _actor: Annotated[str, Depends(principal)]):
    if run_id != active_run_id:
        raise HTTPException(status_code=404, detail="unknown run_id")
    state = run_store.current()
    return {"run_id": run_id, "phase": state.phase, "ready": state.phase == "RUNNING"}


@app.get("/v1/slices", response_model=list[SliceState])
def slices(_actor: Annotated[str, Depends(principal)]) -> list[SliceState]:
    return list(executor.slice_store.list())


@app.get("/v1/slices/{slice_id}", response_model=SliceState)
def slice_status(slice_id: str, _actor: Annotated[str, Depends(principal)]) -> SliceState:
    arbiter.validate_slice_target(slice_id)
    return executor.slice_store.get(slice_id)


@app.post("/v1/runs/{run_id}/reset", status_code=202)
def reset(run_id: str, actor: Annotated[str, Depends(principal)]) -> ControlDispatch:
    if actor != "project":
        raise HTTPException(status_code=403, detail="reset requires the project principal")
    if run_id != active_run_id:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return _dispatch_control("reset")


@app.post("/v1/runs/{run_id}/stop", status_code=202)
def stop(run_id: str, actor: Annotated[str, Depends(principal)]) -> ControlDispatch:
    if actor != "project":
        raise HTTPException(status_code=403, detail="stop requires the project principal")
    if run_id != active_run_id:
        raise HTTPException(status_code=404, detail="unknown run_id")
    return _dispatch_control("stop")


@app.post("/v1/actions/policy", response_model=ActionReceipt)
def policy(action: PolicyAction, actor: Annotated[str, Depends(principal)]) -> ActionReceipt:
    _validate_common(action, actor)
    target = f"path:{action.target.supi}:{action.target.flow_id}"
    with TargetLock(run_dir / "locks", target):
        return executor.policy(action)


@app.post("/v1/actions/resource", response_model=ActionReceipt)
def resource(action: ResourceAction, actor: Annotated[str, Depends(principal)]) -> ActionReceipt:
    _validate_common(action, actor)
    with TargetLock(run_dir / "locks", f"container:{action.target.container}"):
        return executor.resource(action)


@app.post("/v1/actions/lifecycle", response_model=ActionReceipt)
def lifecycle(action: LifecycleAction, actor: Annotated[str, Depends(principal)]) -> ActionReceipt:
    _validate_common(action, actor)
    with TargetLock(run_dir / "locks", f"container:{action.target.container}"):
        return executor.lifecycle(action)


@app.post("/v1/actions/slice-lifecycle", response_model=ActionReceipt)
def slice_lifecycle(
    action: SliceLifecycleAction,
    actor: Annotated[str, Depends(principal)],
) -> ActionReceipt:
    _validate_common(action, actor)
    with TargetLock(run_dir / "locks", "slice-catalog"):
        return executor.slice_lifecycle(action)


@app.post("/v1/actions/slice-resource", response_model=ActionReceipt)
def slice_resource(
    action: SliceResourceAction,
    actor: Annotated[str, Depends(principal)],
) -> ActionReceipt:
    _validate_common(action, actor)
    with TargetLock(run_dir / "locks", "slice-catalog"):
        return executor.slice_resources(action)
