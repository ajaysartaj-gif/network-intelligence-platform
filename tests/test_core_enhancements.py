"""
tests/test_core_enhancements.py
===============================
Comprehensive tests for all 6 core enhancements.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import asyncio
import numpy as np

from core.explainability import ExplainabilityEngine, ExplanationStep
from core.multi_device_orchestrator import MultiDeviceOrchestrator, DeviceCommand
from core.predictive_forecaster_enhanced import PredictiveForecaster, PredictedIssue
from core.hypothesis_generator import AIHypothesisGenerator, GeneratedHypothesis
from core.reinforcement_learning import ReinforcementLearningEngine, CategoryStats
from core.network_health_scorer import NetworkHealthScorer


class TestExplainabilityEngine(unittest.TestCase):
    """Test explanation generation."""

    def setUp(self):
        self.explainer = ExplainabilityEngine()

    def test_explain_full_session(self):
        """Test full session explanation."""
        session = Mock()
        session.problem = Mock()
        session.problem.raw_text = "Network slow"
        session.problem.scope = "link"
        session.problem.symptom = "performance"
        session.problem.severity = "high"
        session.problem.affected_devices = ["router-1"]
        session.problem.confidence = 0.85
        session.diagnosis_confidence = 0.80
        session.root_cause = "MTU mismatch"
        session.suggested_fix = Mock()
        session.suggested_fix.root_cause = "MTU too low"
        session.suggested_fix.fix_explanation = "Set MTU to 1500"
        session.suggested_fix.expected_outcome = "Network speed normal"
        session.suggested_fix.risk_level = "low"
        session.suggested_fix.fix_commands = ["interface Gi0/0", "mtu 1500"]
        session.suggested_fix.rollback_commands = ["interface Gi0/0", "mtu 1514"]
        session.suggested_fix.verification_commands = ["show interface Gi0/0"]
        session.external_solution = None
        session.execution_result = None
        session.outcome = None
        session.duration_seconds = 0

        explanations = self.explainer.explain_full_session(session)

        assert len(explanations) >= 4
        assert explanations[0].stage == "intake"
        assert explanations[1].stage == "diagnosis"

    def test_explanation_output(self):
        """Test explanation can be rendered."""
        session = Mock()
        session.problem = Mock(raw_text="Test", scope="device", symptom="connectivity",
                              severity="high", affected_devices=["dev1"], confidence=0.8)
        session.diagnosis_confidence = 0.75
        session.root_cause = "Test cause"
        session.suggested_fix = Mock(root_cause="Test", fix_explanation="Test fix",
                                     expected_outcome="Fixed", risk_level="low",
                                     fix_commands=[], rollback_commands=[],
                                     verification_commands=[])
        session.external_solution = None
        session.execution_result = None
        session.outcome = None
        session.duration_seconds = 1.0

        explanations = self.explainer.explain_full_session(session)
        summary = self.explainer.generate_summary(session)

        assert "SUMMARY" in summary
        assert "Test cause" in summary


class TestMultiDeviceOrchestrator(unittest.TestCase):
    """Test multi-device coordination."""

    def setUp(self):
        self.orchestrator = MultiDeviceOrchestrator()

    def test_build_dependency_graph(self):
        """Test dependency graph construction."""
        commands = [
            DeviceCommand(device="PE1", commands=[], depends_on=[]),
            DeviceCommand(device="CE1", commands=[], depends_on=["PE1"]),
            DeviceCommand(device="CE2", commands=[], depends_on=["PE1"]),
        ]

        dag = self.orchestrator._build_dependency_graph(commands)

        assert "PE1" in dag.nodes()
        assert "CE1" in dag.nodes()
        assert dag.has_edge("PE1", "CE1")
        assert dag.has_edge("PE1", "CE2")

    def test_identify_parallelizable_levels(self):
        """Test level identification."""
        commands = [
            DeviceCommand(device="PE1", commands=[], depends_on=[]),
            DeviceCommand(device="PE2", commands=[], depends_on=[]),
            DeviceCommand(device="CE1", commands=[], depends_on=["PE1"]),
            DeviceCommand(device="CE2", commands=[], depends_on=["PE2"]),
        ]

        dag = self.orchestrator._build_dependency_graph(commands)
        levels = self.orchestrator._identify_parallelizable_levels(dag)

        # Level 1: PE1 and PE2 in parallel
        # Level 2: CE1 and CE2 in parallel
        assert len(levels) == 2
        assert set(levels[0]) == {"PE1", "PE2"}
        assert set(levels[1]) == {"CE1", "CE2"}

    def test_print_execution_plan(self):
        """Test execution plan generation."""
        commands = [
            DeviceCommand(device="dev1", commands=["cmd1"], description="Step 1"),
            DeviceCommand(device="dev2", commands=["cmd2"], depends_on=["dev1"],
                         description="Step 2"),
        ]

        plan = self.orchestrator.print_execution_plan(commands)

        assert "Step 1" in plan or "dev1" in plan
        assert "Step 2" in plan or "dev2" in plan


class TestPredictiveForecaster(unittest.TestCase):
    """Test predictive forecasting."""

    def setUp(self):
        self.predictor = PredictiveForecaster()

    def test_predict_cpu_exhaustion(self):
        """Test CPU exhaustion prediction."""
        # Simulate CPU trending from 60% to 85% (up 25% over time)
        telemetry = {
            "router-1": {
                "cpu": [60.0, 65.0, 70.0, 75.0, 80.0, 85.0]  # Trending up
            }
        }

        predictions = self.predictor.predict_issues_24h_ahead(telemetry)

        # Should predict CPU exhaustion
        cpu_preds = [p for p in predictions if p.issue_type == "cpu_exhaustion"]
        assert len(cpu_preds) > 0

    def test_predict_memory_exhaustion(self):
        """Test memory exhaustion prediction."""
        telemetry = {
            "router-1": {
                "memory": [50.0, 55.0, 60.0, 65.0, 70.0, 75.0]  # Trending up
            }
        }

        predictions = self.predictor.predict_issues_24h_ahead(telemetry)

        mem_preds = [p for p in predictions if p.issue_type == "memory_exhaustion"]
        assert len(mem_preds) > 0

    def test_calculate_trend(self):
        """Test trend calculation."""
        values = [10.0, 11.0, 12.0, 13.0, 14.0]  # Up 1 per period
        trend = self.predictor._calculate_trend(values)

        # Should be positive (trending up)
        assert trend > 0

    def test_print_predictions(self):
        """Test prediction report generation."""
        predictions = [
            PredictedIssue(
                device="dev1",
                issue_type="cpu_exhaustion",
                eta_hours=4.0,
                confidence=0.85,
                current_value=85.0,
                threshold_value=90.0,
                trend_rate=0.1,
                urgency="high"
            )
        ]

        report = self.predictor.print_predictions(predictions)

        assert "cpu_exhaustion" in report
        assert "4.0" in report or "4" in report


class TestAIHypothesisGenerator(unittest.TestCase):
    """Test hypothesis generation."""

    def setUp(self):
        self.generator = AIHypothesisGenerator(ai_call=Mock())

    def test_parse_hypotheses(self):
        """Test hypothesis parsing."""
        response = """
HYPOTHESIS 1:
Hypothesis: MTU mismatch on WAN link
Reasoning: Packets fragmented, causing loss
Test: ping -df -s 1472 destination
Fix: Set MTU to 1500
Confidence: 85

HYPOTHESIS 2:
Hypothesis: BGP session instability
Reasoning: Neighbors flapping
Test: show bgp neighbors
Fix: Clear BGP session
Confidence: 70
"""

        hypotheses = self.generator._parse_hypotheses_from_response(response, 3)

        assert len(hypotheses) > 0
        assert hypotheses[0].hypothesis != ""
        assert hypotheses[0].confidence > 0


class TestReinforcementLearning(unittest.TestCase):
    """Test learning from outcomes."""

    def setUp(self):
        self.learner = ReinforcementLearningEngine()

    def test_calculate_reward(self):
        """Test reward calculation."""
        assert self.learner._calculate_reward("fixed") == 1.0
        assert self.learner._calculate_reward("degraded") == -0.5
        assert self.learner._calculate_reward("error") == -1.0

    def test_update_category_stats(self):
        """Test category statistics."""
        session = Mock()
        session.problem = Mock(scope="device", symptom="connectivity")
        session.diagnosis_confidence = 0.85
        session.duration_seconds = 30.0

        self.learner._update_category_stats(session, success=True)
        self.learner._update_category_stats(session, success=True)
        self.learner._update_category_stats(session, success=False)

        category = ("device", "connectivity")
        assert category in self.learner.category_stats
        stats = self.learner.category_stats[category]
        assert stats.total == 3
        assert stats.successes == 2
        assert stats.success_rate == 2 / 3

    def test_learning_report(self):
        """Test learning report generation."""
        session = Mock()
        session.problem = Mock(scope="link", symptom="performance")
        session.diagnosis_confidence = 0.8
        session.duration_seconds = 5.0

        self.learner._update_category_stats(session, success=True)
        report = self.learner.print_learning_report()

        assert "LEARNING REPORT" in report


class TestNetworkHealthScorer(unittest.TestCase):
    """Test network health scoring."""

    def setUp(self):
        self.scorer = NetworkHealthScorer()

    def test_score_to_grade(self):
        """Test score to grade conversion."""
        assert "A" in self.scorer._score_to_grade(95)
        assert "B" in self.scorer._score_to_grade(80)
        assert "C" in self.scorer._score_to_grade(65)
        assert "D" in self.scorer._score_to_grade(45)
        assert "F" in self.scorer._score_to_grade(20)

    def test_calculate_health(self):
        """Test health calculation."""
        telemetry = {
            "router-1": {
                "cpu": [50.0, 55.0, 60.0],
                "memory": [40.0, 42.0, 44.0],
            }
        }

        health = self.scorer.calculate_network_health(telemetry)

        assert "overall_health" in health
        assert "health_grade" in health
        assert 0 <= health["overall_health"] <= 100

    def test_print_health_report(self):
        """Test health report generation."""
        telemetry = {
            "router-1": {
                "cpu": [50.0, 55.0, 60.0],
            }
        }

        health = self.scorer.calculate_network_health(telemetry)
        report = self.scorer.print_health_report(health)

        assert "HEALTH REPORT" in report
        assert "Grade" in report


if __name__ == "__main__":
    unittest.main()
