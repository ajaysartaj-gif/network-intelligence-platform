"""
core/intelligence/forecasting/forecasters_operational.py
========================================================
Anticipating the operation itself — change, people, threats, and the platform's
own reliability.

  DeploymentSuccess  — will the next change succeed? (military course-of-action)
  RollbackProbability— will we have to back it out? (aviation go-around rate)
  ConfigurationDrift — will config drift out of policy before we look again?
                       (control-chart drift / financial mean-reversion)
  OperatorError      — likelihood the human makes a mistake on the next action
                       (aviation/medicine human-factors & alarm fatigue)
  SecurityThreat     — indications & warning of rising threat surface, NOT traffic
                       anomaly (military I&W + medical screening)
  CascadingFailure   — if X fails, how far does it spread? (power-grid cascade)
  ChangeConflict     — will two changes/maintenances collide in time on coupled
                       devices? (ATC separation assurance)
  BusinessImpact /
  CustomerImpact     — expected damage if a predicted failure lands (finance
                       expected-loss PD×LGD×EAD; medical prognosis)
  ConfidenceDrift    — is the platform's own forecasting getting worse? (model
                       drift / forecast-verification control chart)
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from core.intelligence.forecasting.base import (
    Forecaster, ForecasterSpec, Forecast, ForecastType, Driver, HOUR, DAY, WEEK, MONTH,
)
from core.intelligence.forecasting import ensemble as E
from core.intelligence.forecasting import signals as S


class DeploymentSuccess(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "deployment_success", "Deployment Success",
            "Will the proposed change succeed?", ForecastType.EVENT,
            discipline="military course-of-action analysis", default_horizon_s=HOUR))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        intent = ctx.get("intent", "")
        if not intent:
            return None
        protocol = ctx.get("protocol", "")
        proc = S.procedure_stats(intent, protocol)
        comp = S.domain_competence(protocol or "general")
        p_proc = proc["success_rate"] if proc else 0.5
        p_exp = comp.get("success_rate", 0.5) if comp.get("attempts") else 0.5
        scars = S.contraindications(f"{intent} {protocol}")
        scar_pen = min(0.3, 0.1 * len(scars))
        trisk = S.temporal_risk(f"domain:{protocol or 'general'}")
        p = E.pool_logodds([(p_proc, 1.0), (p_exp, 0.8)], prior=0.5)
        p = E.clamp(p - scar_pen - (0.1 if trisk.get("elevated") else 0))
        drivers = [Driver("known procedure", round(p_proc - 0.5, 2),
                          f"{p_proc:.0%}" + (f" over {proc['attempts']}" if proc else " (none)")),
                   Driver("competence", round(p_exp - 0.5, 2),
                          f"{comp.get('level')} ({p_exp:.0%})")]
        if scars:
            drivers.append(Driver("contraindications", -scar_pen, f"{len(scars)} scars"))
        return Forecast(
            target="deployment success", subject=intent, kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=self.spec.default_horizon_s,
            probability=p, severity=0.4, drivers=drivers,
            method="COA: pool procedural+experience, penalise scars/timing",
            recommended_action=("proceed" if p >= 0.7 else
                                "review / dry-run first" if p >= 0.4 else
                                "do not deploy as-is"),
            metadata={"claim": "change will succeed"})


class RollbackProbability(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "rollback_probability", "Rollback Probability",
            "Will this change need to be rolled back?", ForecastType.EVENT,
            discipline="aviation go-around rate", default_horizon_s=DAY))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        intent = ctx.get("intent", "")
        if not intent:
            return None
        protocol = ctx.get("protocol", "")
        proc = S.procedure_stats(intent, protocol)
        p_fail = 1 - (proc["success_rate"] if proc else 0.5)
        scars = S.contraindications(f"{intent} {protocol}")
        # base-rate of rollbacks across the estate as a weak prior
        rb = S.rollback_events(limit=200)
        base = E.clamp(len(rb) / 200.0)
        p = E.pool_logodds([(p_fail, 1.0), (0.7 if scars else 0.1, 0.7)],
                           prior=max(0.08, base))
        return Forecast(
            target="rollback needed", subject=intent, kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=self.spec.default_horizon_s,
            probability=p, severity=0.45,
            drivers=[Driver("procedure failure rate", round(p_fail - 0.1, 2),
                            f"{p_fail:.0%}"),
                     Driver("scar tissue", 0.3 if scars else 0.0, f"{len(scars)} scars")],
            method="failure-rate + contraindication pooling vs rollback base-rate",
            recommended_action=("pre-stage and test rollback path" if p >= 0.35
                                else "standard rollback readiness"),
            metadata={"claim": "change will be rolled back"})


class ConfigurationDrift(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "configuration_drift", "Configuration Drift",
            "Will this device drift out of policy before next review?",
            ForecastType.EVENT, discipline="control-chart drift", default_horizon_s=MONTH))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        if not device:
            return None
        age = S.last_known_good_age(device)            # since last verified-good
        if age is None:
            return None
        # change frequency raises drift odds; long time since known-good too.
        hist = S.device_failure_history(device, limit=50)
        changes = len(hist)
        horizon = ctx.get("horizon_s") or self.spec.default_horizon_s
        p_age = E.logistic(age / (horizon or MONTH), midpoint=1.0, steepness=2.0)
        p_freq = E.clamp(changes / 20.0)
        p = E.pool_logodds([(p_age, 1.0), (p_freq, 0.6)], prior=0.12)
        return Forecast(
            target="configuration drift", subject=device, kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=horizon, probability=p,
            lead_time_s=max(0.0, (horizon or MONTH) - age) if age < (horizon or MONTH) else 0.0,
            severity=0.4,
            drivers=[Driver("time since known-good", round(p_age - 0.1, 2),
                            f"{age/DAY:.0f}d"),
                     Driver("change churn", round(p_freq - 0.1, 2), f"{changes} changes")],
            method="logistic drift on known-good age + churn",
            recommended_action=("schedule a compliance re-baseline" if p >= 0.4
                                else "routine review cadence"),
            metadata={"claim": "device will drift out of policy"})


class OperatorError(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "operator_error", "Operator Error",
            "Is the next human action error-prone right now?", ForecastType.EVENT,
            discipline="aviation/medicine human factors", default_horizon_s=HOUR))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        operator = ctx.get("operator", "")
        fatigue, why = S.fatigue_factor()
        actions = S.operator_recent_actions(operator) if operator else 0
        comp = S.domain_competence(ctx.get("protocol") or "general")
        inexperience = 1 - float(comp.get("success_rate") or 0.5)
        # alarm-fatigue / workload: many actions in the last hour raises error odds
        workload = E.clamp(actions / 12.0)
        base = E.clamp(0.05 * fatigue)
        p = E.pool_logodds([(workload, 0.9), (inexperience, 0.7),
                            (E.clamp(fatigue - 1.0), 0.8)], prior=base)
        return Forecast(
            target="operator error", subject=operator or "operator", kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=self.spec.default_horizon_s,
            probability=p, severity=0.5,
            drivers=[Driver("workload", round(workload - 0.1, 2), f"{actions} actions/h"),
                     Driver("time-of-day fatigue", round(E.clamp(fatigue-1.0), 2), why),
                     Driver("domain inexperience", round(inexperience - 0.1, 2),
                            comp.get("level", ""))],
            method="human-factors pooling (workload·fatigue·inexperience)",
            recommended_action=("add a second-set-of-eyes / require confirmation"
                                if p >= 0.4 else "normal guardrails"),
            metadata={"claim": "next human action is error-prone"})


class SecurityThreat(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "security_threat", "Security Threat",
            "Is the threat surface rising toward an incident?", ForecastType.SCORE,
            discipline="military indications & warning", default_horizon_s=WEEK))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        # indications & warning: stale config, out-of-window changes, known scars
        # tagged security, and drift — composed, not traffic-anomaly based.
        indicators: List = []
        age = S.last_known_good_age(device) if device else None
        if age is not None:
            indicators.append((E.clamp(age / (90 * DAY)), 0.7,
                               f"unverified {age/DAY:.0f}d"))
        scars = S.contraindications(f"security {device}")
        if scars:
            indicators.append((min(0.8, 0.2 * len(scars)), 0.9,
                               f"{len(scars)} security scars"))
        # off-hours change activity as a warning indicator
        fatigue, _ = S.fatigue_factor()
        if device:
            hist = S.device_failure_history(device, limit=20)
            if hist:
                indicators.append((E.clamp(len(hist) / 10.0), 0.5,
                                   "recent change instability"))
        if not indicators:
            return None
        score = E.pool_logodds([(p, w) for p, w, _ in indicators], prior=0.1)
        return Forecast(
            target="security threat surface", subject=device or "estate",
            kind=self.spec.key, ftype=ForecastType.SCORE.value,
            horizon_s=self.spec.default_horizon_s, probability=score, severity=0.7,
            drivers=[Driver(d, round(p - 0.1, 2), d) for p, w, d in indicators],
            method="indications & warning composition (no traffic anomaly)",
            recommended_action=("audit & harden; verify config baseline" if score >= 0.4
                                else "routine posture"),
            metadata={"claim": "threat surface is rising"})


class CascadingFailure(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "cascading_failure", "Cascading Failure",
            "If this node fails, how far does it spread?", ForecastType.SCORE,
            discipline="power-grid cascade / N-1 contingency", default_horizon_s=DAY))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        adj = S.topology_graph(ctx.get("site", ""))
        if not device or device not in adj:
            return None
        # nodes that lose ALL paths if `device` is removed (articulation impact).
        reachable_with = _reachable(adj, exclude=None)
        reachable_without = _reachable(adj, exclude=device)
        isolated = (reachable_with - reachable_without) - {device}
        total = max(1, len(adj))
        spread = len(isolated) / total
        # weight by business criticality of the isolated set
        crit = 0.0
        for n in isolated:
            crit = max(crit, float(S.business_impact(n).get("criticality") or 0.3))
        score = E.clamp(0.5 * spread + 0.5 * (spread > 0) * crit)
        return Forecast(
            target="cascade blast radius", subject=device, kind=self.spec.key,
            ftype=ForecastType.SCORE.value, horizon_s=self.spec.default_horizon_s,
            probability=score, severity=E.clamp(0.4 + 0.5 * crit),
            drivers=[Driver("isolated-on-failure", round(spread, 2),
                            f"{len(isolated)} of {total} nodes"),
                     Driver("critical dependents", round(crit - 0.1, 2),
                            f"max criticality {crit:.0%}")],
            method="N-1 contingency on the topology graph",
            recommended_action=("add redundancy / protect this node" if score >= 0.4
                                else "no single-point exposure"),
            metadata={"claim": "failure cascades", "isolated": sorted(isolated)})


class ChangeConflict(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "change_conflict", "Change Conflict",
            "Will concurrent changes collide on coupled devices?",
            ForecastType.EVENT, discipline="ATC separation assurance",
            default_horizon_s=4 * HOUR))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        if not device:
            return None
        window = ctx.get("horizon_s") or self.spec.default_horizon_s
        m = S._mem()
        if not m:
            return None
        try:
            since = time.time() - window
            recent = m.temporal(since=since, limit=100)
        except Exception:
            recent = []
        adj = S.topology_graph(ctx.get("site", ""))
        neighbours = set(adj.get(device, [])) | {device}
        # other devices changed in the window that are topologically coupled
        coupled = [e for e in recent
                   if (e.get("device") or "") and e.get("device") != device
                   and e.get("device") in neighbours]
        if not coupled:
            return None
        p = E.clamp(0.25 + 0.15 * len(coupled))
        return Forecast(
            target="change conflict", subject=device, kind=self.spec.key,
            ftype=ForecastType.EVENT.value, horizon_s=window, probability=p,
            severity=0.5,
            drivers=[Driver("coupled concurrent changes", round(p - 0.1, 2),
                            f"{len(coupled)} on neighbours in window")],
            method="ATC-style separation over the change timeline",
            recommended_action="serialise the changes; hold a maintenance lock",
            metadata={"claim": "changes will conflict",
                      "coupled_devices": sorted({e.get('device') for e in coupled})})


class BusinessImpact(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "business_impact", "Business Impact",
            "Expected business damage if the predicted failure lands.",
            ForecastType.SCORE, discipline="finance expected-loss (PD×LGD×EAD)",
            default_horizon_s=WEEK))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        if not device:
            return None
        pd = float(ctx.get("failure_probability") or 0.0)
        if pd <= 0:
            # derive a quick PD from failure-prediction signals if not supplied
            from core.intelligence.forecasting.forecasters_reliability import FailurePrediction
            fp = FailurePrediction().forecast({"device": device}, log=False)
            pd = fp.probability if fp and fp.probability is not None else 0.1
        impact = S.business_impact(device)
        lgd = float(impact.get("criticality") or 0.3)         # loss given default
        services = impact.get("services") or []
        ead = E.clamp(0.3 + 0.1 * len(services))              # exposure
        expected = E.clamp(pd * lgd * (0.6 + 0.4 * ead))
        return Forecast(
            target="expected business impact", subject=device, kind=self.spec.key,
            ftype=ForecastType.SCORE.value, horizon_s=self.spec.default_horizon_s,
            probability=expected, severity=E.clamp(0.3 + 0.6 * lgd),
            drivers=[Driver("failure probability (PD)", round(pd - 0.1, 2), f"{pd:.0%}"),
                     Driver("criticality (LGD)", round(lgd - 0.1, 2), impact.get("detail", "")),
                     Driver("exposure (EAD)", round(ead - 0.1, 2),
                            f"{len(services)} services")],
            method="expected-loss PD×LGD×EAD",
            recommended_action=("prioritise protection of this asset" if expected >= 0.3
                                else "standard priority"),
            metadata={"claim": "failure carries business impact",
                      "services": services})


class CustomerImpact(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "customer_impact", "Customer Impact",
            "How many customers/services feel a predicted failure.",
            ForecastType.SCORE, discipline="medical prognosis / blast radius",
            default_horizon_s=WEEK))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        device = ctx.get("device", "")
        if not device:
            return None
        adj = S.topology_graph(ctx.get("site", ""))
        downstream = _reachable(adj, exclude=None) - (_reachable(adj, exclude=device) | {device}) if device in adj else set()
        impact = S.business_impact(device)
        services = impact.get("services") or []
        reach = E.clamp((len(downstream) + len(services)) / 8.0)
        if reach <= 0:
            return None
        return Forecast(
            target="customer impact reach", subject=device, kind=self.spec.key,
            ftype=ForecastType.SCORE.value, horizon_s=self.spec.default_horizon_s,
            probability=reach, severity=E.clamp(0.3 + 0.5 * float(impact.get("criticality") or 0.3)),
            drivers=[Driver("downstream isolated", round(reach - 0.1, 2),
                            f"{len(downstream)} nodes, {len(services)} services")],
            method="downstream reachability + service binding",
            recommended_action=("notify owners; protect path" if reach >= 0.4 else "low reach"),
            metadata={"claim": "customers will be affected",
                      "downstream": sorted(downstream)})


class ConfidenceDrift(Forecaster):
    def __init__(self):
        super().__init__(ForecasterSpec(
            "confidence_drift", "Confidence Drift",
            "Is the platform's own forecasting getting worse?", ForecastType.SCORE,
            discipline="forecast verification / model-drift control chart",
            default_horizon_s=WEEK))

    def _forecast(self, ctx: Dict[str, Any]) -> Optional[Forecast]:
        s = S._sys()
        if not s:
            return None
        try:
            hr = s.prediction.hit_rate()
        except Exception:
            return None
        n = int(hr.get("resolved") or 0)
        if n < 8:
            return None
        rate = float(hr.get("hit_rate") or 0.0)
        # degradation score: how far below a healthy 0.7 calibration we are.
        drift = E.clamp((0.7 - rate) / 0.7)
        return Forecast(
            target="self-calibration drift", subject="platform", kind=self.spec.key,
            ftype=ForecastType.SCORE.value, horizon_s=self.spec.default_horizon_s,
            probability=drift, severity=0.4,
            drivers=[Driver("resolved hit-rate", round(0.7 - rate, 2),
                            f"{rate:.0%} over {n}")],
            method="hit-rate vs target control chart",
            recommended_action=("widen uncertainty; re-consolidate memory" if drift >= 0.3
                                else "calibration healthy"),
            metadata={"claim": "platform forecasting is drifting", "hit_rate": rate})


# ── helpers ──────────────────────────────────────────────────────────────────
def _reachable(adj: Dict[str, List[str]], exclude: Optional[str]) -> set:
    """Set of nodes reachable from an arbitrary anchor, optionally removing one
    node (N-1). Uses the largest connected component as the 'served' set."""
    nodes = [n for n in adj if n != exclude]
    if not nodes:
        return set()
    seen = set()
    best = set()
    for start in nodes:
        if start in seen:
            continue
        comp, stack = set(), [start]
        while stack:
            x = stack.pop()
            if x in comp or x == exclude:
                continue
            comp.add(x)
            for nb in adj.get(x, []):
                if nb != exclude and nb not in comp:
                    stack.append(nb)
        seen |= comp
        if len(comp) > len(best):
            best = comp
    return best


def build() -> list:
    return [DeploymentSuccess(), RollbackProbability(), ConfigurationDrift(),
            OperatorError(), SecurityThreat(), CascadingFailure(), ChangeConflict(),
            BusinessImpact(), CustomerImpact(), ConfidenceDrift()]
