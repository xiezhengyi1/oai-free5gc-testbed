import pytest
from pydantic import ValidationError

from testbed.orchestration.host_profile import HostProfile, apply_profile


def profile(**changes):
    return HostProfile.model_validate(
        dict(
            name="test",
            images={"old": "pinned"},
            digests={"pinned": "sha256:" + "a" * 64},
            control_cpus=[0],
            radio_cpus=[1],
            **changes,
        )
    )


def test_host_profile_requires_disjoint_cpu_pools_and_pinned_service_images():
    with pytest.raises(ValidationError):
        HostProfile(
            name="bad",
            images={},
            digests={"x": "sha256:" + "a" * 64},
            control_cpus=[0],
            radio_cpus=[0],
        )
    compose = {
        "services": {
            "oai-gnb-1": {"image": "old"},
            "oai-nrue-1": {"image": "old"},
            "free5gc-amf": {"image": "old"},
        }
    }
    apply_profile(compose, profile())
    assert compose["services"]["oai-gnb-1"]["cpuset"] == "0,1"
    assert compose["services"]["oai-nrue-1"]["cpuset"] == "1"
    assert compose["services"]["free5gc-amf"]["cpuset"] == "0"
    with pytest.raises(ValueError, match="pin"):
        apply_profile({"services": {"unknown": {"image": "unreviewed"}}}, profile())


def test_rendered_mounts_are_readable_inside_containers_but_run_stays_private(tmp_path):
    from types import SimpleNamespace
    from testbed.rendering.compose_renderer import set_generated_permissions

    generated = tmp_path / "generated"
    generated.mkdir(mode=0o700)
    directory = generated / "config"
    directory.mkdir(mode=0o700)
    config = directory / "upf.yaml"
    config.write_text("configuration")
    script = directory / "upf.sh"
    script.write_text("#!/bin/sh\n")
    config.chmod(0o600)
    script.chmod(0o600)
    set_generated_permissions(SimpleNamespace(root=tmp_path, generated=generated))
    assert tmp_path.stat().st_mode & 0o777 == 0o700
    assert directory.stat().st_mode & 0o777 == 0o755
    assert config.stat().st_mode & 0o777 == 0o644
    assert script.stat().st_mode & 0o777 == 0o755


def test_cpu_isolation_identifies_main_process_by_container_init_parent():
    from testbed.orchestration.cpu_isolation import main_gnb_pid

    rows = ["100 1 tini", "101 100 nr-softmodem", "102 101 nr-softmodem"]
    assert main_gnb_pid(rows, 100) == 101
    with pytest.raises(RuntimeError, match="not unique"):
        main_gnb_pid(rows + ["103 100 nr-softmodem"], 100)
    with pytest.raises(RuntimeError, match="not unique"):
        main_gnb_pid(rows, 999)


def test_cpu_isolation_waits_for_protocol_threads_before_any_affinity_write(tmp_path, monkeypatch):
    import testbed.orchestration.cpu_isolation as cpu

    task = tmp_path / "42/task/11"
    task.mkdir(parents=True)
    (task / "comm").write_text("nr-softmodem")
    monkeypatch.setattr(cpu, "Path", lambda _path: tmp_path)
    monkeypatch.setattr(cpu, "process_identity", lambda _pid: (0, "ticks"))
    writes = []
    monkeypatch.setattr(cpu.os, "cpu_count", lambda: 2)
    monkeypatch.setattr(
        cpu.os, "sched_setaffinity", lambda tid, pool: writes.append((tid, pool)), raising=False
    )
    request = dict(targets=[dict(pid=42, uid=0, ticks="ticks")], control=[0], radio=[1])
    with pytest.raises(cpu.ThreadsNotReady):
        cpu.pin_threads(request)
    assert not writes


def test_telemetry_readiness_requires_a_successful_persisted_snapshot(monkeypatch):
    from pathlib import Path
    import httpx
    from testbed.orchestration.readiness import Readiness
    from testbed.scenario.loader import load_scenario
    import testbed.orchestration.readiness as module

    scenario = load_scenario(
        Path(__file__).resolve().parents[2] / "scenarios/mvp/s1_single_ue_single_upf.yaml"
    )

    class Prometheus:
        def ready(self):
            pass

        def instant_query(self, _query):
            return [dict(metric={}, value=[0, "1"]) for _ in range(7)]

    monkeypatch.setattr(module, "PrometheusAdapter", lambda _url: Prometheus())
    monkeypatch.setattr(
        module.httpx,
        "get",
        lambda url, **kwargs: httpx.Response(
            200, json={"status": "ok"}, request=httpx.Request("GET", url)
        ),
    )
    monkeypatch.setattr(
        module.httpx,
        "post",
        lambda url, **kwargs: httpx.Response(500, request=httpx.Request("POST", url)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        Readiness(object(), scenario).telemetry()
    body = dict(
        snapshot_id="snapshot-test",
        run_id="run-test",
        baseline_epoch="epoch-test",
        observed_from="2026-10-28T00:00:00Z",
        observed_to="2026-10-28T00:00:10Z",
        topology={},
        slice_states=[],
        sessions=[],
        flows=[
            {
                "flow_id": scenario.flows[0].id,
                "data_quality": {"correlation_status": "complete", "stale": False},
            }
        ],
        ran_nodes=[],
        core_nodes=[],
        containers=[],
        mec_sites=[],
        mobility=[],
        active_actions=[],
        trigger_event="TelemetryReadiness",
    )
    monkeypatch.setattr(
        module.httpx,
        "post",
        lambda url, **kwargs: httpx.Response(201, json=body, request=httpx.Request("POST", url)),
    )
    assert Readiness(object(), scenario).telemetry()["snapshot_id"] == "snapshot-test"
    body["flows"][0]["data_quality"]["stale"] = True
    with pytest.raises(RuntimeError, match="stale"):
        Readiness(object(), scenario).telemetry()
