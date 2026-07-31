"""Diagnostic Policy Engine: decides WHETHER a diagnostic action should run,
never HOW to run it (that's `executor.py`) or WHAT it looks like on the wire
(that's `registry.py`).

Deliberately deterministic -- no LLM call, no fuzzy relevance scoring -- to
match core.governance.GovernanceEngine's own documented philosophy that the
LLM never decides whether a device-affecting action is safe. "Will this
capability help distinguish between the remaining hypotheses" is enforced
editorially at registration time (a capability is only added to the registry
when its `expected_evidence` genuinely discriminates), not computed here.

Governance stays centralized: `governance_gate()` is a thin wrapper around
the existing `core.governance.govern_change()` used before deploying any
remediation fix -- no parallel authorization logic is introduced.
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from . import registry
from .capability import DiagnosticActionSpec, DiagnosticCapability
from .executor import DiagnosticResult, run_diagnostic


def governance_gate(
    device: str, commands: List[str], *, intent: str = "", protocol: str = "",
    site: str = "", operator: str = "", strict: bool = True,
) -> Tuple[bool, str]:
    from core.governance import govern_change
    contract = govern_change(
        device=device, commands=commands,
        intent=intent or "diagnostic capability request",
        protocol=protocol, site=site, operator=operator,
        strict=strict,
    )
    return bool(contract.authorized), contract.summary()


class DiagnosticPolicyEngine:
    """Selects which registered capability, if any, is appropriate right now."""

    def select_capability(
        self, *, technology: str, vendor: str, active_hypotheses: List[Any],
        read_only_evidence_exhausted: bool,
    ) -> Optional[Tuple[DiagnosticCapability, DiagnosticActionSpec]]:
        if not read_only_evidence_exhausted:
            return None
        if len(active_hypotheses) < 2:
            return None  # nothing left to discriminate between
        capability = registry.get_capability(technology)
        if capability is None:
            return None
        action_spec = registry.get_action_spec(vendor, technology)
        if action_spec is None:
            return None
        return capability, action_spec


def request_evidence(
    *, technology: str, vendor: str, device: str, send,
    active_hypotheses: List[Any], read_only_evidence_exhausted: bool,
    intent: str = "", site: str = "", operator: str = "",
    duration_seconds: Optional[int] = None,
) -> Optional[DiagnosticResult]:
    """The one public entry point orchestration code should call. Returns
    None when no capability applies (nothing registered, evidence not
    actually exhausted, or too few competing hypotheses to discriminate
    between) -- callers should fall back to their existing behavior in that
    case exactly as if this framework didn't exist.
    """
    selected = DiagnosticPolicyEngine().select_capability(
        technology=technology, vendor=vendor, active_hypotheses=active_hypotheses,
        read_only_evidence_exhausted=read_only_evidence_exhausted,
    )
    if selected is None:
        return None
    capability, action_spec = selected

    if capability.requires_governance:
        authorized, reason = governance_gate(
            device, [*action_spec.enable_commands, action_spec.disable_command],
            intent=intent or f"diagnostic capability: {technology}/{capability.action}",
            protocol=technology, site=site, operator=operator,
        )
        if not authorized:
            return DiagnosticResult(
                device=device, technology=technology, action=capability.action,
                command="; ".join(action_spec.enable_commands),
                requested_duration_s=duration_seconds or capability.max_duration_s,
                refused=True, refusal_reason=f"governance denied: {reason}",
            )

    return run_diagnostic(capability, action_spec, device, send, duration_seconds=duration_seconds)
