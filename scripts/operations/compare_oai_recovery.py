"""Compare rebuilt OAI ELFs with retained image binaries without claiming equivalence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE)


def inspect_elf(path: Path) -> dict:
    symbols = {}
    for line in command("nm", "-P", "-S", "--defined-only", str(path)).splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] in ("T", "t", "W", "w"):
            symbols[parts[0]] = {"type": parts[1], "size": int(parts[3], 16)}
    dynamic = command("readelf", "-d", str(path))
    notes = command("readelf", "-n", str(path))
    comment = command("readelf", "-p", ".comment", str(path))
    dwarf = command("readelf", "--debug-dump=info", "--dwarf-depth=1", str(path))
    units = []
    for line in dwarf.splitlines():
        if "DW_AT_name" in line:
            match = re.search(r": (/[^\n]+)$", line)
            if match:
                units.append(match.group(1))
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "build_id": re.findall(r"Build ID: (\w+)", notes),
        "compiler": comment.strip(),
        "needed_libraries": re.findall(r"\(NEEDED\).*?\[(.*?)\]", dynamic),
        "runpath": re.findall(r"\((?:RUNPATH|RPATH)\).*?\[(.*?)\]", dynamic),
        "functions": symbols,
        "compile_units": units,
    }


def feature_symbol(name: str) -> bool:
    return any(
        marker in name
        for marker in (
            "ue_policy_",
            "rfsp",
            "admissible",
            "note_removed_drb",
            "forget_removed_drbs",
            "collect_pending_drb_releases",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("comparison output already exists; preserve previous evidence")
    report = {
        "compared_at": datetime.now(UTC).isoformat(),
        "scope": "ELF hashes, metadata, dependencies, function inventory; no live equivalence claim",
        "roles": {},
    }
    for role, binary in (("gnb", "nr-softmodem"), ("ue", "nr-uesoftmodem")):
        existing = inspect_elf(args.experiment / "binaries" / f"{role}-existing")
        rebuilt = inspect_elf(args.experiment / "build" / binary)
        old, new = set(existing["functions"]), set(rebuilt["functions"])
        role_report = {
            "existing": existing,
            "rebuilt": rebuilt,
            "byte_identical": existing["sha256"] == rebuilt["sha256"],
            "functions_only_in_existing": sorted(old - new),
            "functions_only_in_rebuilt": sorted(new - old),
            "feature_functions_only_in_existing": sorted(n for n in old - new if feature_symbol(n)),
            "common_feature_functions": sorted(n for n in old & new if feature_symbol(n)),
            "matching_common_function_sizes": sum(
                existing["functions"][n]["size"] == rebuilt["functions"][n]["size"]
                for n in old & new
            ),
            "common_function_count": len(old & new),
        }
        report["roles"][role] = role_report
        print(
            json.dumps(
                {
                    "role": role,
                    "byte_identical": role_report["byte_identical"],
                    "existing_sha256": existing["sha256"],
                    "rebuilt_sha256": rebuilt["sha256"],
                    "feature_functions_only_in_existing": role_report[
                        "feature_functions_only_in_existing"
                    ],
                    "common_feature_functions": role_report["common_feature_functions"],
                }
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()
