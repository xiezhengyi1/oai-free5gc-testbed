from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ActionStore:
    def __init__(self, run_dir: Path) -> None:
        self.actions = run_dir / "actions.jsonl"
        self.receipts = run_dir / "receipts.jsonl"

    def append_action(self, payload: dict[str, Any]) -> None:
        with self.actions.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def append_receipt(self, payload: dict[str, Any]) -> None:
        with self.receipts.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
