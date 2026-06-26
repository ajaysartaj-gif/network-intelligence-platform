"""
core/intelligence/learning/base.py
===================================
The substrate for ORGANIZATIONAL learning — institutional memory, not model
weights.

A team that has run a network for fifteen years is not better because anyone
re-trained their brain. They are better because the organization accumulated
LESSONS: "EXSTART that never reaches FULL is almost always MTU"; "never bounce
the hub to fix an edge adjacency"; "the clean OSPF-area fix is these four
commands, in this order"; "this operator wants eyes on anything touching
payments". Those lessons are written down, reinforced when they prove out,
demoted when they don't, retrieved when a similar situation recurs, and taught
to every newcomer. That is what this package builds — a living lessons-learned
registry that improves the platform across every dimension without touching the
LLM.

A Lesson is the unit of institutional knowledge. The LessonStore reuses the
derived-memory substrate (reinforce / decay / semantic recall, same brain) so
lessons strengthen with evidence and surface by relevance. A Learner is an
active behaviour that turns experience into lessons — online (per event) and in
retrospect (mining the whole corpus).
"""
from __future__ import annotations

import hashlib
import time
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


class LessonType(str, Enum):
    PATTERN = "pattern"            # a discovered correlation (symptom→cause→fix)
    MISTAKE = "mistake"           # a repeated error / anti-pattern to avoid
    STRATEGY = "strategy"         # a proven successful approach / best practice
    HEURISTIC = "heuristic"       # an if-then rule for reasoning
    CALIBRATION = "calibration"   # a confidence/trust correction
    PREFERENCE = "preference"     # a learned operator/business preference
    RISK_RULE = "risk_rule"       # a condition that predicts harm
    PLANNING_RULE = "planning"    # a refinement to how plans are built


# the platform dimensions every lesson can improve (the user's list + more).
DIMENSIONS = ("knowledge", "memory", "reasoning", "prediction", "decision",
              "risk", "execution", "confidence", "trust", "planning")


@dataclass
class Lesson:
    lesson_type: str
    statement: str                 # the lesson, in plain words (embedded for recall)
    trigger: str = ""              # the situation it applies to
    recommendation: str = ""       # what to do / avoid
    scope: str = "global"          # global | <protocol> | <device> | <operator>
    dimensions: List[str] = field(default_factory=list)  # what it improves
    confidence: float = 0.55
    evidence_count: int = 1
    validated: bool = False
    source: str = ""               # which learner produced it
    metadata: Dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        raw = f"{self.lesson_type}|{self.scope}|{self.trigger}|{self.statement}".lower()
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass
class LearningEvent:
    """The single normalised thing every workflow feeds back into learning."""
    kind: str                      # deployment | incident | action | operator | verification
    success: Optional[bool] = None
    intent: str = ""
    device: str = ""
    protocol: str = ""
    site: str = ""
    operator: str = ""
    commands: List[str] = field(default_factory=list)
    conditions: List[Dict[str, Any]] = field(default_factory=list)  # post-condition verdicts
    signature: str = ""
    resolution_time_s: Optional[float] = None
    stated_confidence: float = 0.0
    operator_action: str = ""      # approved | edited | rejected
    ts: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def domain(self) -> str:
        return (self.protocol or "general").lower()


class LessonStore(MemoryStore):
    """Durable, reinforceable, decaying, semantically-recallable lessons —
    the institution's written memory, living in the shared brain."""
    table = "learning_lessons"
    semantic = True
    # lessons are institutional: they fade very slowly compared to raw episodes.
    half_life_s = 3 * 365 * 24 * 3600
    columns = (
        ("lesson_type", "TEXT"),
        ("scope", "TEXT"),
        ("trigger", "TEXT"),
        ("recommendation", "TEXT"),
        ("dimensions", "TEXT"),      # csv
        ("evidence_count", "INTEGER"),
        ("validated", "INTEGER"),
        ("source", "TEXT"),
    )

    def write(self, lesson: Lesson) -> str:
        ex = self._by_key(lesson.key())
        evid = int((ex or {}).get("evidence_count") or 0) + 1
        # validation: a lesson is 'validated' once independently seen enough times.
        validated = lesson.validated or evid >= 3
        return self.learn(
            lesson.key(), lesson.statement, confidence=lesson.confidence,
            extra={"recommendation": lesson.recommendation, **lesson.metadata},
            lesson_type=lesson.lesson_type, scope=lesson.scope,
            trigger=lesson.trigger, recommendation=lesson.recommendation,
            dimensions=",".join(lesson.dimensions), evidence_count=evid,
            validated=1 if validated else 0, source=lesson.source)

    def recall(self, query: str, top_k: int = 5, lesson_type: str = "",
               scope: str = "", validated_only: bool = False) -> List[Dict[str, Any]]:
        hits = self.recall_similar(query, top_k=top_k * 2,
                                   lesson_type=lesson_type or None,
                                   scope=scope or None)
        if validated_only:
            hits = [h for h in hits if int(h.get("validated") or 0) == 1]
        return hits[:top_k]

    def of_type(self, lesson_type: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self.top(limit=limit, lesson_type=lesson_type)

    def digest(self) -> Dict[str, Any]:
        out = {}
        for lt in LessonType:
            out[lt.value] = self.count(lesson_type=lt.value)
        out["validated"] = self.count(validated=1)
        out["total"] = self.count()
        return out


@dataclass
class LearnerSpec:
    key: str
    name: str
    dimension: str                 # the primary platform dimension it improves
    purpose: str


class Learner(ABC):
    """An active learning behaviour. Subclasses implement observe and/or
    retrospect; both are optional so a learner can be online-only or batch-only."""

    def __init__(self, spec: LearnerSpec, store: LessonStore):
        self.spec = spec
        self.store = store
        self._lessons_written = 0

    # online: react to a single event as it happens.
    def observe(self, ev: LearningEvent) -> List[str]:
        return []

    # retrospect: mine the whole corpus periodically (after-action review).
    def retrospect(self, corpus: "Corpus") -> Dict[str, Any]:
        return {}

    def _emit(self, lesson: Lesson) -> str:
        rid = self.store.write(lesson)
        self._lessons_written += 1
        return rid

    def health(self) -> Dict[str, Any]:
        return {"key": self.spec.key, "dimension": self.spec.dimension,
                "lessons_written": self._lessons_written}


class Corpus:
    """A read-only view over operational + derived memory for retrospectives."""

    def __init__(self, window_s: float = 365 * 24 * 3600, limit: int = 2000):
        self.window_s = window_s
        self.limit = limit
        self._events: Optional[List[Dict[str, Any]]] = None

    def _opmem(self):
        from core.intelligence.operational_memory import get_operational_memory
        return get_operational_memory()

    def sys(self):
        from core.intelligence.memory import get_memory_system
        return get_memory_system()

    def events(self) -> List[Dict[str, Any]]:
        if self._events is None:
            try:
                since = time.time() - self.window_s
                self._events = self._opmem().temporal(
                    since=since, limit=self.limit, newest_first=False)
            except Exception:
                self._events = []
        return self._events

    def by_outcome(self, success: bool) -> List[Dict[str, Any]]:
        want = "success" if success else "failure"
        return [e for e in self.events() if e.get("outcome") == want]

    def recurring_failures(self, min_count: int = 2) -> List[Dict[str, Any]]:
        try:
            return self._opmem().recurring_failures(min_count=min_count, limit=200)
        except Exception:
            return []
