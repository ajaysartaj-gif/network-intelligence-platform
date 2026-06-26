"""
core/intelligence/forecasting/base.py
======================================
The substrate for ANTICIPATION — prediction as a first-class organ.

Reasoning (reasoning.py) asks "what is true now / what just happened". This
package asks the orthogonal question an autonomous engineer must answer to be
trusted: "what is about to happen, how sure am I, and how long do I have?"

Borrowing the shape of every serious forecasting discipline:
  • weather      → a probabilistic forecast with a horizon and a cone of
                   uncertainty, not a point claim.
  • aviation/ATC → a LEAD TIME (look-ahead): how long until the event, so there
                   is time to act before it happens.
  • medicine     → an early-warning SCORE combining weak signals, with a
                   recommended action keyed to severity.
  • finance      → calibration: a forecaster is only as good as its track record,
                   so every forecast is scored against reality and the raw signal
                   is shifted toward demonstrated accuracy.

A Forecaster is the prediction analogue of a Reasoner: self-describing,
registered, composable, and — crucially — SELF-IMPROVING. Each forecast is
logged when made and scored when the future arrives; the forecaster's reported
confidence becomes its real, measured reliability instead of an assertion.
"""
from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NetBrain.Intelligence.Forecasting")

# Convenience horizons (seconds).
HOUR = 3600.0
DAY = 24 * HOUR
WEEK = 7 * DAY
MONTH = 30 * DAY
QUARTER = 90 * DAY


class ForecastType(str, Enum):
    EVENT = "event"        # something will/won't happen → probability in [0,1]
    QUANTITY = "quantity"  # a value will reach X → value + threshold + ETA
    SCORE = "score"        # a composite risk score in [0,1]


@dataclass
class Driver:
    """One contributing signal behind a forecast — provenance for anticipation."""
    name: str
    contribution: float        # signed influence on the forecast [-1,1]
    detail: str = ""


@dataclass
class Forecast:
    target: str                       # what is predicted ("interface utilization")
    subject: str                      # about what ("R2 Gi0/0", "ospf", "vendor:cisco")
    kind: str                         # forecaster key
    ftype: str = ForecastType.EVENT.value
    horizon_s: float = DAY            # how far ahead this looks
    probability: Optional[float] = None   # for EVENT/SCORE
    value: Optional[float] = None         # for QUANTITY
    value_unit: str = ""
    threshold: Optional[float] = None     # the level that matters (for QUANTITY)
    lead_time_s: Optional[float] = None   # estimated time until the event/threshold
    confidence: float = 0.5               # calibrated reliability of THIS forecast
    severity: float = 0.3                 # expected impact if it happens [0,1]
    drivers: List[Driver] = field(default_factory=list)
    recommended_action: str = ""
    method: str = ""                      # borrowed technique used
    discipline: str = ""                  # discipline the method comes from
    resolve_key: str = ""                 # PredictionMemory key, set when logged
    made_ts: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def risk(self) -> float:
        """Expected risk = likelihood × impact (finance PD×LGD; medicine triage)."""
        p = self.probability if self.probability is not None else (
            self.value is not None and self.threshold and
            min(1.0, self.value / self.threshold) or 0.0)
        return round(float(p or 0.0) * float(self.severity), 4)

    def is_actionable(self, risk_threshold: float = 0.25) -> bool:
        return self.risk >= risk_threshold

    def lead_time_human(self) -> str:
        s = self.lead_time_s
        if s is None:
            return "unknown"
        if s < HOUR:
            return f"{s/60:.0f} min"
        if s < DAY:
            return f"{s/HOUR:.1f} h"
        return f"{s/DAY:.1f} d"

    def explain(self) -> str:
        head = f"{self.target} for {self.subject}: "
        if self.probability is not None:
            head += f"p={self.probability:.0%}"
        if self.value is not None:
            head += f" value≈{self.value:.1f}{self.value_unit}"
            if self.threshold:
                head += f" (threshold {self.threshold:.1f})"
        head += (f", lead {self.lead_time_human()}, conf {self.confidence:.0%},"
                 f" risk {self.risk:.0%}")
        lines = [head]
        for d in self.drivers:
            lines.append(f"   • {d.name} ({d.contribution:+.2f}) {d.detail}")
        if self.recommended_action:
            lines.append(f"   ↳ act: {self.recommended_action}")
        return "\n".join(lines)


@dataclass
class ForecasterSpec:
    key: str
    name: str
    question: str                      # the future question it answers
    ftype: ForecastType
    discipline: str = ""               # which forecasting field it borrows from
    default_horizon_s: float = DAY
    cost_hint: str = "low"
    maturity: str = "III"


class Forecaster(ABC):
    """Base class for every anticipatory faculty. Mirrors Reasoner's contract."""

    def __init__(self, spec: ForecasterSpec):
        self.spec = spec
        self._runs = 0
        self._errors = 0
        self._last_latency = 0.0

    # ── the anticipatory act ─────────────────────────────────────────────────
    @abstractmethod
    def _forecast(self, context: Dict[str, Any]) -> Optional[Forecast]:
        """Produce a Forecast (or None if nothing to predict)."""

    def forecast(self, context: Dict[str, Any], *, log: bool = True) -> Optional[Forecast]:
        """Public entry: time, calibrate against track record, log for scoring."""
        t0 = time.time()
        self._runs += 1
        try:
            f = self._forecast(context or {})
        except Exception as exc:
            self._errors += 1
            logger.debug(f"forecaster {self.spec.key} failed: {exc}")
            return None
        finally:
            self._last_latency = time.time() - t0
        if f is None:
            return None
        f.kind = self.spec.key
        f.ftype = f.ftype or self.spec.ftype.value
        f.discipline = f.discipline or self.spec.discipline
        f.made_ts = f.made_ts or time.time()
        if not f.horizon_s:
            f.horizon_s = self.spec.default_horizon_s
        self._calibrate(f)
        if log:
            self._log(f)
        return f

    # ── calibration from demonstrated accuracy (finance/weather) ─────────────
    def _calibrate(self, f: Forecast) -> None:
        """Shift the raw probability toward this forecaster's measured accuracy
        and set the reported confidence to its empirical reliability."""
        try:
            from core.intelligence.memory import get_memory_system
            trust = get_memory_system().trust
        except Exception:
            return
        domain = f"forecast:{self.spec.key}"
        raw = f.probability if f.probability is not None else f.confidence
        cal = trust.calibrate(domain, float(raw if raw is not None else 0.5))
        if f.probability is not None:
            f.probability = cal["calibrated"]
        # reliability = 1 - mean Brier; falls back to a modest prior pre-history.
        rel = self.reliability()
        f.confidence = round(rel if rel is not None else max(0.45, f.confidence), 4)
        f.metadata.setdefault("calibration", cal)

    def reliability(self) -> Optional[float]:
        try:
            from core.intelligence.memory import get_memory_system
            ex = get_memory_system().trust._by_key(f"forecast:{self.spec.key}")
            if not ex or int(ex.get("n") or 0) < 4:
                return None
            return round(float(ex.get("confidence") or 0.5), 4)
        except Exception:
            return None

    # ── logging so the future can grade it (closing the loop) ────────────────
    def _log(self, f: Forecast) -> None:
        try:
            from core.intelligence.memory import get_memory_system
            pm = get_memory_system().prediction
            p = f.probability if f.probability is not None else (f.risk or 0.5)
            key = pm.predict(f"{self.spec.key}:{f.subject}",
                             f"{f.target}: {f.metadata.get('claim', f.recommended_action or f.target)}",
                             float(p))
            f.resolve_key = key
        except Exception as exc:
            logger.debug(f"forecast log skipped: {exc}")

    # ── uniform inspection surface (mirrors Reasoner) ─────────────────────────
    def health(self) -> Dict[str, Any]:
        err = self._errors / max(1, self._runs)
        status = "active" if self._runs and err < 0.5 else ("partial" if not self._runs else "degraded")
        rel = self.reliability()
        return {"status": status, "runs": self._runs, "error_rate": round(err, 3),
                "reliability": rel, "key": self.spec.key}

    def metrics(self) -> Dict[str, Any]:
        return {"runs": self._runs, "errors": self._errors,
                "reliability": self.reliability(),
                "last_latency_ms": round(self._last_latency * 1000, 2),
                "discipline": self.spec.discipline, "maturity": self.spec.maturity}

    def tests(self) -> Dict[str, Any]:
        try:
            f = self.forecast({}, log=False)
            ok = f is None or isinstance(f, Forecast)
            rng = True if f is None else (
                (f.probability is None or 0.0 <= f.probability <= 1.0) and
                0.0 <= f.confidence <= 1.0 and 0.0 <= f.severity <= 1.0)
            return {"passed": ok and rng, "checks": {"returns_forecast": ok,
                                                      "ranges_valid": rng}}
        except Exception as exc:
            return {"passed": False, "checks": {"callable": False}, "error": str(exc)}


class ForecastRegistry:
    """Where anticipatory faculties register and the forecast board is assembled."""

    def __init__(self):
        self._fc: Dict[str, Forecaster] = {}

    def register(self, fc: Forecaster) -> None:
        self._fc[fc.spec.key] = fc

    def get(self, key: str) -> Optional[Forecaster]:
        return self._fc.get(key)

    def all(self) -> List[Forecaster]:
        return list(self._fc.values())

    def forecast(self, key: str, context: Dict[str, Any]) -> Optional[Forecast]:
        fc = self._fc.get(key)
        return fc.forecast(context) if fc else None

    def run_self_tests(self) -> Dict[str, Any]:
        res = {k: f.tests() for k, f in self._fc.items()}
        passed = sum(1 for v in res.values() if v.get("passed"))
        return {"total": len(res), "passed": passed,
                "all_passed": passed == len(res), "detail": res}

    def report(self) -> List[Dict[str, Any]]:
        return [{"key": f.spec.key, "name": f.spec.name, "question": f.spec.question,
                 "discipline": f.spec.discipline, "health": f.health(),
                 "maturity": f.spec.maturity} for f in self._fc.values()]
