"""
core/knowledge_first_investigator.py
====================================
Refactored investigation workflow: Knowledge-first approach.

Current (broken): Investigate locally → Gaps found? → Then search knowledge
New (fixed): Load knowledge FIRST → Plan with knowledge → Investigate → Seek gaps

Main orchestrator for the new investigation engine.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

from core.protocol_planner import ProtocolPlanner, Protocol, InvestigationPlan
from core.evidence_interpreter import EvidenceInterpreter, EvidenceResult, InterpretationResult
from core.bayesian_confidence_manager import BayesianConfidenceManager, Hypothesis
from core.knowledge_gap_detector import KnowledgeGapDetector, KnowledgeGap

logger = logging.getLogger(__name__)


@dataclass
class InvestigationCycle:
    """A single cycle of the investigation loop."""
    cycle_number: int
    checks_executed: List[str]
    evidence_collected: List[EvidenceResult]
    interpretations: List[InterpretationResult]
    hypotheses_state: List[Tuple[str, float]]  # [(name, probability), ...]
    confidence: float
    gaps_detected: List[KnowledgeGap]
    knowledge_retrieved: Dict[str, Any]
    converged: bool
    next_steps: List[str]


class KnowledgeFirstInvestigator:
    """
    Main orchestrator for knowledge-first investigation.

    Workflow:
    1. Load protocol knowledge (OSPF state machine, prerequisites, etc.)
    2. Load enterprise knowledge (past similar issues)
    3. Plan investigation WITH knowledge
    4. Execute investigation cycle (collect → interpret → update confidence)
    5. Detect knowledge gaps
    6. Retrieve knowledge for gaps
    7. Refine hypotheses based on evidence
    8. If converged: done. Otherwise: next cycle
    """

    def __init__(self,
                 ai_call: Optional[callable] = None,
                 rag_engine: Optional[Any] = None,
                 mcp_tools: Optional[Any] = None,
                 web_search_fn: Optional[callable] = None):
        """
        Parameters
        ----------
        ai_call : callable, optional
            LLM function for fallback reasoning
        rag_engine : Any, optional
            Enterprise knowledge base
        mcp_tools : Any, optional
            Vendor APIs
        web_search_fn : callable, optional
            Web search function
        """

        self.ai_call = ai_call
        self.rag = rag_engine
        self.mcp = mcp_tools
        self.web_search = web_search_fn

        # Components
        self.protocol_planner = ProtocolPlanner()
        self.evidence_interpreter = EvidenceInterpreter()
        self.confidence_manager = BayesianConfidenceManager()
        self.gap_detector = KnowledgeGapDetector()

        # State
        self.current_plan: Optional[InvestigationPlan] = None
        self.investigation_cycles: List[InvestigationCycle] = []
        self.accumulated_knowledge: Dict[str, Any] = {}

        logger.info("KnowledgeFirstInvestigator initialized")

    def investigate(self,
                   protocol: Protocol,
                   issue_type: str,
                   root_device: str,
                   affected_devices: List[str],
                   device_outputs: Optional[Dict[str, str]] = None,
                   max_cycles: int = 5,
                   confidence_threshold: float = 0.85) -> Dict[str, Any]:
        """
        Execute knowledge-first investigation.

        Parameters
        ----------
        protocol : Protocol
            Protocol to investigate (OSPF, BGP, etc.)
        issue_type : str
            Type of issue (EXSTART, FLAPPING, SESSION_DOWN, etc.)
        root_device : str
            Starting device
        affected_devices : List[str]
            All affected devices
        device_outputs : Dict[str, str], optional
            Map of check names to actual device outputs (for testing)
        max_cycles : int
            Maximum investigation cycles before stopping
        confidence_threshold : float
            Confidence level required to converge (0.0-1.0)

        Returns
        -------
        Dict
            Investigation result with root cause, confidence, and actions
        """

        logger.info(
            f"Starting investigation: {protocol.value} {issue_type} on {root_device}"
        )

        # PHASE 1: Load Knowledge Upfront
        logger.info("PHASE 1: Loading knowledge upfront...")
        self._load_protocol_knowledge(protocol, issue_type)
        self._load_enterprise_knowledge(protocol, issue_type, root_device)
        self._load_vendor_knowledge(protocol, issue_type)

        # PHASE 2: Generate Investigation Plan
        logger.info("PHASE 2: Generating investigation plan...")
        neighbor_device = affected_devices[1] if len(affected_devices) > 1 else None
        plan = self.protocol_planner.plan_investigation(
            protocol=protocol,
            issue_type=issue_type,
            root_device=root_device,
            affected_devices=affected_devices,
            neighbor_device=neighbor_device
        )

        if not plan:
            logger.error(f"Could not create investigation plan for {protocol.value} / {issue_type}")
            return self._generate_result_unknown()

        self.current_plan = plan

        # Initialize confidence manager with hypotheses
        if protocol == Protocol.OSPF:
            self.confidence_manager.register_hypotheses_for_ospf_exstart()

        logger.info(f"Investigation plan: {plan.expected_duration_sec}s, {plan.confidence_threshold:.0%} confidence needed")

        # PHASE 3: Investigation Loop
        logger.info("PHASE 3: Investigation loop...")
        for cycle_num in range(1, max_cycles + 1):
            logger.info(f"\n--- Investigation Cycle {cycle_num} ---")

            cycle_result = self._run_investigation_cycle(
                cycle_num=cycle_num,
                plan=plan,
                root_device=root_device,
                device_outputs=device_outputs
            )

            self.investigation_cycles.append(cycle_result)

            if cycle_result.converged:
                logger.info(f"✅ Investigation converged in cycle {cycle_num}")
                break

            if cycle_num < max_cycles:
                logger.info(f"⏳ Cycle {cycle_num} complete, continuing...")

        # PHASE 4: Generate Result
        logger.info("PHASE 4: Generating final result...")
        result = self._generate_result(plan)

        logger.info(f"Investigation complete: confidence={result['confidence']:.0%}, root_cause={result['root_cause']}")

        return result

    def _load_protocol_knowledge(self, protocol: Protocol, issue_type: str):
        """Load protocol-specific knowledge."""

        logger.info(f"Loading {protocol.value} protocol knowledge...")

        knowledge = {}

        if protocol == Protocol.OSPF:
            knowledge = {
                "state_machine": ["DOWN", "INIT", "2-WAY", "EXSTART", "EXCHANGE", "LOADING", "FULL"],
                "hello_interval_default": 10,
                "dead_interval_default": 40,
                "mtu_minimum": 1500,
                "issue_types": {
                    "EXSTART": "Neighbors stuck in EXSTART state (database exchange issue)",
                    "FLAPPING": "Neighbors repeatedly becoming full then down",
                    "DEGRADATION": "Routes present but with poor metrics"
                }
            }

        elif protocol == Protocol.BGP:
            knowledge = {
                "state_machine": ["IDLE", "CONNECT", "ACTIVE", "OPENSENT", "OPENCONFIRM", "ESTABLISHED"],
                "holdtime_default": 180,
                "keepalive_default": 60,
                "tcp_port": 179,
            }

        self.accumulated_knowledge[protocol.value] = knowledge
        logger.info(f"Protocol knowledge loaded: {len(knowledge)} items")

    def _load_enterprise_knowledge(self, protocol: Protocol, issue_type: str, root_device: str):
        """Load enterprise-specific knowledge from RAG."""

        if not self.rag:
            logger.debug("RAG engine not available, skipping enterprise knowledge")
            return

        logger.info(f"Querying RAG for similar {protocol.value} {issue_type} issues...")

        try:
            # Query RAG for similar issues
            query = f"{protocol.value} {issue_type} troubleshooting {root_device}"
            similar_issues = self.rag.search(query, limit=3)

            if similar_issues:
                logger.info(f"Found {len(similar_issues)} similar issues in enterprise knowledge")
                self.accumulated_knowledge["enterprise"] = similar_issues
            else:
                logger.info("No similar issues found in enterprise knowledge")

        except Exception as e:
            logger.warning(f"Error querying RAG: {e}")

    def _load_vendor_knowledge(self, protocol: Protocol, issue_type: str):
        """Load vendor-specific knowledge."""

        logger.info(f"Loading vendor-specific knowledge for {protocol.value}...")

        # This would query vendor APIs via MCP
        # For now, placeholder
        self.accumulated_knowledge["vendor"] = {}

    def _run_investigation_cycle(self,
                                cycle_num: int,
                                plan: InvestigationPlan,
                                root_device: str,
                                device_outputs: Optional[Dict[str, str]] = None) -> InvestigationCycle:
        """Execute a single investigation cycle."""

        logger.info(f"Cycle {cycle_num}: Plan → Collect → Interpret → Update")

        # STEP 1: Plan checks (prioritized by info gain)
        checks_to_run = self.protocol_planner.get_checks_sorted_by_priority(plan)
        checks_to_run = checks_to_run[:5]  # Limit to 5 per cycle

        logger.info(f"Planning {len(checks_to_run)} checks...")

        # STEP 2: Collect evidence (from device outputs if provided)
        evidence_collected = self._collect_evidence(checks_to_run, root_device, device_outputs)
        logger.info(f"Collected {len(evidence_collected)} evidence items")

        # STEP 3: Interpret evidence
        interpretations = self.evidence_interpreter.interpret_ospf_evidence(evidence_collected)
        logger.info(f"Interpreted {len(interpretations)} evidence items")

        # STEP 4: Update confidence based on interpretations
        for interp in interpretations:
            # Build likelihood ratios for each hypothesis based on evidence strength
            likelihood_ratios = {}

            if interp.eliminates_hypothesis:
                for hyp in interp.eliminates_hypothesis:
                    # Evidence strongly contradicts this hypothesis
                    # Use confidence_delta to determine strength
                    if interp.confidence_delta > 0.5:
                        likelihood_ratios[hyp] = 0.05  # Very strong contradiction
                    elif interp.confidence_delta > 0.3:
                        likelihood_ratios[hyp] = 0.1   # Strong contradiction
                    else:
                        likelihood_ratios[hyp] = 0.3   # Moderate contradiction

            if interp.supports_hypothesis:
                for hyp in interp.supports_hypothesis:
                    # Evidence supports this hypothesis
                    if interp.confidence_delta > 0.5:
                        likelihood_ratios[hyp] = 100.0  # Very strong support
                    elif interp.confidence_delta > 0.3:
                        likelihood_ratios[hyp] = 20.0   # Strong support
                    else:
                        likelihood_ratios[hyp] = 5.0    # Moderate support

            if likelihood_ratios:
                self.confidence_manager.update_with_evidence(
                    evidence_name=interp.evidence.check_name,
                    likelihood_ratio_per_hypothesis=likelihood_ratios
                )

            logger.info(
                f"Evidence '{interp.evidence.check_name}': {interp.interpretation} "
                f"(delta: +{interp.confidence_delta:.0%})"
            )

        confidence = self.confidence_manager.get_confidence_score()
        logger.info(f"Confidence after cycle: {confidence:.0%}")

        # STEP 5: Detect knowledge gaps
        top_hyp, top_prob = self.confidence_manager.get_top_hypothesis() or ("Unknown", 0.0)
        gaps = self.gap_detector.detect_gaps(
            current_hypothesis=top_hyp,
            confidence=confidence,
            evidence_collected=evidence_collected
        )

        if gaps:
            logger.info(f"Detected {len(gaps)} knowledge gaps")

            # Retrieve knowledge for gaps
            for gap in gaps:
                self._retrieve_knowledge_for_gap(gap)

        # STEP 6: Check convergence
        converged = self.confidence_manager.should_converge()

        # Build cycle result
        top_hypotheses = self.confidence_manager.get_top_n_hypotheses(3)

        cycle_result = InvestigationCycle(
            cycle_number=cycle_num,
            checks_executed=[c.name for c in checks_to_run],
            evidence_collected=evidence_collected,
            interpretations=interpretations,
            hypotheses_state=top_hypotheses,
            confidence=confidence,
            gaps_detected=gaps,
            knowledge_retrieved=self.accumulated_knowledge.copy(),
            converged=converged,
            next_steps=self._determine_next_steps(converged, gaps, confidence)
        )

        return cycle_result

    def _collect_evidence(self,
                         checks: List[Any],
                         root_device: str,
                         device_outputs: Optional[Dict[str, str]] = None) -> List[EvidenceResult]:
        """Collect evidence from device (using test data if provided, or simulated)."""

        evidence = []

        if device_outputs:
            # When test data provided, extract ALL device outputs and create evidence
            for check_name, output in device_outputs.items():
                parsed_value = self._parse_evidence(check_name, output)
                result = EvidenceResult(
                    check_name=check_name,
                    command=f"[test output for {check_name}]",
                    output=output,
                    parsed_value=parsed_value
                )
                evidence.append(result)
        else:
            # Fallback to check-based collection (simulated)
            for check in checks:
                parsed_value = self._parse_evidence(check.name, None)
                result = EvidenceResult(
                    check_name=check.name,
                    command=check.command,
                    output="[simulated output]",
                    parsed_value=parsed_value
                )
                evidence.append(result)

        return evidence

    def _parse_evidence(self, check_name: str, output: Optional[str]) -> Dict[str, Any]:
        """Parse device output to extract relevant values."""

        if not output:
            # Fallback to sensible defaults if no output provided
            if "hello" in check_name.lower():
                return {"hello": 10, "dead": 40}
            elif "mtu" in check_name.lower():
                return {"mtu": 1500}
            elif "authentication" in check_name.lower():
                return {"auth_type": "none"}
            elif "neighbor" in check_name.lower():
                return {"state": "EXSTART"}
            else:
                return {}

        # Parse actual output
        parsed = {}

        # OSPF Hello/Dead interval parsing
        if "hello" in check_name.lower() or "interface_detail" in check_name.lower():
            for line in output.split('\n'):
                if 'hello' in line.lower() and 'interval' in line.lower():
                    # "Hello interval is 10 sec" or "Hello 10"
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'hello' in part.lower() and i + 2 < len(parts):
                            try:
                                parsed["hello"] = int(parts[i + 2])
                            except (ValueError, IndexError):
                                pass
                if 'dead' in line.lower() and 'interval' in line.lower():
                    # "Dead interval is 40 sec" or "Dead 40"
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'dead' in part.lower() and i + 2 < len(parts):
                            try:
                                parsed["dead"] = int(parts[i + 2])
                            except (ValueError, IndexError):
                                pass

        # OSPF neighbor state parsing
        if "neighbors" in check_name.lower():
            for line in output.split('\n'):
                if any(state in line for state in ["EXSTART", "EXCHANGE", "LOADING", "FULL", "DOWN", "INIT"]):
                    # Extract state from output
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if "/" in part:  # State format is "EXSTART/DR" or similar
                            parsed["state"] = part.split("/")[0]
                            break

        # OSPF Area parsing
        if "process" in check_name.lower() or "area" in check_name.lower():
            for line in output.split('\n'):
                if 'area' in line.lower() and any(c.isdigit() for c in line):
                    # "Area 0" or "Area 1" etc
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'area' in part.lower() and i + 1 < len(parts):
                            try:
                                parsed["area"] = int(parts[i + 1])
                            except (ValueError, IndexError):
                                pass

        # MTU parsing
        if "mtu" in check_name.lower():
            for line in output.split('\n'):
                if 'mtu' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'mtu' in part.lower() and i + 1 < len(parts):
                            try:
                                parsed["mtu"] = int(parts[i + 1])
                            except (ValueError, IndexError):
                                pass

        # BGP AS number parsing
        if "bgp" in check_name.lower() and "neighbor" in check_name.lower():
            for line in output.split('\n'):
                if 'remote as' in line.lower() or 'remote-as' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'as' in part.lower() and i + 1 < len(parts):
                            try:
                                parsed["remote_as"] = int(parts[i + 1])
                            except (ValueError, IndexError):
                                pass
                if 'local as' in line.lower():
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if 'as' in part.lower() and i + 1 < len(parts):
                            try:
                                parsed["local_as"] = int(parts[i + 1])
                            except (ValueError, IndexError):
                                pass

        return parsed if parsed else {"raw": output[:100]}

    def _retrieve_knowledge_for_gap(self, gap: KnowledgeGap):
        """Retrieve knowledge to fill a gap."""

        logger.info(f"Retrieving knowledge for gap: {gap.gap_description}")

        if gap.source == "protocol":
            # Already have protocol knowledge loaded
            pass

        elif gap.source == "rag" and self.rag:
            # Query enterprise knowledge base
            try:
                results = self.rag.search(gap.gap_description, limit=2)
                if results:
                    logger.info(f"Found RAG results for gap")
            except Exception as e:
                logger.warning(f"Error querying RAG: {e}")

        elif gap.source == "mcp" and self.mcp:
            # Query vendor APIs
            logger.info(f"Would query MCP for: {gap.gap_description}")

        elif gap.source == "web" and self.web_search:
            # Search web
            try:
                results = self.web_search(gap.gap_description)
                if results:
                    logger.info(f"Found web results for gap")
            except Exception as e:
                logger.warning(f"Error searching web: {e}")

    def _determine_next_steps(self,
                            converged: bool,
                            gaps: List[KnowledgeGap],
                            confidence: float) -> List[str]:
        """Determine what to do next."""

        if converged:
            return ["Investigation converged", "Generate report", "Propose fix"]

        if gaps:
            return [f"Retrieve knowledge for {len(gaps)} gap(s)", "Continue investigating"]

        if confidence < 0.60:
            return ["Confidence still low", "Consider external knowledge"]

        return ["Continue investigating"]

    def _generate_result(self, plan: InvestigationPlan) -> Dict[str, Any]:
        """Generate final investigation result."""

        top_hyp, top_prob = self.confidence_manager.get_top_hypothesis() or ("Unknown", 0.0)
        confidence = self.confidence_manager.get_confidence_score()

        return {
            "root_cause": top_hyp,
            "confidence": confidence,
            "protocol": plan.protocol.value,
            "issue_type": plan.issue_type,
            "cycles": len(self.investigation_cycles),
            "total_evidence": sum(len(c.evidence_collected) for c in self.investigation_cycles),
            "converged": confidence >= plan.confidence_threshold,
            "top_3_hypotheses": self.confidence_manager.get_top_n_hypotheses(3),
            "accumulated_knowledge": self.accumulated_knowledge,
            "cycles_detail": [
                {
                    "cycle": c.cycle_number,
                    "checks": c.checks_executed,
                    "confidence": c.confidence,
                    "converged": c.converged
                }
                for c in self.investigation_cycles
            ]
        }

    def _generate_result_unknown(self) -> Dict[str, Any]:
        """Generate error result."""

        return {
            "root_cause": "Unknown - plan generation failed",
            "confidence": 0.0,
            "protocol": "unknown",
            "issue_type": "unknown",
            "cycles": 0,
            "total_evidence": 0,
            "converged": False,
            "top_3_hypotheses": [],
            "accumulated_knowledge": {},
            "cycles_detail": []
        }

    def print_investigation_summary(self) -> str:
        """Generate human-readable investigation summary."""

        if not self.investigation_cycles:
            return "No investigation cycles completed\n"

        report = "🔬 INVESTIGATION SUMMARY\n"
        report += "=" * 70 + "\n\n"

        report += f"Total Cycles: {len(self.investigation_cycles)}\n"

        last_cycle = self.investigation_cycles[-1]
        report += f"Final Confidence: {last_cycle.confidence:.0%}\n"
        report += f"Converged: {'✅ Yes' if last_cycle.converged else '❌ No'}\n\n"

        report += "Hypothesis Probabilities (Final):\n"
        for name, prob in last_cycle.hypotheses_state:
            report += f"  • {name}: {prob:.0%}\n"

        report += f"\nTotal Evidence Collected: {sum(len(c.evidence_collected) for c in self.investigation_cycles)}\n"

        return report
