"""
AI Design Engine — models
=========================
Independent from the Troubleshooting and Configuration engines. Produces
ARCHITECTURE (options, trade-offs, roadmap, documentation) — never vendor CLI,
never device config, never troubleshooting.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _uid(p: str) -> str: return f"{p}_{uuid4().hex[:8]}"
def _now() -> str: return datetime.utcnow().isoformat(timespec="seconds")


class DesignStatus(str, Enum):
    DRAFT = "draft"
    OPTIONS_READY = "options_ready"          # multiple options + recommendation produced
    INSUFFICIENT = "insufficient"            # too little to design even with assumptions


# Scoring dimensions (illustrative, NOT exhaustive). Balanced by design principle:
# never optimize only for cost or only for performance.
DIMENSIONS: Dict[str, float] = {
    "cost": 0.10,
    "performance": 0.12,
    "scalability": 0.15,
    "availability": 0.15,
    "security": 0.13,
    "operational_simplicity": 0.15,
    "future_readiness": 0.12,
    "vendor_independence": 0.08,
}


@dataclass
class Requirement:
    kind: str            # business/technical/operational/security/compliance/performance/availability/growth
    detail: str


@dataclass
class Constraint:
    kind: str            # budget/technology/vendor/operational/compliance/geographical/latency/power/space/migration
    detail: str


@dataclass
class ExistingAssessment:
    summary: str = ""
    bottlenecks: List[str] = field(default_factory=list)
    technical_debt: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)   # discovered via Vendor Gateway (optional)


@dataclass
class DesignOption:
    id: str = field(default_factory=lambda: _uid("opt"))
    name: str = ""
    architecture: str = ""                                   # narrative (technologies, topology)
    technologies: List[str] = field(default_factory=list)
    advantages: List[str] = field(default_factory=list)
    disadvantages: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)   # dimension -> 0..1 (LLM estimate)
    weighted_total: float = 0.0
    recommended: bool = False


@dataclass
class RiskItem:
    kind: str            # spof/operational/security/migration/performance/vendor/business
    detail: str
    severity: str = "medium"    # low/medium/high


@dataclass
class CapacityEstimate:
    dimension: str       # bandwidth/cpu/memory/routing_scale/address_utilization/growth
    current: str = ""
    projected: str = ""
    headroom: str = ""


@dataclass
class MigrationPhase:
    order: int
    name: str
    actions: str = ""
    validation: str = ""
    rollback: str = ""
    downtime: str = ""


@dataclass
class MigrationPlan:
    strategy: str = ""
    phases: List[MigrationPhase] = field(default_factory=list)
    success_criteria: str = ""


@dataclass
class DesignDoc:
    high_level: str = ""
    low_level: str = ""
    decision_log: str = ""
    assumptions: List[str] = field(default_factory=list)
    future_recommendations: List[str] = field(default_factory=list)


@dataclass
class DesignSession:
    id: str = field(default_factory=lambda: _uid("dsn"))
    query: str = ""
    business_summary: str = ""
    technical_summary: str = ""
    status: DesignStatus = DesignStatus.DRAFT
    requirements: List[Requirement] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    existing: Optional[ExistingAssessment] = None
    options: List[DesignOption] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)        # names of dismissed options (memory)
    recommended_id: str = ""
    tradeoff_matrix: List[Dict[str, Any]] = field(default_factory=list)
    technologies: List[str] = field(default_factory=list)
    risks: List[RiskItem] = field(default_factory=list)
    capacity: List[CapacityEstimate] = field(default_factory=list)
    migration: Optional[MigrationPlan] = None
    operational_recommendations: List[str] = field(default_factory=list)
    documentation: Optional[DesignDoc] = None
    confidence: float = 0.0
    decision_rationale: str = ""
    history: List[str] = field(default_factory=list)

    def record(self, note: str) -> None:
        self.history.append(f"{_now()} :: {note}")

    def recommended(self) -> Optional[DesignOption]:
        return next((o for o in self.options if o.id == self.recommended_id), None)


@dataclass
class DesignReport:
    session: DesignSession

    def to_dict(self) -> Dict[str, Any]:
        s = self.session
        rec = s.recommended()
        return {
            "business_summary": s.business_summary,
            "technical_summary": s.technical_summary,
            "current_architecture_assessment": (s.existing.summary if s.existing else ""),
            "design_constraints": [{"kind": c.kind, "detail": c.detail} for c in s.constraints],
            "architecture_options": [
                {"name": o.name, "technologies": o.technologies, "advantages": o.advantages,
                 "disadvantages": o.disadvantages, "assumptions": o.assumptions,
                 "risks": o.risks, "score": o.weighted_total, "recommended": o.recommended}
                for o in s.options],
            "tradeoff_analysis": s.tradeoff_matrix,
            "recommended_design": (rec.name if rec else ""),
            "risk_assessment": [{"kind": r.kind, "detail": r.detail, "severity": r.severity} for r in s.risks],
            "capacity_assessment": [c.__dict__ for c in s.capacity],
            "migration_plan": ({"strategy": s.migration.strategy,
                                "phases": [p.__dict__ for p in s.migration.phases],
                                "success_criteria": s.migration.success_criteria}
                               if s.migration else None),
            "implementation_phases": [p.name for p in (s.migration.phases if s.migration else [])],
            "operational_recommendations": s.operational_recommendations,
            "documentation": (s.documentation.__dict__ if s.documentation else None),
            "confidence_score": s.confidence,
            "decision_rationale": s.decision_rationale,
        }

    def to_markdown(self) -> str:
        s = self.session
        rec = s.recommended()
        L: List[str] = []
        L.append(f"## 🏛️ Network Architecture Design\n")
        L.append(f"### 💼 Business Summary\n{s.business_summary or s.query}")
        if s.technical_summary:
            L.append(f"\n### 🔧 Technical Summary\n{s.technical_summary}")
        if s.existing and s.existing.summary:
            L.append(f"\n### 🗺️ Current Architecture Assessment\n{s.existing.summary}")
            if s.existing.bottlenecks:
                L.append("Bottlenecks: " + ", ".join(s.existing.bottlenecks))
        if s.constraints:
            L.append("\n### ⛓️ Design Constraints")
            for c in s.constraints:
                L.append(f"- **{c.kind}**: {c.detail}")
        L.append("\n### 🧩 Architecture Options")
        for o in s.options:
            star = " ⭐ **RECOMMENDED**" if o.recommended else ""
            L.append(f"\n**{o.name}** (score {o.weighted_total:.2f}){star}")
            L.append(f"{o.architecture}")
            if o.technologies:
                L.append(f"_Technologies:_ {', '.join(o.technologies)}")
            if o.advantages:
                L.append("_Advantages:_ " + "; ".join(o.advantages))
            if o.disadvantages:
                L.append("_Disadvantages:_ " + "; ".join(o.disadvantages))
            if o.assumptions:
                L.append("_Assumptions:_ " + "; ".join(o.assumptions))
            if o.risks:
                L.append("_Risks:_ " + "; ".join(o.risks))
        if s.tradeoff_matrix:
            L.append("\n### ⚖️ Trade-off Analysis")
            dims = [d for d in DIMENSIONS]
            header = "| Option | " + " | ".join(dims) + " | Total |"
            sep = "|" + "---|" * (len(dims) + 2)
            L.append(header)
            L.append(sep)
            for row in s.tradeoff_matrix:
                cells = " | ".join(f"{row.get(d, 0):.2f}" for d in dims)
                L.append(f"| {row.get('option', '')} | {cells} | {row.get('total', 0):.2f} |")
        if rec:
            L.append(f"\n### ✅ Recommended Design\n**{rec.name}** — {s.decision_rationale}")
        if s.risks:
            L.append("\n### ⚠️ Risk Assessment")
            for r in s.risks:
                L.append(f"- [{r.severity.upper()}] {r.kind}: {r.detail}")
        if s.capacity:
            L.append("\n### 📈 Capacity Assessment")
            for c in s.capacity:
                L.append(f"- {c.dimension}: current {c.current or '—'} → projected {c.projected or '—'} "
                         f"(headroom {c.headroom or '—'})")
        if s.migration:
            L.append(f"\n### 🚚 Migration Plan\n_Strategy:_ {s.migration.strategy}")
            for p in s.migration.phases:
                L.append(f"- **Phase {p.order}: {p.name}** — {p.actions} "
                         f"(validate: {p.validation}; rollback: {p.rollback}; downtime: {p.downtime or 'none'})")
            if s.migration.success_criteria:
                L.append(f"_Success criteria:_ {s.migration.success_criteria}")
        if s.operational_recommendations:
            L.append("\n### 🛠️ Operational Recommendations")
            for r in s.operational_recommendations:
                L.append(f"- {r}")
        if s.documentation:
            L.append("\n### 📚 Documentation")
            if s.documentation.high_level:
                L.append(f"**HLD:** {s.documentation.high_level}")
            if s.documentation.low_level:
                L.append(f"**LLD:** {s.documentation.low_level}")
            if s.documentation.future_recommendations:
                L.append("**Future:** " + "; ".join(s.documentation.future_recommendations))
        L.append(f"\n### 📊 Confidence Score\n**{s.confidence:.0%}**")
        L.append("\n_Design only — to implement the recommended architecture, switch to "
                 "**Configure Network & Services**; for incidents, use **Troubleshoot & Fix**._")
        return "\n".join(L)
