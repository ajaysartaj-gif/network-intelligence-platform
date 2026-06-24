"""
core/intelligence/capability_model.py
======================================
The architectural backbone of NetBrain's "Network Intelligence".

Network Intelligence is defined here as ELEVEN capability pillars:

    Knowledge + Context + Memory + Reasoning + Topology Understanding
    + Dependency Awareness + Risk Assessment + Prediction
    + Decision Making + Autonomous Execution + Continuous Learning

This module turns that definition into a real contract instead of a slogan.
Each pillar is a first-class Capability object that knows:

  • what it MEANS for this tool (not a generic definition),
  • which module/function actually IMPLEMENTS it (bound to real code),
  • a live HEALTH PROBE that reports active / partial / planned from
    real state (is RAG populated? is topology discovered? etc.),
  • which other pillars it DEPENDS ON (so the model is a graph, not a list).

Subsystems register their probe here; the rest of the tool reads status,
dependencies, and readiness from one place. Nothing claims a capability it
can't back with code — an unbacked pillar reports PLANNED, honestly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("NetBrain.Intelligence.Capabilities")


class CapabilityStatus(str, Enum):
    ACTIVE = "active"     # implemented AND healthy/ready right now
    PARTIAL = "partial"   # implemented but incomplete or not yet populated/wired
    PLANNED = "planned"   # defined as a pillar, not yet built
    ERROR = "error"       # implemented but its probe failed


@dataclass
class CapabilityHealth:
    status: CapabilityStatus
    detail: str = ""                       # human-readable one-liner
    metrics: Dict[str, object] = field(default_factory=dict)


# A probe inspects real state and returns CapabilityHealth. Optional: a pillar
# with no probe yet is reported PLANNED.
HealthProbe = Callable[[], CapabilityHealth]


@dataclass
class Capability:
    key: str                               # stable id, e.g. "knowledge"
    name: str                              # display name, e.g. "Knowledge"
    definition: str                        # what it means FOR THIS TOOL
    implemented_by: str                    # module/function path (or "" if none)
    depends_on: List[str] = field(default_factory=list)   # other capability keys
    probe: Optional[HealthProbe] = None

    def health(self) -> CapabilityHealth:
        if self.probe is None:
            return CapabilityHealth(CapabilityStatus.PLANNED,
                                    "No implementation bound yet.")
        try:
            return self.probe()
        except Exception as exc:
            logger.debug(f"probe for {self.key} failed: {exc}")
            return CapabilityHealth(CapabilityStatus.ERROR, f"probe failed: {exc}")


class CapabilityRegistry:
    """The single backbone every subsystem plugs into."""

    def __init__(self):
        self._caps: Dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        self._caps[cap.key] = cap

    def bind_probe(self, key: str, probe: HealthProbe) -> None:
        """A subsystem attaches its live health probe to a pillar."""
        if key in self._caps:
            self._caps[key].probe = probe
        else:
            logger.warning(f"bind_probe: unknown capability '{key}'")

    def get(self, key: str) -> Optional[Capability]:
        return self._caps.get(key)

    def all(self) -> List[Capability]:
        return list(self._caps.values())

    def report(self) -> List[Dict[str, object]]:
        """Full status of every pillar — what the rest of the tool reads."""
        out = []
        for cap in self._caps.values():
            h = cap.health()
            out.append({
                "key": cap.key, "name": cap.name,
                "definition": cap.definition,
                "implemented_by": cap.implemented_by,
                "depends_on": cap.depends_on,
                "status": h.status.value, "detail": h.detail,
                "metrics": h.metrics,
            })
        return out

    def unmet_dependencies(self, key: str) -> List[str]:
        """Which of a pillar's dependencies are NOT currently active — so a
        capability can refuse/degrade when its foundations aren't ready
        (e.g. Dependency Awareness needs Topology Understanding active)."""
        cap = self._caps.get(key)
        if not cap:
            return []
        unmet = []
        for dep in cap.depends_on:
            dcap = self._caps.get(dep)
            if not dcap or dcap.health().status != CapabilityStatus.ACTIVE:
                unmet.append(dep)
        return unmet


# ── Live health probes (bound to REAL state) ────────────────────────────────
# Each probe imports lazily so importing this backbone never drags in heavy
# deps or fails if a subsystem is mid-refactor.

def _probe_knowledge() -> CapabilityHealth:
    try:
        from core.knowledge.rag import get_rag_engine
        n = get_rag_engine().count()
        if n > 0:
            return CapabilityHealth(CapabilityStatus.ACTIVE,
                                    f"RAG store populated ({n} chunks).", {"chunks": n})
        return CapabilityHealth(CapabilityStatus.PARTIAL,
                                "RAG engine ready but store is empty — ingest knowledge.",
                                {"chunks": 0})
    except Exception as exc:
        return CapabilityHealth(CapabilityStatus.PARTIAL, f"RAG not ready: {exc}")


def _probe_topology() -> CapabilityHealth:
    try:
        from core.topology.topology_cache import get_topology_cache
        # If any site graph has been built, topology understanding is active.
        cache = get_topology_cache()
        data = getattr(cache, "_data", {}) or {}
        sites = len(data)
        if sites:
            return CapabilityHealth(CapabilityStatus.ACTIVE,
                                    f"Topology discovered for {sites} site(s).",
                                    {"sites": sites})
        return CapabilityHealth(CapabilityStatus.PARTIAL,
                                "Topology engine ready; no site built yet.")
    except Exception as exc:
        return CapabilityHealth(CapabilityStatus.PARTIAL, f"Topology not ready: {exc}")


def _probe_risk() -> CapabilityHealth:
    try:
        from core.ai_remediation import DENY_PATTERNS
        return CapabilityHealth(CapabilityStatus.ACTIVE,
                                f"Command safety active ({len(DENY_PATTERNS)} deny rules).",
                                {"deny_rules": len(DENY_PATTERNS)})
    except Exception as exc:
        return CapabilityHealth(CapabilityStatus.PARTIAL, f"Risk layer not ready: {exc}")


def _probe_context() -> CapabilityHealth:
    # Context = reading real device state to ground generation. Implemented in
    # the intent engine's per-device config flow.
    try:
        from core.intent_engine import IntentEngine
        ok = hasattr(IntentEngine, "_read_device_facts")
        return (CapabilityHealth(CapabilityStatus.ACTIVE,
                                 "Live per-device state grounds generation.")
                if ok else
                CapabilityHealth(CapabilityStatus.PARTIAL, "Context reader not found."))
    except Exception as exc:
        return CapabilityHealth(CapabilityStatus.PARTIAL, str(exc))


def _probe_memory() -> CapabilityHealth:
    # Memory = past incidents in the RAG store (symptom->resolution).
    try:
        from core.knowledge.rag import get_rag_engine
        hits = get_rag_engine().search("incident", top_k=1, min_score=0.0, source="incident")
        if hits:
            return CapabilityHealth(CapabilityStatus.ACTIVE, "Past incidents recorded.")
        return CapabilityHealth(CapabilityStatus.PARTIAL,
                                "Incident memory wired but empty — record resolutions.")
    except Exception as exc:
        return CapabilityHealth(CapabilityStatus.PARTIAL, str(exc))


def _probe_reasoning() -> CapabilityHealth:
    try:
        from core.intent_engine import IntentEngine  # noqa
        return CapabilityHealth(CapabilityStatus.PARTIAL,
                                "LLM reasoning via intent engine (prompt-driven).")
    except Exception as exc:
        return CapabilityHealth(CapabilityStatus.PLANNED, str(exc))


def _probe_prediction() -> CapabilityHealth:
    try:
        import core.autonomous_monitor  # noqa
        return CapabilityHealth(CapabilityStatus.PARTIAL,
                                "Anomaly detection present; forecasting not yet.")
    except Exception:
        return CapabilityHealth(CapabilityStatus.PLANNED, "No prediction yet.")


def _probe_decision() -> CapabilityHealth:
    try:
        import core.autonomous_monitor  # noqa
        return CapabilityHealth(CapabilityStatus.PARTIAL,
                                "Approval-gated decisioning in autonomous monitor.")
    except Exception:
        return CapabilityHealth(CapabilityStatus.PLANNED, "No decision layer yet.")


def _probe_autonomous() -> CapabilityHealth:
    try:
        from core.ai_remediation import generate_fix_commands  # noqa
        from core.config_rollback import inverse_ios_deploy_commands  # noqa
        return CapabilityHealth(CapabilityStatus.PARTIAL,
                                "Auto-remediation with rollback, approval-gated.")
    except Exception as exc:
        return CapabilityHealth(CapabilityStatus.PLANNED, str(exc))


def _probe_dependency() -> CapabilityHealth:
    # Real dependency graph not built yet — honest PLANNED.
    return CapabilityHealth(CapabilityStatus.PLANNED,
                            "No dependency graph yet (foundation: topology graph).")


def _probe_continuous_learning() -> CapabilityHealth:
    # Nothing feeds deploy outcomes back into knowledge yet — honest PLANNED.
    return CapabilityHealth(CapabilityStatus.PLANNED,
                            "No outcome→knowledge feedback loop yet.")


# ── The canonical registry (the eleven pillars, in the operator's order) ─────
def build_default_registry() -> CapabilityRegistry:
    r = CapabilityRegistry()
    r.register(Capability(
        "knowledge", "Knowledge",
        "Semantic retrieval over vendor docs, runbooks and past incidents (RAG).",
        "core/knowledge/rag/rag_engine.py", [], _probe_knowledge))
    r.register(Capability(
        "context", "Context",
        "Reads each device's real live state (interfaces/routes) to ground actions.",
        "core/intent_engine.py::_read_device_facts", ["knowledge"], _probe_context))
    r.register(Capability(
        "memory", "Memory",
        "Remembers past symptoms→resolutions and reuses them on similar problems.",
        "core/knowledge/rag (source=incident)", ["knowledge"], _probe_memory))
    r.register(Capability(
        "reasoning", "Reasoning",
        "Infers cause/fix from evidence (LLM + structured plans).",
        "core/intent_engine.py", ["knowledge", "context", "memory"], _probe_reasoning))
    r.register(Capability(
        "topology", "Topology Understanding",
        "Discovers and models the real L1-L3 topology from CDP/LLDP + routing.",
        "core/topology/topology_engine.py", [], _probe_topology))
    r.register(Capability(
        "dependency", "Dependency Awareness",
        "Knows how a change on one device affects others (built on the topology graph).",
        "(planned)", ["topology"], _probe_dependency))
    r.register(Capability(
        "risk", "Risk Assessment",
        "Blocks unsafe commands and scores blast radius before any change.",
        "core/ai_remediation.py (DENY_PATTERNS) + core/verification/command_validator.py",
        ["dependency"], _probe_risk))
    r.register(Capability(
        "prediction", "Prediction",
        "Anticipates failures/anomalies before they cause outages.",
        "core/autonomous_monitor.py", ["topology", "memory"], _probe_prediction))
    r.register(Capability(
        "decision", "Decision Making",
        "Chooses the right action (fix / wait / escalate) given risk and context.",
        "core/autonomous_monitor.py", ["risk", "reasoning"], _probe_decision))
    r.register(Capability(
        "autonomous", "Autonomous Execution",
        "Executes approved fixes per-device with verification and rollback.",
        "core/ai_remediation.py + core/config_rollback.py + app.py(deploy)",
        ["decision", "risk"], _probe_autonomous))
    r.register(Capability(
        "learning", "Continuous Learning",
        "Feeds deploy outcomes back into Knowledge/Memory so the tool improves.",
        "(planned)", ["autonomous", "memory"], _probe_continuous_learning))
    return r


# ── Singleton backbone ──────────────────────────────────────────────────────
_registry: Optional[CapabilityRegistry] = None


def get_capability_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry
