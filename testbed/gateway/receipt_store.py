from __future__ import annotations

from testbed.gateway.contracts import ActionReceipt
from testbed.state.action_store import ActionStore


class ReceiptStore:
    def __init__(self, actions: ActionStore) -> None:
        self.actions = actions

    def write(self, receipt: ActionReceipt) -> ActionReceipt:
        self.actions.append_receipt(receipt.model_dump(mode="json"))
        return receipt
