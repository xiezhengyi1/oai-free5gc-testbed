from __future__ import annotations

import re
from typing import Any

PATTERNS = {
    "supi": re.compile(r"(?:SUPI|Supi)\[?(imsi-\d+)\]?"),
    "pdu_session_id": re.compile(r"(?:PDU.?Session.?ID|PDUSessionID)\D+(\d+)", re.IGNORECASE),
    "dnn": re.compile(r"(?:DNN|Dnn)\[?([a-z][a-z0-9-]+)\]?"),
    "ue_ip": re.compile(
        r"(?:PDUAddress|UE IP|PDU Address)\D+((?:\d{1,3}\.){3}\d{1,3})", re.IGNORECASE
    ),
    "qfi": re.compile(r"(?:QFI|Qfi)\D+(\d+)", re.IGNORECASE),
    "five_qi": re.compile(r"(?:5QI|FiveQI)\D+(\d+)", re.IGNORECASE),
    "ul_teid": re.compile(r"(?:UL TEID|UplinkTEID)\D+(0x[0-9a-fA-F]+|\d+)", re.IGNORECASE),
    "dl_teid": re.compile(r"(?:DL TEID|DownlinkTEID)\D+(0x[0-9a-fA-F]+|\d+)", re.IGNORECASE),
}


def parse_session_fields(log_text: str, supi: str, dnn: str) -> dict[str, Any]:
    relevant = "\n".join(
        line
        for line in log_text.splitlines()
        if supi in line or dnn in line or "TEID" in line or "QFI" in line
    )
    result: dict[str, Any] = {"supi": supi, "dnn": dnn}
    for name, pattern in PATTERNS.items():
        matches = pattern.findall(relevant)
        if matches:
            value: Any = matches[-1]
            if name in {"pdu_session_id", "qfi", "five_qi"}:
                value = int(value)
            result[name] = value
    return result
