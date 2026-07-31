"""Diagnostic Capability Framework.

A vendor-agnostic, policy-driven layer for running bounded, self-cleaning
diagnostic actions (starting with `debug`) against real devices. OSPF/HSRP/
VRRP are the first three registered technologies, not special cases --
adding a new one is pure data in `registry.py`, never a code change here or
in the orchestration layer that calls `request_evidence()`.

Public interface:
    DiagnosticCapability, DiagnosticActionSpec, Precondition, PreconditionKind
    DiagnosticResult, run_diagnostic()
    DiagnosticPolicyEngine, governance_gate(), request_evidence()
    get_capability(), get_action_spec(), list_technologies()
"""
from .capability import DiagnosticActionSpec, DiagnosticCapability, Precondition, PreconditionKind
from .executor import DiagnosticResult, run_diagnostic
from .policy import DiagnosticPolicyEngine, governance_gate, request_evidence
from .registry import get_action_spec, get_capability, list_technologies

__all__ = [
    "DiagnosticCapability",
    "DiagnosticActionSpec",
    "Precondition",
    "PreconditionKind",
    "DiagnosticResult",
    "run_diagnostic",
    "DiagnosticPolicyEngine",
    "governance_gate",
    "request_evidence",
    "get_capability",
    "get_action_spec",
    "list_technologies",
]
