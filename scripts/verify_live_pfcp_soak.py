"""Five-minute live PFCP report-rate check; does not mutate policies or containers."""
import json
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

run = Path(__file__).resolve().parents[1] / "artifacts/runs/s2-live-auto"
directory = run / "ue-policy/evidence" / datetime.now(UTC).strftime("pfcp-soak-%Y%m%dT%H%M%SZ")
directory.mkdir()
samples = []
for index in range(10):
    time.sleep(30)
    sample = {"at": datetime.now(UTC).isoformat(), "upfs": {}}
    for name in ("free5gc-upf-slice-1", "free5gc-upf-slice-2", "free5gc-upf-slice-3"):
        runtime = json.loads(subprocess.check_output(["docker", "inspect", name]))[0]
        assert runtime["State"]["Running"], name
        logs = subprocess.check_output(["docker", "logs", "--since", "30s", name], stderr=subprocess.STDOUT).decode()
        reports = logs.count("serveUSAReport")
        timeouts = logs.count("handleSessionReportRequestTimeout")
        sample["upfs"][name] = {"reports_30s": reports, "timeouts_30s": timeouts}
        assert 0 < reports < 500 and timeouts == 0, sample
    samples.append(sample)
    (directory / "samples.json").write_text(json.dumps(samples, indent=2))
    print(json.dumps({"sample": index + 1, **sample}), flush=True)
summary = {"status": "verified", "samples": len(samples), "minimum_duration_seconds": 300,
           "periodic_reports": "present", "pfcp_report_timeouts": 0, "evidence": str(directory)}
(directory / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary))
