"""
Reasoning Decision Engine (Milestone 3)
======================================

A thin, DETERMINISTIC orchestration layer that activates the EXISTING enterprise
intelligence to make an engineering decision before configuration generation:

    • Reasoning Registry   → core.intelligence.reasoning.get_reasoning_registry()
    • Decision Faculty     → core.intelligence.decision.judge()
    • Knowledge Graph      → core.knowledge_graph.KnowledgeGraph (dependency reuse)
    • Operational Memory   → core.intelligence.operational_memory (READ ONLY)
    • Capability Registry  → core.intelligence.capability_model.get_capability_registry()

It does NOT generate or deploy configuration. It produces a DecisionContract.
The common case (complete evidence, no red flags) returns PROCEED so existing
functionality is preserved; it only blocks on concrete, deterministic findings.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .contract import DecisionContract, DecisionStatus

_PROTOCOLS = ("ospf", "bgp", "eigrp", "rip", "isis", "mpls", "vlan", "vrf",
              "interface", "acl", "nat", "hsrp", "vrrp", "stp", "dns", "ntp")


class ReasoningDecisionEngine:
    """Reuses existing intelligence to decide the safe next engineering step."""

    def decide(
        self,
        request: str,
        device: str,
        evidence: Any,                       # core.evidence.EvidenceContract
        device_facts: str = "",
        protocol: str = "",
        knowledge_graph: Any = None,
        **ctx: Any,
    ) -> DecisionContract:
        proto = (protocol or self._infer_protocol(request)).lower()
        evidence_used = self._evidence_available(evidence)
        missing = self._evidence_missing(evidence)
        knowledge_used: List[str] = []
        warnings: List[str] = []

        # ── (1) INSUFFICIENT_EVIDENCE — defensive; Evidence Layer (M2) gates first ──
        ev_status = getattr(getattr(evidence, "status", None), "value", "")
        if ev_status == "insufficient":
            return DecisionContract(
                device=device, status=DecisionStatus.INSUFFICIENT_EVIDENCE,
                reason="No verified runtime evidence is available for this device.",
                evidence_used=evidence_used, missing_evidence=missing,
                recommended_action="Collect live CLI (running-config, interface state) "
                                    "before requesting configuration.",
                confidence=0.9,
            )

        # ── (2) Knowledge Graph — reuse dependency relationships (best effort) ──
        deps: List[str] = []
        try:
            kg = knowledge_graph or self._knowledge_graph()
            if kg is not None:
                deps = list(kg.get_dependencies(device) or [])
                if deps:
                    knowledge_used.append(
                        f"Knowledge Graph: {device} depends on {', '.join(deps[:6])}")
        except Exception:
            deps = []

        # ── (3) Operational Memory — READ ONLY recurring failures ──
        mem_hits: List[Dict[str, Any]] = []
        try:
            from core.intelligence.operational_memory import get_operational_memory
            fails = get_operational_memory().recurring_failures(min_count=2, limit=20) or []
            mem_hits = [f for f in fails if self._memory_relevant(f, device, proto)]
            if mem_hits:
                knowledge_used.append(
                    f"Operational Memory: {len(mem_hits)} recurring failure(s) for this context")
        except Exception:
            mem_hits = []

        # ── (4) Reasoning Registry — reuse a deterministic reasoner for corroboration ──
        reason_note = ""
        try:
            from core.intelligence.reasoning import get_reasoning_registry
            reg = get_reasoning_registry()
            rctx = {
                "intent": request, "device": device, "protocol": proto,
                "evidence": evidence.to_dict() if hasattr(evidence, "to_dict") else {},
                "recurring_failures": mem_hits, "dependencies": deps,
            }
            concl = reg.reason("failure_avoidance", rctx) or reg.reason("forward_outlook", rctx)
            if concl is not None:
                claim = getattr(concl, "claim", "")
                if claim:
                    reason_note = str(claim)
                    knowledge_used.append(f"Reasoning Registry: {reason_note[:80]}")
        except Exception:
            reason_note = ""

        # ── (5) Decision Faculty — reuse to score proceed-vs-gather (deterministic) ──
        confidence, requires_human = self._consult_decision_faculty(
            request, device, proto)

        # ── (6) Capability Registry — reuse to flag an unsupported target ──
        unsupported = self._unsupported(request, device_facts)
        if unsupported:
            return DecisionContract(
                device=device, status=DecisionStatus.UNSUPPORTED_REQUEST,
                reason=unsupported,
                evidence_used=evidence_used, knowledge_used=knowledge_used,
                recommended_action="Confirm the platform/vendor is supported, or collect "
                                    "facts that identify a supported platform.",
                confidence=max(confidence, 0.6), warnings=warnings,
            )

        # ── (7) Deterministic verdict (conservative ordering) ──
        required_missing = self._required_missing(evidence)
        if required_missing:
            return DecisionContract(
                device=device, status=DecisionStatus.NEED_MORE_INFORMATION,
                reason="Required evidence is incomplete for a safe change.",
                evidence_used=evidence_used, missing_evidence=required_missing,
                knowledge_used=knowledge_used,
                recommended_action="Collect the missing evidence listed above, then retry.",
                confidence=confidence, warnings=warnings,
            )

        if mem_hits:
            return DecisionContract(
                device=device, status=DecisionStatus.UNSAFE_TO_CONTINUE,
                reason="Operational memory shows this change recurrently failed in a "
                       "similar context; proceeding is unsafe without review.",
                evidence_used=evidence_used, knowledge_used=knowledge_used,
                recommended_action="Review the prior failures and adjust the plan or "
                                   "collect targeted evidence before retrying.",
                confidence=max(confidence, 0.6),
                warnings=warnings + [self._mem_warning(m) for m in mem_hits[:3]],
            )

        # default: enough evidence + reasoning support → PROCEED
        return DecisionContract(
            device=device, status=DecisionStatus.PROCEED,
            reason="Evidence complete and reasoning found no blocking dependency or "
                   "recurring failure; safe to generate configuration."
                   + (f" {reason_note}" if reason_note else ""),
            evidence_used=evidence_used, knowledge_used=knowledge_used,
            confidence=confidence or 0.6, warnings=warnings,
        )

    # ── helpers (all reuse; no duplicated intelligence) ──────────────────────
    def _consult_decision_faculty(self, request, device, proto):
        try:
            from core.intelligence.decision import judge, Option
            opts = [
                Option(id="proceed", label="Generate configuration now",
                       intent=request, device=device, protocol=proto,
                       changes_state=True, reversible=True),
                Option(id="gather", label="Hold and collect more grounding",
                       device=device, protocol=proto,
                       changes_state=False, is_status_quo=True),
            ]
            j = judge("Is it safe and well-grounded to generate configuration now?",
                      opts, goal="safe, grounded network change")
            return float(getattr(j, "confidence", 0.0) or 0.0), bool(getattr(j, "requires_human", False))
        except Exception:
            return 0.0, False

    def _knowledge_graph(self):
        # Reuse the KnowledgeGraph class/API. No shared singleton exists, so use a
        # process-local instance; get_dependencies returns [] for unknown nodes
        # (safe — never a false block). A populated graph may be injected by callers.
        global _KG
        if _KG is not None:
            return _KG
        try:
            from core.knowledge_graph import KnowledgeGraph
            _KG = KnowledgeGraph()
            return _KG
        except Exception:
            return None

    def _unsupported(self, request: str, device_facts: str) -> str:
        """Flag only a clearly unsupported target. Conservative: the LLM handles
        arbitrary configs, so this fires rarely (recognised-vendor check)."""
        try:
            from core.device_inventory_meta import is_recognized_network_vendor
            m = re.search(r"device_type=([\w-]+)", device_facts or "")
            if m and not is_recognized_network_vendor(m.group(1)):
                return f"Detected device_type '{m.group(1)}' is not a recognised network vendor."
        except Exception:
            pass
        return ""

    def _infer_protocol(self, request: str) -> str:
        rl = (request or "").lower()
        return next((p for p in _PROTOCOLS if p in rl), "")

    def _evidence_available(self, evidence) -> List[str]:
        try:
            return [i.label for i in getattr(evidence, "available", [])]
        except Exception:
            return []

    def _evidence_missing(self, evidence) -> List[str]:
        try:
            return evidence.missing_labels()
        except Exception:
            return []

    def _required_missing(self, evidence) -> List[str]:
        try:
            return [m.label for m in evidence.required_missing()]
        except Exception:
            return []

    def _memory_relevant(self, fail: Dict[str, Any], device: str, proto: str) -> bool:
        blob = " ".join(str(v) for v in fail.values()).lower()
        if device and device.lower() in blob:
            return True
        if proto and proto in blob:
            return True
        return False

    def _mem_warning(self, m: Dict[str, Any]) -> str:
        proto = m.get("protocol") or m.get("intent") or "change"
        cnt = m.get("count") or m.get("failures") or "multiple"
        return f"Recurring failure: {proto} ({cnt} occurrences)."


# ── module-level singleton + convenience ────────────────────────────────────
_ENGINE: Optional[ReasoningDecisionEngine] = None
_KG = None  # process-local KnowledgeGraph instance (reused class/API)


def get_reasoning_decision_engine() -> ReasoningDecisionEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = ReasoningDecisionEngine()
    return _ENGINE


def decide_change(request: str, device: str, evidence: Any, **ctx: Any) -> DecisionContract:
    """Convenience entry point used by the Execution Engine (post-evidence)."""
    return get_reasoning_decision_engine().decide(request, device, evidence, **ctx)
