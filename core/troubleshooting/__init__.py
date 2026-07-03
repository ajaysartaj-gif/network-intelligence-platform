"""
Autonomous Troubleshooting Engine
=================================
Confidence-driven, evidence-first troubleshooting that reasons before acting,
never repeats completed investigations, and never concludes a root cause below a
confidence threshold.

Spec component → implementation map
-----------------------------------
 1. Goal Manager           → models.Goal + engine.run() setup
 2. Diagnostic Planner     → reasoning.Reasoner.plan_commands (+ engine adapts each step)
 3. Hypothesis Manager     → hypotheses.HypothesisManager, reasoning.generate_hypotheses
 4. Evidence Collector     → engine._collect (delegates to IntentEngine SSH, read-only)
 5. Evidence Graph         → evidence_graph.EvidenceGraph (+ contradiction detection)
 6. Executed Cmds Memory   → memory.ExecutedCommandsMemory (dedup + reuse)
 7. Command Planner        → engine._pick_command (info-gain scoring over candidates)
 8. Command Validator      → engine._validator (IntentEngine.is_read_only/is_dangerous)
 9. Result Analyzer        → reasoning.Reasoner.analyze → structured facts + impacts
10. Confidence Calculator  → hypotheses.ConfidenceCalculator (log-odds, traceable)
11. Root Cause Ranker      → hypotheses.RootCauseRanker (threshold + margin gated)
12. Fix Generator          → reasoning.generate_fix + IntentEngine fix validation
13. Verification Planner   → reasoning.plan_verification (+ rollback on fail)
14. Session Memory         → memory.SessionMemory (serialize / resume)

Usage
-----
    from core.troubleshooting import TroubleshootingEngine
    engine = TroubleshootingEngine(ai_call=call_ai, devices=selected_devices)
    report = engine.run("why do I see OSPF issues on the core routers")
    print(report.to_markdown())      # or report.to_dict()
"""
from .engine import TroubleshootingEngine, TSConfig
from .models import (
    ResolutionStatus, TroubleshootReport, Session, Hypothesis, Goal,
)

__all__ = [
    "TroubleshootingEngine",
    "TSConfig",
    "TroubleshootReport",
    "ResolutionStatus",
    "Session",
    "Hypothesis",
    "Goal",
]
