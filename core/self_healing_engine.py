from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class RemediationAction:
    action_id: str
    device: str
    description: str
    risk: str
    approved: bool = False
    executed: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    approval_comments: Optional[str] = None


class SelfHealingEngine:
    """Self-healing engine with remediation and approval workflow simulation."""

    def recommend_remediation(self, alert: Dict[str, object], device: Dict[str, object]) -> List[RemediationAction]:
        actions: List[RemediationAction] = []
        device_name = device.get("hostname", "unknown")
        alert_type = alert.get("alert_type", "unknown")
        severity = alert.get("severity", "low")

        if alert_type == "cpu":
            actions.append(
                RemediationAction(
                    action_id=f"R-{device_name}-CPU",
                    device=device_name,
                    description="Reduce CPU load by disabling noncritical services and rebalancing traffic.",
                    risk="medium" if severity == "critical" else "low",
                )
            )
        elif alert_type == "memory":
            actions.append(
                RemediationAction(
                    action_id=f"R-{device_name}-MEM",
                    device=device_name,
                    description="Restart memory-intensive processes or clear cache to recover memory.",
                    risk="medium" if severity == "critical" else "low",
                )
            )
        elif alert_type == "bgp":
            actions.append(
                RemediationAction(
                    action_id=f"R-{device_name}-BGP",
                    device=device_name,
                    description="Validate BGP neighbor configuration and reset the BGP session on the affected peer.",
                    risk="high" if severity == "critical" else "medium",
                )
            )
        else:
            actions.append(
                RemediationAction(
                    action_id=f"R-{device_name}-GEN",
                    device=device_name,
                    description="Collect diagnostics and escalate to the operations team for manual remediation.",
                    risk="low",
                )
            )

        return actions

    def simulate_auto_remediation(self, action: RemediationAction, approve: bool = True) -> RemediationAction:
        action.approved = approve
        if not approve:
            action.approval_comments = "Auto-remediation deferred pending approval."
            return action

        action.executed = True
        action.executed_at = datetime.utcnow()
        action.approval_comments = "Simulated automation executed successfully."
        return action

    def risk_score(self, incident: Dict[str, object]) -> int:
        base = incident.get("severity", "low").lower()
        score_map = {"low": 20, "medium": 50, "high": 75, "critical": 95}
        return score_map.get(base, 30)

    def approval_workflow(self, action: RemediationAction, approver: Optional[str] = None) -> Dict[str, object]:
        approved = action.risk != "high" or approver is not None
        action.approved = approved
        action.approval_comments = (
            "Auto-approved by workflow." if approved else "Pending engineer approval due to elevated risk."
        )
        return {
            "action_id": action.action_id,
            "approved": approved,
            "approver": approver or "system",
            "risk": action.risk,
            "timestamp": datetime.utcnow(),
            "comments": action.approval_comments,
        }

    def validate_remediation(self, action: RemediationAction, device: Dict[str, object]) -> bool:
        if action.risk == "high" and device.get("status", "healthy") != "healthy":
            return False
        return True
