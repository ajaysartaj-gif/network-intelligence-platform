"""
core/intelligence/autonomy/base.py
===================================
The substrate for SELF-DIRECTION.

Automation runs a fixed script. Autonomy decides — for itself — what to do, in
what order, whether now is the right time, whether it is allowed, whether it
worked, and what to change next time. The faculties that make that difference
are modelled here as first-class, inspectable units (the same discipline as
Reasoner and Forecaster), and they are governed by three hard structures that
keep self-direction SAFE:

  • the AUTONOMY LADDER — a graduated scale from OBSERVE to FULL. The platform
    never assumes a rung; it EARNS each one, per domain, from demonstrated
    competence and calibration, and never climbs above a configured ceiling.
    Authority is granted, not taken.

  • GOALS — standing objectives with priority and success criteria, so the
    system pursues outcomes instead of merely reacting to the last event.

  • POLICY + DECISIONS — every proposed action passes a policy envelope and
    returns a Decision (ALLOW / GATE / DENY) with reasons. When in doubt, the
    safe verdict wins. This is what makes "more autonomous" compatible with
    "remaining safe".

The control loop that composes these (controller.py) is the classic autonomic-
computing MAPE-K loop — Monitor, Analyze, Plan, Execute over shared Knowledge —
the reference model for self-managing systems.
"""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NetBrain.Intelligence.Autonomy")


# ── the autonomy ladder ──────────────────────────────────────────────────────
class AutonomyLevel(IntEnum):
    OBSERVE = 0             # watch and report only
    RECOMMEND = 1           # propose actions for a human to take
    APPROVE_GATED = 2       # may act, but every change needs human approval
    BOUNDED_AUTONOMOUS = 3  # may act alone within strict risk/resource bounds
    FULL = 4               # may act alone (still inside the policy envelope)

    @classmethod
    def parse(cls, s: str) -> "AutonomyLevel":
        s = (s or "").strip().lower()
        return {
            "observe": cls.OBSERVE, "recommend": cls.RECOMMEND,
            "approve_gated": cls.APPROVE_GATED, "gated": cls.APPROVE_GATED,
            "bounded": cls.BOUNDED_AUTONOMOUS, "bounded_autonomous": cls.BOUNDED_AUTONOMOUS,
            "full": cls.FULL,
        }.get(s, cls.APPROVE_GATED)


# The configured CEILING — autonomy can never exceed this regardless of how much
# competence is earned. Defaults to APPROVE_GATED: safe out of the box.
def autonomy_ceiling() -> AutonomyLevel:
    return AutonomyLevel.parse(os.environ.get("NETBRAIN_AUTONOMY_MAX", "approve_gated"))


class Verdict(str, Enum):
    ALLOW = "allow"             # proceed autonomously
    GATE = "gate"               # allowed only with human approval
    DENY = "deny"               # must not happen now


@dataclass
class Goal:
    key: str
    description: str
    priority: float = 0.5              # 0..1, higher = more important
    target: str = ""                   # what it concerns (domain/device/site)
    success_metric: str = ""           # how we know it's met
    status: str = "open"               # open | progressing | met | at_risk
    progress: float = 0.0              # 0..1
    last_update: float = field(default_factory=time.time)


@dataclass
class Action:
    """A proposed unit of work the controller may authorize."""
    kind: str                          # e.g. "config_change", "rollback", "internal_recovery", "observe"
    intent: str = ""
    device: str = ""
    protocol: str = ""
    site: str = ""
    operator: str = ""
    changes_state: bool = True         # does it modify the network?
    internal: bool = False             # an action on the platform itself, not the net
    risk: float = 0.0                  # filled by the controller from forecasting
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    verdict: Verdict
    reasons: List[str] = field(default_factory=list)
    level: AutonomyLevel = AutonomyLevel.APPROVE_GATED
    risk: float = 0.0
    requires_approval: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.verdict == Verdict.ALLOW

    def explain(self) -> str:
        return (f"{self.verdict.value.upper()} (level={self.level.name}, "
                f"risk={self.risk:.0%}): " + "; ".join(self.reasons))


# ── faculty base ─────────────────────────────────────────────────────────────
@dataclass
class FacultySpec:
    key: str
    name: str
    purpose: str
    cost_hint: str = "low"


class AutonomyFaculty(ABC):
    """Base for every self-* faculty: self-describing, inspectable, uniform."""

    def __init__(self, spec: FacultySpec):
        self.spec = spec
        self._runs = 0
        self._errors = 0
        self._last = 0.0

    @abstractmethod
    def _run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        ...

    def run(self, ctx: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.time()
        self._runs += 1
        try:
            out = self._run(ctx or {})
            return out if isinstance(out, dict) else {"result": out}
        except Exception as exc:
            self._errors += 1
            logger.debug(f"faculty {self.spec.key} failed: {exc}")
            return {"error": str(exc)}
        finally:
            self._last = time.time() - t0

    def health(self) -> Dict[str, Any]:
        err = self._errors / max(1, self._runs)
        status = "active" if self._runs and err < 0.5 else ("partial" if not self._runs else "degraded")
        return {"key": self.spec.key, "status": status, "runs": self._runs,
                "error_rate": round(err, 3), "last_latency_ms": round(self._last * 1000, 2)}


class FacultyRegistry:
    def __init__(self):
        self._f: Dict[str, AutonomyFaculty] = {}

    def register(self, f: AutonomyFaculty) -> None:
        self._f[f.spec.key] = f

    def get(self, key: str) -> Optional[AutonomyFaculty]:
        return self._f.get(key)

    def all(self) -> List[AutonomyFaculty]:
        return list(self._f.values())

    def report(self) -> List[Dict[str, Any]]:
        return [{"key": f.spec.key, "name": f.spec.name, "purpose": f.spec.purpose,
                 "health": f.health()} for f in self._f.values()]
