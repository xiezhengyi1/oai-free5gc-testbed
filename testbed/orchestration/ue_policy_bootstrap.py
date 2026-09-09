"""Provision the initial URSP over NAS before starting policy-driven traffic."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from testbed.adapters.free5gc.pcf_adapter import PcfAdapter
from testbed.adapters.free5gc.subscriber_adapter import SubscriberAdapter
from testbed.gateway.ue_policy import URSPPolicy, validate_subscription
from testbed.scenario.loader import load_scenario


def bootstrap(run_dir: Path) -> None:
    scenario = load_scenario(run_dir / "source-scenario.yaml")
    pcf = PcfAdapter()
    subscribers = SubscriberAdapter("http://free5gc-webui:5000")
    plmn = scenario.plmn.mcc + scenario.plmn.mnc
    services = {item.id: item for item in scenario.services}
    slices = {item.id: item for item in scenario.slices}
    for ue in scenario.ues:
        state = pcf.ue_policy(ue.supi)
        associations = state["ue_policy_associations"]
        if len(associations) != 1:
            raise RuntimeError(f"{ue.supi}: expected one active UE policy association")
        association = associations[0]
        if association["version"] != 0:
            raise RuntimeError(f"{ue.supi}: bootstrap requires a new association")
        sessions = {item.id: item for item in ue.sessions}
        rules = []
        for index, flow in enumerate((item for item in scenario.flows if item.ue_id == ue.id), 1):
            session = sessions[flow.session_id]
            snssai = slices[session.slice_id]
            rules.append(
                {
                    "precedence": index,
                    "remoteIpv4": services[flow.service_instance_id].ip + "/32",
                    "protocol": 17 if flow.protocol == "udp" else 6,
                    "remotePort": flow.dst_port,
                    "routes": [
                        {"precedence": 1, "dnn": session.dnn, "sst": snssai.sst, "sd": snssai.sd}
                    ],
                }
            )
        policy = URSPPolicy.model_validate({"plmn": plmn, "upsc": 1, "rules": rules})
        validate_subscription(policy, subscribers.get(ue.supi, plmn))
        pcf.apply_ue_policy(
            ue.supi,
            "ursp",
            {
                "associationId": association["id"],
                "expectedVersion": 0,
                "policy": policy.model_dump(mode="json", exclude_none=True),
            },
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            current = next(
                row
                for row in pcf.ue_policy(ue.supi)["ue_policy_associations"]
                if row["id"] == association["id"]
            )
            if current["status"] == "complete":
                print(
                    json.dumps(
                        {
                            "supi": ue.supi,
                            "association_id": current["id"],
                            "status": "complete",
                            "version": current["version"],
                        }
                    ),
                    flush=True,
                )
                break
            if current["status"] in {"rejected", "transfer_failed", "delivery_timeout"}:
                raise RuntimeError(str(current))
            time.sleep(1)
        else:
            raise TimeoutError(f"{ue.supi}: UE did not acknowledge its initial policy")


if __name__ == "__main__":
    bootstrap(Path(os.environ["RUN_DIR"]))
