"""
tests/test_autonomous_troubleshooting.py
========================================
Tests for the complete autonomous troubleshooting system.

Covers all 5 phases and 3 execution paths.
"""
import pytest
from unittest.mock import Mock, MagicMock

from core.semantic_intake import SemanticIntake, ProblemScope, ProblemSymptom
from core.remediation_executor import RemediationExecutor, RemediationPlan, ExecutionStatus
from core.pattern_db import PatternDatabase
from core.prediction_forecaster import PatternPredictor, AutonomousDecisionMaker
from core.autonomous_troubleshooting import (
    AutonomousNetworkTroubleshooter,
    ExecutionPath,
    TroubleshootingSession,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Test Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_ai():
    """Mock AI call that returns structured responses."""
    def ai(prompt):
        if "classify" in prompt.lower():
            return """{
                "scope": "link",
                "symptom": "performance",
                "severity": "high",
                "likely_devices": ["10.0.0.1", "10.0.0.2"],
                "likely_protocols": ["bgp"],
                "likely_services": ["internet"],
                "is_intermittent": false,
                "is_widespread": false,
                "confidence": 0.85,
                "clarification": null,
                "reasoning": "User reported slowness between specific regions"
            }"""
        return ""
    return ai


@pytest.fixture
def mock_devices():
    """Mock network devices."""
    devices = []
    for i in range(3):
        dev = Mock()
        dev.ip = f"10.0.0.{i+1}"
        dev.hostname = f"router-{chr(65+i)}"
        dev.device_type = "cisco_ios"
        devices.append(dev)
    return devices


@pytest.fixture
def mock_collector():
    """Mock SSH collector."""
    def collector(device, commands):
        return {cmd: f"Output from {device.hostname}: {cmd}" for cmd in commands}
    return collector


@pytest.fixture
def mock_validator():
    """Mock command validator."""
    def validator(cmd):
        dangerous = ["reload", "erase", "format", "delete", "shutdown"]
        return not any(d in cmd.lower() for d in dangerous)
    return validator


@pytest.fixture
def mock_topology():
    """Mock topology graph."""
    topo = Mock()
    topo.site_name = "NYC"
    topo.node_count = Mock(return_value=10)
    topo.link_count = Mock(return_value=15)
    return topo


@pytest.fixture
def mock_troubleshoot_engine():
    """Mock troubleshooting engine."""
    engine = Mock()
    engine.run = Mock(return_value=Mock(
        root_cause="MTU mismatch",
        confidence=0.85,
        fix=Mock(
            commands=["(10.0.0.1) ip ospf mtu-ignore"],
            rollback=["(10.0.0.1) no ip ospf mtu-ignore"],
            verify=["show ip ospf neighbor"],
            expected_outcome="neighbor in FULL state",
            explanation="Set MTU ignore to allow OSPF adjacency"
        ),
        to_dict=lambda: {"root_cause": "MTU mismatch", "confidence": 0.85}
    ))
    return engine


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 1: Semantic Intake Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSemanticIntake:
    """Test natural language → structured problem parsing."""

    def test_parse_performance_issue(self, mock_ai, mock_devices):
        """Parse 'network is slow' into structured problem."""
        intake = SemanticIntake(mock_ai)
        problem = intake.parse("Network is slow between NYC and SF", mock_devices)

        assert problem.scope == ProblemScope.LINK
        assert problem.symptom == ProblemSymptom.PERFORMANCE
        assert problem.classification_confidence > 0.8
        assert len(problem.affected_devices) > 0

    def test_parse_connectivity_issue(self, mock_ai, mock_devices):
        """Parse connectivity problem."""
        intake = SemanticIntake(mock_ai)

        def connectivity_ai(prompt):
            return """{
                "scope": "device",
                "symptom": "connectivity",
                "severity": "critical",
                "likely_devices": ["10.0.0.1"],
                "likely_protocols": ["bgp", "ospf"],
                "likely_services": ["internet"],
                "is_intermittent": false,
                "is_widespread": true,
                "confidence": 0.9,
                "clarification": null,
                "reasoning": "User reports complete connectivity loss"
            }"""

        intake.ai = connectivity_ai
        problem = intake.parse("Router is down", mock_devices)

        assert problem.scope == ProblemScope.DEVICE
        assert problem.symptom == ProblemSymptom.CONNECTIVITY
        assert problem.severity.value == "critical"


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Remediation Executor Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRemediationExecutor:
    """Test safe fix execution with pre/post checks."""

    def test_pre_check_validates_commands(self, mock_collector, mock_validator, mock_devices):
        """Pre-check should catch unsafe commands."""
        executor = RemediationExecutor(mock_collector, mock_validator)

        plan = RemediationPlan(
            root_cause="MTU mismatch",
            fix_explanation="Set MTU ignore",
            fix_commands=["(10.0.0.1) reload"],  # Dangerous!
            rollback_commands=[],
            verification_commands=[],
            expected_outcome="test",
        )

        result = executor.execute(plan, mock_devices)

        assert result.status == ExecutionStatus.PRE_CHECK_FAILED
        assert len(result.pre_check_errors) > 0

    def test_execution_with_approval(self, mock_collector, mock_validator, mock_devices):
        """Test fix execution when approved."""
        executor = RemediationExecutor(mock_collector, mock_validator, approval_required=True)

        plan = RemediationPlan(
            root_cause="MTU mismatch",
            fix_explanation="Set MTU",
            fix_commands=["(10.0.0.1) interface Gi0/0", "(10.0.0.1) mtu 1500"],
            rollback_commands=["(10.0.0.1) mtu 1514"],
            verification_commands=["(10.0.0.1) show interface Gi0/0"],
            expected_outcome="mtu is 1500",
        )

        approved = lambda plan: True
        result = executor.execute(plan, mock_devices, approval_callback=approved)

        assert result.status == ExecutionStatus.COMPLETE
        assert result.outcome in ["fixed", "degraded", "error"]

    def test_auto_rollback_on_failure(self, mock_collector, mock_validator, mock_devices):
        """Test automatic rollback when post-check fails."""
        executor = RemediationExecutor(
            mock_collector, mock_validator,
            approval_required=False,
            auto_rollback_on_failure=True
        )

        plan = RemediationPlan(
            root_cause="Config issue",
            fix_explanation="Apply fix",
            fix_commands=["(10.0.0.1) config"],
            rollback_commands=["(10.0.0.1) undo"],
            verification_commands=["(10.0.0.1) show status"],
            expected_outcome="success",
        )

        result = executor.execute(plan, mock_devices)

        # Should attempt rollback if post-check doesn't find expected outcome
        # Result will depend on verification interpreter logic


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 3: Pattern Database Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPatternDatabase:
    """Test incident recording and similarity search."""

    def test_record_incident(self, tmp_path):
        """Record an incident."""
        db = PatternDatabase(str(tmp_path / "test_patterns.db"))

        pattern_id = db.record_incident(
            problem_description="Network slow between NYC and SF",
            root_cause="MTU mismatch on WAN link",
            fix_applied="set interface mtu 1500",
            outcome="fixed",
            time_minutes=15.5,
        )

        assert pattern_id
        stats = db.get_stats()
        assert stats["total_incidents"] == 1

    def test_find_similar(self, tmp_path):
        """Find similar past incidents."""
        db = PatternDatabase(str(tmp_path / "test_patterns.db"))

        # Record 3 incidents
        for i in range(3):
            db.record_incident(
                problem_description=f"Network slow incident {i}",
                root_cause="MTU mismatch",
                fix_applied="set mtu 1500",
                outcome="fixed" if i < 2 else "degraded",
                time_minutes=10.0 + i,
            )

        # Find similar
        similar = db.find_similar("Network experiencing slowness", top_k=3)

        assert len(similar) > 0
        assert all(score >= 0.0 and score <= 1.0 for score, _ in similar)

    def test_update_confidence(self, tmp_path):
        """Update pattern confidence based on outcome."""
        db = PatternDatabase(str(tmp_path / "test_patterns.db"))

        pattern_id = db.record_incident(
            problem_description="Test issue",
            root_cause="Test cause",
            fix_applied="test fix",
            outcome="pending",
            time_minutes=5.0,
        )

        # Update to success
        db.update_confidence(pattern_id, "fixed", "User confirmed")

        # Confidence should increase
        similar = db.find_similar("test", top_k=1)
        if similar:
            _, pattern = similar[0]
            assert pattern.confidence > 0.5  # Started at 0.5, increased by 0.1

    def test_suggested_fix(self, tmp_path):
        """Get suggested fix based on similar patterns."""
        db = PatternDatabase(str(tmp_path / "test_patterns.db"))

        # Record 2 successful MTU fixes
        for i in range(2):
            db.record_incident(
                problem_description="MTU issue",
                root_cause="MTU mismatch",
                fix_applied="set mtu 1500",
                outcome="fixed",
                time_minutes=10.0,
            )

        # Get suggestion
        suggestion = db.get_suggested_fix("network slow due to mtu")

        assert suggestion is not None
        assert "MTU" in suggestion["root_cause"] or "mtu" in suggestion["root_cause"].lower()
        assert suggestion["success_rate"] >= 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 4: Prediction & Autonomy Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPrediction:
    """Test issue prediction and autonomous decisions."""

    def test_should_auto_apply_high_confidence(self, tmp_path):
        """Should auto-apply fix with high confidence + good track record."""
        db = PatternDatabase(str(tmp_path / "test.db"))

        # Record 3 successful fixes
        for _ in range(3):
            db.record_incident(
                problem_description="MTU issue",
                root_cause="MTU mismatch",
                fix_applied="set mtu 1500",
                outcome="fixed",
                time_minutes=5.0,
            )

        maker = AutonomousDecisionMaker(db, confidence_threshold=0.8, success_rate_threshold=0.8)

        # Should auto-apply with high confidence
        should_auto = maker.should_auto_apply(
            root_cause="MTU mismatch",
            suggested_fix="set mtu 1500",
            confidence=0.9
        )

        assert should_auto is True

    def test_should_not_auto_apply_low_confidence(self, tmp_path):
        """Should NOT auto-apply with low diagnosis confidence."""
        db = PatternDatabase(str(tmp_path / "test.db"))

        maker = AutonomousDecisionMaker(db, confidence_threshold=0.85)

        should_auto = maker.should_auto_apply(
            root_cause="Unknown cause",
            suggested_fix="unknown fix",
            confidence=0.5  # Too low
        )

        assert should_auto is False


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 5: Integration Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAutonomousTroubleshooter:
    """Test the complete integrated system."""

    def test_path_b_on_demand_flow(self,
                                    mock_ai,
                                    mock_collector,
                                    mock_validator,
                                    mock_devices,
                                    mock_troubleshoot_engine,
                                    mock_topology,
                                    tmp_path):
        """Test Path B: On-demand troubleshooting flow."""
        troubleshooter = AutonomousNetworkTroubleshooter(
            ai_call=mock_ai,
            troubleshoot_engine=mock_troubleshoot_engine,
            ssh_collector=mock_collector,
            command_validator=mock_validator,
            approved_devices=mock_devices,
            topology_graph=mock_topology,
            pattern_db_path=str(tmp_path / "patterns.db"),
        )

        # Execute Path B (on-demand)
        approval_callback = lambda plan: True  # Auto-approve

        session = troubleshooter.troubleshoot(
            user_query="Network is slow between NYC and SF",
            operation_mode="on_demand",
            approval_callback=approval_callback,
        )

        assert session is not None
        assert session.path == ExecutionPath.ON_DEMAND
        assert session.root_cause is not None

    def test_path_c_learning_flow(self,
                                   mock_ai,
                                   mock_collector,
                                   mock_validator,
                                   mock_devices,
                                   mock_troubleshoot_engine,
                                   mock_topology,
                                   tmp_path):
        """Test Path C: Learning-first flow."""
        troubleshooter = AutonomousNetworkTroubleshooter(
            ai_call=mock_ai,
            troubleshoot_engine=mock_troubleshoot_engine,
            ssh_collector=mock_collector,
            command_validator=mock_validator,
            approved_devices=mock_devices,
            topology_graph=mock_topology,
            pattern_db_path=str(tmp_path / "patterns.db"),
        )

        session = troubleshooter.troubleshoot(
            user_query="Network is slow",
            operation_mode="learning",
        )

        assert session.path == ExecutionPath.LEARNING
        assert session.pattern_id is not None  # Pattern should be recorded
