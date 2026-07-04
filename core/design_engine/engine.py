"""
AI Design Engine — orchestrator (independent Principal-Architect engine)
=======================================================================
Own reasoning, workflow, memory, decision process. Shares only the AI runtime and
(optionally) the Vendor Gateway — used ONLY for capability discovery on brownfield
devices, never for configuration. Produces architecture options + recommendation;
never vendor CLI, never device config, never troubleshooting.

Pipeline: summarize → requirements → constraints → assess existing → generate
options (≥ min) → score (deterministic MCDA) → recommend → technologies →
capacity → risks (+deterministic SPOF) → migration → operational → docs →
confidence → rationale.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from .memory import DesignMemory
from .models import (CapacityEstimate, Constraint, DesignDoc, DesignOption, DesignReport,
                     DesignSession, DesignStatus, ExistingAssessment, MigrationPhase,
                     MigrationPlan, Requirement, RiskItem)
from .reasoning import DesignReasoner
from .scoring import RiskAggregator, TradeoffScorer

logger = logging.getLogger(__name__)


@dataclass
class DesignEngineConfig:
    min_options: int = 3        # ALWAYS multiple options; never one
    max_options: int = 5


class AIDesignEngine:
    def __init__(self, ai_call: Callable[[str], str], devices: List[Any] = None,
                 gateway: Optional[object] = None,
                 config: Optional[DesignEngineConfig] = None,
                 memory_backend: Optional[object] = None) -> None:
        self.ai = ai_call
        self.devices = devices or []
        self.gateway = gateway
        self.cfg = config or DesignEngineConfig()
        self.r = DesignReasoner(ai_call)
        self.scorer = TradeoffScorer()
        self.risk_agg = RiskAggregator()
        self.memory = DesignMemory(memory_backend)

    def run(self, query: str) -> DesignReport:
        s = DesignSession(query=query)

        summ = self.r.summarize(query)
        s.business_summary = summ.get("business_summary", "")
        s.technical_summary = summ.get("technical_summary", "")
        s.record("summarized request")

        # 1. Requirement Manager
        s.requirements = [Requirement(kind=r.get("kind", ""), detail=r.get("detail", ""))
                          for r in self.r.requirements(query) if r.get("detail")]
        # 2. Constraint Manager
        s.constraints = [Constraint(kind=c.get("kind", ""), detail=c.get("detail", ""))
                         for c in self.r.constraints(query) if c.get("detail")]
        s.record(f"{len(s.requirements)} requirement(s), {len(s.constraints)} constraint(s)")

        # 3. Existing Network Analyzer (+ optional capability discovery via Vendor Gateway)
        caps = self._discover_capabilities()
        ex = self.r.assess_existing(query, caps)
        s.existing = ExistingAssessment(summary=ex.get("summary", ""),
                                        bottlenecks=list(ex.get("bottlenecks", [])),
                                        technical_debt=list(ex.get("technical_debt", [])),
                                        capabilities=caps)

        # 5. Design Generator (MULTIPLE options mandatory)
        raw = self.r.generate_options(
            query, [r.__dict__ for r in s.requirements],
            [c.__dict__ for c in s.constraints], self.cfg.min_options)[: self.cfg.max_options]
        for o in raw:
            if not o.get("name"):
                continue
            s.options.append(DesignOption(
                name=o.get("name", ""), architecture=o.get("architecture", ""),
                technologies=list(o.get("technologies", [])),
                advantages=list(o.get("advantages", [])),
                disadvantages=list(o.get("disadvantages", [])),
                assumptions=list(o.get("assumptions", [])),
                risks=list(o.get("risks", [])),
                scores=dict(o.get("scores", {}) or {})))

        if len(s.options) < 2:
            s.status = DesignStatus.INSUFFICIENT
            s.record("insufficient options generated")
            self.memory.save(s)
            return DesignReport(s)

        # 6. Technology Recommendation
        s.technologies = self.r.technologies(query)

        # 7. Trade-off Analyzer + recommendation (deterministic MCDA)
        s.tradeoff_matrix = self.scorer.score(s.options)
        rec = max(s.options, key=lambda x: x.weighted_total)
        s.recommended_id = rec.id
        s.rejected = [o.name for o in s.options if not o.recommended]
        s.record(f"recommended '{rec.name}' via weighted trade-off matrix")

        # 8. Capacity Planning
        s.capacity = [CapacityEstimate(dimension=c.get("dimension", ""), current=c.get("current", ""),
                                       projected=c.get("projected", ""), headroom=c.get("headroom", ""))
                      for c in self.r.capacity(query, [r.__dict__ for r in s.requirements])
                      if c.get("dimension")]

        # 9. Risk Analyzer (LLM + deterministic SPOF surfacing)
        s.risks = [RiskItem(kind=r.get("kind", ""), detail=r.get("detail", ""),
                            severity=r.get("severity", "medium"))
                   for r in self.r.risks(rec.name, rec.architecture) if r.get("detail")]
        s.risks.extend(self.risk_agg.spofs(rec))

        # 10. Migration Planner
        mig = self.r.migration(rec.name, s.existing.summary if s.existing else "")
        s.migration = MigrationPlan(
            strategy=mig.get("strategy", ""), success_criteria=mig.get("success_criteria", ""),
            phases=[MigrationPhase(order=int(p.get("order", i + 1)), name=p.get("name", ""),
                                   actions=p.get("actions", ""), validation=p.get("validation", ""),
                                   rollback=p.get("rollback", ""), downtime=p.get("downtime", ""))
                    for i, p in enumerate(mig.get("phases", []))])

        # operational + documentation
        s.operational_recommendations = self.r.operational(rec.name)
        doc = self.r.documentation(query, rec.name, rec.architecture)
        s.documentation = DesignDoc(
            high_level=doc.get("high_level", ""), low_level=doc.get("low_level", ""),
            decision_log=doc.get("decision_log", ""),
            assumptions=[a for o in s.options for a in o.assumptions],
            future_recommendations=list(doc.get("future_recommendations", [])))

        # confidence + rationale
        s.confidence = self.scorer.confidence(s.options, len(s.requirements))
        s.decision_rationale = self.r.rationale(rec.name, s.tradeoff_matrix)

        s.status = DesignStatus.OPTIONS_READY
        s.record(f"design ready (confidence {s.confidence})")
        self.memory.save(s)
        return DesignReport(s)

    def _discover_capabilities(self) -> List[str]:
        """Optional brownfield capability discovery via the Vendor Gateway. Read-only,
        never configuration. Silent if no gateway/devices."""
        if self.gateway is None or not self.devices:
            return []
        caps: set = set()
        for d in self.devices:
            try:
                for c in (self.gateway.capabilities(d) or []):
                    caps.add(c)
            except Exception:
                continue
        return sorted(caps)
