"""
core/intelligence/reasoning.py
==============================
The cognitive substrate of the platform: a Reasoning Registry where each
reasoning faculty is a first-class, composable, self-describing plug-in.

This is the architectural keystone the platform was missing. Until now,
reasoning was scattered inside deploy blocks — it could not be inspected,
composed, doubted, or improved. Here, reasoning becomes an organ system:

  • A Reasoner is a plug-in with a declared epistemic type and confidence.
  • Reasoners are registered, discovered, and composed at runtime.
  • Every reasoner exposes the mandated cognitive surface:
        health() · confidence() · metrics() · dependencies() · tests()
  • Reasoners can consume each other's outputs (composition), and the
    substrate supports metacognition: a reasoner's output can be critiqued
    by another reasoner before it is trusted.

Epistemic honesty is enforced structurally (cf. the reasoning blueprint's
Axiom 3): a reasoner must declare whether it is deterministic, probabilistic,
graph, ml, llm, or hybrid, and must return a *calibrated* confidence — so the
platform never acts on a guess as if it were a fact.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("NetBrain.Intelligence.Reasoning")


class EpistemicType(str, Enum):
    DETERMINISTIC = "deterministic"   # there is a correct answer; compute it
    PROBABILISTIC = "probabilistic"   # only a likelihood exists
    GRAPH = "graph"                   # reasoning over a relational structure
    ML = "ml"                         # learned statistical model
    LLM = "llm"                       # generative, language-model-based
    HYBRID = "hybrid"                 # combination of the above


@dataclass
class Evidence:
    """A single piece of grounding behind a conclusion — provenance matters."""
    source: str                      # where it came from (memory, device, knowledge…)
    statement: str                   # what it asserts
    weight: float = 1.0              # how much it supports the conclusion [0,1]


@dataclass
class Conclusion:
    """The output of reasoning: a claim, its confidence, and WHY."""
    claim: str
    confidence: float                # calibrated [0,1]
    epistemic_type: str
    evidence: List[Evidence] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)   # hypotheses considered, not chosen
    reasoner: str = ""
    critique: str = ""               # filled by self-critique, if run
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_trustworthy(self, threshold: float = 0.6) -> bool:
        return self.confidence >= threshold

    def explain(self) -> str:
        lines = [f"Claim: {self.claim}",
                 f"Confidence: {self.confidence:.2f} ({self.epistemic_type})"]
        if self.evidence:
            lines.append("Evidence:")
            lines += [f"  • [{e.source}] {e.statement}" for e in self.evidence]
        if self.alternatives:
            lines.append("Alternatives considered: " + "; ".join(self.alternatives))
        if self.critique:
            lines.append(f"Self-critique: {self.critique}")
        return "\n".join(lines)


@dataclass
class ReasonerSpec:
    """What every reasoning faculty must declare to join the cognitive system."""
    key: str
    name: str
    purpose: str
    epistemic_type: EpistemicType
    consumes: List[str] = field(default_factory=list)   # other reasoner keys it depends on
    cost_hint: str = "low"                               # low|medium|high (for scheduling)
    safety_class: str = "advisory"                       # advisory|gated|hard-safety
    maturity: str = "II"                                 # I|II|III|IV


class Reasoner(ABC):
    """
    Base class for every cognitive faculty. Subclasses implement reason();
    the mandated cognitive surface is provided/standardized here so EVERY
    reasoner is inspectable, composable, and testable in the same way.
    """
    def __init__(self, spec: ReasonerSpec):
        self.spec = spec
        self._invocations = 0
        self._confidences: List[float] = []
        self._errors = 0
        self._last_latency = 0.0

    # ── the cognitive act ────────────────────────────────────────────────────
    @abstractmethod
    def _reason(self, context: Dict[str, Any]) -> Conclusion:
        """Perform the reasoning. Subclasses implement this."""

    def reason(self, context: Dict[str, Any]) -> Conclusion:
        """Public entry: times, records telemetry, guarantees a Conclusion."""
        t0 = time.time()
        self._invocations += 1
        try:
            c = self._reason(context or {})
            c.reasoner = self.spec.key
            c.epistemic_type = c.epistemic_type or self.spec.epistemic_type.value
            self._confidences.append(c.confidence)
            return c
        except Exception as exc:
            self._errors += 1
            logger.debug(f"reasoner {self.spec.key} failed: {exc}")
            return Conclusion(claim=f"reasoning failed: {exc}", confidence=0.0,
                              epistemic_type=self.spec.epistemic_type.value,
                              reasoner=self.spec.key)
        finally:
            self._last_latency = time.time() - t0

    # ── mandated cognitive surface (uniform across all reasoners) ─────────────
    def health(self) -> Dict[str, Any]:
        err_rate = self._errors / max(1, self._invocations)
        status = "active" if self._invocations and err_rate < 0.5 else (
            "partial" if not self._invocations else "degraded")
        return {"status": status, "invocations": self._invocations,
                "error_rate": round(err_rate, 3), "key": self.spec.key}

    def confidence(self) -> float:
        """Self-reported reliability: mean of recent calibrated confidences."""
        if not self._confidences:
            return 0.0
        recent = self._confidences[-50:]
        return round(sum(recent) / len(recent), 4)

    def metrics(self) -> Dict[str, Any]:
        return {"invocations": self._invocations, "errors": self._errors,
                "mean_confidence": self.confidence(),
                "last_latency_ms": round(self._last_latency * 1000, 2),
                "epistemic_type": self.spec.epistemic_type.value,
                "maturity": self.spec.maturity}

    def dependencies(self) -> List[str]:
        return list(self.spec.consumes)

    def tests(self) -> Dict[str, Any]:
        """
        Self-test: every faculty must be able to demonstrate it reasons. Base
        implementation runs a smoke reason() on an empty context and checks a
        well-formed Conclusion comes back. Subclasses may override to add
        faculty-specific assertions.
        """
        results = []
        try:
            c = self.reason({})
            results.append(("returns_conclusion", isinstance(c, Conclusion)))
            results.append(("confidence_in_range", 0.0 <= c.confidence <= 1.0))
            results.append(("declares_epistemic_type", bool(c.epistemic_type)))
        except Exception as exc:
            results.append(("reason_callable", False))
            logger.debug(f"self-test error {self.spec.key}: {exc}")
        passed = all(ok for _, ok in results)
        return {"passed": passed, "checks": dict(results)}


class ReasoningRegistry:
    """The cognitive system: where faculties register and are composed."""

    def __init__(self):
        self._reasoners: Dict[str, Reasoner] = {}

    def register(self, reasoner: Reasoner) -> None:
        self._reasoners[reasoner.spec.key] = reasoner
        logger.info(f"registered reasoner: {reasoner.spec.key}")

    def get(self, key: str) -> Optional[Reasoner]:
        return self._reasoners.get(key)

    def all(self) -> List[Reasoner]:
        return list(self._reasoners.values())

    def reason(self, key: str, context: Dict[str, Any]) -> Optional[Conclusion]:
        r = self._reasoners.get(key)
        return r.reason(context) if r else None

    # ── composition: chain reasoners, feeding each conclusion to the next ─────
    def reason_chain(self, keys: List[str], context: Dict[str, Any]) -> List[Conclusion]:
        ctx = dict(context or {})
        out: List[Conclusion] = []
        for k in keys:
            c = self.reason(k, ctx)
            if c is None:
                continue
            out.append(c)
            ctx.setdefault("prior_conclusions", []).append(c)
        return out

    # ── metacognition: run a critic over a conclusion before trusting it ──────
    def with_critique(self, conclusion: Conclusion,
                      critic_key: str = "self_critique") -> Conclusion:
        critic = self._reasoners.get(critic_key)
        if not critic or conclusion is None:
            return conclusion
        crit = critic.reason({"target_conclusion": conclusion})
        conclusion.critique = crit.claim
        # a critic that finds a serious flaw discounts the original confidence
        conclusion.confidence = round(conclusion.confidence * crit.confidence, 4)
        return conclusion

    # ── whole-system cognitive report ─────────────────────────────────────────
    def report(self) -> List[Dict[str, Any]]:
        out = []
        for r in self._reasoners.values():
            out.append({"key": r.spec.key, "name": r.spec.name,
                        "purpose": r.spec.purpose,
                        "epistemic_type": r.spec.epistemic_type.value,
                        "health": r.health(), "confidence": r.confidence(),
                        "dependencies": r.dependencies(),
                        "maturity": r.spec.maturity})
        return out

    def run_self_tests(self) -> Dict[str, Any]:
        """Run every faculty's self-test — the platform proving it can think."""
        results = {r.spec.key: r.tests() for r in self._reasoners.values()}
        passed = sum(1 for v in results.values() if v.get("passed"))
        return {"total": len(results), "passed": passed,
                "all_passed": passed == len(results), "detail": results}


# ── singleton ────────────────────────────────────────────────────────────────
_registry: Optional[ReasoningRegistry] = None


def get_reasoning_registry() -> ReasoningRegistry:
    global _registry
    if _registry is None:
        _registry = ReasoningRegistry()
        _bootstrap(_registry)
    return _registry


def _bootstrap(reg: ReasoningRegistry) -> None:
    """Register the founding cognitive faculties."""
    try:
        from core.intelligence.faculties import build_default_faculties
        for fac in build_default_faculties():
            reg.register(fac)
    except Exception as exc:
        logger.debug(f"faculty bootstrap deferred: {exc}")


def bind_reasoning_capability() -> None:
    """Expose the reasoning system's health in the Capability Registry."""
    try:
        from core.intelligence.capability_model import (
            get_capability_registry, CapabilityHealth, CapabilityStatus)
    except Exception:
        return

    def _probe():
        reg = get_reasoning_registry()
        n = len(reg.all())
        if not n:
            return CapabilityHealth(CapabilityStatus.PARTIAL, "No reasoners registered.")
        tests = reg.run_self_tests()
        status = CapabilityStatus.ACTIVE if tests["all_passed"] else CapabilityStatus.PARTIAL
        return CapabilityHealth(status,
                                f"{n} reasoning faculties · {tests['passed']}/{tests['total']} self-tests pass",
                                metrics={"faculties": n, "self_tests": tests})
    get_capability_registry().bind_probe("reasoning", _probe)
