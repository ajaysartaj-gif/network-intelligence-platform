"""
Enterprise Policy Engine (Milestone 5)
=====================================

A thin, DETERMINISTIC organizational-policy layer that activates the EXISTING
business-rules subsystem to decide whether a change is organizationally
permitted to execute:

    • Change freeze / maintenance window → memory.business.in_freeze(device)
    • Business criticality / business risk → memory.business.impact_of(device)
    • Operator / role authorization        → operator presence + autonomy context
    • Autonomous execution eligibility      → derived (no freeze, criticality ceiling)

It does NOT deploy, generate configuration, reason, or collect evidence. It
returns a PolicyContract.

Leniency (default): the business subsystem reports no freeze and default
criticality unless an organization explicitly configures them, so existing
flows stay PERMITTED. Policy blocks only on a configured change freeze or an
explicit business-rule violation. ``strict=True`` additionally requires manual
approval for business-critical devices.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .contract import PolicyContract, PolicyStatus


class EnterprisePolicyEngine:
    """Reuses the business-rules subsystem to permit (or stop) execution."""

    def evaluate(
        self,
        *,
        device: str,
        intent: str = "",
        operator: str = "",
        protocol: str = "",
        site: str = "",
        autonomous: bool = False,
        strict: bool = False,
        **ctx: Any,
    ) -> PolicyContract:
        rules_applied: List[str] = []
        violations: List[str] = []
        warnings: List[str] = []

        business = self._business()

        # ── (1) Change freeze / maintenance window (reuse business.in_freeze) ──
        rules_applied.append("change_freeze_window")
        frozen, window_reason = self._in_freeze(business, device)
        maintenance_window = "freeze" if frozen else "open"
        if frozen:
            violations.append(f"Change freeze in effect: {window_reason or 'active'}")

        # ── (2) Business criticality / business risk (reuse business.impact_of) ──
        rules_applied.append("business_criticality")
        criticality = self._criticality(business, device)
        if criticality >= 0.7:
            warnings.append(f"Business-critical device (criticality {criticality:.2f}).")

        # ── (3) Operator / role authorization ──
        rules_applied.append("operator_authorization")
        if operator:
            role_validation = "validated"
        elif autonomous:
            role_validation = "autonomous"
        else:
            role_validation = "unverified"
            warnings.append("No operator identified for a manual change.")

        # ── (4) Autonomous execution eligibility ──
        autonomous_eligible = (not frozen) and (criticality < 0.8)

        # ── DETERMINISTIC DECISION (lenient default) ──
        if frozen:
            status = PolicyStatus.DENIED                      # org freeze = hard stop
        elif autonomous and not autonomous_eligible:
            status = PolicyStatus.MANUAL_APPROVAL_REQUIRED
            violations.append("Autonomous execution not eligible "
                              "(business-critical or frozen); manual approval required.")
        elif strict and criticality >= 0.8:
            status = PolicyStatus.MANUAL_APPROVAL_REQUIRED
            violations.append(f"Business-critical device requires manual approval "
                              f"(criticality {criticality:.2f}).")
        elif violations:
            status = PolicyStatus.DENIED
        else:
            status = (PolicyStatus.PERMITTED_WITH_WARNING
                      if warnings else PolicyStatus.PERMITTED)

        return PolicyContract(
            device=device,
            status=status,
            business_rules_applied=rules_applied,
            policy_violations=violations,
            maintenance_window=maintenance_window,
            role_validation=role_validation,
            autonomous_eligible=autonomous_eligible,
            business_warnings=warnings,
        )

    # ── reuse helpers (no duplicated business rules) ─────────────────────────
    def _business(self):
        try:
            from core.intelligence.memory import get_memory_system
            return getattr(get_memory_system(), "business", None)
        except Exception:
            return None

    def _in_freeze(self, business, device):
        if business is None:
            return False, ""
        try:
            res = business.in_freeze(device) or {}
            return bool(res.get("frozen")), str(res.get("reason", ""))
        except Exception:
            return False, ""

    def _criticality(self, business, device) -> float:
        if business is None:
            return 0.0
        try:
            res = business.impact_of(device) or {}
            return float(res.get("criticality") or 0.0)
        except Exception:
            return 0.0


# ── module-level singleton + convenience ────────────────────────────────────
_ENGINE: Optional[EnterprisePolicyEngine] = None


def get_policy_engine() -> EnterprisePolicyEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = EnterprisePolicyEngine()
    return _ENGINE


def evaluate_policy(*, device: str, **ctx: Any) -> PolicyContract:
    """Convenience entry point used by the Execution Engine after governance."""
    return get_policy_engine().evaluate(device=device, **ctx)
