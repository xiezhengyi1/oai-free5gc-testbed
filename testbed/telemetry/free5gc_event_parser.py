from __future__ import annotations

import re
from typing import Any

SESSION_QOS = re.compile(
    r"UE (\d+): assigned DRB (\d+) to QFI (\d+) \(5QI (\d+)\) in PDU session (\d+)",
    re.IGNORECASE,
)
SESSION_QOS_RELEASE = re.compile(
    r"UE (\d+): removed QoS flow with QFI=(\d+)"
    r"(?:\s+(?:in|from) PDU session (\d+))?",
    re.IGNORECASE,
)
SESSION_UL_TEID = re.compile(
    r"N3 GTP-U tunnel: PDUSession=(\d+)/UL TEID=(0x[0-9a-fA-F]+|\d+)",
    re.IGNORECASE,
)
SESSION_DL_TEID = re.compile(
    r"PDU Session Setup: ID=(\d+), outgoing TEID=(0x[0-9a-fA-F]+|\d+)",
    re.IGNORECASE,
)


def _session_blocks(log_text: str, cu_ue_id: int, pdu_session_id: int) -> list[str]:
    events = list(SESSION_QOS.finditer(log_text))
    blocks: list[str] = []
    for index, event in enumerate(events):
        if int(event.group(1)) != cu_ue_id or int(event.group(5)) != pdu_session_id:
            continue
        end = events[index + 1].start() if index + 1 < len(events) else len(log_text)
        blocks.append(log_text[event.start() : end])
    return blocks


def parse_session_fields(
    log_text: str,
    supi: str,
    dnn: str,
    pdu_session_id: int,
    cu_ue_id: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "supi": supi,
        "dnn": dnn,
        "pdu_session_id": pdu_session_id,
    }
    # Replay all sessions for this UE so a legacy release without a session ID
    # is used only when its QFI has one unambiguous owner. QFIs are session scoped.
    active: dict[tuple[int, int], dict[str, int]] = {}
    ambiguous: set[int] = set()
    events = [(m.start(), "assign", m) for m in SESSION_QOS.finditer(log_text)]
    events += [(m.start(), "release", m) for m in SESSION_QOS_RELEASE.finditer(log_text)]
    for _, kind, event in sorted(events, key=lambda row: row[0]):
        if int(event.group(1)) != cu_ue_id:
            continue
        if kind == "assign":
            session_id, qfi = int(event.group(5)), int(event.group(3))
            key = (session_id, qfi)
            active.pop(key, None)  # An update is the latest event, not the first insertion.
            active[key] = dict(drb_id=int(event.group(2)), qfi=qfi, five_qi=int(event.group(4)))
        else:
            qfi = int(event.group(2))
            session_id = int(event.group(3)) if event.group(3) is not None else None
            owners = [
                key
                for key in active
                if key[1] == qfi and (session_id is None or key[0] == session_id)
            ]
            if session_id is None and len(owners) > 1:
                ambiguous.update(key[0] for key in owners)
            for key in owners:
                del active[key]
    if pdu_session_id in ambiguous:
        result["correlation_error"] = "QoS release has ambiguous PDU session ownership"
    else:
        current = [
            value for (session_id, _), value in active.items() if session_id == pdu_session_id
        ]
        if current:
            result.update(current[-1])
    for block in _session_blocks(log_text, cu_ue_id, pdu_session_id):
        for session_id, teid in SESSION_UL_TEID.findall(block):
            if int(session_id) == pdu_session_id:
                result["ul_teid"] = teid
        for session_id, teid in SESSION_DL_TEID.findall(block):
            if int(session_id) == pdu_session_id:
                result["dl_teid"] = teid
    return result
