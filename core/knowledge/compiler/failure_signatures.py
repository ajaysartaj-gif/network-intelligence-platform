"""
core/knowledge/compiler/failure_signatures.py
================================================
Thin, backward-compatible shim over protocol_registry.py, which is now
the single canonical source of truth for every protocol's failure
signatures (both the six FSM protocols' compiled signature lists AND
ACL/NAT/VLAN's reactive compile_*_signature functions).
compile_failure_signatures(), compile_acl_deny_signature(),
compile_nat_role_signature(), and compile_vlan_native_mismatch_signature()
all keep their exact prior names/signatures/behavior — nothing importing
from this module needs to change.

compile_operational_failure_signatures() is UNRELATED to any specific
protocol (it converts OperationalMemory's learned recurring-failure
history into the same FailureSignature shape) and stays exactly here,
unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.knowledge.compiler.artifacts import FailureSignature
from core.knowledge.compiler.protocol_registry import (
    PROTOCOL_SPECS,
    compile_acl_deny_signature,
    compile_nat_role_signature,
    compile_vlan_native_mismatch_signature,
)
from core.knowledge.compiler.protocol_models import build_protocol_model

__all__ = [
    "compile_failure_signatures", "compile_acl_deny_signature", "compile_nat_role_signature",
    "compile_vlan_native_mismatch_signature", "compile_operational_failure_signatures",
    "explain_stuck_state",
]


def compile_failure_signatures(protocol: str) -> List[FailureSignature]:
    """Returns the seeded failure signatures for `protocol`'s states. []
    for any protocol without a verified state model — never a guess."""
    protocol = (protocol or "").strip().lower()
    if build_protocol_model(protocol) is None:
        return []
    spec = PROTOCOL_SPECS.get(protocol)
    return list(spec.signatures) if spec else []


def explain_stuck_state(protocol: str, stuck_state: str) -> Optional[Dict[str, Any]]:
    """
    Builds the deterministic reasoning-chain data for a protocol stuck at
    `stuck_state`: what the compiled FSM model confirms already succeeded
    (every transition on the path INTO this state) and what being stuck
    HERE specifically means is failing (the transition OUT of it that
    hasn't happened) — entirely grounded in the compiled ProtocolStateModel
    and FailureSignature, no LLM guessing about protocol mechanics.

    Feedback this closes: a report jumping straight from "84% confidence"
    to "MTU mismatch" with no explanation of WHY EXSTART specifically
    means DBD exchange is what's failing (as opposed to Hellos, or Layer 1/
    2, both of which EXSTART already rules out having a problem with) reads
    as an assertion, not a diagnosis — an engineer reconstructs that
    reasoning chain mentally every time; the report should show it, not
    make the reader re-derive it.

    Returns None if `protocol`/`stuck_state` isn't a verified, compiled
    combination (never fabricates one).
    """
    protocol = (protocol or "").strip().lower()
    model = build_protocol_model(protocol)
    if model is None or stuck_state not in model.states:
        return None

    idx = model.states.index(stuck_state)
    confirmed_stages: List[str] = []
    for i in range(idx):
        cur, nxt = model.states[i], model.states[i + 1]
        trans = next((t for t in model.transitions
                     if t.from_state == cur and t.to_state == nxt), None)
        if trans:
            confirmed_stages.append(f"{cur} → {nxt}: {trans.trigger}")

    # Forward-only transitions out of stuck_state (excludes regressions back
    # to an earlier state, e.g. Full/2-Way -> Down on a dead-interval timeout).
    forward = [t for t in model.transitions
              if t.from_state == stuck_state and t.to_state in model.states
              and model.states.index(t.to_state) > idx]
    if forward:
        stuck_meaning = (f"{stuck_state} means the neighbor has NOT yet completed: "
                        + "; ".join(t.trigger for t in forward))
    else:
        stuck_meaning = f"{stuck_state} is the final modeled state for {protocol.upper()} — no further progression defined."

    sigs = compile_failure_signatures(protocol)
    sig = next((s for s in sigs if s.stuck_state == stuck_state), None)

    return {
        "protocol": protocol,
        "stuck_state": stuck_state,
        "confirmed_stages": confirmed_stages,
        "stuck_meaning": stuck_meaning,
        "likely_cause": sig.likely_cause if sig else "",
        "evidence_fields": list(sig.evidence_fields) if sig else [],
        "confidence": sig.confidence if sig else 0.0,
    }


def compile_operational_failure_signatures(recurring: List[dict]) -> List[FailureSignature]:
    """
    Converts core.intelligence.operational_memory.OperationalMemory.
    recurring_failures()'s output — real operational history, not textbook
    protocol knowledge — into the SAME FailureSignature shape the OSPF/STP/
    ACL signatures above use, so patterns LEARNED FROM OPERATIONS join the
    same artifact model rather than living in a separate, second shape.

    Expects the exact dict shape recurring_failures() returns:
    {"signature": str, "count": int, "last_ts": float, "intent": str,
    "protocol": str}. Confidence scales with recurrence count — more
    independent failures of the same signature is stronger evidence this
    is a real pattern, not noise — capped at 0.9 (the same ceiling the
    textbook ExStart/MTU signature uses; operational evidence earns the
    same trust as verified protocol knowledge, never more).
    """
    signatures: List[FailureSignature] = []
    for row in recurring:
        signature = row.get("signature", "")
        count = int(row.get("count", 0) or 0)
        intent = row.get("intent", "") or "(no intent recorded)"
        protocol = (row.get("protocol", "") or "operational").lower()
        confidence = min(0.9, 0.5 + 0.1 * max(0, count - 2))
        signatures.append(FailureSignature(
            protocol=protocol, stuck_state=f"recurring:{signature[:12]}",
            likely_cause=f"Recurring failure pattern (seen {count}x): intent "
                        f"'{intent}' on protocol '{protocol}'",
            evidence_fields=["signature", "count"], confidence=confidence))
    return signatures
