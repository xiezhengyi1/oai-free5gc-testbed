from __future__ import annotations

from typing import Any

from testbed.gateway.contracts import PolicyAction
from testbed.telemetry.models import UnifiedSnapshot


def verify_policy(action: PolicyAction, snapshot: UnifiedSnapshot) -> dict[str, Any]:
    flow = next(
        item
        for item in snapshot.flows
        if item["flow_id"] == action.target.flow_id and item["supi"] == action.target.supi
    )
    session = flow["session"]
    ran = flow["ran"]
    observed = {
        "five_qi": session["five_qi"],
        "qfi": session["qfi"],
        "drb_id": ran["drb_id"],
    }
    if observed["five_qi"] != action.parameters.five_qi:
        raise RuntimeError(
            f"policy postcondition expected 5QI {action.parameters.five_qi}, "
            f"observed {observed['five_qi']}"
        )
    if observed["qfi"] is None or observed["drb_id"] is None:
        raise RuntimeError("policy postcondition is missing QFI or DRB evidence")
    return observed


def verify_resources(
    expected_cpus: float, expected_memory_mb: int, observed: dict[str, Any]
) -> dict[str, Any]:
    expected = {"cpus": expected_cpus, "memory_mb": expected_memory_mb}
    if observed != expected:
        raise RuntimeError(f"resource postcondition mismatch: {observed}")
    return observed


def verify_restart(observed: dict[str, Any]) -> dict[str, Any]:
    if observed["running"] is not True:
        raise RuntimeError("lifecycle postcondition expected a running container")
    if observed["started_at_before"] == observed["started_at_after"]:
        raise RuntimeError("lifecycle postcondition expected a changed start timestamp")
    return observed
