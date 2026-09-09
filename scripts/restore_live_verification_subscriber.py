"""Explicit repair after an interrupted live test; preserve the latest AKA sequence."""
import json
import os
from pathlib import Path

from testbed.adapters.free5gc.subscriber_adapter import SubscriberAdapter

assert os.environ["RUN_ID"] == "s2-live-auto"
run = Path(os.environ["RUN_DIR"])
supi = "imsi-208930000000009"
saved = json.loads((run / "ue-policy/dynamic-live-before.json").read_text())["subscribers"][supi]
adapter = SubscriberAdapter("http://free5gc-webui:5000")
current = adapter.get(supi, saved["plmnID"])
saved["AuthenticationSubscription"] = current["AuthenticationSubscription"]
adapter.upsert(saved)
print("Live test subscriber restored; current authentication sequence retained")
