"""Explicitly rebind operator policy after the SM workflow re-registers a UE."""

import time


def rebind_policy(pcf, supi: str, previous: dict, timeout: float, poll: float) -> dict:
    old = previous["ue_policy_associations"][0]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = pcf.ue_policy(supi)
        records = current["ue_policy_associations"]
        if (
            len(records) == 1
            and records[0]["id"] == old["id"]
            and records[0]["status"] == "complete"
        ):
            association = records[0]
            am = current["am_policy_associations"][0]
            return {
                "ue_association_id": association["id"],
                "ursp_status": association["status"],
                "am_association_id": am["id"],
                "rfsp": am["rfsp"],
            }
        if len(records) == 1 and records[0]["id"] != old["id"]:
            association = records[0]
            break
        time.sleep(poll)
    else:
        raise TimeoutError("UE did not create a new policy association after SM re-registration")
    if association["version"] != 0:
        raise ValueError("new UE association already has a policy; refusing to overwrite it")
    delivery = pcf.apply_ue_policy(
        supi,
        "ursp",
        {"associationId": association["id"], "expectedVersion": 0, "policy": old["policy"]},
    )
    while time.monotonic() < deadline:
        current = pcf.ue_policy(supi)
        association = next(
            row for row in current["ue_policy_associations"] if row["id"] == delivery["id"]
        )
        if association["status"] == "complete":
            break
        if association["status"] in {"rejected", "transfer_failed", "delivery_timeout"}:
            raise RuntimeError(f"URSP rebind failed: {association['status']}")
        time.sleep(poll)
    else:
        raise TimeoutError("UE did not confirm its rebound URSP")
    rfsp = previous["am_policy_associations"][0]["rfsp"]
    am = current["am_policy_associations"][0]
    if rfsp:
        pcf.apply_ue_policy(supi, "am", {"associationId": am["id"], "rfsp": rfsp})
    return {
        "ue_association_id": association["id"],
        "ursp_status": association["status"],
        "am_association_id": am["id"],
        "rfsp": rfsp,
    }
