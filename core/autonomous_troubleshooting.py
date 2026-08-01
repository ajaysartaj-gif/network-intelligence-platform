"""
core/autonomous_troubleshooting.py
==================================
Integration layer: ties all 5 phases together.

Implements 3 execution paths:
  Path A: Fully autonomous (predict → diagnose → auto-fix → learn)
  Path B: On-demand troubleshooting (diagnose → approve → execute → learn)
  Path C: Learning-first (diagnose → store pattern → next time faster)

This is the main orchestrator called from app.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.semantic_intake import ProblemStatement, ProblemScope, ProblemSymptom, SemanticIntake
from core.remediation_executor import ExecutionResult, RemediationExecutor, RemediationPlan
from core.pattern_db import PatternDatabase
from core.prediction_forecaster import AutonomousDecisionMaker, PatternPredictor, PredictedIssue
from core.external_knowledge_layer import ExternalKnowledgeIntegrator, ExternalSolution

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Execution Path Enum
# ═══════════════════════════════════════════════════════════════════════════════

class ExecutionPath(str, Enum):
    """Which troubleshooting mode?"""
    AUTONOMOUS = "autonomous"          # Path A: predict → diagnose → auto-fix → learn
    ON_DEMAND = "on_demand"             # Path B: diagnose → approve → execute
    LEARNING = "learning"               # Path C: diagnose → store → learn


@dataclass
class TroubleshootingSession:
    """Full session trace from problem → resolution."""
    problem: ProblemStatement
    path: ExecutionPath
    predictions: List[PredictedIssue]  # (Path A only) Issues predicted before incident
    diagnosis_report: Optional[Dict[str, Any]] = None  # From troubleshooting engine
    root_cause: Optional[str] = None
    suggested_fix: Optional[RemediationPlan] = None
    execution_result: Optional[ExecutionResult] = None
    outcome: Optional[str] = None  # "fixed" | "degraded" | "error"
    pattern_id: Optional[str] = None  # (Path C) Stored pattern ID
    external_solution: Optional[ExternalSolution] = None  # (Unknown issues) External sources
    diagnosis_confidence: float = 0.0  # Confidence of diagnosis (0.0-1.0)
    used_external_knowledge: bool = False  # Did we search external sources?
    duration_seconds: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Main Autonomous Troubleshooting Orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

class AutonomousNetworkTroubleshooter:
    """
    Unified troubleshooting orchestrator supporting all 3 paths.

    Core flow:
      1. User describes problem (natural language)
      2. Semantic intake classifies it
      3. Route to appropriate path (A/B/C based on settings)
      4. Execute path-specific workflow
      5. Record outcome and update patterns
    """

    def __init__(self,
                 ai_call: Callable[[str], str],
                 troubleshoot_engine: Any,  # TroubleshootingEngine instance
                 ssh_collector: Callable[[Any, List[str]], Dict[str, str]],
                 command_validator: Callable[[str], bool],
                 approved_devices: List[Any],
                 topology_graph: Optional[Any] = None,
                 pattern_db_path: str = "./network_pattern_db.sqlite"):
        """
        Parameters
        ----------
        ai_call : Callable
            LLM function (e.g., core.ai_engine.ask_ai)
        troubleshoot_engine : TroubleshootingEngine
            Hypothesis + evidence engine for diagnosis
        ssh_collector : Callable(device, cmds) -> {cmd: output}
            SSH executor
        command_validator : Callable(cmd) -> bool
            Safety validator for commands
        approved_devices : List[Device]
            Approved network devices
        topology_graph : TopologyGraph, optional
            Current network topology
        pattern_db_path : str
            Path to pattern database
        """
        self.ai = ai_call
        self.troubleshoot_engine = troubleshoot_engine
        self.approved_devices = approved_devices
        self.topology = topology_graph

        # Phase 1: Semantic Intake
        self.intake = SemanticIntake(ai_call)

        # Phase 2: Remediation Executor
        self.executor = RemediationExecutor(
            ssh_collector=ssh_collector,
            command_validator=command_validator,
            approval_required=True,
            auto_rollback_on_failure=True
        )

        # Phase 3: Pattern Database
        self.pattern_db = PatternDatabase(pattern_db_path)

        # Phase 4: Prediction + Autonomy
        self.predictor = PatternPredictor(self.pattern_db)
        self.decision_maker = AutonomousDecisionMaker(
            self.pattern_db,
            confidence_threshold=0.85,
            success_rate_threshold=0.80
        )

        # Phase 4.5: External Knowledge Integration (for unknown issues)
        # Will be initialized lazily with RAG + web search
        self.external_knowledge: Optional[ExternalKnowledgeIntegrator] = None
        self.use_external_knowledge = False  # Flag to enable/disable

        logger.info("AutonomousNetworkTroubleshooter initialized with all 5 phases + external knowledge")

    def troubleshoot(self,
                     user_query: str,
                     operation_mode: str = "on_demand",
                     approval_callback: Optional[Callable] = None,
                     telemetry_metrics: Optional[Dict[str, Any]] = None) -> TroubleshootingSession:
        """
        Main entry point: user describes problem → system troubleshoots.

        Parameters
        ----------
        user_query : str
            User's problem description
        operation_mode : str
            "autonomous" | "on_demand" | "learning"
        approval_callback : Callable(RemediationPlan) -> bool
            Function to get human approval for fixes
        telemetry_metrics : Dict, optional
            Current telemetry (used for predictions in Path A)

        Returns
        -------
        TroubleshootingSession
            Complete trace from problem to resolution
        """
        logger.info(f"Starting troubleshooting session: {operation_mode} mode")

        # STEP 1: Parse problem (Phase 1)
        logger.info(f"Parsing user query: {user_query[:60]}")
        problem = self.intake.parse(user_query, self.approved_devices)

        # STEP 2: Route to path
        path = ExecutionPath(operation_mode)
        session = TroubleshootingSession(
            problem=problem,
            path=path,
            predictions=[]
        )

        # STEP 3: Path-specific workflows
        if path == ExecutionPath.AUTONOMOUS:
            self._execute_path_a_autonomous(session, approval_callback, telemetry_metrics)
        elif path == ExecutionPath.ON_DEMAND:
            self._execute_path_b_on_demand(session, approval_callback)
        else:  # LEARNING
            self._execute_path_c_learning(session)

        return session

    def _execute_path_a_autonomous(self,
                                   session: TroubleshootingSession,
                                   approval_callback: Optional[Callable] = None,
                                   telemetry_metrics: Optional[Dict[str, Any]] = None) -> None:
        """
        Path A: Fully Autonomous
        predict → diagnose → auto-fix (if confident) → verify → learn
        """
        logger.info("=== PATH A: AUTONOMOUS ===")

        # STEP 1: Predict issues before they happen (Phase 4)
        if telemetry_metrics:
            logger.info("Predicting potential issues...")
            predictions = self.predictor.predict_degradation(
                self.topology, telemetry_metrics
            )
            session.predictions = predictions

            if predictions:
                best_pred = predictions[0]
                logger.warning(
                    f"🔮 Predicted: {best_pred.issue_description} "
                    f"(ETA: {best_pred.eta_minutes:.0f}m, confidence: {best_pred.confidence:.0%})"
                )

        # STEP 2: Diagnose the actual problem (existing engine)
        logger.info("Diagnosing problem...")
        report = self.troubleshoot_engine.run(session.problem.raw_text)
        session.diagnosis_report = report.to_dict() if hasattr(report, "to_dict") else {}
        session.root_cause = report.root_cause if hasattr(report, "root_cause") else None
        session.diagnosis_confidence = report.confidence if hasattr(report, "confidence") else 0.5

        # STEP 2.5: If low confidence, search external sources
        if session.diagnosis_confidence < 0.75:
            if self._search_external_knowledge(session):
                logger.info("✨ Using external solution for autonomous path")

        # STEP 3: Decide on fix (Phase 4 - autonomous decision)
        if not session.suggested_fix and (report.fix if hasattr(report, "fix") else None):
            # Create remediation plan from internal diagnosis
            fix = report.fix
            plan = RemediationPlan(
                root_cause=session.root_cause or "Unknown",
                fix_explanation=fix.explanation if hasattr(fix, "explanation") else "",
                fix_commands=fix.commands if hasattr(fix, "commands") else [],
                rollback_commands=fix.rollback if hasattr(fix, "rollback") else [],
                verification_commands=fix.verify if hasattr(fix, "verify") else [],
                expected_outcome=fix.expected_outcome if hasattr(fix, "expected_outcome") else "",
                risk_level="medium",
            )
            session.suggested_fix = plan

        if session.suggested_fix:
            confidence = session.diagnosis_confidence
            plan = session.suggested_fix

            # If external solution, cap confidence at 0.95 (untested)
            if session.external_solution:
                confidence = min(confidence, external_solution.confidence)
                logger.warning("⚠️ Using untested external solution - confidence capped")

            # STEP 4: Autonomous decision
            should_auto_apply = self.decision_maker.should_auto_apply(
                session.root_cause or "",
                str(plan.fix_commands),
                confidence
            )

            if should_auto_apply and not session.external_solution:
                # Only auto-apply if NOT external (external always needs approval)
                logger.info("✅ Applying fix autonomously (high confidence + good track record)")
                result = self.executor.execute(
                    plan, self.approved_devices,
                    approval_callback=None  # No approval needed
                )
                session.execution_result = result
                session.outcome = result.outcome
            else:
                logger.info("⏳ Queuing for human approval (new/uncertain fix or external source)")
                if approval_callback:
                    approved = approval_callback(plan)
                    if approved:
                        result = self.executor.execute(
                            plan, self.approved_devices,
                            approval_callback=None
                        )
                        session.execution_result = result
                        session.outcome = result.outcome

        # STEP 5: Learn from outcome (Phase 3)
        self._record_and_learn(session)

    def _execute_path_b_on_demand(self,
                                  session: TroubleshootingSession,
                                  approval_callback: Optional[Callable] = None) -> None:
        """
        Path B: On-Demand Troubleshooting
        diagnose → [search external if low confidence] → approve → execute
        """
        logger.info("=== PATH B: ON-DEMAND TROUBLESHOOTING ===")

        # STEP 1: Diagnose
        logger.info("Running diagnosis...")
        report = self.troubleshoot_engine.run(session.problem.raw_text)
        session.diagnosis_report = report.to_dict() if hasattr(report, "to_dict") else {}
        session.root_cause = report.root_cause if hasattr(report, "root_cause") else None
        session.diagnosis_confidence = report.confidence if hasattr(report, "confidence") else 0.5

        # STEP 2: If low confidence, search external sources
        if session.diagnosis_confidence < 0.75:
            if self._search_external_knowledge(session):
                # External solution found, use it
                logger.info("✨ Using external solution")
            else:
                # No fix available (internal or external)
                if not (report.fix if hasattr(report, "fix") else None):
                    logger.warning("❌ No solution found (internal or external)")
                    self._record_and_learn(session)
                    return

        # STEP 3: Prepare fix
        if not session.suggested_fix:  # Not already set by external search
            if report.fix if hasattr(report, "fix") else None:
                fix = report.fix
                plan = RemediationPlan(
                    root_cause=session.root_cause or "Unknown",
                    fix_explanation=fix.explanation if hasattr(fix, "explanation") else "",
                    fix_commands=fix.commands if hasattr(fix, "commands") else [],
                    rollback_commands=fix.rollback if hasattr(fix, "rollback") else [],
                    verification_commands=fix.verify if hasattr(fix, "verify") else [],
                    expected_outcome=fix.expected_outcome if hasattr(fix, "expected_outcome") else "",
                    risk_level="medium",
                )
                session.suggested_fix = plan
            else:
                logger.warning("❌ No fix available")
                self._record_and_learn(session)
                return

        # STEP 4: Mark external fixes as requiring approval
        if session.external_solution:
            logger.warning(
                "⚠️ This is an untested fix from external sources - "
                "requires your approval and careful validation"
            )

        # STEP 5: Wait for approval
        logger.info("Awaiting human approval...")
        if approval_callback:
            approved = approval_callback(session.suggested_fix)
            if approved:
                logger.info("✅ Fix approved, executing...")
                result = self.executor.execute(
                    session.suggested_fix, self.approved_devices,
                    approval_callback=None
                )
                session.execution_result = result
                session.outcome = result.outcome
            else:
                logger.info("❌ Fix not approved")

        # STEP 6: Learn (optional for Path B, but supported)
        self._record_and_learn(session)

    def _execute_path_c_learning(self, session: TroubleshootingSession) -> None:
        """
        Path C: Learning-First
        Check pattern DB → diagnose → store pattern
        """
        logger.info("=== PATH C: LEARNING FIRST ===")

        # STEP 1: Check pattern DB for similar past incidents
        logger.info("Checking pattern database for similar issues...")
        suggestion = self.pattern_db.get_suggested_fix(session.problem.raw_text)

        if suggestion:
            logger.info(
                f"✨ Similar issue found: success rate {suggestion['success_rate']:.0%} "
                f"in {suggestion['precedent_count']} past incidents"
            )

        # STEP 2: Diagnose
        logger.info("Diagnosing...")
        report = self.troubleshoot_engine.run(session.problem.raw_text)
        session.diagnosis_report = report.to_dict() if hasattr(report, "to_dict") else {}
        session.root_cause = report.root_cause if hasattr(report, "root_cause") else None

        # STEP 3: Record in pattern DB (regardless of outcome)
        logger.info("Recording pattern for future reference...")
        if report.fix if hasattr(report, "fix") else None:
            fix = report.fix
            pattern_id = self.pattern_db.record_incident(
                problem_description=session.problem.raw_text,
                root_cause=session.root_cause or "Unknown",
                fix_applied=" | ".join(fix.commands) if hasattr(fix, "commands") else "",
                outcome="pending",  # Will be graded later
                time_minutes=0.0,
            )
            session.pattern_id = pattern_id
            logger.info(f"Pattern recorded: {pattern_id}")

    def _record_and_learn(self, session: TroubleshootingSession) -> None:
        """
        After execution, record outcome and update pattern confidence.

        This closes the learning loop for Paths A & B, and completes Path C.
        """
        if not session.root_cause or not session.outcome:
            return

        logger.info(f"Recording outcome: {session.outcome}")

        # Record incident in pattern DB
        fix_commands = ""
        if session.suggested_fix:
            fix_commands = " | ".join(session.suggested_fix.fix_commands)

        pattern_id = self.pattern_db.record_incident(
            problem_description=session.problem.raw_text,
            root_cause=session.root_cause,
            fix_applied=fix_commands,
            outcome=session.outcome,
            time_minutes=session.duration_seconds / 60,
            operator_feedback=f"Outcome: {session.outcome}",
        )

        session.pattern_id = pattern_id

        # Update confidence if this was a known pattern
        if session.path == ExecutionPath.LEARNING and session.pattern_id:
            self.pattern_db.update_confidence(
                session.pattern_id,
                session.outcome,
                operator_feedback="User confirmed outcome"
            )

        logger.info(f"✅ Pattern learned: {pattern_id}")

    # ── External Knowledge Integration ────────────────────────────────────────────

    def enable_external_knowledge(self,
                                  rag_engine: Any,
                                  web_search_fn: Optional[Callable] = None,
                                  mcp_tools: Optional[Any] = None) -> None:
        """
        Enable external knowledge integration for unknown issues.

        Parameters
        ----------
        rag_engine : RAGEngine
            Knowledge base retrieval engine (from core.knowledge.rag)
        web_search_fn : Callable, optional
            Web search function
        mcp_tools : Any, optional
            MCP tools for vendor APIs
        """
        from core.external_knowledge_layer import create_external_knowledge_integrator

        self.external_knowledge = create_external_knowledge_integrator(
            rag_engine=rag_engine,
            web_search_fn=web_search_fn,
            mcp_tools=mcp_tools,
            ai_call=self.ai,
        )
        self.use_external_knowledge = True
        logger.info("✅ External knowledge integration enabled (RAG + web search)")

    def _search_external_knowledge(self, session: TroubleshootingSession) -> bool:
        """
        Search external sources for solution to unknown issue.

        Returns
        -------
        bool
            True if external solution was found and applied, False otherwise
        """
        if not self.use_external_knowledge or not self.external_knowledge:
            return False

        if session.diagnosis_confidence >= 0.75:  # Good enough confidence
            return False

        logger.info("🔍 Diagnosis confidence too low, searching external sources...")
        external_solution = self.external_knowledge.find_solution_for_unknown_issue(
            problem_statement=session.problem,
            confidence=session.diagnosis_confidence
        )

        if not external_solution:
            logger.warning("  No external solutions found")
            return False

        logger.info(
            f"  ✅ Found external solution from {len(external_solution.sources)} source(s) "
            f"(confidence: {external_solution.confidence:.0%})"
        )

        # Store external solution in session
        session.external_solution = external_solution
        session.used_external_knowledge = True

        # Create remediation plan from external solution
        plan = RemediationPlan(
            root_cause=external_solution.root_cause,
            fix_explanation=external_solution.fix_explanation,
            fix_commands=external_solution.fix_commands,
            rollback_commands=external_solution.rollback_commands,
            verification_commands=external_solution.verification_commands,
            expected_outcome=external_solution.expected_outcome,
            risk_level=external_solution.risk_level,
        )
        session.suggested_fix = plan

        return True

    # ── Utility methods ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics."""
        return {
            "pattern_db": self.pattern_db.get_stats(),
            "approved_devices": len(self.approved_devices),
            "external_knowledge_enabled": self.use_external_knowledge,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Quick Integration Helper
# ═══════════════════════════════════════════════════════════════════════════════

def create_autonomous_troubleshooter(
    ai_call: Callable,
    troubleshoot_engine: Any,
    ssh_collector: Callable,
    command_validator: Callable,
    approved_devices: List[Any],
    topology: Optional[Any] = None,
) -> AutonomousNetworkTroubleshooter:
    """
    Factory function to create and initialize the autonomous troubleshooter.

    Recommended usage:
        from core.autonomous_troubleshooting import create_autonomous_troubleshooter

        troubleshooter = create_autonomous_troubleshooter(
            ai_call=ask_ai,
            troubleshoot_engine=ts_engine,
            ssh_collector=collector,
            command_validator=validator,
            approved_devices=devices,
            topology=graph,
        )

        session = troubleshooter.troubleshoot(
            user_query="Network is slow between NYC and SF",
            operation_mode="on_demand",
            approval_callback=lambda plan: st.button("Approve"),
        )
    """
    return AutonomousNetworkTroubleshooter(
        ai_call=ai_call,
        troubleshoot_engine=troubleshoot_engine,
        ssh_collector=ssh_collector,
        command_validator=command_validator,
        approved_devices=approved_devices,
        topology_graph=topology,
    )
