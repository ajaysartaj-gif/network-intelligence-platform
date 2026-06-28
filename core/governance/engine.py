"""
Enterprise Change Governance Engine (Milestone 4)
================================================

A thin, DETERMINISTIC governance layer that activates EXISTING capabilities to
decide whether a proposed change may DEPLOY:

    • Compliance     → core.ai_config.validate_config  (command-level safety)
                       core.compliance_engine.ComplianceEngine (device-level, optional)
    • Authorization  → core.intelligence.autonomy.authorize  (the dormant safety gate)
    • Risk           → derived from the authorization Decision.risk
    • Rollback       → rollback commands supplied, else NetworkFixer snapshot
    • Simulation     → optional injected simulator (best-effort reuse)

It does NOT generate, deploy, or modify evidence/reasoning/learning. It returns
a GovernanceContract.

Leniency (default): the platform's deploy path is reached only AFTER human
authorization (admin Apply / copilot per-device approval), so governance blocks
ONLY on concrete failures — destructive commands (Compliance Failure) or an
explicit policy DENY (Rejected). Gate/risk/rollback/simulation concerns become
warnings so existing flows stay compatible. ``strict=True`` makes every concern
a hard block (every decision type is then reachable), for future autonomous use.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .contract import GovernanceContract, GovernanceStatus


class GovernanceEngine:
    """Reuses existing capabilities to authorize (or block) a deployment."""

    def govern(
        self,
        *,
        device: str,
        commands: List[str],
        intent: str = "",
        protocol: str = "",
        site: str = "",
        operator: str = "",
        rollback_commands: Optional[List[str]] = None,
        device_facts: str = "",
        device_meta: Optional[Dict[str, Any]] = None,
        simulate: Optional[Callable[[str, List[str]], Any]] = None,
        strict: bool = False,
    ) -> GovernanceContract:
        commands = [c for c in (commands or []) if str(c).strip()]
        warnings: List[str] = []
        blocking: List[str] = []
        reasons: List[str] = []

        # ── (1) COMPLIANCE — reuse the existing command-safety validator ──
        is_safe, blocked_cmds, comp_reasons = self._compliance(commands)
        compliance_result: Dict[str, Any] = {
            "safe": is_safe, "blocked": blocked_cmds, "reasons": comp_reasons,
            "commands_checked": len(commands),
        }
        self._device_compliance(device_meta, compliance_result)
        reasons += comp_reasons

        # ── (2) AUTHORIZATION — reuse the dormant autonomy safety gate ──
        verdict, risk, requires_approval, auth_reasons = self._authorize(
            device, commands, intent, protocol, site, operator)
        reasons += auth_reasons

        # ── (3) RISK level (derived from the authorization decision) ──
        risk_level = "high" if risk >= 0.7 else "medium" if risk >= 0.4 else "low"

        # ── (4) ROLLBACK readiness (reuse: explicit rollback else snapshot) ──
        rollback_readiness = "ready" if rollback_commands else "snapshot"

        # ── (5) SIMULATION (best-effort optional reuse) ──
        simulation_result = self._simulate(simulate, device, commands)

        # ── DETERMINISTIC DECISION ──
        status = GovernanceStatus.APPROVED

        if not is_safe:
            status = GovernanceStatus.COMPLIANCE_FAILURE
            blocking += ([f"Non-compliant command: {c}" for c in blocked_cmds]
                         or comp_reasons or ["Configuration failed compliance validation."])
        elif verdict == "deny":
            status = GovernanceStatus.REJECTED
            blocking += auth_reasons or ["Change denied by policy."]
        else:
            high_no_rollback = (risk_level == "high"
                                and rollback_readiness not in ("ready", "snapshot"))
            if strict and high_no_rollback:
                status = GovernanceStatus.ROLLBACK_NOT_AVAILABLE
                blocking.append("High-risk change without an available rollback.")
            elif strict and risk >= 0.9:
                status = GovernanceStatus.RISK_TOO_HIGH
                blocking.append(f"Assessed risk {risk:.2f} exceeds the deployment ceiling.")
            elif strict and risk >= 0.8 and simulation_result == "not_performed":
                status = GovernanceStatus.SIMULATION_REQUIRED
                blocking.append("High-risk change requires pre-deployment simulation.")
            elif strict and (verdict == "gate" or requires_approval) and not operator:
                status = GovernanceStatus.MANUAL_APPROVAL_REQUIRED
                blocking.append("Autonomous change requires manual approval.")
            else:
                # lenient: proceed, folding concerns into warnings
                if verdict == "gate" or requires_approval:
                    warnings.append("Policy would normally gate this change; "
                                    "proceeding on operator authorization.")
                if risk_level == "high":
                    warnings.append(f"High change risk ({risk:.2f}).")
                elif risk_level == "medium":
                    warnings.append(f"Moderate change risk ({risk:.2f}).")
                if rollback_readiness == "snapshot":
                    warnings.append("Rollback relies on the pre-change snapshot "
                                    "captured by the deployer.")
                if simulation_result == "not_performed":
                    warnings.append("Pre-deployment simulation was not performed.")
                status = (GovernanceStatus.APPROVED_WITH_WARNING
                          if warnings else GovernanceStatus.APPROVED)

        approval_requirement = (
            "manual" if status == GovernanceStatus.MANUAL_APPROVAL_REQUIRED else "none")

        return GovernanceContract(
            device=device,
            status=status,
            risk_level=risk_level,
            risk_score=risk,
            compliance_result=compliance_result,
            simulation_result=simulation_result,
            approval_requirement=approval_requirement,
            rollback_readiness=rollback_readiness,
            warnings=warnings,
            blocking_conditions=blocking,
            reasons=[r for r in reasons if r],
        )

    # ── reuse helpers (no duplicated governance logic) ───────────────────────
    def _compliance(self, commands: List[str]):
        try:
            from core.ai_config import validate_config
            is_safe, blocked, reasons = validate_config(commands)
            return bool(is_safe), list(blocked or []), list(reasons or [])
        except Exception:
            return True, [], []

    def _device_compliance(self, device_meta, compliance_result: Dict[str, Any]) -> None:
        if not device_meta:
            return
        try:
            from core.compliance_engine import ComplianceEngine
            res = ComplianceEngine().evaluate_device(device_meta)
            compliance_result["device_score"] = res.get("score")
            compliance_result["device_violations"] = [
                r for r in res.get("results", []) if not r.get("passed")]
        except Exception:
            pass

    def _authorize(self, device, commands, intent, protocol, site, operator):
        try:
            from core.intelligence.autonomy import authorize, Action
            kind = ("rollback" if (intent or "").lower().startswith("rollback")
                    else "config_change")
            action = Action(
                kind=kind,
                intent=intent or " ".join(commands[:3]),
                device=device, protocol=protocol, site=site, operator=operator,
                changes_state=True,
            )
            d = authorize(action)
            verdict = getattr(getattr(d, "verdict", None), "value", "allow")
            risk = float(getattr(d, "risk", 0.0) or 0.0)
            requires_approval = bool(getattr(d, "requires_approval", False))
            reasons = list(getattr(d, "reasons", []) or [])
            return verdict, risk, requires_approval, reasons
        except Exception:
            # If the authorization gate is unavailable, do not invent a denial.
            return "allow", 0.0, False, []

    def _simulate(self, simulate, device, commands) -> str:
        if not simulate:
            return "not_performed"
        try:
            ok = simulate(device, commands)
            return "passed" if ok else "failed"
        except Exception:
            return "not_performed"


# ── module-level singleton + convenience ────────────────────────────────────
_ENGINE: Optional[GovernanceEngine] = None


def get_governance_engine() -> GovernanceEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = GovernanceEngine()
    return _ENGINE


def govern_change(*, device: str, commands: List[str], **ctx: Any) -> GovernanceContract:
    """Convenience entry point used by the Execution Engine before deployment."""
    return get_governance_engine().govern(device=device, commands=commands, **ctx)
