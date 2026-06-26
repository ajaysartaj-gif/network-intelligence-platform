"""
core/intelligence/forecasting/forecasters_capacity.py
=====================================================
Anticipating load — the capacity-planning family.

  CongestionPrediction — will a link/queue saturate within the horizon, and when?
                         (power-grid peak-load forecasting + ATC look-ahead)
  CapacityForecast      — time-to-exhaustion of a finite resource (table size,
                         bandwidth, CPU). The autonomous-vehicle "time to
                         collision": project the trend, solve when it hits the
                         wall, and act before impact.
  TrafficEvolution      — the shape of demand over time (trend + volatility cone)
                         so growth isn't a surprise. (weather cone + finance)
  GrowthPrediction      — longer-horizon structural growth (devices/prefixes/
                         sessions) for procurement lead time.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from core.intelligence.forecasting.base import (
    Forecaster, ForecasterSpec, Forecast, ForecastType, Driver, HOUR, DAY, WEEK, MONTH, QUARTER,
)
from core.intelligence.forecasting import ensemble as E
from core.intelligence.forecasting import signals as S


def _series(ctx: Dict[str, Any], subject: str, metric: str
            ) -> List[Tuple[float, float]]:
    """Prefer a caller-supplied series; else read recorded history; else []."""
    sv = ctx.get("series")
    if sv and isinstance(sv, list) and all(isinstance(p, (list, tuple)) for p in sv):
        return [(float(t), float(v)) for t, v in sv]
    return S.metric_series(subject, metric)


class _Projector(Forecaster):
    """Shared projection→threshold logic for the quantity forecasters."""
    metric = "utilization"
    threshold_default = 90.0
    unit = "%"
    sev = 0.5

    def _project_forecast(self, ctx: Dict[str, Any], target: str,
                          action_hi: str) -> Optional[Forecast]:
        subject = ctx.get("subject") or ctx.get("interface") or ctx.get("device", "")
        if not subject:
            return None
        series = _series(ctx, subject, self.metric)
        if len(series) < 3:
            return None
        threshold = float(ctx.get("threshold") or self.threshold_default)
        horizon = ctx.get("horizon_s") or self.spec.default_horizon_s
        times = [p[0] for p in series]
        vals = [p[1] for p in series]
        pr = E.project(times, vals, horizon, threshold=threshold)
        proj = pr["projection"]
        if proj is None:
            return None
        ttt = pr["time_to_threshold_s"]
        # probability of breaching within horizon: projection vs threshold,
        # softened by the uncertainty band (cone) and trend trustworthiness (r²).
        band = max(1e-6, pr["band"])
        z = (proj - threshold) / band
        p = E.clamp(E.sigmoid(z) * (0.5 + 0.5 * pr["r2"]))
        if ttt is not None and ttt <= horizon:
            p = max(p, 0.6)
        return Forecast(
            target=target, subject=subject, kind=self.spec.key,
            ftype=ForecastType.QUANTITY.value, horizon_s=horizon,
            value=round(proj, 2), value_unit=self.unit, threshold=threshold,
            probability=p, lead_time_s=ttt, severity=self.sev,
            drivers=[Driver("trend", round(pr["slope_per_s"] * DAY, 3),
                            f"{pr['slope_per_s']*DAY:+.2f}{self.unit}/day, r²={pr['r2']}"),
                     Driver("projected vs threshold", round(p - 0.1, 2),
                            f"≈{proj:.0f}{self.unit} vs {threshold:.0f}{self.unit}")],
            method="least-squares trend + uncertainty cone, time-to-threshold",
            recommended_action=(action_hi if p >= 0.5 else "within capacity"),
            metadata={"claim": f"{target} breaches threshold in horizon",
                      "band": round(band, 2)})


class CongestionPrediction(_Projector):
    metric = "utilization"
    threshold_default = 85.0
    unit = "%"
    sev = 0.55

    def __init__(self):
        super().__init__(ForecasterSpec(
            "congestion_prediction", "Congestion Prediction",
            "Will this link saturate within the horizon?", ForecastType.QUANTITY,
            discipline="power-grid peak-load + ATC look-ahead", default_horizon_s=DAY))

    def _forecast(self, ctx):
        return self._project_forecast(ctx, "link utilization",
                                      "shift traffic / raise capacity before peak")


class CapacityForecast(_Projector):
    metric = "resource_pct"
    threshold_default = 95.0
    unit = "%"
    sev = 0.6

    def __init__(self):
        super().__init__(ForecasterSpec(
            "capacity_forecast", "Capacity Forecast",
            "When will a finite resource exhaust?", ForecastType.QUANTITY,
            discipline="autonomous-vehicle time-to-collision", default_horizon_s=MONTH))

    def _forecast(self, ctx):
        return self._project_forecast(ctx, "resource utilization",
                                      "procure / expand before exhaustion")


class TrafficEvolution(_Projector):
    metric = "throughput"
    threshold_default = 1e12       # effectively report the trend, not a wall
    unit = ""
    sev = 0.35

    def __init__(self):
        super().__init__(ForecasterSpec(
            "traffic_evolution", "Traffic Evolution",
            "How is demand trending over time?", ForecastType.QUANTITY,
            discipline="weather cone + financial trend", default_horizon_s=WEEK))

    def _forecast(self, ctx):
        f = self._project_forecast(ctx, "throughput", "plan for growth")
        if f:
            # this is informational trend, not a breach event
            f.probability = None
            f.recommended_action = "feed capacity planning"
        return f


class GrowthPrediction(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "growth_prediction", "Growth Prediction",
            "How will the estate grow over the planning horizon?",
            ForecastType.QUANTITY, discipline="procurement demand forecasting",
            default_horizon_s=QUARTER))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        # estate growth from topology-evolution snapshots over time.
        s = S._sys()
        if not s:
            return None
        try:
            snaps = s.topology_evo.recent(limit=20)
        except Exception:
            snaps = []
        points = []
        for r in snaps:
            ts = float(r.get("snap_ts") or r.get("updated_ts") or 0)
            try:
                import json
                n = len(json.loads(r.get("nodes") or "[]"))
            except Exception:
                n = 0
            if ts and n:
                points.append((ts, float(n)))
        if len(points) < 3:
            return None
        points.sort()
        horizon = ctx.get("horizon_s") or self.spec.default_horizon_s
        pr = E.project([p[0] for p in points], [p[1] for p in points], horizon)
        proj = pr["projection"]
        if proj is None:
            return None
        cur = points[-1][1]
        growth = proj - cur
        return Forecast(
            target="estate node count", subject="network", kind=self.spec.key,
            ftype=ForecastType.QUANTITY.value, horizon_s=horizon,
            value=round(proj, 1), value_unit="nodes", threshold=None,
            probability=None, severity=0.3,
            drivers=[Driver("node growth trend", round(pr["slope_per_s"] * MONTH, 2),
                            f"{pr['slope_per_s']*MONTH:+.1f} nodes/month")],
            method="snapshot regression over topology evolution",
            recommended_action=(f"plan for ~{growth:+.0f} nodes; check addressing/licensing"
                                if abs(growth) >= 1 else "stable"),
            metadata={"claim": "estate will grow", "current": cur})


def build() -> list:
    return [CongestionPrediction(), CapacityForecast(), TrafficEvolution(),
            GrowthPrediction()]
