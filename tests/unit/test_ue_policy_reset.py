from pathlib import Path
from types import SimpleNamespace

from testbed.orchestration.ue_policy_reset import reset_policy_runtime


def test_reset_policy_runtime_clears_only_live_policy_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    ue = SimpleNamespace(id="ue-1", supi="imsi-208930000000001")
    flow = SimpleNamespace(id="flow-1", ue_id="ue-1")
    scenario = SimpleNamespace(ues=[ue], flows=[flow])
    monkeypatch.setattr(
        "testbed.orchestration.ue_policy_reset.load_scenario", lambda _: scenario
    )
    directory = tmp_path / "ue-policy" / "ue-1"
    directory.mkdir(parents=True)
    (tmp_path / "ue-policy" / "pcf").mkdir()
    artifacts = [
        tmp_path / "ue-policy" / "pcf" / "associations.json",
        directory / "208930000000001.policy",
        directory / "208930000000001.policy.sock",
        directory / "208930000000001.policy.state.json",
        directory / "flow-1.route.json",
    ]
    for artifact in artifacts:
        artifact.write_text("state")
    dynamic_marker = tmp_path / "ue-policy" / "dynamic-pdu.json"
    dynamic_marker.write_text("{}")

    reset_policy_runtime(tmp_path)

    assert not any(artifact.exists() for artifact in artifacts)
    assert not dynamic_marker.exists()
