"""Packet timing shared by traffic profiles and scenario inputs."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrafficTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    interval_ms: float | None = Field(default=None, gt=0)
    burst_on_ms: float = Field(default=0, ge=0)
    burst_off_ms: float = Field(default=0, ge=0)
    start_offset_ms: float = Field(default=0, ge=0)

    @model_validator(mode="after")
    def paired_burst(self):
        if bool(self.burst_on_ms) != bool(self.burst_off_ms):
            raise ValueError("burst_on_ms and burst_off_ms must both be positive or zero")
        return self

    def next_active(self, deadline: float, origin: float) -> float:
        start = origin + self.start_offset_ms / 1000
        deadline = max(deadline, start)
        if self.burst_on_ms == 0:
            return deadline
        cycle = (self.burst_on_ms + self.burst_off_ms) / 1000
        phase = (deadline - start) % cycle
        if phase >= self.burst_on_ms / 1000:
            deadline += cycle - phase
        return deadline

    def packet_interval(self, packet_bytes: int, rate_mbps: float) -> float:
        if self.interval_ms is not None:
            return self.interval_ms / 1000
        return packet_bytes * 8 / (rate_mbps * 1_000_000)

    def packet_rate(self, packet_bytes: int, rate_mbps: float) -> float:
        """Long-run scheduled arrival rate; independent of measured throughput."""
        duty = self.burst_on_ms / (self.burst_on_ms + self.burst_off_ms) if self.burst_on_ms else 1
        return duty / self.packet_interval(packet_bytes, rate_mbps)

    def scheduled_rate_mbps(self, packet_bytes: int, rate_mbps: float) -> float:
        if self.interval_ms is None and not self.burst_on_ms:
            return rate_mbps
        return self.packet_rate(packet_bytes, rate_mbps) * packet_bytes * 8 / 1_000_000
