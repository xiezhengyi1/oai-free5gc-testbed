from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from testbed.scenario.schema import GnbSpec, Scenario


def render_gnb_config(scenario: Scenario, gnb: GnbSpec, destination: Path) -> None:
    template_dir = Path(__file__).resolve().parents[2] / "deployment" / "oai"
    environment = Environment(
        loader=FileSystemLoader(template_dir), undefined=StrictUndefined, autoescape=False
    )
    template = environment.get_template("gnb.conf.j2")
    index = scenario.ran.gnbs.index(gnb)
    destination.write_text(
        template.render(
            scenario=scenario,
            gnb=gnb,
            gnb_numeric_id=f"0x{0xE00 + index:x}",
            nr_cell_id=12345678 + index,
        )
        + "\n",
        encoding="utf-8",
    )
