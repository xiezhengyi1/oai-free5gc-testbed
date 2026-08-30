from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from testbed.gateway.contracts import PolicyAction
from testbed.gateway.postcondition_verifier import verify_policy
from testbed.telemetry.models import UnifiedSnapshot


class PolicyWatchdog:
    def __init__(self, timeout_seconds: int, poll_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def wait(
        self,
        action: PolicyAction,
        take_snapshot: Callable[[], UnifiedSnapshot],
    ) -> tuple[UnifiedSnapshot, dict[str, Any]]:
        deadline = time.monotonic() + self.timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            snapshot = take_snapshot()
            try:
                return snapshot, verify_policy(action, snapshot)
            except RuntimeError as error:
                last_error = error
                time.sleep(self.poll_seconds)
        if last_error is None:
            raise RuntimeError("policy watchdog expired without a post-action snapshot")
        raise TimeoutError(str(last_error))
