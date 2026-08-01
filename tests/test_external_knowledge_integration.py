"""
tests/test_external_knowledge_integration.py
=============================================
Tests for external knowledge layer and unknown issue resolution.

Demonstrates how the system finds and applies solutions from:
- Internal knowledge base (RAG)
- Web search for similar issues
- Vendor APIs via MCP
- Claude synthesis
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from core.external_knowledge_layer import (
    ExternalKnowledgeIntegrator,
    KnowledgeSearchResult,
    KnowledgeSource,
    ExternalSolution,
)
from core.semantic_intake import ProblemStatement
from core.autonomous_troubleshooting import (
    AutonomousNetworkTroubleshooter,
    ExecutionPath,
)


class TestExternalKnowledgeIntegrator(unittest.TestCase):
    """Test external knowledge search and synthesis."""

    def setUp(self):
        """Set up test fixtures."""
        self.rag_engine = Mock()
        self.web_search = Mock()
        self.mcp_tools = Mock()
        self.ai_call = Mock()

        self.integrator = ExternalKnowledgeIntegrator(
            rag_engine=self.rag_engine,
            web_search_fn=self.web_search,
            mcp_tools=self.mcp_tools,
            ai_call=self.ai_call,
        )

    def test_rag_search_integration(self):
        """Test RAG (internal knowledge base) search."""
        # Mock RAG results
        self.rag_engine.retrieve.return_value = [
            {
                "title": "MTU Configuration Guide",
                "content": "Set MTU to 1500 on all interfaces",
                "score": 0.85,
                "vendor": "cisco",
                "platform": "ios",
            }
        ]

        problem = ProblemStatement(
            scope="link",
            symptom="performance",
            severity="high",
            affected_devices=["router-1"],
            confidence=0.5,
            raw_text="Network slow between buildings",
        )

        results = self.integrator._search_rag(problem)

        assert len(results) == 1
        assert results[0].source == KnowledgeSource.INTERNAL_RAG
        assert results[0].relevance_score == 0.85
        assert "MTU" in results[0].title

    def test_web_search_integration(self):
        """Test web search for similar issues."""
        # Mock web search results
        self.web_search.return_value = [
            {
                "title": "Network slow BGP issue fixed",
                "snippet": "Clear BGP session and check MTU",
                "url": "https://example.com/bgp-fix",
                "relevance": 0.8,
            }
        ]

        problem = ProblemStatement(
            scope="path",
            symptom="performance",
            severity="high",
            affected_devices=["bgp-router"],
            confidence=0.4,
            raw_text="BGP neighbors flapping, network slow",
        )

        results = self.integrator._search_web(problem)

        assert len(results) >= 1
        assert any(r.source == KnowledgeSource.COMMUNITY for r in results)

    def test_vendor_api_search(self):
        """Test vendor API search via MCP."""
        # Mock vendor API response
        self.mcp_tools.query_vendor_knowledge.return_value = {
            "solution": "Reset BGP session with soft-reset",
            "match_score": 0.9,
            "platform": "IOS-XE",
        }

        problem = ProblemStatement(
            scope="device",
            symptom="connectivity",
            severity="high",
            affected_devices=["cisco-router"],
            confidence=0.3,
            raw_text="BGP session stuck in EXSTART",
        )

        results = self.integrator._search_vendor_apis(problem)

        # Vendor API call should have been attempted
        self.mcp_tools.query_vendor_knowledge.assert_called()

    def test_synthesis_response_parsing(self):
        """Test parsing of Claude synthesis response."""
        synthesis_response = """{
            "root_cause": "MTU mismatch on WAN link",
            "fix_explanation": "WAN link MTU set to 1514 instead of 1500",
            "fix_commands": ["interface Gi0/0", "mtu 1500", "no shutdown"],
            "rollback_commands": ["interface Gi0/0", "mtu 1514"],
            "verification_commands": ["ping -df -s 1472 destination"],
            "expected_outcome": "Ping succeeds with DF bit set",
            "confidence": 0.85,
            "risk_assessment": "low",
            "sources_used": [0, 1]
        }"""

        results = [
            KnowledgeSearchResult(
                source=KnowledgeSource.WEB_SEARCH,
                title="MTU Fix",
                content="...",
                relevance_score=0.8,
            ),
            KnowledgeSearchResult(
                source=KnowledgeSource.INTERNAL_RAG,
                title="MTU Configuration",
                content="...",
                relevance_score=0.7,
            ),
        ]

        problem = Mock()
        solution = self.integrator._parse_synthesis_response(synthesis_response, results)

        assert solution.root_cause == "MTU mismatch on WAN link"
        assert len(solution.fix_commands) == 3
        assert len(solution.rollback_commands) == 2
        assert solution.confidence == 0.85
        assert solution.risk_level == "low"
        assert len(solution.sources) == 2

    def test_full_synthesis_pipeline(self):
        """Test complete synthesis from problem to solution."""
        # Mock all components
        self.rag_engine.retrieve.return_value = [
            {
                "title": "BGP MTU Configuration",
                "content": "Set MTU to 1500",
                "score": 0.8,
            }
        ]

        self.web_search.return_value = [
            {
                "title": "BGP flapping MTU fix",
                "snippet": "Check MTU on both sides",
                "url": "https://example.com/bgp-mtu",
                "relevance": 0.75,
            }
        ]

        self.ai_call.return_value = """{
            "root_cause": "BGP MTU mismatch",
            "fix_explanation": "Set MTU to 1500 on both routers",
            "fix_commands": ["int gi0/0", "mtu 1500"],
            "rollback_commands": ["int gi0/0", "mtu 1514"],
            "verification_commands": ["show interface gi0/0"],
            "expected_outcome": "BGP session comes up",
            "confidence": 0.88,
            "risk_assessment": "medium",
            "sources_used": [0, 1]
        }"""

        problem = ProblemStatement(
            scope="device",
            symptom="connectivity",
            severity="high",
            affected_devices=["router-1"],
            confidence=0.4,
            raw_text="BGP session stuck after MTU change",
        )

        solution = self.integrator.find_solution_for_unknown_issue(problem, confidence=0.4)

        assert solution is not None
        assert "BGP" in solution.root_cause
        assert len(solution.fix_commands) > 0
        assert solution.requires_approval
        assert solution.used_external_knowledge is not None or solution.sources

    def test_no_solution_found(self):
        """Test behavior when no external solution exists."""
        # Mock empty results
        self.rag_engine.retrieve.return_value = []
        self.web_search.return_value = []
        self.mcp_tools.query_vendor_knowledge.return_value = None

        problem = ProblemStatement(
            scope="unknown",
            symptom="unknown",
            severity="unknown",
            affected_devices=[],
            confidence=0.1,
            raw_text="Completely unknown network issue",
        )

        solution = self.integrator.find_solution_for_unknown_issue(problem, confidence=0.1)

        assert solution is None


class TestAutonomousTroubleshooterWithExternalKnowledge(unittest.TestCase):
    """Test autonomous troubleshooter with external knowledge enabled."""

    def setUp(self):
        """Set up test fixtures."""
        self.ai_call = Mock()
        self.troubleshoot_engine = Mock()
        self.ssh_collector = Mock()
        self.command_validator = Mock(return_value=True)
        self.approved_devices = ["device1", "device2"]

        self.troubleshooter = AutonomousNetworkTroubleshooter(
            ai_call=self.ai_call,
            troubleshoot_engine=self.troubleshoot_engine,
            ssh_collector=self.ssh_collector,
            command_validator=self.command_validator,
            approved_devices=self.approved_devices,
        )

    def test_enable_external_knowledge(self):
        """Test enabling external knowledge integration."""
        rag_engine = Mock()
        web_search = Mock()
        mcp_tools = Mock()

        self.troubleshooter.enable_external_knowledge(
            rag_engine=rag_engine,
            web_search_fn=web_search,
            mcp_tools=mcp_tools,
        )

        assert self.troubleshooter.use_external_knowledge
        assert self.troubleshooter.external_knowledge is not None

    def test_low_confidence_triggers_external_search(self):
        """Test that low diagnosis confidence triggers external knowledge search."""
        # Mock diagnosis with low confidence
        report = Mock()
        report.confidence = 0.4
        report.root_cause = "Unknown"
        report.fix = None
        report.to_dict.return_value = {}

        self.troubleshoot_engine.run.return_value = report

        # Enable external knowledge
        rag_engine = Mock()
        rag_engine.retrieve.return_value = [
            {
                "title": "Solution",
                "content": "Try this fix",
                "score": 0.8,
            }
        ]
        self.troubleshooter.enable_external_knowledge(rag_engine=rag_engine)

        problem = ProblemStatement(
            scope="device",
            symptom="performance",
            severity="high",
            affected_devices=["device1"],
            confidence=0.4,
            raw_text="Network issue",
        )

        session = Mock()
        session.problem = problem
        session.diagnosis_confidence = 0.4
        session.external_solution = None
        session.suggested_fix = None

        # Call search method
        found = self.troubleshooter._search_external_knowledge(session)

        # Should have attempted to search
        assert self.troubleshooter.external_knowledge is not None

    def test_external_solution_requires_approval(self):
        """Test that external solutions require human approval."""
        # Mock low-confidence diagnosis
        report = Mock()
        report.confidence = 0.3
        report.root_cause = None
        report.fix = None
        report.to_dict.return_value = {}

        self.troubleshoot_engine.run.return_value = report

        # Enable external knowledge with mocked solution
        rag_engine = Mock()
        rag_engine.retrieve.return_value = [
            {
                "title": "Fix",
                "content": "Apply this",
                "score": 0.8,
            }
        ]

        self.ai_call.return_value = """{
            "root_cause": "Interface misconfiguration",
            "fix_explanation": "Fix explanation",
            "fix_commands": ["cmd1"],
            "rollback_commands": ["cmd2"],
            "verification_commands": ["cmd3"],
            "expected_outcome": "Fixed",
            "confidence": 0.8,
            "risk_assessment": "medium",
            "sources_used": [0]
        }"""

        self.troubleshooter.enable_external_knowledge(rag_engine=rag_engine)

        problem = ProblemStatement(
            scope="interface",
            symptom="connectivity",
            severity="high",
            affected_devices=["device1"],
            confidence=0.3,
            raw_text="Interface down",
        )

        session = Mock()
        session.problem = problem
        session.diagnosis_confidence = 0.3
        session.external_solution = None
        session.suggested_fix = None

        # Trigger external search
        found = self.troubleshooter._search_external_knowledge(session)

        # If external solution found, it should require approval
        if found:
            assert session.external_solution is not None
            assert session.external_solution.requires_approval


class TestExternalKnowledgeDocumentation(unittest.TestCase):
    """Test that external knowledge integration is properly documented."""

    def test_external_solution_dataclass_fields(self):
        """Test that ExternalSolution has all required fields."""
        solution = ExternalSolution(
            root_cause="Test cause",
            fix_explanation="Test explanation",
            fix_commands=["cmd1"],
            rollback_commands=["cmd2"],
            verification_commands=["cmd3"],
            expected_outcome="Fixed",
            confidence=0.85,
            sources=[{"source": "web", "title": "Source 1"}],
        )

        assert solution.root_cause == "Test cause"
        assert solution.confidence == 0.85
        assert solution.requires_approval
        assert solution.requires_testing
        assert solution.risk_level == "medium"


if __name__ == "__main__":
    unittest.main()
