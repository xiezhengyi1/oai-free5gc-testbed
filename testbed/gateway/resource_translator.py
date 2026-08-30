from __future__ import annotations

from dataclasses import dataclass

from testbed.gateway.contracts import ResourceAction


@dataclass(frozen=True)
class TranslatedResourceAction:
    container: str
    cpus: float
    memory_mb: int


def translate_resource(action: ResourceAction) -> TranslatedResourceAction:
    return TranslatedResourceAction(
        container=action.target.container,
        cpus=action.parameters.cpus,
        memory_mb=action.parameters.memory_mb,
    )
