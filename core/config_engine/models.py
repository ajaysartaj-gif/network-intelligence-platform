"""
AI Configuration Engine — normalized models
===========================================
The engine reasons ONLY on these vendor-neutral objects and emits normalized
ConfigIntent. Vendor syntax is produced later, exclusively via the Vendor Gateway.
No vendor names, products or commands appear anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _uid(p: str) -> str: return f"{p}_{uuid4().hex[:8]}"
def _now() -> str: return datetime.utcnow().isoformat(timespec="seconds")


class ConfigStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_INPUT = "needs_input"              # mandatory info missing — ask, never assume
    BLOCKED = "blocked"                      # design flaw / conflict / policy violation
    NEEDS_APPROVAL = "needs_approval"        # package ready, awaiting explicit approval
    APPROVED = "approved"                    # human approved (still not deployed here)


class RiskLevel(str, Enum):
    LOW = "low"; MEDIUM = "medium"; HIGH = "high"; CRITICAL = "critical"


class Severity(str, Enum):
    INFO = "info"; WARN = "warn"; CRITICAL = "critical"


class DeploymentStrategy:
    """Well-known strategies (NOT exhaustive; any string is accepted)."""
    IMMEDIATE = "immediate"; MAINTENANCE_WINDOW = "maintenance_window"
    PHASED = "phased_rollout"; SITE_BY_SITE = "site_by_site"
    CANARY = "canary"; BLUE_GREEN = "blue_green"; BATCH = "batch"


@dataclass
class Goal:
    query: str
    objective: str = ""
    category: str = ""                       # e.g. routing/switching/security (free-form)
    scope: List[str] = field(default_factory=list)   # device ips / sites
    started_at: str = field(default_factory=_now)


@dataclass
class MissingInput:
    field: str                               # e.g. "area", "asn", "vlan"
    question: str = ""
    required: bool = True


@dataclass
class TechnologyOption:
    name: str
    rationale: str = ""
    tradeoffs: str = ""
    recommended: bool = False


@dataclass
class Dependency:
    kind: str                                # e.g. interface/vrf/vlan/license/feature
    detail: str = ""
    satisfied: Optional[bool] = None


@dataclass
class Check:
    """Generic result for policy / standards / compliance / validation / design."""
    name: str
    severity: Severity = Severity.INFO
    passed: bool = True
    detail: str = ""


@dataclass
class Conflict:
    kind: str                                # duplicate/address_overlap/policy/routing/...
    detail: str
    severity: Severity = Severity.WARN


@dataclass
class ConfigIntent:
    """Normalized, vendor-neutral configuration intent (the engine's product)."""
    id: str = field(default_factory=lambda: _uid("ci"))
    name: str = ""                           # e.g. "configure_ospf_interface"
    params: Dict[str, Any] = field(default_factory=dict)
    target_devices: List[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class PlanStep:
    order: int
    description: str
    intent_id: str = ""
    prerequisite: str = ""


@dataclass
class ImpactAssessment:
    factors: List[str] = field(default_factory=list)     # e.g. "protocol_reset"
    downtime_expected: bool = False
    summary: str = ""


@dataclass
class RiskAssessment:
    level: RiskLevel = RiskLevel.LOW
    score: float = 0.0                       # 0..1
    drivers: List[str] = field(default_factory=list)
    mitigations: List[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class VendorArtifact:
    """Vendor output for ONE device, produced by the Vendor Gateway (not the engine)."""
    device: str
    adapter: str = ""
    config_commands: List[str] = field(default_factory=list)
    rollback_commands: List[str] = field(default_factory=list)
    verification_commands: List[str] = field(default_factory=list)
    supported: bool = True
    note: str = ""


@dataclass
class DeploymentPlan:
    strategy: str = DeploymentStrategy.MAINTENANCE_WINDOW
    ordered_devices: List[str] = field(default_factory=list)
    rationale: str = ""


@dataclass
class ApprovalPackage:
    executive_summary: str = ""
    impact_summary: str = ""
    risk_summary: str = ""
    verification_summary: str = ""
    rollback_summary: str = ""
    approved: bool = False


@dataclass
class AuditEntry:
    step: str
    detail: str
    at: str = field(default_factory=_now)


@dataclass
class ConfigSession:
    id: str = field(default_factory=lambda: _uid("cfg"))
    goal: Optional[Goal] = None
    status: ConfigStatus = ConfigStatus.DRAFT
    technologies: List[str] = field(default_factory=list)
    protocols: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    provided: Dict[str, Any] = field(default_factory=dict)
    missing: List[MissingInput] = field(default_factory=list)
    tech_options: List[TechnologyOption] = field(default_factory=list)
    dependencies: List[Dependency] = field(default_factory=list)
    policy_checks: List[Check] = field(default_factory=list)
    standards_checks: List[Check] = field(default_factory=list)
    best_practices: List[str] = field(default_factory=list)
    design_checks: List[Check] = field(default_factory=list)
    plan: List[PlanStep] = field(default_factory=list)
    intents: List[ConfigIntent] = field(default_factory=list)
    impact: Optional[ImpactAssessment] = None
    risk: Optional[RiskAssessment] = None
    conflicts: List[Conflict] = field(default_factory=list)
    compliance_checks: List[Check] = field(default_factory=list)
    validation_checks: List[Check] = field(default_factory=list)
    simulation_targets: List[str] = field(default_factory=list)
    artifacts: List[VendorArtifact] = field(default_factory=list)
    deployment: Optional[DeploymentPlan] = None
    approval: Optional[ApprovalPackage] = None
    audit: List[AuditEntry] = field(default_factory=list)

    def record(self, step: str, detail: str) -> None:
        self.audit.append(AuditEntry(step=step, detail=detail))


@dataclass
class ConfigReport:
    session: ConfigSession

    def to_dict(self) -> Dict[str, Any]:
        s = self.session
        return {
            "goal": s.goal.objective if s.goal else "",
            "status": s.status.value,
            "technologies": s.technologies,
            "missing_inputs": [{"field": m.field, "question": m.question} for m in s.missing],
            "technology_options": [{"name": t.name, "recommended": t.recommended,
                                    "tradeoffs": t.tradeoffs} for t in s.tech_options],
            "dependencies": [{"kind": d.kind, "detail": d.detail} for d in s.dependencies],
            "normalized_intents": [{"name": i.name, "params": i.params,
                                    "devices": i.target_devices} for i in s.intents],
            "impact": (s.impact.__dict__ if s.impact else None),
            "risk": ({"level": s.risk.level.value, "score": s.risk.score,
                      "drivers": s.risk.drivers, "mitigations": s.risk.mitigations}
                     if s.risk else None),
            "conflicts": [{"kind": c.kind, "detail": c.detail, "severity": c.severity.value}
                          for c in s.conflicts],
            "vendor_artifacts": [{"device": a.device, "adapter": a.adapter,
                                  "config": a.config_commands, "rollback": a.rollback_commands,
                                  "verification": a.verification_commands, "supported": a.supported}
                                 for a in s.artifacts],
            "deployment": (s.deployment.__dict__ if s.deployment else None),
            "approval": (s.approval.__dict__ if s.approval else None),
            "final_status": s.status.value,
        }

    def to_markdown(self) -> str:
        s = self.session
        L: List[str] = []
        L.append(f"### 🎯 Goal\n{s.goal.objective if s.goal else ''}")
        L.append(f"\n**Status:** `{s.status.value}`")
        if s.status == ConfigStatus.NEEDS_INPUT and s.missing:
            L.append("\n### ❓ I need a few details before designing this (I won't assume them):")
            for m in s.missing:
                L.append(f"- **{m.field}** — {m.question}")
            return "\n".join(L)
        if s.technologies:
            L.append(f"\n### 🧩 Technologies\n{', '.join(s.technologies)}")
        if s.tech_options:
            L.append("\n### 🧠 Technology Options")
            for t in s.tech_options:
                star = " ⭐" if t.recommended else ""
                L.append(f"- **{t.name}**{star} — {t.rationale} _(trade-offs: {t.tradeoffs})_")
        if s.dependencies:
            L.append("\n### 🔗 Dependencies\n" + ", ".join(f"{d.kind}: {d.detail}" for d in s.dependencies))
        if s.intents:
            L.append("\n### 🧱 Normalized Configuration Intent (vendor-neutral)")
            for i in s.intents:
                L.append(f"- `{i.name}` {i.params} → {', '.join(i.target_devices) or 'scope'}")
        if s.conflicts:
            L.append("\n### ⚠️ Conflicts")
            for c in s.conflicts:
                L.append(f"- [{c.severity.value.upper()}] {c.kind}: {c.detail}")
        if s.impact:
            L.append(f"\n### 📉 Impact\n{s.impact.summary} "
                     f"(factors: {', '.join(s.impact.factors) or 'none'})")
        if s.risk:
            L.append(f"\n### 🎲 Risk\n**{s.risk.level.value.upper()}** (score {s.risk.score:.2f}) — "
                     f"drivers: {', '.join(s.risk.drivers) or 'none'}")
            if s.risk.mitigations:
                L.append("Mitigations: " + "; ".join(s.risk.mitigations))
        if s.artifacts:
            L.append("\n### 🛠️ Vendor Artifacts (via Vendor Gateway)")
            for a in s.artifacts:
                head = f"**{a.device}** _({a.adapter or 'unresolved'})_"
                if not a.supported:
                    L.append(f"- {head}: {a.note or 'vendor translation not available; kept as intent'}")
                    continue
                L.append(f"- {head}")
                if a.config_commands:
                    L.append("  config:\n```\n" + "\n".join(a.config_commands) + "\n```")
                if a.rollback_commands:
                    L.append("  rollback:\n```\n" + "\n".join(a.rollback_commands) + "\n```")
        if s.deployment:
            L.append(f"\n### 🚀 Deployment Strategy\n`{s.deployment.strategy}` — {s.deployment.rationale}")
        if s.approval:
            L.append("\n### 📦 Approval Package")
            L.append(f"**Executive:** {s.approval.executive_summary}")
            L.append(f"**Impact:** {s.approval.impact_summary}")
            L.append(f"**Risk:** {s.approval.risk_summary}")
            L.append(f"**Verification:** {s.approval.verification_summary}")
            L.append(f"**Rollback:** {s.approval.rollback_summary}")
            L.append("\n⚠️ **Nothing is deployed until you explicitly approve.**")
        return "\n".join(L)
