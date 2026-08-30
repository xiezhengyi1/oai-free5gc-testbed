from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{1,62}$")]
ContainerName = Annotated[str, Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}$")]
Hex32 = Annotated[str, Field(pattern=r"^[0-9a-fA-F]{32}$")]
IPv4Text = Annotated[str, Field(pattern=r"^(?:\d{1,3}\.){3}\d{1,3}$")]
CIDRText = Annotated[str, Field(pattern=r"^(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )


class SourceRoots(StrictModel):
    oai: str
    free5gc_compose: str

    @field_validator("oai", "free5gc_compose")
    @classmethod
    def absolute_linux_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if not path.is_absolute():
            raise ValueError("source roots must be absolute Linux paths")
        return str(path)


class VersionSpec(StrictModel):
    oai: Literal["2026.w35"]
    free5gc_compose: Literal["v4.1.0"]
    gtp5g: Literal["v0.9.5"]


class Plmn(StrictModel):
    mcc: Literal["208"]
    mnc: Literal["93"]
    tac: Annotated[int, Field(ge=0, le=0xFFFFFF)]

    @field_validator("mcc")
    @classmethod
    def validate_mcc(cls, value: str) -> str:
        if re.fullmatch(r"\d{3}", value) is None:
            raise ValueError("mcc must contain exactly three digits")
        return value

    @field_validator("mnc")
    @classmethod
    def validate_mnc(cls, value: str) -> str:
        if re.fullmatch(r"\d{2,3}", value) is None:
            raise ValueError("mnc must contain two or three digits")
        return value


class SliceSpec(StrictModel):
    id: Identifier
    sst: Annotated[int, Field(ge=0, le=255)]
    sd: Annotated[str, Field(pattern=r"^[0-9a-fA-F]{6}$")]

    @field_validator("sd")
    @classmethod
    def normalize_sd(cls, value: str) -> str:
        return value.lower()


class SiteSpec(StrictModel):
    id: Identifier
    type: Literal["edge", "cloud"]


class NetworkSpec(StrictModel):
    cidr: CIDRText
    bridge_name: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,15}$")]


class NetworkPlan(StrictModel):
    sbi: NetworkSpec = Field(alias="sbi-net")
    n2: NetworkSpec = Field(alias="n2-net")
    n3: NetworkSpec = Field(alias="n3-net")
    n4: NetworkSpec = Field(alias="n4-net")
    edge_n6: NetworkSpec = Field(alias="edge-n6-net")
    cloud_n6: NetworkSpec = Field(alias="cloud-n6-net")
    cloud_app: NetworkSpec = Field(alias="cloud-app-net")
    monitoring: NetworkSpec = Field(alias="monitoring-net")
    control: NetworkSpec = Field(alias="control-net")


class AmfSpec(StrictModel):
    sbi_ip: IPv4Text
    n2_ip: IPv4Text


class SmfSpec(StrictModel):
    sbi_ip: IPv4Text
    n4_ip: IPv4Text


class UpfSpec(StrictModel):
    id: Identifier
    container: ContainerName
    site_id: Identifier
    n3_ip: IPv4Text
    n4_ip: IPv4Text
    n6_ip: IPv4Text
    dnn: Identifier
    ue_pool: CIDRText


class CoreSpec(StrictModel):
    amf: AmfSpec
    smf: SmfSpec
    upfs: tuple[UpfSpec, ...] = Field(min_length=1)


class Position(StrictModel):
    x: float
    y: float
    z: float


class CellSpec(StrictModel):
    id: Identifier
    pci: Annotated[int, Field(ge=0, le=1007)]
    position: Position


class GnbSpec(StrictModel):
    id: Identifier
    container: ContainerName
    site_id: Identifier
    n2_ip: IPv4Text
    n3_ip: IPv4Text
    cells: tuple[CellSpec, ...] = Field(min_length=1)


class RanSpec(StrictModel):
    mode: Literal["rfsim"]
    band: Literal[78]
    numerology: Literal[1]
    bandwidth_rb: Literal[106]
    frequency_hz: Literal[3619200000]
    gnbs: tuple[GnbSpec, ...] = Field(min_length=1)


class PduSessionSpec(StrictModel):
    id: Identifier
    dnn: Identifier
    slice_id: Identifier


class UeSpec(StrictModel):
    id: Identifier
    container: ContainerName
    traffic_sidecar: ContainerName
    supi: Annotated[str, Field(pattern=r"^imsi-\d{5,15}$")]
    key: Hex32
    opc: Hex32
    serving_gnb: Identifier
    sessions: tuple[PduSessionSpec, ...] = Field(min_length=1)

    @field_validator("key", "opc")
    @classmethod
    def normalize_hex(cls, value: str) -> str:
        return value.lower()


class ResourceLimit(StrictModel):
    cpus: Annotated[float, Field(gt=0)]
    memory_mb: Annotated[int, Field(gt=0)]


class ServiceSpec(StrictModel):
    id: Identifier
    container: ContainerName
    service_id: Identifier
    site_id: Identifier
    network: Literal["edge-n6-net", "cloud-app-net"]
    ip: IPv4Text
    port: Annotated[int, Field(ge=1, le=65535)]
    resources: ResourceLimit


class LinkSpec(StrictModel):
    id: Identifier
    container: Literal["cloud-link-emulator"]
    n6_ip: IPv4Text
    app_side_ip: IPv4Text
    delay_ms: Annotated[float, Field(ge=0)]
    jitter_ms: Annotated[float, Field(ge=0)]
    loss_rate: Annotated[float, Field(ge=0, le=1)]
    bandwidth_mbps: Annotated[float, Field(gt=0)]


class SlaSpec(StrictModel):
    latency_ms: Annotated[float, Field(gt=0)]
    jitter_ms: Annotated[float, Field(ge=0)]
    loss_rate: Annotated[float, Field(ge=0, le=1)]
    guaranteed_bandwidth_mbps: Annotated[float, Field(gt=0)]


class FlowSpec(StrictModel):
    id: Identifier
    ue_id: Identifier
    session_id: Identifier
    service_instance_id: Identifier
    protocol: Literal["tcp", "udp", "http"]
    src_port: Annotated[int, Field(ge=1024, le=65535)]
    dst_port: Annotated[int, Field(ge=1, le=65535)]
    rate_mbps: Annotated[float, Field(gt=0)]
    packet_size_bytes: Annotated[int, Field(ge=64, le=65507)]
    sla: SlaSpec

    @model_validator(mode="after")
    def guaranteed_rate_not_above_offered_rate(self) -> FlowSpec:
        if self.sla.guaranteed_bandwidth_mbps > self.rate_mbps:
            raise ValueError("guaranteed bandwidth cannot exceed offered rate")
        return self


class ResourcePlan(StrictModel):
    containers: dict[str, ResourceLimit]


class ObservabilitySpec(StrictModel):
    scrape_interval_seconds: Annotated[int, Field(ge=1)]
    snapshot_interval_seconds: Annotated[int, Field(ge=1)]
    snapshot_window_seconds: Annotated[int, Field(ge=1)]
    prometheus: Literal[True]
    cadvisor: Literal[True]
    grafana: Literal[True]
    traffic_exporter: Literal[True]
    ran_exporter: Literal[True]

    @model_validator(mode="after")
    def window_covers_interval(self) -> ObservabilitySpec:
        if self.snapshot_window_seconds < self.snapshot_interval_seconds:
            raise ValueError("snapshot window must cover at least one snapshot interval")
        return self


class RuntimeSpec(StrictModel):
    startup_timeout_seconds: Annotated[int, Field(gt=0)]
    readiness_poll_seconds: Annotated[int, Field(gt=0)]
    action_timeout_seconds: Annotated[int, Field(gt=0)]


class MobilityEvent(StrictModel):
    at_seconds: Annotated[int, Field(gt=0)]
    ue_id: Identifier
    target_gnb: Identifier
    position: Position


class IntegrationSpec(StrictModel):
    multiagents_database_url_env: Literal["MULTIAGENTS_DATABASE_URL"]
    action_gateway_api_keys_env: Literal["ACTION_GATEWAY_API_KEYS"]


class Scenario(StrictModel):
    schema_version: Literal["1.0"]
    scenario_id: Identifier
    sources: SourceRoots
    versions: VersionSpec
    networks: NetworkPlan
    plmn: Plmn
    slices: tuple[SliceSpec, ...] = Field(min_length=1)
    sites: tuple[SiteSpec, ...] = Field(min_length=1)
    core: CoreSpec
    ran: RanSpec
    ues: tuple[UeSpec, ...] = Field(min_length=1)
    services: tuple[ServiceSpec, ...] = Field(min_length=1)
    links: tuple[LinkSpec, ...]
    flows: tuple[FlowSpec, ...] = Field(min_length=1)
    mobility: tuple[MobilityEvent, ...]
    resources: ResourcePlan
    observability: ObservabilitySpec
    runtime: RuntimeSpec
    integrations: IntegrationSpec
