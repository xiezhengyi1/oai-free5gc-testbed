from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from testbed.scenario.schema import ContainerName, Identifier, StrictModel


class PolicyTarget(StrictModel):
    supi: str = Field(pattern=r"^imsi-\d{5,15}$")
    flow_id: Identifier


class PolicyParameters(StrictModel):
    five_qi: int = Field(ge=1, le=255)
    gbr_ul_mbps: float = Field(gt=0)
    mbr_ul_mbps: float = Field(gt=0)
    gbr_dl_mbps: float = Field(gt=0)
    mbr_dl_mbps: float = Field(gt=0)

    @model_validator(mode="after")
    def gbr_not_above_mbr(self) -> PolicyParameters:
        if self.gbr_ul_mbps > self.mbr_ul_mbps:
            raise ValueError("gbr_ul_mbps cannot exceed mbr_ul_mbps")
        if self.gbr_dl_mbps > self.mbr_dl_mbps:
            raise ValueError("gbr_dl_mbps cannot exceed mbr_dl_mbps")
        return self


class PolicyAction(StrictModel):
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action_type: Literal["sm_policy_update"]
    target: PolicyTarget
    parameters: PolicyParameters


class ResourceTarget(StrictModel):
    container: ContainerName


class ResourceParameters(StrictModel):
    cpus: float = Field(gt=0)
    memory_mb: int = Field(gt=0)


class ResourceAction(StrictModel):
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action_type: Literal["update_container_resources"]
    target: ResourceTarget
    parameters: ResourceParameters


class LifecycleAction(StrictModel):
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action_type: Literal["restart_container"]
    target: ResourceTarget


class SliceTarget(StrictModel):
    slice_id: Identifier


class SliceLifecycleAction(StrictModel):
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action_type: Literal["create_slice", "start_slice", "stop_slice", "delete_slice"]
    target: SliceTarget


class SliceResourceParameters(StrictModel):
    cpus: float = Field(gt=0)
    memory_mb: int = Field(gt=0)


class SliceResourceAction(StrictModel):
    run_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    action_type: Literal["update_slice_resources"]
    target: SliceTarget
    parameters: SliceResourceParameters


class Dispatch(StrictModel):
    accepted_at: datetime
    completed_at: datetime


class ActionReceipt(StrictModel):
    action_id: str
    run_id: str
    snapshot_before: str
    status: Literal["verified", "rejected", "failed"]
    dispatch: Dispatch
    observed_effect: dict[str, Any]
    snapshot_after: str | None
