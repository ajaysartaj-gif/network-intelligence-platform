"""
Troubleshooting Engine — data models
====================================
Structured state for a confidence-driven, evidence-first troubleshooting session.

Every conclusion is traceable: a Hypothesis holds the ids of the Evidence that
raised or lowered its confidence, and every ConfidenceDelta records the evidence
that caused it. Nothing here executes anything — these are pure state objects.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


# ── Enums ──────────────────────────────────────────────────────────────────────
class Effect(str, Enum):
    SUPPORT = "support"
    CONTRADICT = "contradict"
    NEUTRAL = "neutral"


class HypothesisState(str, Enum):
    ACTIVE = "active"
    ELIMINATED = "eliminated"
    CONFIRMED = "confirmed"


class ResolutionStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    RESOLVED_PENDING_APPROVAL = "resolved_pending_approval"   # fix found, awaiting human
    LIKELY_CAUSE_PRESENT = "likely_cause_present"             # below threshold; alternatives shown
    ESCALATE = "escalate"                                     # no safe conclusion possible
    HEALTHY = "healthy"                                       # nothing wrong found


# ── Confidence primitives ──────────────────────────────────────────────────────
def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1 / (1 + z)
    z = math.exp(x)
    return z / (1 + z)


@dataclass
class ConfidenceDelta:
    """One traceable change to a hypothesis's confidence."""
    evidence_id: str
    effect: Effect
    weight: float                 # 0..1 strength of this evidence
    log_odds_change: float
    reason: str = ""
    at: str = field(default_factory=_now)


# ── Core state objects ─────────────────────────────────────────────────────────
@dataclass
class Goal:
    """Goal Manager state: what we're trying to establish and when we're done."""
    query: str
    objective: str = ""                       # AI-phrased objective
    devices: List[str] = field(default_factory=list)   # device IPs in scope
    completion_criteria: str = (
        "A single root cause reaches the confidence threshold with a safe, "
        "minimal fix, OR evidence is exhausted and alternatives/escalation are presented."
    )
    started_at: str = field(default_factory=_now)


@dataclass
class Observation:
    """A structured fact extracted from a command output."""
    id: str = field(default_factory=lambda: _uid("obs"))
    device: str = ""
    subject: str = ""        # e.g. "ospf.neighbor" / "interface.Gi0/0.mtu"
    attribute: str = ""      # e.g. "state" / "value"
    value: str = ""          # e.g. "EXSTART" / "1500"
    source_command: str = ""
    raw_snippet: str = ""
    at: str = field(default_factory=_now)

    @property
    def key(self) -> str:
        return f"{self.device}|{self.subject}|{self.attribute}"


@dataclass
class Evidence:
    """A piece of evidence: an observation together with how it bears on hypotheses."""
    id: str = field(default_factory=lambda: _uid("ev"))
    observation_id: str = ""
    hypothesis_id: str = ""
    effect: Effect = Effect.NEUTRAL
    weight: float = 0.0
    reason: str = ""
    at: str = field(default_factory=_now)


@dataclass
class Hypothesis:
    """A candidate root cause with a confidence that only moves on evidence."""
    id: str = field(default_factory=lambda: _uid("hyp"))
    statement: str = ""
    rationale: str = ""
    discriminating_signals: List[str] = field(default_factory=list)  # what would confirm/deny it
    state: HypothesisState = HypothesisState.ACTIVE
    _log_odds: float = 0.0
    evidence_ids: List[str] = field(default_factory=list)
    deltas: List[ConfidenceDelta] = field(default_factory=list)
    at: str = field(default_factory=_now)

    def set_prior(self, prior_confidence: float) -> None:
        self._log_odds = logit(prior_confidence)

    @property
    def confidence(self) -> float:
        return round(sigmoid(self._log_odds), 4)

    def apply(self, delta: ConfidenceDelta, evidence_id: str) -> None:
        self._log_odds += delta.log_odds_change
        self.deltas.append(delta)
        if evidence_id and evidence_id not in self.evidence_ids:
            self.evidence_ids.append(evidence_id)


@dataclass
class ExecutedCommand:
    """One command that actually ran (or was reused from memory)."""
    id: str = field(default_factory=lambda: _uid("cmd"))
    device: str = ""
    command: str = ""
    normalized: str = ""
    purpose: str = ""              # WHY it was run (which hypotheses it tested)
    output: str = ""
    reused: bool = False           # True if served from memory instead of re-running
    at: str = field(default_factory=_now)


@dataclass
class Fix:
    root_cause: str = ""
    config_commands: List[str] = field(default_factory=list)
    rollback_commands: List[str] = field(default_factory=list)
    explanation: str = ""          # WHY this addresses the root cause
    validation_md: str = ""        # syntax/safety validation result
    syntax_ok: bool = False


@dataclass
class VerificationPlan:
    commands: List[str] = field(default_factory=list)     # post-change read-only checks
    success_criteria: str = ""
    rollback_on_fail: List[str] = field(default_factory=list)


# ── Full session + report ──────────────────────────────────────────────────────
@dataclass
class Session:
    """Session Memory: everything needed to resume without losing context."""
    id: str = field(default_factory=lambda: _uid("sess"))
    goal: Optional[Goal] = None
    hypotheses: List[Hypothesis] = field(default_factory=list)
    observations: List[Observation] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    executed: List[ExecutedCommand] = field(default_factory=list)
    steps_taken: int = 0
    best_confidence_history: List[float] = field(default_factory=list)
    status: ResolutionStatus = ResolutionStatus.IN_PROGRESS
    fix: Optional[Fix] = None
    verification: Optional[VerificationPlan] = None
    next_best_command: str = ""
    escalation_reason: str = ""

    def active_hypotheses(self) -> List[Hypothesis]:
        return [h for h in self.hypotheses if h.state == HypothesisState.ACTIVE]

    def ranked(self) -> List[Hypothesis]:
        # Rank all non-eliminated hypotheses (a CONFIRMED cause is still the answer).
        live = [h for h in self.hypotheses if h.state != HypothesisState.ELIMINATED]
        return sorted(live, key=lambda h: h.confidence, reverse=True)

    def top(self) -> Optional[Hypothesis]:
        r = self.ranked()
        return r[0] if r else None


@dataclass
class TroubleshootReport:
    """The structured output the spec asks for."""
    session: Session

    def to_dict(self) -> Dict[str, Any]:
        s = self.session
        top = s.top()
        return {
            "goal": s.goal.objective if s.goal else s.goal.query if s.goal else "",
            "current_state": s.status.value,
            "active_hypotheses": [
                {"statement": h.statement, "confidence": h.confidence,
                 "evidence_count": len(h.evidence_ids)}
                for h in s.ranked()
            ],
            "evidence_summary": [
                {"device": o.device, "fact": f"{o.subject}.{o.attribute}={o.value}"}
                for o in s.observations
            ],
            "executed_commands": [
                {"device": c.device, "command": c.command, "purpose": c.purpose,
                 "reused": c.reused}
                for c in s.executed
            ],
            "next_best_command": s.next_best_command,
            "confidence_score": top.confidence if top else 0.0,
            "likely_root_cause": top.statement if top else "",
            "recommended_fix": (
                {"commands": s.fix.config_commands, "rollback": s.fix.rollback_commands,
                 "explanation": s.fix.explanation, "syntax_ok": s.fix.syntax_ok}
                if s.fix else None
            ),
            "verification_plan": (
                {"commands": s.verification.commands,
                 "success_criteria": s.verification.success_criteria}
                if s.verification else None
            ),
            "final_resolution_status": s.status.value,
        }

    def to_markdown(self) -> str:
        s = self.session
        top = s.top()
        lines: List[str] = []
        lines.append(f"### 🎯 Goal\n{s.goal.objective or s.goal.query if s.goal else ''}")
        lines.append(f"\n**Current state:** `{s.status.value}`  ·  **Steps:** {s.steps_taken}")

        lines.append("\n### 🧪 Active Hypotheses")
        if s.ranked():
            for h in s.ranked():
                bar = "🟩" if h.confidence >= 0.8 else "🟨" if h.confidence >= 0.4 else "🟥"
                lines.append(f"- {bar} **{h.confidence:.0%}** — {h.statement} "
                             f"_(evidence: {len(h.evidence_ids)})_")
        else:
            lines.append("- _none active_")

        lines.append("\n### 🔍 Evidence Summary")
        if s.observations:
            for o in s.observations[-10:]:
                lines.append(f"- `{o.device}` {o.subject}.{o.attribute} = **{o.value}**")
        else:
            lines.append("- _no observations collected_")

        lines.append("\n### 🖥️ Executed Commands")
        for c in s.executed:
            tag = " ♻️(reused)" if c.reused else ""
            lines.append(f"- `{c.device}` → `{c.command}`{tag} — {c.purpose}")

        if s.next_best_command:
            lines.append(f"\n### ⏭️ Next Best Command\n`{s.next_best_command}`")

        lines.append(f"\n### 📊 Confidence Score\n**{(top.confidence if top else 0.0):.0%}**")

        lines.append("\n### 🎯 Likely Root Cause")
        lines.append(f"{top.statement if top else '_undetermined_'}")

        lines.append("\n### 🛠️ Recommended Fix")
        if s.fix and s.fix.config_commands:
            lines.append(s.fix.explanation)
            lines.append("```")
            lines.extend(s.fix.config_commands)
            lines.append("```")
            if s.fix.validation_md:
                lines.append(s.fix.validation_md)
        else:
            lines.append("_no fix generated — see resolution status_")

        lines.append("\n### ✅ Verification Plan")
        if s.verification and s.verification.commands:
            lines.append(s.verification.success_criteria)
            lines.append("```")
            lines.extend(s.verification.commands)
            lines.append("```")
        else:
            lines.append("_pending root-cause confirmation_")

        status_msg = {
            ResolutionStatus.RESOLVED_PENDING_APPROVAL: "🟢 Root cause confirmed — fix awaiting your approval.",
            ResolutionStatus.LIKELY_CAUSE_PRESENT: "🟡 Most likely cause identified below threshold — alternatives shown.",
            ResolutionStatus.ESCALATE: f"🔴 Escalated: {s.escalation_reason or 'no safe conclusion possible from available evidence.'}",
            ResolutionStatus.HEALTHY: "🟢 No fault found — system appears healthy.",
            ResolutionStatus.IN_PROGRESS: "⏳ Investigation in progress.",
        }.get(s.status, s.status.value)
        lines.append(f"\n### 🏁 Final Resolution Status\n{status_msg}")
        return "\n".join(lines)
