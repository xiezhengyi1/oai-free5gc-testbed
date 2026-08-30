from __future__ import annotations

from statistics import fmean

from testbed.adapters.prometheus_adapter import PrometheusAdapter


class WindowManager:
    def __init__(
        self, prometheus: PrometheusAdapter, start: float, end: float, step: float = 1
    ) -> None:
        self.prometheus = prometheus
        self.start = start
        self.end = end
        self.step = step

    def mean(self, query: str) -> tuple[float | None, int]:
        series = self.prometheus.range_query(query, self.start, self.end, self.step)
        values = [float(value) for item in series for _, value in item["values"]]
        return (fmean(values), len(values)) if values else (None, 0)

    def latest(self, query: str) -> float | None:
        vector = self.prometheus.instant_query(query, self.end)
        return float(vector[0]["value"][1]) if vector else None
