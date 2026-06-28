"""
Governance Contract (Milestone 4 — Enterprise Change Governance Engine)
=====================================================================

The single, reusable interface carrying the final engineering decision on
whether a proposed change may DEPLOY. Produced by orchestrating the EXISTING
capabilities (Compliance, Authorization, Risk, Rollback readiness, Simulation).
It contains no configuration and performs no deployment.

Future milestones depend on THIS contract — never on raw governance internals.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class GovernanceStatus(str, Enum):
    """The only governance decisions that may be returned (deterministic)."""
    APPROVED = "approved"
    APPROVED_WITH_WARNING = "approved_with_warning"
    MANUAL_APPROVAL_REQUIRED = "manual_approval_required"
    REJECTED = "rejected"
    SIMULATION_REQUIRED = "simulation_required"
    COMPLIANCE_FAILURE = "compliance_failure"
    RISK_TOO_HIGH = "risk_too_high"
    ROLLBACK_NOT_AVAILABLE = "rollback_not_available"
    DEPLOYMENT_BLOCKED = "deployment_blocked"


# Statuses under which deployment is permitted to proceed.
_AUTHORIZED = {GovernanceStatus.APPROVED, GovernanceStatus.APPROVED_WITH_WARNING}


@dataclass
class GovernanceContract:
    """Standard governance result — the CAB/Principal-Architect verdict."""
    device: str
    status: GovernanceStatus = GovernanceStatus.APPROVED
    risk_level: str = "low"                      # low | medium | high
    risk_score: float = 0.0                      # 0..1
    compliance_result: Dict[str, Any] = field(default_factory=dict)
    simulation_result: str = "not_performed"     # passed | failed | not_performed
    approval_requirement: str = "none"           # none | manual
    rollback_readiness: str = "unknown"          # ready | snapshot | unavailable
    warnings: List[str] = field(default_factory=list)
    blocking_conditions: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)     # audit timestamp

    @property
    def authorized(self) -> bool:
        """Deployment is permitted ONLY when this is True."""
        return self.status in _AUTHORIZED

    @property
    def simulation_performed(self) -> bool:
        """Explicit simulation state (never assumed)."""
        return self.simulation_result in ("passed", "failed")

    @property
    def deployment_authorization(self) -> str:
        return "authorized" if self.authorized else "blocked"

    def summary(self) -> str:
        head = self.status.value.replace("_", " ").title()
        if self.authorized:
            extra = f" ({len(self.warnings)} warning(s))" if self.warnings else ""
            return f"{head}: deployment authorized for {self.device}{extra}."
        why = "; ".join(self.blocking_conditions) or "; ".join(self.reasons) or "see governance report"
        return f"{head}: deployment blocked for {self.device} — {why}."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device": self.device,
            "status": self.status.value,
            "risk_level": self.risk_level,
            "risk_score": round(self.risk_score, 2),
            "compliance_result": self.compliance_result,
            "simulation_result": self.simulation_result,
            "simulation_performed": self.simulation_performed,
            "approval_requirement": self.approval_requirement,
            "rollback_readiness": self.rollback_readiness,
            "warnings": list(self.warnings),
            "blocking_conditions": list(self.blocking_conditions),
            "deployment_authorization": self.deployment_authorization,
            "reasons": list(self.reasons),
            "summary": self.summary(),
            "ts": self.ts,
        }
