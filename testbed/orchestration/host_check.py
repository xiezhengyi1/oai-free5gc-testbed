from __future__ import annotations

import json
import platform
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from testbed.orchestration.network_setup import host_route_conflicts
from testbed.scenario.schema import Scenario


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str


def _command(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def _check(name: str, operation: Callable[[], str]) -> CheckResult:
    try:
        detail = operation()
        return CheckResult(name=name, passed=True, detail=detail)
    except Exception as error:
        return CheckResult(name=name, passed=False, detail=f"{type(error).__name__}: {error}")


def _require(condition: bool, detail: str) -> str:
    if not condition:
        raise RuntimeError(detail)
    return detail


def _compose_version() -> str:
    text = _command(["docker", "compose", "version", "--short"])
    numbers = tuple(int(value) for value in re.match(r"v?(\d+)\.(\d+)\.(\d+)", text).groups())
    if numbers < (2, 36, 0):
        raise RuntimeError(f"Docker Compose >=2.36.0 is required, found {text}")
    return text


def _git_tag(path: str, expected: str) -> str:
    root = Path(path).resolve(strict=True)
    tag = _command(["git", "-C", str(root), "describe", "--tags", "--exact-match"])
    if tag != expected:
        raise RuntimeError(f"expected tag {expected}, found {tag}")
    status = _command(["git", "-C", str(root), "status", "--porcelain"])
    if status:
        raise RuntimeError(f"source tree is dirty: {root}")
    return f"{root}@{tag}"


def _image_digest(image: str) -> str:
    payload = json.loads(_command(["docker", "image", "inspect", image]))
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError(f"invalid docker image inspect response for {image}")
    repo_digests = payload[0]["RepoDigests"]
    return repo_digests[0].split("@", 1)[1] if repo_digests else payload[0]["Id"]


def lock_images(lock_path: Path) -> dict[str, object]:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    payload["images"] = {image: _image_digest(image) for image in payload["images"]}
    payload["locked"] = True
    lock_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _verify_images(lock_path: Path) -> str:
    payload = json.loads(lock_path.read_text(encoding="utf-8"))
    if payload.get("locked") is not True:
        raise RuntimeError("deployment/images.lock.json has not been locked")
    observed = {image: _image_digest(image) for image in payload["images"]}
    mismatches = {
        image: {"expected": digest, "observed": observed[image]}
        for image, digest in payload["images"].items()
        if observed[image] != digest
    }
    if mismatches:
        raise RuntimeError(f"image digest mismatches: {mismatches}")
    return f"verified {len(payload['images'])} images"


def run_host_checks(repository_root: Path, scenario: Scenario) -> list[CheckResult]:
    lock_path = repository_root / "deployment" / "images.lock.json"
    checks = [
        _check(
            "linux-x86_64",
            lambda: _require(
                platform.system() == "Linux" and platform.machine() == "x86_64",
                f"found {platform.system()}/{platform.machine()}",
            ),
        ),
        _check(
            "cpu-avx",
            lambda: _require(
                " avx " in f" {Path('/proc/cpuinfo').read_text()} ", "AVX CPU flag is absent"
            ),
        ),
        _check("tun-device", lambda: str(Path("/dev/net/tun").resolve(strict=True))),
        _check(
            "gtp5g-module",
            lambda: _require(
                _command(["modinfo", "-F", "version", "gtp5g"])
                == scenario.versions.gtp5g.removeprefix("v"),
                "gtp5g module version mismatch",
            ),
        ),
        _check(
            "docker-engine",
            lambda: _command(["docker", "version", "--format", "{{.Server.Version}}"]),
        ),
        _check("docker-compose", _compose_version),
        _check("sctp-kernel", lambda: _command(["modinfo", "sctp"])),
        _check(
            "route-overlap",
            lambda: _require(
                not (conflicts := host_route_conflicts(scenario)),
                f"host route conflicts: {conflicts}",
            ),
        ),
        _check("oai-source", lambda: _git_tag(scenario.sources.oai, scenario.versions.oai)),
        _check(
            "free5gc-source",
            lambda: _git_tag(scenario.sources.free5gc_compose, scenario.versions.free5gc_compose),
        ),
        _check("image-lock", lambda: _verify_images(lock_path)),
    ]
    return checks


def host_check_payload(repository_root: Path, scenario: Scenario) -> dict[str, object]:
    checks = run_host_checks(repository_root, scenario)
    return {
        "passed": all(item.passed for item in checks),
        "checks": [asdict(item) for item in checks],
    }
