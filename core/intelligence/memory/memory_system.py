"""
core/intelligence/memory/memory_system.py
==========================================
The MemorySystem facade — one mind made of many memories.

This is the single object the rest of the platform talks to. It owns one lazy
instance of every derived memory, the EpisodicRecall layer over the raw log, and
the ConsolidationEngine that keeps them fed. It exposes:

  • get_memory_system()      — process singleton.
  • .record_episode(...)     — the ONE call after a verified change; fans out to
                               every memory via consolidation (the write path).
  • .recall(context)         — gather everything the platform "knows" relevant to
                               a situation: similar cases, known-good procedure,
                               contraindications, competence, business impact,
                               operator stance, temporal risk. The read path that
                               makes the platform reason like it has been here
                               before.
  • .consolidate()           — batch replay of the episodic log into expertise.
  • wire_memory_system()     — startup hook: register expert faculties + bind the
                               new pillars into the Capability Registry, including
                               upgrading the honest "Continuous Learning" pillar
                               from PLANNED to live, because the feedback loop now
                               exists.

Everything is best-effort: any single memory failing degrades that lens only.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NetBrain.Intelligence.Memory.System")


class MemorySystem:
    def __init__(self):
        # lazy handles; constructed on first access so import never blocks.
        self._semantic = None
        self._procedural = None
        self._pattern = None
        self._failure = None
        self._experience = None
        self._temporal = None
        self._environmental = None
        self._topology_evo = None
        self._operator = None
        self._trust = None
        self._prediction = None
        self._decision = None
        self._verification = None
        self._business = None
        self._episodic = None
        self._consolidator = None

    # ── lazy properties ──────────────────────────────────────────────────────
    @property
    def semantic(self):
        if self._semantic is None:
            from core.intelligence.memory.semantic import SemanticMemory
            self._semantic = SemanticMemory()
        return self._semantic

    @property
    def procedural(self):
        if self._procedural is None:
            from core.intelligence.memory.procedural import ProceduralMemory
            self._procedural = ProceduralMemory()
        return self._procedural

    @property
    def pattern(self):
        if self._pattern is None:
            from core.intelligence.memory.pattern import PatternMemory
            self._pattern = PatternMemory()
        return self._pattern

    @property
    def failure(self):
        if self._failure is None:
            from core.intelligence.memory.failure import FailureMemory
            self._failure = FailureMemory()
        return self._failure

    @property
    def experience(self):
        if self._experience is None:
            from core.intelligence.memory.experience import ExperienceMemory
            self._experience = ExperienceMemory()
        return self._experience

    @property
    def temporal(self):
        if self._temporal is None:
            from core.intelligence.memory.temporal import TemporalMemory
            self._temporal = TemporalMemory()
        return self._temporal

    @property
    def environmental(self):
        if self._environmental is None:
            from core.intelligence.memory.environmental import EnvironmentalMemory
            self._environmental = EnvironmentalMemory()
        return self._environmental

    @property
    def topology_evo(self):
        if self._topology_evo is None:
            from core.intelligence.memory.topology_evolution import TopologyEvolutionMemory
            self._topology_evo = TopologyEvolutionMemory()
        return self._topology_evo

    @property
    def operator(self):
        if self._operator is None:
            from core.intelligence.memory.operator import OperatorPreferenceMemory
            self._operator = OperatorPreferenceMemory()
        return self._operator

    @property
    def trust(self):
        if self._trust is None:
            from core.intelligence.memory.feedback import TrustMemory
            self._trust = TrustMemory()
        return self._trust

    @property
    def prediction(self):
        if self._prediction is None:
            from core.intelligence.memory.feedback import PredictionMemory
            self._prediction = PredictionMemory()
        return self._prediction

    @property
    def decision(self):
        if self._decision is None:
            from core.intelligence.memory.feedback import DecisionMemory
            self._decision = DecisionMemory()
        return self._decision

    @property
    def verification(self):
        if self._verification is None:
            from core.intelligence.memory.feedback import VerificationMemory
            self._verification = VerificationMemory()
        return self._verification

    @property
    def business(self):
        if self._business is None:
            from core.intelligence.memory.business import BusinessMemory
            self._business = BusinessMemory()
        return self._business

    @property
    def episodic(self):
        if self._episodic is None:
            from core.intelligence.memory.episodic import EpisodicRecall
            self._episodic = EpisodicRecall()
        return self._episodic

    @property
    def consolidator(self):
        if self._consolidator is None:
            from core.intelligence.memory.consolidation import ConsolidationEngine
            self._consolidator = ConsolidationEngine(self)
        return self._consolidator

    def all_stores(self) -> Dict[str, Any]:
        return {
            "semantic": self.semantic, "procedural": self.procedural,
            "pattern": self.pattern, "failure": self.failure,
            "experience": self.experience, "temporal": self.temporal,
            "environmental": self.environmental, "topology_evolution": self.topology_evo,
            "operator": self.operator, "trust": self.trust,
            "prediction": self.prediction, "decision": self.decision,
            "verification": self.verification, "business": self.business,
        }

    # ── write path: one call updates every memory ────────────────────────────
    def record_episode(self, **kw) -> Dict[str, Any]:
        return self.consolidator.record_episode(**kw)

    def record_from_contract(self, contract: Any, *, site: str = "",
                             protocol: str = "", operator: str = "",
                             commands: Optional[List[str]] = None,
                             stated_confidence: float = 0.0) -> Dict[str, Any]:
        """Adapter: feed a ContractResult straight into consolidation, mirroring
        OperationalMemory.record_from_contract so the app can call both from the
        same hook with the same object."""
        intent = getattr(contract, "intent", "") or ""
        device = getattr(contract, "device", "") or ""
        satisfied = bool(getattr(contract, "satisfied", False))
        conds = []
        for c in getattr(contract, "conditions", []) or []:
            verdict = getattr(getattr(c, "verdict", None), "value", None)
            conds.append({"description": getattr(c, "description", ""),
                          "check_command": getattr(c, "check_command", ""),
                          "verdict": verdict, "reason": getattr(c, "reason", "")})
        return self.record_episode(
            intent=intent, device=device, protocol=protocol, site=site,
            success=satisfied, commands=commands or [], conditions=conds,
            operator=operator, stated_confidence=stated_confidence)

    # ── read path: everything relevant to a situation ────────────────────────
    def recall(self, *, intent: str = "", symptoms: str = "", protocol: str = "",
               device: str = "", operator: str = "default") -> Dict[str, Any]:
        probe = symptoms or intent
        out: Dict[str, Any] = {}

        def _safe(name, fn):
            try:
                out[name] = fn()
            except Exception as exc:
                out[name] = None
                logger.debug(f"recall {name}: {exc}")

        _safe("similar_cases", lambda: self.episodic.similar_cases(probe, top_k=3))
        _safe("known_procedure", lambda: self.procedural.best_for(intent, protocol, min_rate=0.5))
        _safe("contraindications",
              lambda: self.failure.contraindications(f"{intent} {protocol} {device}", top_k=4))
        _safe("competence", lambda: self.experience.competence(protocol or "general"))
        _safe("relevant_facts", lambda: self.semantic.known(probe, top_k=5))
        _safe("likely_causes", lambda: self.pattern.likely_causes(symptoms, top_k=4) if symptoms else [])
        _safe("temporal_risk", lambda: self.temporal.risk_now(f"domain:{protocol or 'general'}"))
        _safe("business_impact", lambda: self.business.impact_of(device) if device else None)
        _safe("freeze", lambda: self.business.in_freeze(device) if device else {"frozen": False})
        _safe("device_quirks", lambda: self.environmental.fingerprint(device, limit=8) if device else [])
        _safe("recent_topology_change",
              lambda: self.topology_evo.recent_changes(site="", since_s=3 * 24 * 3600))
        from core.intelligence.memory.consolidation import _class_intent
        _safe("operator_stance",
              lambda: self.operator.stance_for(operator, "approval",
                                               f"{protocol or 'generic'}:{_class_intent(intent)}"))
        return out

    # ── batch consolidation ──────────────────────────────────────────────────
    def consolidate(self, **kw) -> Dict[str, Any]:
        return self.consolidator.consolidate(**kw)

    # ── status surface ───────────────────────────────────────────────────────
    def report(self) -> Dict[str, Any]:
        rep = {}
        for name, store in self.all_stores().items():
            try:
                rep[name] = store.metrics()
            except Exception as exc:
                rep[name] = {"error": str(exc)}
        try:
            rep["episodic"] = {"hit_rate": self.prediction.hit_rate()}
        except Exception:
            pass
        return rep


# ── singleton ────────────────────────────────────────────────────────────────
_system: Optional[MemorySystem] = None


def get_memory_system() -> MemorySystem:
    global _system
    if _system is None:
        _system = MemorySystem()
    return _system


# ── startup wiring (mirrors bind_memory_capability / bind_reasoning_capability)
def wire_memory_system() -> Dict[str, Any]:
    result = {"faculties": 0, "capabilities": []}

    # 1) register the expert faculties into the reasoning system
    try:
        from core.intelligence.memory.expert_faculties import register_expert_faculties
        result["faculties"] = register_expert_faculties()
    except Exception as exc:
        logger.debug(f"faculty wiring deferred: {exc}")

    # 2) register + bind new capability pillars (and upgrade Continuous Learning)
    try:
        from core.intelligence.capability_model import (
            get_capability_registry, Capability, CapabilityHealth, CapabilityStatus)
        reg = get_capability_registry()
        sysm = get_memory_system()

        def _store_probe(store_name: str, label: str):
            def _p():
                try:
                    store = sysm.all_stores()[store_name]
                    m = store.metrics()
                    n = int(m.get("count") or 0)
                    status = CapabilityStatus.ACTIVE if n else CapabilityStatus.PARTIAL
                    return CapabilityHealth(
                        status, f"{label}: {n} consolidated", metrics=m)
                except Exception as exc:
                    return CapabilityHealth(CapabilityStatus.PARTIAL, f"{label}: {exc}")
            return _p

        new_pillars = [
            ("memory.experience", "Experience Memory", "experience"),
            ("memory.failure", "Failure Memory", "failure"),
            ("memory.pattern", "Pattern Memory", "pattern"),
            ("memory.procedural", "Procedural Memory", "procedural"),
            ("memory.semantic", "Semantic Memory", "semantic"),
            ("memory.temporal", "Temporal Memory", "temporal"),
            ("memory.environmental", "Environmental Memory", "environmental"),
            ("memory.topology_evolution", "Topology Evolution Memory", "topology_evolution"),
            ("memory.operator", "Operator Preference Memory", "operator"),
            ("memory.trust", "Trust Memory", "trust"),
            ("memory.prediction", "Prediction Memory", "prediction"),
            ("memory.decision", "Decision Memory", "decision"),
            ("memory.verification", "Verification Memory", "verification"),
            ("memory.business", "Business Memory", "business"),
        ]
        for key, name, store_name in new_pillars:
            reg.register(Capability(
                key, name,
                f"Derived {name.lower()} that consolidates from the episodic log "
                f"and feeds reasoning/prediction/decisions.",
                f"core/intelligence/memory/{store_name}.py",
                ["memory", "learning"], _store_probe(store_name, name)))
            result["capabilities"].append(key)

        # The platform now HAS an outcome→memory feedback loop: make the honest
        # "Continuous Learning" pillar reflect reality instead of PLANNED.
        def _learning_probe():
            try:
                stores = sysm.all_stores()
                total = sum(int(s.metrics().get("count") or 0) for s in stores.values())
                if total > 0:
                    return CapabilityHealth(
                        CapabilityStatus.ACTIVE,
                        f"Outcome→memory loop live across {len(stores)} memory types "
                        f"({total} consolidated beliefs).",
                        {"memory_types": len(stores), "consolidated": total})
                return CapabilityHealth(
                    CapabilityStatus.PARTIAL,
                    "Feedback loop wired; nothing consolidated yet.")
            except Exception as exc:
                return CapabilityHealth(CapabilityStatus.PARTIAL, str(exc))
        reg.bind_probe("learning", _learning_probe)
        result["capabilities"].append("learning(upgraded)")

        # Prediction pillar: now backed by a scored prediction memory.
        def _prediction_probe():
            try:
                hr = sysm.prediction.hit_rate()
                n = int(hr.get("resolved") or 0)
                if n:
                    return CapabilityHealth(
                        CapabilityStatus.ACTIVE,
                        f"Predictions scored against outcomes (hit-rate "
                        f"{hr['hit_rate']:.0%} over {n}).", hr)
                return CapabilityHealth(
                    CapabilityStatus.PARTIAL,
                    "Prediction memory live; no resolved predictions yet.", hr)
            except Exception as exc:
                return CapabilityHealth(CapabilityStatus.PARTIAL, str(exc))
        reg.bind_probe("prediction", _prediction_probe)
        result["capabilities"].append("prediction(upgraded)")

    except Exception as exc:
        logger.debug(f"capability wiring deferred: {exc}")

    return result
