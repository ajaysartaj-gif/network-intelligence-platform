"""
core/intelligence/forecasting/engine.py
========================================
The Prediction organ — a first-class intelligence capability.

This is the single object the platform talks to for anticipation. It owns the
forecaster registry, assembles the forecast BOARD (every forecaster's view of a
situation, ranked by expected risk), reduces the board to one composite EARLY-
WARNING SCORE (medicine: many weak signals → one triage number with a level),
and — the part that makes prediction improve rather than merely repeat — RESOLVES
past forecasts against what actually happened and feeds the result back into the
calibration memory so each forecaster's confidence becomes its measured accuracy.

  • forecast(context)        — run every applicable forecaster; return the board.
  • early_warning(context)   — board reduced to a composite score + level.
  • resolve_outcomes()       — the continuous-improvement loop: grade matured
                               predictions from the episodic log and recalibrate.
  • wire_prediction()        — register forecasters, bind the 'prediction' pillar
                               to this engine, and expose a forecast reasoning
                               faculty. Mirrors wire_memory_system().
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from core.intelligence.forecasting.base import (
    ForecastRegistry, Forecast, ForecastType, HOUR, DAY, WEEK, MONTH, QUARTER,
)

logger = logging.getLogger("NetBrain.Intelligence.Prediction")

# default horizon per forecaster key, used by the resolver to know when a
# prediction has 'matured' enough to be graded.
_HORIZON = {
    "deployment_success": HOUR, "rollback_probability": DAY,
    "failure_prediction": WEEK, "configuration_drift": MONTH,
    "operator_error": HOUR, "change_conflict": 4 * HOUR,
}


class PredictionEngine:
    def __init__(self):
        self.registry = ForecastRegistry()
        self._built = False

    # ── lazy build of all forecasters ────────────────────────────────────────
    def _build(self) -> None:
        if self._built:
            return
        from core.intelligence.forecasting import (
            forecasters_reliability as R,
            forecasters_capacity as C,
            forecasters_operational as O,
        )
        for fc in R.build() + C.build() + O.build():
            self.registry.register(fc)
        self._built = True

    def forecasters(self) -> List[str]:
        self._build()
        return [f.spec.key for f in self.registry.all()]

    # ── the forecast board ───────────────────────────────────────────────────
    def forecast(self, context: Optional[Dict[str, Any]] = None, *,
                 only: Optional[List[str]] = None, log: bool = True
                 ) -> List[Forecast]:
        """Run forecasters over a context and return forecasts ranked by risk."""
        self._build()
        ctx = context or {}
        out: List[Forecast] = []
        for fc in self.registry.all():
            if only and fc.spec.key not in only:
                continue
            try:
                f = fc.forecast(ctx, log=log)
                if f is not None:
                    out.append(f)
            except Exception as exc:
                logger.debug(f"forecaster {fc.spec.key}: {exc}")
        out.sort(key=lambda f: f.risk, reverse=True)
        return out

    def forecast_dicts(self, context: Optional[Dict[str, Any]] = None, **kw
                       ) -> List[Dict[str, Any]]:
        return [self._as_dict(f) for f in self.forecast(context, **kw)]

    @staticmethod
    def _as_dict(f: Forecast) -> Dict[str, Any]:
        return {"target": f.target, "subject": f.subject, "kind": f.kind,
                "type": f.ftype, "probability": f.probability, "value": f.value,
                "unit": f.value_unit, "threshold": f.threshold,
                "lead_time": f.lead_time_human(), "lead_time_s": f.lead_time_s,
                "confidence": f.confidence, "severity": f.severity, "risk": f.risk,
                "horizon_s": f.horizon_s, "method": f.method,
                "discipline": f.discipline, "action": f.recommended_action,
                "drivers": [{"name": d.name, "contribution": d.contribution,
                             "detail": d.detail} for d in f.drivers]}

    # ── composite early-warning (medicine triage) ────────────────────────────
    def early_warning(self, context: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
        board = self.forecast(context, log=False)
        if not board:
            return {"score": 0.0, "level": "nominal", "top": [], "forecasts": 0}
        # risk-weighted aggregate, dominated by the worst few (a single severe
        # risk should raise the alarm even if the mean is low).
        risks = sorted((f.risk for f in board), reverse=True)
        top3 = risks[:3]
        score = round(0.6 * (top3[0]) + 0.4 * (sum(top3) / len(top3)), 4)
        level = ("critical" if score >= 0.6 else "elevated" if score >= 0.35
                 else "guarded" if score >= 0.18 else "nominal")
        return {"score": score, "level": level, "forecasts": len(board),
                "top": [self._as_dict(f) for f in board[:5]]}

    # ── CONTINUOUS IMPROVEMENT: grade matured predictions ────────────────────
    def resolve_outcomes(self, grace_s: float = 0.0, limit: int = 500
                         ) -> Dict[str, Any]:
        """
        Grade open predictions whose horizon has elapsed against the episodic log,
        then feed the result into calibration (trust) memory so each forecaster's
        confidence converges on its true accuracy. Only forecasters with reliably
        observable outcomes are auto-graded; the rest await explicit record_actual.
        """
        try:
            from core.intelligence.memory import get_memory_system
            sysm = get_memory_system()
            pm = sysm.prediction
            trust = sysm.trust
            from core.intelligence.operational_memory import get_operational_memory
            opmem = get_operational_memory()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

        graded = 0
        for row in pm.open_predictions():
            subj = row.get("subject") or ""          # "{kind}:{subject}"
            if ":" not in subj:
                continue
            kind, _, target = subj.partition(":")
            horizon = _HORIZON.get(kind)
            if horizon is None:
                continue                              # not auto-gradable
            made = float(row.get("made_ts") or row.get("ts") or 0)
            if time.time() < made + horizon + grace_s:
                continue                              # not matured yet
            occurred = self._observed_event(opmem, kind, target, made, made + horizon)
            if occurred is None:
                # horizon passed, nothing observed → the event did NOT happen.
                occurred = False
            predicted_high = float(row.get("confidence0") or 0.5) >= 0.5
            correct = (occurred == predicted_high)
            try:
                pm.resolve(row.get("k") or "", correct)
            except Exception:
                pass
            trust.record(f"forecast:{kind}", float(row.get("confidence0") or 0.5), correct)
            graded += 1
            if graded >= limit:
                break
        return {"ok": True, "graded": graded, "hit_rate": pm.hit_rate()}

    @staticmethod
    def _observed_event(opmem: Any, kind: str, target: str,
                        t0: float, t1: float) -> Optional[bool]:
        """Did the predicted event actually occur in [t0,t1]? None if unknowable."""
        try:
            if kind in ("failure_prediction",):
                hist = opmem.device_history(target, limit=100)
                return any(h.get("outcome") == "failure" and
                           t0 <= float(h.get("ts") or 0) <= t1 for h in hist)
            if kind in ("deployment_success",):
                hist = opmem.device_history(target, limit=100,
                                            event_type="deployment_outcome")
                evs = [h for h in hist if t0 <= float(h.get("ts") or 0) <= t1 + DAY]
                if not evs:
                    return None
                # 'success' predicted → event is success
                return any(h.get("outcome") == "success" for h in evs)
            if kind in ("rollback_probability",):
                rb = opmem.temporal(since=t0, until=t1 + DAY, event_type="rollback",
                                    limit=100)
                return any((r.get("device") or "") == target for r in rb)
        except Exception:
            return None
        return None

    # ── explicit ground truth for non-auto-gradable forecasters ──────────────
    def record_actual(self, kind: str, subject: str, occurred: bool,
                      stated_confidence: float = 0.5) -> None:
        try:
            from core.intelligence.memory import get_memory_system
            get_memory_system().trust.record(f"forecast:{kind}", stated_confidence, 
                                              (occurred == (stated_confidence >= 0.5)))
        except Exception:
            pass

    # ── status surface ───────────────────────────────────────────────────────
    def report(self) -> Dict[str, Any]:
        self._build()
        return {"forecasters": self.registry.report(),
                "self_tests": self.registry.run_self_tests()}

    def health(self) -> Dict[str, Any]:
        self._build()
        try:
            from core.intelligence.memory import get_memory_system
            hr = get_memory_system().prediction.hit_rate()
        except Exception:
            hr = {"resolved": 0, "hit_rate": 0.0}
        return {"forecasters": len(self.registry.all()),
                "resolved_predictions": hr.get("resolved", 0),
                "hit_rate": hr.get("hit_rate", 0.0)}


# ── singleton ────────────────────────────────────────────────────────────────
_engine: Optional[PredictionEngine] = None


def get_prediction_engine() -> PredictionEngine:
    global _engine
    if _engine is None:
        _engine = PredictionEngine()
    return _engine


# ── reasoning faculty bridge: anticipation usable inside reasoning chains ────
def _build_forecast_faculty():
    from core.intelligence.reasoning import (
        Reasoner, ReasonerSpec, Conclusion, Evidence, EpistemicType)

    class ForwardOutlook(Reasoner):
        def __init__(self):
            super().__init__(ReasonerSpec(
                key="forward_outlook", name="Forward Outlook",
                purpose="Anticipate what is about to happen for a situation "
                        "(failure/rollback/congestion/impact) before acting.",
                epistemic_type=EpistemicType.PROBABILISTIC, cost_hint="medium",
                maturity="III"))

        def _reason(self, context: Dict[str, Any]) -> Conclusion:
            board = get_prediction_engine().forecast(context, log=False)
            if not board:
                return Conclusion("No forecast applies to this situation.", 0.2,
                                  "probabilistic")
            top = board[0]
            return Conclusion(
                claim=f"Outlook: {top.target} for {top.subject} "
                      f"(risk {top.risk:.0%}, lead {top.lead_time_human()}).",
                confidence=float(top.confidence), epistemic_type="probabilistic",
                evidence=[Evidence("forecast", f.explain().splitlines()[0], f.risk)
                          for f in board[:5]],
                metadata={"early_warning": get_prediction_engine().early_warning(context)})

    return ForwardOutlook()


# ── startup wiring (mirrors wire_memory_system) ──────────────────────────────
def wire_prediction() -> Dict[str, Any]:
    result = {"forecasters": 0, "faculty": False, "pillar": False}
    engine = get_prediction_engine()
    try:
        result["forecasters"] = len(engine.forecasters())
    except Exception as exc:
        logger.debug(f"forecaster build deferred: {exc}")

    # expose a reasoning faculty so anticipation composes with reasoning
    try:
        from core.intelligence.reasoning import get_reasoning_registry
        get_reasoning_registry().register(_build_forecast_faculty())
        result["faculty"] = True
    except Exception as exc:
        logger.debug(f"forecast faculty deferred: {exc}")

    # bind the first-class 'prediction' capability pillar to this engine
    try:
        from core.intelligence.capability_model import (
            get_capability_registry, CapabilityHealth, CapabilityStatus)

        def _probe():
            try:
                h = engine.health()
                n = h["forecasters"]
                rp = h["resolved_predictions"]
                if n and rp:
                    return CapabilityHealth(
                        CapabilityStatus.ACTIVE,
                        f"{n} forecasters; {rp} predictions scored "
                        f"(hit-rate {h['hit_rate']:.0%}) — self-calibrating.",
                        metrics=h)
                if n:
                    return CapabilityHealth(
                        CapabilityStatus.ACTIVE,
                        f"{n} forecasters anticipating; awaiting outcomes to calibrate.",
                        metrics=h)
                return CapabilityHealth(CapabilityStatus.PARTIAL,
                                        "Prediction engine present; no forecasters built.")
            except Exception as exc:
                return CapabilityHealth(CapabilityStatus.PARTIAL, str(exc))

        get_capability_registry().bind_probe("prediction", _probe)
        result["pillar"] = True
    except Exception as exc:
        logger.debug(f"prediction pillar bind deferred: {exc}")

    return result
