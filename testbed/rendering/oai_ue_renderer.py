from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from testbed.scenario.schema import Scenario, UeSpec


def render_ue_config(scenario: Scenario, ue: UeSpec, destination: Path) -> None:
    template_dir = Path(__file__).resolve().parents[2] / "deployment" / "oai"
    environment = Environment(
        loader=FileSystemLoader(template_dir), undefined=StrictUndefined, autoescape=False
    )
    template = environment.get_template("nrue.conf.j2")
    destination.write_text(template.render(scenario=scenario, ue=ue) + "\n", encoding="utf-8")
