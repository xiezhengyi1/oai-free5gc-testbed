"""Trusted per-host image pins and CPU topology; independent of scenario intent."""

from __future__ import annotations

import json
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class HostProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    images: dict[str, str]
    digests: dict[str, str] = Field(min_length=1)
    control_cpus: list[int] = Field(min_length=1)
    radio_cpus: list[int] = Field(min_length=1)
    isolate_protocol_threads: bool = True

    @model_validator(mode="after")
    def validate_pools(self):
        if set(self.control_cpus) & set(self.radio_cpus):
            raise ValueError("control and radio CPU pools must be disjoint")
        if min(*self.control_cpus, *self.radio_cpus) < 0:
            raise ValueError("CPU numbers must be nonnegative")
        if any(
            not value.startswith("sha256:") or len(value) != 71 for value in self.digests.values()
        ):
            raise ValueError("each image requires a complete SHA-256 pin")
        return self


def configured_profile() -> HostProfile | None:
    path = os.environ.get("TESTBED_HOST_PROFILE")
    return HostProfile.model_validate(yaml.safe_load(Path(path).read_text())) if path else None


def apply_profile(compose: dict, profile: HostProfile) -> None:
    control = ",".join(map(str, profile.control_cpus))
    radio = ",".join(map(str, profile.radio_cpus))
    both = ",".join(map(str, sorted(set(profile.control_cpus + profile.radio_cpus))))
    for name, service in compose["services"].items():
        service["image"] = profile.images.get(service["image"], service["image"])
        if service["image"] not in profile.digests:
            raise ValueError(f"host profile has no image pin for {name}")
        service["cpuset"] = (
            both
            if name.startswith("oai-gnb-")
            else (radio if name.startswith("oai-nrue-") else control)
        )
        service["ports"] = [
            "127.0.0.1:" + port if isinstance(port, str) and port.count(":") == 1 else port
            for port in service.get("ports", [])
        ]


def record_profile(run_dir: Path, profile: HostProfile) -> None:
    (run_dir / "host-profile.json").write_text(profile.model_dump_json(indent=2) + "\n")


def load_run_profile(run_dir: Path) -> HostProfile | None:
    path = run_dir / "host-profile.json"
    return HostProfile.model_validate(json.loads(path.read_text())) if path.exists() else None
