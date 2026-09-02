from __future__ import annotations

import re
from typing import Any

SESSION_QOS = re.compile(
    r"UE (\d+): assigned DRB (\d+) to QFI (\d+) \(5QI (\d+)\) in PDU session (\d+)",
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


def _session_block(log_text: str, cu_ue_id: int, pdu_session_id: int) -> str:
    events = list(SESSION_QOS.finditer(log_text))
    selected = [
        (index, event)
        for index, event in enumerate(events)
        if int(event.group(1)) == cu_ue_id and int(event.group(5)) == pdu_session_id
    ]
    if not selected:
        return ""
    index, event = selected[-1]
    end = events[index + 1].start() if index + 1 < len(events) else len(log_text)
    return log_text[event.start() : end]


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
    block = _session_block(log_text, cu_ue_id, pdu_session_id)
    for event_ue_id, drb_id, qfi, five_qi, session_id in SESSION_QOS.findall(block):
        if int(event_ue_id) == cu_ue_id and int(session_id) == pdu_session_id:
            result.update(drb_id=int(drb_id), qfi=int(qfi), five_qi=int(five_qi))
    for session_id, teid in SESSION_UL_TEID.findall(block):
        if int(session_id) == pdu_session_id:
            result["ul_teid"] = teid
    for session_id, teid in SESSION_DL_TEID.findall(block):
        if int(session_id) == pdu_session_id:
            result["dl_teid"] = teid
    return result
