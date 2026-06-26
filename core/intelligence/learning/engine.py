"""
core/intelligence/learning/engine.py
=====================================
The Learning Engine — the organization's single learning loop.

Two entry points carry the whole promise:

  • learn_from(event)  — the UNIVERSAL FUNNEL. Every workflow calls this once,
    after every deployment, incident, action, verification and operator
    interaction. It fans the event out to every learner, so a single success or
    failure improves knowledge, memory, reasoning, prediction, decision, risk,
    execution, confidence, trust AND planning at once. This is what makes the
    claim literal: every X improves the platform.

  • retrospect()       — the AFTER-ACTION REVIEW. Periodically (and cheaply) it
    mines the entire corpus for what only emerges at scale: new patterns,
    repeated mistakes, and proven strategies — writing them as validated,
    institutional lessons. This is the fifteen-year compounding: the platform
    that has run longer has read more of its own history.

Lessons are queryable (lessons / recall) and are surfaced back into live
reasoning through the LessonRecall faculty, and into knowledge retrieval through
as_documents() — improving the platform continuously, without retraining the LLM.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from core.intelligence.learning.base import (
    LessonStore, Lesson, LessonType, LearningEvent, Corpus,
)
from core.intelligence.learning.learners import build_learners

logger = logging.getLogger("NetBrain.Intelligence.Learning")


class LearningEngine:
    def __init__(self):
        self.store = LessonStore()
        self.learners = build_learners(self.store)
        self._by_key = {l.spec.key: l for l in self.learners}
        self._events_seen = 0
        self._last_retrospect = 0.0

    # ── the universal funnel ─────────────────────────────────────────────────
    def learn_from(self, event: LearningEvent) -> Dict[str, Any]:
        self._events_seen += 1
        emitted: List[str] = []
        for learner in self.learners:
            try:
                emitted += learner.observe(event)
            except Exception as exc:
                logger.debug(f"learner {learner.spec.key} observe: {exc}")
        return {"event": event.kind, "lessons_emitted": len(emitted)}

    def learn_from_contract(self, contract: Any, *, site: str = "",
                            protocol: str = "", operator: str = "",
                            commands: Optional[List[str]] = None,
                            stated_confidence: float = 0.0,
                            resolution_time_s: Optional[float] = None,
                            operator_action: str = "",
                            metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Adapter: feed a verified OutcomeContract straight into learning,
        mirroring memory.record_from_contract so the same hook serves both."""
        conds = []
        for c in getattr(contract, "conditions", []) or []:
            verdict = getattr(getattr(c, "verdict", None), "value", None)
            conds.append({"description": getattr(c, "description", ""),
                          "check_command": getattr(c, "check_command", ""),
                          "verdict": verdict, "reason": getattr(c, "reason", "")})
        ev = LearningEvent(
            kind="deployment",
            success=bool(getattr(contract, "satisfied", False)),
            intent=getattr(contract, "intent", "") or "",
            device=getattr(contract, "device", "") or "",
            protocol=protocol, site=site, operator=operator,
            commands=commands or [], conditions=conds,
            signature=getattr(contract, "signature", "") or "",
            stated_confidence=stated_confidence,
            resolution_time_s=resolution_time_s, operator_action=operator_action,
            metadata=metadata or {})
        return self.learn_from(ev)

    # ── the after-action review ──────────────────────────────────────────────
    def retrospect(self, window_s: float = 365 * 24 * 3600,
                   limit: int = 2000) -> Dict[str, Any]:
        self._last_retrospect = time.time()
        corpus = Corpus(window_s=window_s, limit=limit)
        summary: Dict[str, Any] = {}
        for learner in self.learners:
            try:
                res = learner.retrospect(corpus)
                if res:
                    summary[learner.spec.key] = res
            except Exception as exc:
                logger.debug(f"learner {learner.spec.key} retrospect: {exc}")
        summary["corpus_events"] = len(corpus.events())
        summary["lessons_after"] = self.store.count()
        return summary

    def maybe_retrospect(self, min_interval_s: float = 6 * 3600) -> Optional[Dict[str, Any]]:
        if time.time() - self._last_retrospect < min_interval_s:
            return None
        return self.retrospect()

    # ── institutional knowledge access ───────────────────────────────────────
    def lessons(self, query: str, top_k: int = 5, lesson_type: str = "",
                scope: str = "", validated_only: bool = False) -> List[Dict[str, Any]]:
        return self.store.recall(query, top_k=top_k, lesson_type=lesson_type,
                                 scope=scope, validated_only=validated_only)

    def mistakes(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.store.of_type(LessonType.MISTAKE.value, limit=limit)

    def strategies(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self.store.of_type(LessonType.STRATEGY.value, limit=limit)

    def as_documents(self, limit: int = 200) -> List[Dict[str, str]]:
        kl = self._by_key.get("knowledge_learner")
        return kl.as_documents(limit=limit) if kl else []

    def digest(self) -> Dict[str, Any]:
        return {"events_seen": self._events_seen,
                "last_retrospect": self._last_retrospect,
                "lessons": self.store.digest(),
                "learners": [l.health() for l in self.learners]}

    def health(self) -> Dict[str, Any]:
        d = self.store.digest()
        return {"lessons_total": d.get("total", 0),
                "lessons_validated": d.get("validated", 0),
                "events_seen": self._events_seen,
                "learners": len(self.learners)}


# ── singleton ────────────────────────────────────────────────────────────────
_engine: Optional[LearningEngine] = None


def get_learning_engine() -> LearningEngine:
    global _engine
    if _engine is None:
        _engine = LearningEngine()
    return _engine


def learn_from(event: LearningEvent) -> Dict[str, Any]:
    return get_learning_engine().learn_from(event)


# ── reasoning bridge: live reasoning consults institutional lessons ──────────
def _build_lesson_faculty():
    from core.intelligence.reasoning import (
        Reasoner, ReasonerSpec, Conclusion, Evidence, EpistemicType)

    class LessonRecall(Reasoner):
        def __init__(self):
            super().__init__(ReasonerSpec(
                key="lesson_recall", name="Lesson Recall",
                purpose="Recall validated institutional lessons (patterns, "
                        "mistakes, strategies) relevant to the situation.",
                epistemic_type=EpistemicType.HYBRID, cost_hint="low", maturity="III"))

        def _reason(self, context: Dict[str, Any]) -> Conclusion:
            q = context.get("symptoms") or context.get("intent") or context.get("query") or ""
            if not q:
                return Conclusion("No situation to recall lessons for.", 0.0, "hybrid")
            hits = get_learning_engine().lessons(q, top_k=5)
            if not hits:
                return Conclusion("No institutional lesson applies yet.", 0.15, "hybrid")
            top = hits[0]
            return Conclusion(
                claim=f"Institutional lesson [{top.get('lesson_type')}]: "
                      f"{top.get('summary','')}",
                confidence=float(top.get("confidence") or 0.5),
                epistemic_type="hybrid",
                evidence=[Evidence("lesson", h.get("summary", ""),
                                   h.get("weight", 0.4)) for h in hits],
                alternatives=[h.get("summary", "") for h in hits[1:]],
                metadata={"lessons": hits})

    return LessonRecall()


# ── startup wiring (mirrors wire_memory_system / wire_prediction) ────────────
def wire_learning() -> Dict[str, Any]:
    result = {"learners": 0, "faculty": False, "pillars": []}
    engine = get_learning_engine()
    result["learners"] = len(engine.learners)

    # surface lessons inside reasoning
    try:
        from core.intelligence.reasoning import get_reasoning_registry
        get_reasoning_registry().register(_build_lesson_faculty())
        result["faculty"] = True
    except Exception as exc:
        logger.debug(f"lesson faculty deferred: {exc}")

    # capability pillars
    try:
        from core.intelligence.capability_model import (
            get_capability_registry, Capability, CapabilityHealth, CapabilityStatus)
        reg = get_capability_registry()

        def _learning_probe():
            h = engine.health()
            n = h["lessons_total"]
            if n:
                return CapabilityHealth(
                    CapabilityStatus.ACTIVE,
                    f"Organizational learning: {n} institutional lessons "
                    f"({h['lessons_validated']} validated) from {h['events_seen']} events.",
                    metrics=h)
            return CapabilityHealth(
                CapabilityStatus.PARTIAL,
                "Learning loop wired; no lessons accumulated yet.", metrics=h)
        reg.bind_probe("learning", _learning_probe)
        result["pillars"].append("learning")

        def _il_probe():
            h = engine.health()
            return CapabilityHealth(
                CapabilityStatus.ACTIVE if h["lessons_total"] else CapabilityStatus.PARTIAL,
                f"Lessons-learned registry across {h['learners']} learners; "
                f"discovers patterns, names repeated mistakes, promotes strategies.",
                metrics=h)
        reg.register(Capability(
            "institutional_learning", "Institutional Learning",
            "A growing lessons-learned registry: every action/incident/operator "
            "interaction becomes durable, validated, retrievable improvement — "
            "without retraining the LLM.",
            "core/intelligence/learning/engine.py",
            ["memory", "reasoning", "knowledge"], _il_probe))
        result["pillars"].append("institutional_learning")
    except Exception as exc:
        logger.debug(f"learning pillar wiring deferred: {exc}")

    return result
