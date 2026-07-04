"""
AI Design Engine
================
An independent Principal-Network-Architect engine. Own reasoning, workflow, memory
and decision process; shares only the AI runtime and (optionally) the Vendor
Gateway (capability discovery only). Recommends ARCHITECTURES — never vendor CLI,
never device config, never troubleshooting.

Spec component → implementation
-------------------------------
 1 Requirement Manager          → reasoning.requirements + models.Requirement
 2 Constraint Manager           → reasoning.constraints + models.Constraint
 3 Existing Network Analyzer    → reasoning.assess_existing (+ gateway capabilities)
 4 Topology Intelligence        → captured within option.architecture narratives
 5 Design Generator             → reasoning.generate_options (>=3, always multiple)
 6 Technology Recommendation    → reasoning.technologies
 7 Trade-off Analyzer           → scoring.TradeoffScorer (weighted MCDA matrix)
 8 Capacity Planning Engine     → reasoning.capacity + models.CapacityEstimate
 9 Risk Analyzer                → reasoning.risks + scoring.RiskAggregator (SPOF)
10 Migration Planner            → reasoning.migration + models.MigrationPlan
11 Documentation Generator      → reasoning.documentation + models.DesignDoc
12 Design Memory                → memory.DesignMemory (requirements/options/rejected/history)

Decision principles are enforced deterministically: always multiple options; the
recommendation comes from a balanced weighted matrix (never cost- or
performance-only); assumptions and risks are surfaced explicitly.

Usage
-----
    from core.design_engine import AIDesignEngine
    report = AIDesignEngine(ai_call=call_ai, devices=devs, gateway=gw).run(
        "design a resilient dual-datacenter campus core for 5k users with growth to 15k")
    print(report.to_markdown())
"""
from .engine import AIDesignEngine, DesignEngineConfig
from .models import DesignReport, DesignSession, DesignStatus

__all__ = ["AIDesignEngine", "DesignEngineConfig", "DesignReport", "DesignSession", "DesignStatus"]
