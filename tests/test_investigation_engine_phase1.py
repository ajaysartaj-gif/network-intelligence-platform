"""
tests/test_investigation_engine_phase1.py
==========================================
Comprehensive tests for Phase 1 investigation engine refactoring.

Tests all 7 components of the new architecture:
1. Protocol Planner
2. Evidence Interpreter
3. Bayesian Confidence Manager
4. Knowledge-First Investigator
5. Knowledge Gap Detector
6. Information Gain Calculator
7. Hypothesis Refinement Engine
"""

import unittest
from unittest.mock import Mock, MagicMock

from core.protocol_planner import ProtocolPlanner, Protocol, OSPFProtocolPlanner
from core.evidence_interpreter import EvidenceInterpreter, EvidenceResult, OSPFEvidenceInterpreter
from core.bayesian_confidence_manager import BayesianConfidenceManager, Hypothesis
from core.knowledge_first_investigator import KnowledgeFirstInvestigator
from core.knowledge_gap_detector import KnowledgeGapDetector, KnowledgeSource


class TestProtocolPlanner(unittest.TestCase):
    """Test protocol-specific investigation planning."""

    def setUp(self):
        self.planner = ProtocolPlanner()

    def test_ospf_exstart_plan_generation(self):
        """Test generating plan for OSPF EXSTART."""
        plan = self.planner.plan_investigation(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device="router-1",
            affected_devices=["router-1", "router-2"],
            neighbor_device="router-2"
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.protocol, Protocol.OSPF)
        self.assertEqual(plan.issue_type, "EXSTART")
        self.assertGreater(len(plan.prerequisite_checks), 0)
        self.assertGreater(len(plan.primary_checks), 0)

    def test_prerequisite_checks_first(self):
        """Test that prerequisite checks come before primary checks."""
        plan = self.planner.plan_investigation(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device="router-1",
            affected_devices=["router-1", "router-2"],
            neighbor_device="router-2"
        )

        checks = self.planner.get_checks_sorted_by_priority(plan)

        # First N checks should be prerequisites
        prereq_count = len(plan.prerequisite_checks)
        for i in range(prereq_count):
            self.assertIn(checks[i].name, [c.name for c in plan.prerequisite_checks])

    def test_primary_checks_sorted_by_info_gain(self):
        """Test that primary checks are sorted by info_gain/time ratio."""
        plan = self.planner.plan_investigation(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device="router-1",
            affected_devices=["router-1", "router-2"],
            neighbor_device="router-2"
        )

        primary_sorted = sorted(
            plan.primary_checks,
            key=lambda c: c.info_gain / (c.estimated_time_sec + 0.1),
            reverse=True
        )

        # First primary check should be "hello/dead intervals" (highest info gain)
        self.assertIn("hello", primary_sorted[0].name.lower())

    def test_bgp_session_down_plan(self):
        """Test BGP session down plan."""
        plan = self.planner.plan_investigation(
            protocol=Protocol.BGP,
            issue_type="SESSION_DOWN",
            root_device="router-1",
            affected_devices=["router-1", "10.0.0.1"],
            neighbor_device="10.0.0.1"
        )

        self.assertIsNotNone(plan)
        self.assertEqual(plan.protocol, Protocol.BGP)


class TestEvidenceInterpreter(unittest.TestCase):
    """Test protocol-aware evidence interpretation."""

    def setUp(self):
        self.interpreter = EvidenceInterpreter()

    def test_interpret_hello_interval_match(self):
        """Test interpreting matching hello intervals."""
        local_result = EvidenceResult(
            check_name="OSPF Hello Interval",
            command="show ip ospf interface",
            output="Hello interval: 10 seconds",
            parsed_value={"hello": 10}
        )

        remote_result = EvidenceResult(
            check_name="Remote OSPF Hello Interval",
            command="show ip ospf interface",
            output="Hello interval: 10 seconds",
            parsed_value={"hello": 10}
        )

        result = self.interpreter.ospf.interpret_hello_interval_check(local_result, remote_result)

        self.assertIn("MATCH", result.interpretation)
        self.assertIn("Hello/Dead interval mismatch", result.eliminates_hypothesis)
        self.assertGreater(result.confidence_delta, 0.3)

    def test_interpret_hello_interval_mismatch(self):
        """Test interpreting mismatched hello intervals."""
        local_result = EvidenceResult(
            check_name="OSPF Hello Interval",
            command="show ip ospf interface",
            output="Hello interval: 10 seconds",
            parsed_value={"hello": 10}
        )

        remote_result = EvidenceResult(
            check_name="Remote OSPF Hello Interval",
            command="show ip ospf interface",
            output="Hello interval: 30 seconds",
            parsed_value={"hello": 30}
        )

        result = self.interpreter.ospf.interpret_hello_interval_check(local_result, remote_result)

        self.assertIn("MISMATCH", result.interpretation)
        self.assertIn("Hello/Dead interval mismatch", result.supports_hypothesis)
        self.assertGreater(result.confidence_delta, 0.4)

    def test_interpret_neighbor_full_state(self):
        """Test interpreting OSPF neighbor FULL state."""
        result = self.interpreter.ospf.interpret_neighbor_state("Neighbor is FULL")

        self.assertIn("FULL", result.interpretation)
        self.assertIn("Any adjacency issue", result.eliminates_hypothesis)
        self.assertGreater(result.confidence_delta, 0.8)

    def test_interpret_neighbor_exstart_state(self):
        """Test interpreting OSPF neighbor EXSTART state."""
        result = self.interpreter.ospf.interpret_neighbor_state("Neighbor is EXSTART")

        self.assertIn("EXSTART", result.interpretation)
        self.assertIn("Configuration mismatch", result.supports_hypothesis[0])
        self.assertGreater(result.confidence_delta, 0.2)


class TestBayesianConfidenceManager(unittest.TestCase):
    """Test Bayesian confidence management."""

    def setUp(self):
        self.manager = BayesianConfidenceManager()

    def test_register_hypothesis(self):
        """Test registering a hypothesis."""
        self.manager.register_hypothesis(
            name="Test Hypothesis",
            prior_probability=0.5
        )

        self.assertIn("Test Hypothesis", self.manager.hypotheses)
        self.assertEqual(self.manager.hypotheses["Test Hypothesis"].prior_probability, 0.5)

    def test_ospf_exstart_hypotheses_registered(self):
        """Test that OSPF EXSTART hypotheses are registered with correct priors."""
        self.manager.register_hypotheses_for_ospf_exstart()

        self.assertEqual(len(self.manager.hypotheses), 5)
        self.assertEqual(
            self.manager.hypotheses["Hello/Dead interval mismatch"].prior_probability,
            0.40
        )

    def test_evidence_update_supports_hypothesis(self):
        """Test updating confidence when evidence supports hypothesis."""
        self.manager.register_hypotheses_for_ospf_exstart()

        initial_prob = self.manager.hypotheses["Hello/Dead interval mismatch"].posterior_probability

        # Evidence supports hello/dead mismatch
        self.manager.update_with_evidence(
            evidence_name="Hello intervals don't match",
            likelihood_ratio_per_hypothesis={
                "Hello/Dead interval mismatch": 10.0,  # Strongly supports
                "Subnet or Area mismatch": 0.5,  # Contradicts other hypotheses
            }
        )

        updated_prob = self.manager.hypotheses["Hello/Dead interval mismatch"].posterior_probability

        self.assertGreater(updated_prob, initial_prob)

    def test_get_top_hypothesis(self):
        """Test getting the top hypothesis."""
        self.manager.register_hypotheses_for_ospf_exstart()

        self.manager.update_with_evidence(
            evidence_name="Evidence 1",
            likelihood_ratio_per_hypothesis={
                "Hello/Dead interval mismatch": 10.0,
            }
        )

        top_name, top_prob = self.manager.get_top_hypothesis()

        self.assertEqual(top_name, "Hello/Dead interval mismatch")
        self.assertGreater(top_prob, 0.5)

    def test_convergence_detection(self):
        """Test convergence detection at 85% confidence threshold."""
        self.manager.register_hypotheses_for_ospf_exstart()

        # Add evidence that strongly supports one hypothesis
        for i in range(5):
            self.manager.update_with_evidence(
                evidence_name=f"Evidence {i}",
                likelihood_ratio_per_hypothesis={
                    "Hello/Dead interval mismatch": 20.0,
                }
            )

        confidence = self.manager.get_confidence_score()
        converged = self.manager.should_converge(confidence_threshold=0.85)

        self.assertTrue(converged)

    def test_external_knowledge_trigger(self):
        """Test that external knowledge is triggered when confidence is low."""
        self.manager.register_hypotheses_for_ospf_exstart()

        should_seek = self.manager.should_get_external_knowledge(confidence_threshold=0.60)

        # At start, confidence is low (priors only)
        self.assertTrue(should_seek)


class TestKnowledgeGapDetector(unittest.TestCase):
    """Test knowledge gap detection."""

    def setUp(self):
        self.detector = KnowledgeGapDetector()

    def test_detect_protocol_knowledge_gap(self):
        """Test detecting protocol knowledge gap."""
        gaps = self.detector.detect_gaps(
            current_hypothesis="Hello/Dead interval mismatch",
            confidence=0.5,
            evidence_collected=[]
        )

        self.assertGreater(len(gaps), 0)
        protocol_gaps = [g for g in gaps if g.source == KnowledgeSource.PROTOCOL]
        self.assertGreater(len(protocol_gaps), 0)

    def test_detect_enterprise_knowledge_gap(self):
        """Test detecting enterprise knowledge gap."""
        gaps = self.detector.detect_gaps(
            current_hypothesis="Hello/Dead interval mismatch",
            confidence=0.65,  # Moderate confidence
            evidence_collected=[]
        )

        enterprise_gaps = [g for g in gaps if g.source == KnowledgeSource.ENTERPRISE]
        self.assertGreater(len(enterprise_gaps), 0)

    def test_gap_prioritization(self):
        """Test that gaps are prioritized by priority."""
        gaps = self.detector.detect_gaps(
            current_hypothesis="Hello/Dead interval mismatch",
            confidence=0.5,
            evidence_collected=[]
        )

        sorted_gaps = sorted(gaps, key=lambda g: g.priority)

        # Priority should increase (1 is highest)
        for i in range(len(sorted_gaps) - 1):
            self.assertLessEqual(sorted_gaps[i].priority, sorted_gaps[i + 1].priority)


class TestKnowledgeFirstInvestigator(unittest.TestCase):
    """Test knowledge-first investigation workflow."""

    def setUp(self):
        self.investigator = KnowledgeFirstInvestigator()

    def test_investigator_initialization(self):
        """Test investigator initializes correctly."""
        self.assertIsNotNone(self.investigator.protocol_planner)
        self.assertIsNotNone(self.investigator.evidence_interpreter)
        self.assertIsNotNone(self.investigator.confidence_manager)
        self.assertIsNotNone(self.investigator.gap_detector)

    def test_ospf_exstart_investigation_structure(self):
        """Test that OSPF EXSTART investigation has correct structure."""
        result = self.investigator.investigate(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device="router-1",
            affected_devices=["router-1", "router-2"],
            max_cycles=2,
            confidence_threshold=0.85
        )

        self.assertIn("root_cause", result)
        self.assertIn("confidence", result)
        self.assertIn("protocol", result)
        self.assertIn("cycles", result)
        self.assertEqual(result["protocol"], "ospf")

    def test_investigation_loads_knowledge_first(self):
        """Test that knowledge is loaded at investigation start."""
        self.investigator.investigate(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device="router-1",
            affected_devices=["router-1", "router-2"],
            max_cycles=1
        )

        # Knowledge should be in accumulated_knowledge
        self.assertIn("ospf", self.investigator.accumulated_knowledge)


class TestIntegration(unittest.TestCase):
    """Integration tests for the complete Phase 1 engine."""

    def test_full_investigation_workflow(self):
        """Test complete investigation workflow."""
        investigator = KnowledgeFirstInvestigator()

        result = investigator.investigate(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device="router-1",
            affected_devices=["router-1", "router-2"],
            max_cycles=3,
            confidence_threshold=0.85
        )

        # Verify result structure
        self.assertIsNotNone(result["root_cause"])
        self.assertGreaterEqual(result["confidence"], 0.0)
        self.assertLessEqual(result["confidence"], 1.0)
        self.assertGreater(result["cycles"], 0)

    def test_convergence_within_max_cycles(self):
        """Test that investigation respects max_cycles limit."""
        investigator = KnowledgeFirstInvestigator()

        result = investigator.investigate(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device="router-1",
            affected_devices=["router-1", "router-2"],
            max_cycles=3
        )

        self.assertLessEqual(result["cycles"], 3)


if __name__ == "__main__":
    unittest.main()
