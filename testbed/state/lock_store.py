from __future__ import annotations

import os
import fcntl
from pathlib import Path


class TargetLock:
    def __init__(self, lock_dir: Path, target: str) -> None:
        safe_target = target.replace("/", "_").replace(":", "_")
        self.path = lock_dir / f"{safe_target}.lock"
        self.file_descriptor: int | None = None

    def __enter__(self) -> TargetLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file_descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            fcntl.flock(self.file_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self.file_descriptor)
            self.file_descriptor = None
            raise FileExistsError(f"target is locked: {self.path}") from None
        os.ftruncate(self.file_descriptor, 0)
        os.write(self.file_descriptor, str(os.getpid()).encode())
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if self.file_descriptor is None:
            raise RuntimeError("target lock was not acquired")
        os.close(self.file_descriptor)
        self.file_descriptor = None
