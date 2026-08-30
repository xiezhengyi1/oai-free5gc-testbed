from __future__ import annotations

import subprocess
from dataclasses import dataclass

from testbed.traffic.commands import traffic_command
from testbed.traffic.profiles import TrafficProfile


@dataclass(slots=True)
class FlowProcess:
    profile: TrafficProfile
    process: subprocess.Popen[str]


class TrafficController:
    def __init__(self) -> None:
        self.processes: dict[str, FlowProcess] = {}

    def start(self, profile: TrafficProfile) -> FlowProcess:
        if profile.flow_id in self.processes:
            raise ValueError(f"flow is already active: {profile.flow_id}")
        process = subprocess.Popen(traffic_command(profile), text=True)
        record = FlowProcess(profile, process)
        self.processes[profile.flow_id] = record
        return record

    def stop(self, flow_id: str) -> None:
        record = self.processes.pop(flow_id)
        record.process.terminate()
        record.process.wait(timeout=10)
