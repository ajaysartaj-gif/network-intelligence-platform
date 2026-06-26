"""
core/intelligence/forecasting/forecasters_reliability.py
========================================================
Anticipating breakage — the predictive-maintenance family.

  FailurePrediction  — P(this device/signature fails within the horizon), from
                       recurrence, recent failure density and MTBF. (medicine
                       early-warning score + industrial reliability)
  HardwareAging      — remaining useful life via a Weibull bathtub hazard on
                       device age + health. (industrial RUL / predictive maint.)
  SoftwareAging      — resource exhaustion / bug-exposure that grows with uptime
                       and code age — the case for scheduled rejuvenation.
                       (software-aging & rejuvenation)
  VendorRisk         — exposure carried by a vendor/OS given its track record
                       across the estate. (supply-chain risk)
  MaintenanceRisk    — risk that a PLANNED change causes impact, from criticality,
                       blast radius, freeze windows and earned competence.
                       (ATC pre-flight + power-grid contingency)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.intelligence.forecasting.base import (
    Forecaster, ForecasterSpec, Forecast, ForecastType, Driver, DAY, WEEK, MONTH, QUARTER,
)
from core.intelligence.forecasting import ensemble as E
from core.intelligence.forecasting import signals as S


class FailurePrediction(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "failure_prediction", "Failure Prediction",
            "Will this device fail within the horizon?", ForecastType.EVENT,
            discipline="industrial reliability + medicine early-warning",
            default_horizon_s=WEEK))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        if not device:
            return None
        rate = S.recent_failure_rate(device)                 # fails/day
        mtbf = S.mtbf_seconds(f"device:{device.lower()}")    # seconds
        horizon = ctx.get("horizon_s") or self.spec.default_horizon_s
        health = S.device_health_score(device)               # 0..100 or None

        # signal 1: recent failure density → Poisson P(>=1 in horizon)
        import math
        lam = rate * (horizon / DAY)
        p_density = 1 - math.exp(-lam) if lam > 0 else 0.05
        # signal 2: MTBF position — overdue relative to mean time between failures
        p_mtbf = 0.1
        lead = None
        if mtbf > 0:
            fails = S.device_failure_history(device, limit=1)
            import time
            last = float(fails[0].get("ts")) if fails else (time.time() - mtbf)
            elapsed = max(0.0, time.time() - last)
            p_mtbf = E.clamp(elapsed / mtbf)
            lead = max(0.0, mtbf - elapsed)
        # signal 3: live health (low health → higher hazard)
        sig = [(p_density, 1.0), (p_mtbf, 0.8)]
        drivers = [Driver("recent failure rate", round(p_density - 0.1, 2),
                          f"{rate:.2f}/day"),
                   Driver("MTBF position", round(p_mtbf - 0.1, 2),
                          f"MTBF {mtbf/DAY:.1f}d" if mtbf else "no MTBF yet")]
        if health is not None:
            p_health = E.clamp((100 - health) / 100)
            sig.append((p_health, 0.9))
            drivers.append(Driver("device health", round(p_health - 0.1, 2),
                                  f"health {health:.0f}/100"))

        p = E.pool_logodds(sig, prior=0.08)
        impact = S.business_impact(device)
        sev = E.clamp(0.3 + 0.6 * float(impact.get("criticality") or 0.3))
        return Forecast(
            target="device failure", subject=device, kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=horizon, probability=p,
            lead_time_s=lead, severity=sev, drivers=drivers,
            method="ensemble log-odds pooling (Poisson density + MTBF + health)",
            recommended_action=("pre-stage rollback and inspect" if p >= 0.4
                                else "monitor"),
            metadata={"claim": "device will fail in horizon"})


class HardwareAging(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "hardware_aging", "Hardware Aging",
            "How close is this hardware to wear-out failure?", ForecastType.EVENT,
            discipline="industrial predictive maintenance (Weibull RUL)",
            default_horizon_s=QUARTER))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        if not device:
            return None
        meta = S.device_meta(device)
        import time
        install = meta.get("install_date")
        age_s = None
        try:
            if install:
                # accept epoch or year
                iv = float(install)
                age_s = time.time() - (iv if iv > 1e6 else time.mktime((int(iv), 1, 1, 0, 0, 0, 0, 0, 0)))
        except Exception:
            age_s = None
        # characteristic life eta: default 6 years for access routers.
        eta = float(ctx.get("eta_s") or 6 * 365 * DAY)
        if age_s is None:
            # fall back to failure history as an age proxy
            fails = S.device_failure_history(device)
            if not fails:
                return None
            age_s = 0.4 * eta + len(fails) * 30 * DAY
        haz = E.weibull_hazard(age_s, eta, beta=2.2)         # wear-out region
        lead = E.time_to_event(haz / max(1.0, self.spec.default_horizon_s))
        return Forecast(
            target="hardware wear-out", subject=device, kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=self.spec.default_horizon_s,
            probability=E.clamp(haz), lead_time_s=lead, severity=0.7,
            drivers=[Driver("age vs characteristic life", round(haz, 2),
                            f"age {age_s/DAY/365:.1f}y of ~{eta/DAY/365:.0f}y")],
            method="Weibull bathtub hazard (beta=2.2 wear-out)",
            recommended_action=("plan RMA / refresh" if haz >= 0.4 else "track age"),
            metadata={"claim": "hardware approaches wear-out"})


class SoftwareAging(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "software_aging", "Software Aging",
            "Will accumulated runtime/code-age degrade this node?",
            ForecastType.EVENT,
            discipline="software aging & rejuvenation", default_horizon_s=MONTH))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        if not device:
            return None
        meta = S.device_meta(device)
        uptime = meta.get("uptime_s")
        try:
            uptime = float(uptime) if uptime is not None else None
        except Exception:
            uptime = None
        if uptime is None:
            return None
        # resource exhaustion risk grows with uptime past ~180d (rejuvenation point)
        rej_point = float(ctx.get("rejuvenation_s") or 180 * DAY)
        p = E.logistic(uptime / rej_point, midpoint=1.0, steepness=3.0)
        lead = max(0.0, rej_point - uptime) if uptime < rej_point else 0.0
        return Forecast(
            target="software-aging degradation", subject=device, kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=self.spec.default_horizon_s,
            probability=p, lead_time_s=lead, severity=0.5,
            drivers=[Driver("uptime past rejuvenation point", round(p - 0.1, 2),
                            f"uptime {uptime/DAY:.0f}d / {rej_point/DAY:.0f}d")],
            method="logistic uptime-vs-rejuvenation model",
            recommended_action=("schedule a maintenance reload in a safe window"
                                if p >= 0.5 else "monitor uptime"),
            metadata={"claim": "software aging will degrade node"})


class VendorRisk(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "vendor_risk", "Vendor Risk",
            "How much failure risk does this vendor/OS carry here?",
            ForecastType.SCORE, discipline="supply-chain risk", default_horizon_s=QUARTER))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        vendor = ctx.get("vendor", "")
        if not vendor and ctx.get("device"):
            vendor = (S.device_meta(ctx["device"]).get("vendor") or "")
        if not vendor:
            return None
        rate, n = S.vendor_failure_rate(vendor)
        if n < 3:
            return None
        score = E.clamp(rate)
        return Forecast(
            target="vendor-carried risk", subject=f"vendor:{vendor}",
            kind=self.spec.key, ftype=ForecastType.SCORE.value,
            horizon_s=self.spec.default_horizon_s, probability=score, severity=0.5,
            drivers=[Driver("estate failure rate for vendor", round(score - 0.1, 2),
                            f"{rate:.0%} over {n} changes")],
            method="estate-wide vendor failure-fraction",
            recommended_action=("prioritise patching / standardise OS"
                                if score >= 0.4 else "no action"),
            metadata={"claim": "vendor carries elevated risk"})


class MaintenanceRisk(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "maintenance_risk", "Maintenance Risk",
            "Will this planned change cause impact?", ForecastType.SCORE,
            discipline="ATC pre-flight + power-grid N-1 contingency",
            default_horizon_s=DAY))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        intent = ctx.get("intent", "")
        protocol = ctx.get("protocol", "")
        if not (device or intent):
            return None
        impact = S.business_impact(device) if device else {"criticality": 0.3}
        crit = float(impact.get("criticality") or 0.3)
        comp = S.domain_competence(protocol or "general")
        inexperience = 1 - float(comp.get("success_rate") or 0.5)
        # blast radius via topology degree (power-grid contingency)
        adj = S.topology_graph()
        degree = len(adj.get(device, [])) if device else 0
        blast = E.clamp(degree / 6.0)
        frozen = False
        s = S._sys()
        if s and device:
            try:
                frozen = bool(s.business.in_freeze(device).get("frozen"))
            except Exception:
                frozen = False
        score = E.pool_logodds(
            [(crit, 1.0), (inexperience, 0.9), (blast, 0.8),
             (0.9 if frozen else 0.1, 1.2)], prior=0.15)
        drivers = [Driver("business criticality", round(crit - 0.1, 2), impact.get("detail", "")),
                   Driver("inexperience", round(inexperience - 0.1, 2),
                          f"{comp.get('level')} ({comp.get('success_rate',0):.0%})"),
                   Driver("blast radius", round(blast - 0.1, 2), f"{degree} neighbours")]
        if frozen:
            drivers.append(Driver("change freeze", 0.4, "inside a freeze window"))
        return Forecast(
            target="maintenance impact", subject=device or intent, kind=self.spec.key,
            ftype=ForecastType.SCORE.value, horizon_s=self.spec.default_horizon_s,
            probability=score, severity=E.clamp(0.4 + 0.5 * crit), drivers=drivers,
            method="log-odds pooling of criticality·experience·blast·freeze",
            recommended_action=("defer to safe window; pre-stage rollback"
                                if score >= 0.5 else "proceed with verification"),
            metadata={"claim": "planned change will cause impact", "frozen": frozen})


def build() -> list:
    return [FailurePrediction(), HardwareAging(), SoftwareAging(),
            VendorRisk(), MaintenanceRisk()]
