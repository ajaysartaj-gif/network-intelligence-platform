"""
core/external_knowledge_layer.py
================================
External Knowledge Integration for Unknown Network Issues

When the troubleshooting engine has low confidence on a problem,
this layer searches external sources (web, RAG, MCP) and synthesizes fixes.

Enables autonomous troubleshooting for novel/undocumented issues.
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class KnowledgeSource(str, Enum):
    """Where did this knowledge come from?"""
    INTERNAL_RAG = "internal_rag"       # Your knowledge base
    WEB_SEARCH = "web_search"           # Public internet
    VENDOR_API = "vendor_api"           # Vendor APIs via MCP
    COMMUNITY = "community"             # GitHub, forums, etc.
    PATTERN_DB = "pattern_db"           # Your own pattern database


@dataclass
class ExternalSolution:
    """Solution synthesized from external sources."""
    root_cause: str
    fix_explanation: str
    fix_commands: List[str]
    rollback_commands: List[str]
    verification_commands: List[str]
    expected_outcome: str
    confidence: float
    sources: List[Dict[str, Any]]       # [{source, url, relevance_score}]
    requires_approval: bool = True      # External fixes need human approval
    requires_testing: bool = True       # Should test in lab first
    risk_level: str = "medium"


@dataclass
class KnowledgeSearchResult:
    """A single result from knowledge search."""
    source: KnowledgeSource
    title: str
    content: str
    relevance_score: float              # 0.0-1.0
    url: Optional[str] = None
    vendor: Optional[str] = None
    platform: Optional[str] = None


class ExternalKnowledgeIntegrator:
    """
    Searches external sources for solutions to unknown network issues.

    Pipeline:
      1. Search RAG (internal knowledge base)
      2. Search web for similar issues
      3. Query vendor APIs via MCP
      4. Synthesize solution using Claude
      5. Return annotated fix with sources
    """

    def __init__(self,
                 rag_engine: Any,
                 web_search_fn: Optional[Callable] = None,
                 mcp_tools: Optional[Any] = None,
                 ai_call: Optional[Callable] = None):
        """
        Parameters
        ----------
        rag_engine : RAGEngine
            Knowledge base retrieval engine
        web_search_fn : Callable, optional
            Function to search web: query(str) -> List[Dict]
        mcp_tools : Any, optional
            MCP connections to vendor APIs
        ai_call : Callable, optional
            LLM function for synthesis: ai_call(prompt) -> str
        """
        self.rag = rag_engine
        self.web_search = web_search_fn
        self.mcp = mcp_tools
        self.ai = ai_call

        logger.info("ExternalKnowledgeIntegrator initialized")

    def find_solution_for_unknown_issue(
        self,
        problem_statement: Any,  # ProblemStatement
        confidence: float = 0.0,
        timeout_seconds: int = 30
    ) -> Optional[ExternalSolution]:
        """
        Search external sources for a solution to an unknown issue.

        Parameters
        ----------
        problem_statement : ProblemStatement
            The classified problem from semantic intake
        confidence : float
            Confidence of internal diagnosis (0.0-1.0)
        timeout_seconds : int
            Max time to spend searching

        Returns
        -------
        ExternalSolution or None
            Synthesized fix with sources, or None if no solution found
        """
        logger.info(
            f"🔍 Searching external sources for unknown issue "
            f"(confidence: {confidence:.0%}, symptom: {problem_statement.symptom})"
        )

        all_results: List[KnowledgeSearchResult] = []

        # STEP 1: Search internal RAG
        try:
            rag_results = self._search_rag(problem_statement)
            all_results.extend(rag_results)
            logger.info(f"  ✓ RAG: found {len(rag_results)} result(s)")
        except Exception as e:
            logger.warning(f"  ✗ RAG search failed: {e}")

        # STEP 2: Web search for similar issues
        try:
            web_results = self._search_web(problem_statement)
            all_results.extend(web_results)
            logger.info(f"  ✓ Web: found {len(web_results)} result(s)")
        except Exception as e:
            logger.warning(f"  ✗ Web search failed: {e}")

        # STEP 3: Query vendor APIs via MCP
        try:
            vendor_results = self._search_vendor_apis(problem_statement)
            all_results.extend(vendor_results)
            logger.info(f"  ✓ Vendor APIs: found {len(vendor_results)} result(s)")
        except Exception as e:
            logger.warning(f"  ✗ Vendor API search failed: {e}")

        # STEP 4: No results? Return None
        if not all_results:
            logger.warning("  ⚠️ No external solutions found")
            return None

        # STEP 5: Synthesize solution from results
        try:
            solution = self._synthesize_solution(problem_statement, all_results)
            logger.info(
                f"  ✅ Synthesized solution (confidence: {solution.confidence:.0%})"
            )
            return solution
        except Exception as e:
            logger.error(f"  ✗ Synthesis failed: {e}")
            return None

    def _search_rag(
        self,
        problem_statement: Any
    ) -> List[KnowledgeSearchResult]:
        """Search internal knowledge base (RAG)."""
        if not self.rag:
            return []

        try:
            # Query RAG with problem description
            results = self.rag.retrieve(
                query=problem_statement.raw_text,
                top_k=5
            )

            knowledge_results = []
            for doc in results:
                knowledge_results.append(
                    KnowledgeSearchResult(
                        source=KnowledgeSource.INTERNAL_RAG,
                        title=doc.get("title", ""),
                        content=doc.get("content", ""),
                        relevance_score=doc.get("score", 0.5),
                        vendor=doc.get("vendor"),
                        platform=doc.get("platform")
                    )
                )

            return knowledge_results
        except Exception as e:
            logger.error(f"RAG retrieval error: {e}")
            return []

    def _search_web(
        self,
        problem_statement: Any
    ) -> List[KnowledgeSearchResult]:
        """Search public internet for similar issues."""
        if not self.web_search:
            return []

        try:
            # Build search query
            search_query = self._build_search_query(problem_statement)
            logger.debug(f"Web search query: {search_query}")

            # Execute search
            web_results = self.web_search(search_query)

            knowledge_results = []
            for result in web_results:
                # Prioritize official vendor docs
                source = KnowledgeSource.COMMUNITY
                if any(domain in result.get("url", "") for domain in
                       ["cisco.com", "arista.com", "juniper.net", "fortinet.com"]):
                    source = KnowledgeSource.VENDOR_API

                knowledge_results.append(
                    KnowledgeSearchResult(
                        source=source,
                        title=result.get("title", ""),
                        content=result.get("snippet", ""),
                        relevance_score=result.get("relevance", 0.5),
                        url=result.get("url")
                    )
                )

            return knowledge_results
        except Exception as e:
            logger.error(f"Web search error: {e}")
            return []

    def _search_vendor_apis(
        self,
        problem_statement: Any
    ) -> List[KnowledgeSearchResult]:
        """Query vendor APIs via MCP for official solutions."""
        if not self.mcp:
            return []

        results = []
        try:
            # Determine vendors from affected devices
            vendors = self._extract_vendors(problem_statement)

            for vendor in vendors:
                try:
                    # Call vendor API via MCP
                    vendor_data = self.mcp.query_vendor_knowledge(
                        vendor=vendor,
                        symptom=problem_statement.symptom,
                        scope=problem_statement.scope
                    )

                    if vendor_data:
                        results.append(
                            KnowledgeSearchResult(
                                source=KnowledgeSource.VENDOR_API,
                                title=f"{vendor.upper()} Official Solution",
                                content=vendor_data.get("solution", ""),
                                relevance_score=vendor_data.get("match_score", 0.8),
                                vendor=vendor,
                                platform=vendor_data.get("platform")
                            )
                        )
                except Exception as e:
                    logger.debug(f"Vendor API error for {vendor}: {e}")

        except Exception as e:
            logger.error(f"Vendor API search error: {e}")

        return results

    def _synthesize_solution(
        self,
        problem_statement: Any,
        results: List[KnowledgeSearchResult]
    ) -> ExternalSolution:
        """
        Use Claude to synthesize a solution from multiple sources.
        """
        if not self.ai:
            raise RuntimeError("AI synthesis engine not available")

        # Build synthesis prompt
        prompt = self._build_synthesis_prompt(problem_statement, results)

        # Call Claude
        synthesis = self.ai(prompt)

        # Parse response
        solution = self._parse_synthesis_response(synthesis, results)

        return solution

    def _build_search_query(self, problem_statement: Any) -> str:
        """Build effective web search query."""
        query_parts = []

        # Add problem symptom
        if hasattr(problem_statement, 'symptom'):
            query_parts.append(str(problem_statement.symptom))

        # Add scope
        if hasattr(problem_statement, 'scope'):
            query_parts.append(str(problem_statement.scope))

        # Add device types
        if hasattr(problem_statement, 'affected_devices'):
            for device in problem_statement.affected_devices[:2]:
                query_parts.append(str(device))

        # Add "fix" keyword
        query_parts.append("fix solution")

        return " ".join(query_parts)

    def _extract_vendors(self, problem_statement: Any) -> List[str]:
        """Extract vendor names from affected devices."""
        vendors = set()

        if hasattr(problem_statement, 'affected_devices'):
            for device in problem_statement.affected_devices:
                device_str = str(device).lower()
                if "cisco" in device_str:
                    vendors.add("cisco")
                elif "arista" in device_str:
                    vendors.add("arista")
                elif "juniper" in device_str:
                    vendors.add("juniper")
                elif "fortinet" in device_str or "fortigate" in device_str:
                    vendors.add("fortinet")

        return list(vendors) if vendors else []

    def _build_synthesis_prompt(
        self,
        problem_statement: Any,
        results: List[KnowledgeSearchResult]
    ) -> str:
        """Build Claude prompt to synthesize solution."""
        prompt = f"""
You are an expert network engineer synthesizing a fix for an unknown network issue.

PROBLEM DESCRIPTION:
{problem_statement.raw_text if hasattr(problem_statement, 'raw_text') else 'Unknown'}

SCOPE: {problem_statement.scope if hasattr(problem_statement, 'scope') else 'Unknown'}
SYMPTOM: {problem_statement.symptom if hasattr(problem_statement, 'symptom') else 'Unknown'}
SEVERITY: {problem_statement.severity if hasattr(problem_statement, 'severity') else 'Unknown'}

SOURCES FOUND:
"""
        for i, result in enumerate(results, 1):
            prompt += f"""
{i}. Source: {result.source.value} (relevance: {result.relevance_score:.0%})
   Title: {result.title}
   Content: {result.content[:500]}
   {"URL: " + result.url if result.url else ""}
"""

        prompt += """
REQUIRED OUTPUT FORMAT (JSON):
{
    "root_cause": "Concise diagnosis of root cause",
    "fix_explanation": "Why this fix works",
    "fix_commands": ["cmd1", "cmd2", ...],
    "rollback_commands": ["rollback1", "rollback2", ...],
    "verification_commands": ["verify1", "verify2", ...],
    "expected_outcome": "What should happen if fix works",
    "confidence": 0.75,
    "risk_assessment": "low|medium|high",
    "sources_used": [source indices, e.g., [1, 3]]
}

IMPORTANT:
- Only recommend actions you have high confidence in
- Include rollback commands for every fix
- Be conservative with risk assessment
- Cite which sources led to this solution
"""
        return prompt

    def _parse_synthesis_response(
        self,
        synthesis: str,
        results: List[KnowledgeSearchResult]
    ) -> ExternalSolution:
        """Parse Claude's synthesis response into ExternalSolution."""
        import json

        try:
            # Extract JSON from response
            json_start = synthesis.find("{")
            json_end = synthesis.rfind("}") + 1
            json_str = synthesis[json_start:json_end]
            data = json.loads(json_str)

            # Map cited source indices to actual sources
            sources = []
            if "sources_used" in data:
                for idx in data.get("sources_used", []):
                    if 0 <= idx < len(results):
                        result = results[idx]
                        sources.append({
                            "source": result.source.value,
                            "title": result.title,
                            "url": result.url,
                            "relevance": result.relevance_score
                        })

            return ExternalSolution(
                root_cause=data.get("root_cause", "Unknown"),
                fix_explanation=data.get("fix_explanation", ""),
                fix_commands=data.get("fix_commands", []),
                rollback_commands=data.get("rollback_commands", []),
                verification_commands=data.get("verification_commands", []),
                expected_outcome=data.get("expected_outcome", ""),
                confidence=min(data.get("confidence", 0.5), 0.95),  # Cap at 0.95 (external fix)
                sources=sources,
                risk_level=data.get("risk_assessment", "medium")
            )
        except Exception as e:
            logger.error(f"Synthesis parsing error: {e}")
            # Return a default solution with low confidence
            return ExternalSolution(
                root_cause="Unable to synthesize solution",
                fix_explanation="",
                fix_commands=[],
                rollback_commands=[],
                verification_commands=[],
                expected_outcome="",
                confidence=0.1,
                sources=[],
                risk_level="high"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# Utility function for integration
# ═══════════════════════════════════════════════════════════════════════════════

def create_external_knowledge_integrator(
    rag_engine: Any,
    web_search_fn: Optional[Callable] = None,
    mcp_tools: Optional[Any] = None,
    ai_call: Optional[Callable] = None,
) -> ExternalKnowledgeIntegrator:
    """
    Factory function to create the external knowledge integrator.

    Recommended usage:
        from core.external_knowledge_layer import create_external_knowledge_integrator
        from core.knowledge.rag import get_rag_engine

        integrator = create_external_knowledge_integrator(
            rag_engine=get_rag_engine(),
            web_search_fn=your_web_search_function,
            mcp_tools=your_mcp_instance,
            ai_call=ask_ai,
        )

        solution = integrator.find_solution_for_unknown_issue(
            problem_statement=problem,
            confidence=0.4
        )
    """
    return ExternalKnowledgeIntegrator(
        rag_engine=rag_engine,
        web_search_fn=web_search_fn,
        mcp_tools=mcp_tools,
        ai_call=ai_call,
    )
