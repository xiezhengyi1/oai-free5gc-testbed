"""Exact scoped SM inverse planning; no network mutation or success claim."""

from copy import deepcopy

MAPS = ("pccRules", "qosDecs", "chgDecs", "traffContDecs")
IDENTITY = ("supi", "flow_id", "association_id", "session")


def plan_restore(before, after, owned_ids):
    for key in IDENTITY:
        if before[key] != after[key]:
            raise ValueError(f"restore identity changed: {key}")
    if before["protected_state"] != after["protected_state"]:
        raise ValueError("protected state changed")
    if set(owned_ids) != set(MAPS):
        raise ValueError("explicit owned IDs required for all SM decision maps")
    old, new = before["decision"], after["decision"]
    if {k: v for k, v in old.items() if k not in MAPS} != {
        k: v for k, v in new.items() if k not in MAPS
    }:
        raise ValueError("unowned decision fields changed")
    delta = {}
    for field in MAPS:
        previous = old.get(field) or {}
        current = new.get(field) or {}
        owned = set(owned_ids[field])
        if {k: v for k, v in previous.items() if k not in owned} != {
            k: v for k, v in current.items() if k not in owned
        }:
            raise ValueError(f"unowned {field} changed")
        changed = {}
        for identifier in sorted(owned):
            if (identifier in previous, previous.get(identifier)) != (
                identifier in current,
                current.get(identifier),
            ):
                changed[identifier] = deepcopy(previous.get(identifier))
        if changed:
            delta[field] = changed
    return {
        "identity": {key: deepcopy(before[key]) for key in IDENTITY},
        "expected_current": deepcopy(after),
        "restore_state": deepcopy(before),
        "notification_delta": delta,
        "requires_deletion": any(v is None for m in delta.values() for v in m.values()),
    }


def verify_restore(actual, plan):
    if actual != plan["restore_state"]:
        raise ValueError("complete restored state differs from captured pre-state")
