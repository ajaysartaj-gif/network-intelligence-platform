"""
core/semantic_intake.py
========================
AI-powered semantic problem classification.

Converts natural language ("network is slow between NYC and SF") into
structured problem representation ({scope, symptom, affected_devices, severity}).

This is the foundation for all 3 operational paths (A/B/C).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Problem Classification Enums
# ═══════════════════════════════════════════════════════════════════════════════

class ProblemScope(str, Enum):
    """Where is the problem located?"""
    DEVICE = "device"               # Single device issue (CPU, memory, crash)
    INTERFACE = "interface"         # One network interface (errors, flapping)
    LINK = "link"                   # Point-to-point connection (down, high latency)
    PATH = "path"                   # End-to-end multi-hop path (src → dst)
    END_TO_END = "end_to_end"       # Service/application level
    REGION = "region"               # Multiple sites affected
    UNKNOWN = "unknown"

    @property
    def discovery_scope(self) -> str:
        """What topology scope should discovery focus on?"""
        return {
            "device": "single_device",
            "interface": "single_device_interfaces",
            "link": "two_devices",
            "path": "multi_hop",
            "end_to_end": "full_topology",
            "region": "multi_site",
            "unknown": "full_topology"
        }[self.value]


class ProblemSymptom(str, Enum):
    """What type of issue is it?"""
    CONNECTIVITY = "connectivity"        # Can't reach something
    PERFORMANCE = "performance"          # Slow: latency, throughput, jitter
    STATE = "state"                      # Interface down, neighbor flap, protocol unstable
    CONFIG = "config"                    # Configuration mismatch or incorrect
    ANOMALY = "anomaly"                  # Unusual behavior detected
    RESOURCE = "resource"                # CPU, memory, buffer exhaustion
    UNKNOWN = "unknown"

    @property
    def hypothesis_family(self) -> List[str]:
        """Which hypothesis families are most likely?"""
        return {
            "connectivity": ["reachability_failure", "routing_loop", "acl_blocking", "interface_down"],
            "performance": ["bandwidth_congestion", "latency_increase", "mtu_mismatch", "qos_drop"],
            "state": ["protocol_flap", "neighbor_loss", "config_mismatch", "hw_failure"],
            "config": ["parameter_mismatch", "version_incompatibility", "policy_conflict"],
            "anomaly": ["memory_leak", "cpu_spike", "packet_loss_sudden", "jitter_increase"],
            "resource": ["cpu_exhaustion", "memory_exhaustion", "buffer_drop"],
            "unknown": []
        }[self.value]


class ProblemSeverity(str, Enum):
    """How urgent is this?"""
    CRITICAL = "critical"           # Service down, user impact immediate
    HIGH = "high"                   # Service degraded, user impact
    MEDIUM = "medium"               # Partial impact or localized
    LOW = "low"                     # No user impact detected yet


# ═══════════════════════════════════════════════════════════════════════════════
# Problem Statement Data Model
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProblemStatement:
    """Structured representation of a network problem."""
    raw_text: str                                               # Original user query

    # Classification
    scope: ProblemScope = ProblemScope.UNKNOWN
    symptom: ProblemSymptom = ProblemSymptom.UNKNOWN
    severity: ProblemSeverity = ProblemSeverity.MEDIUM

    # Affected entities
    affected_devices: List[str] = field(default_factory=list)  # IPs or hostnames
    affected_protocols: List[str] = field(default_factory=list)  # bgp, ospf, eigrp, etc
    affected_services: List[str] = field(default_factory=list)  # internet, vpn, wan, voice, etc

    # Characteristics
    is_intermittent: bool = False                              # Steady vs flapping/transient
    is_widespread: bool = False                                # Affects many devices or services

    # Confidence
    classification_confidence: float = 0.0                      # 0.0-1.0

    # Follow-up
    clarification_needed: Optional[str] = None                 # Question to ask user


# ═══════════════════════════════════════════════════════════════════════════════
# Semantic Intake Engine
# ═══════════════════════════════════════════════════════════════════════════════

class SemanticIntake:
    """AI-powered natural language → structured problem classification."""

    def __init__(self, ai_call: Callable[[str], str]):
        """
        Parameters
        ----------
        ai_call : Callable that takes a prompt and returns AI response.
                 Typically: core.ai_engine.ask_ai or Groq LLM call.
        """
        self.ai = ai_call
        self._prompt_cache = {}

    def parse(self,
              user_query: str,
              discovered_devices: Optional[List[Dict[str, Any]]] = None,
              topology_context: Optional[str] = None) -> ProblemStatement:
        """
        Convert user's natural language problem description into structured statement.

        Parameters
        ----------
        user_query : str
            User's problem description, e.g., "Network is slow between NYC and SF"
        discovered_devices : List[Dict]
            Approved devices {ip, hostname, vendor, device_type, region, city}
        topology_context : str
            Optional context about current topology state

        Returns
        -------
        ProblemStatement
            Structured problem representation
        """
        logger.info(f"Parsing problem: {user_query[:80]}")

        # Build classification prompt
        prompt = self._build_classification_prompt(
            user_query,
            discovered_devices or [],
            topology_context
        )

        # Call AI for classification
        ai_response = self.ai(prompt)
        logger.debug(f"AI response: {ai_response[:200]}")

        # Parse AI response into structured format
        classification = self._parse_classification_response(ai_response)

        # Create ProblemStatement
        problem = self._build_problem_statement(
            user_query,
            classification,
            discovered_devices or []
        )

        return problem

    def _build_classification_prompt(self,
                                     query: str,
                                     devices: List[Dict[str, Any]],
                                     topology_context: Optional[str] = None) -> str:
        """Build prompt for AI to classify the problem."""

        # Device list context
        device_lines = []
        for dev in devices[:15]:  # Limit to prevent prompt bloat
            device_lines.append(
                f"  - {dev.get('hostname', 'unknown')} ({dev.get('ip', '?')}) "
                f"[{dev.get('device_type', 'unknown')}] "
                f"in {dev.get('city', dev.get('region', '?'))}"
            )
        device_context = "\n".join(device_lines) if device_lines else "  (no devices)"

        # Topology context
        topo_context = topology_context or "No topology context provided."

        prompt = f"""You are a network operations AI. Analyze this problem statement and classify it.

USER PROBLEM STATEMENT:
"{query}"

NETWORK TOPOLOGY CONTEXT:
{topo_context}

APPROVED DEVICES IN NETWORK:
{device_context}

Classify this problem by responding with ONLY valid JSON (no markdown, no explanation):
{{
  "scope": "device|interface|link|path|end_to_end|region|unknown",
  "symptom": "connectivity|performance|state|config|anomaly|resource|unknown",
  "severity": "critical|high|medium|low",
  "likely_devices": ["ip_or_hostname1", "ip_or_hostname2"],
  "likely_protocols": ["bgp", "ospf", "eigrp", "vxlan"] or [],
  "likely_services": ["internet", "vpn", "wan", "voice"] or [],
  "is_intermittent": true|false,
  "is_widespread": true|false,
  "confidence": 0.0 to 1.0,
  "clarification": null or "Do you mean device X or Y?",
  "reasoning": "Brief explanation of classification"
}}"""

        return prompt

    def _parse_classification_response(self, ai_response: str) -> Dict[str, Any]:
        """Parse AI's JSON response."""
        try:
            # Try direct JSON parsing
            return json.loads(ai_response)
        except json.JSONDecodeError:
            # Try extracting JSON from markdown code blocks
            if "```json" in ai_response:
                start = ai_response.index("```json") + 7
                end = ai_response.index("```", start)
                json_str = ai_response[start:end].strip()
                return json.loads(json_str)
            elif "```" in ai_response:
                start = ai_response.index("```") + 3
                end = ai_response.index("```", start)
                json_str = ai_response[start:end].strip()
                return json.loads(json_str)
            else:
                logger.warning(f"Failed to parse AI response: {ai_response[:100]}")
                return self._default_classification()

    def _build_problem_statement(self,
                                 raw_query: str,
                                 classification: Dict[str, Any],
                                 devices: List[Dict[str, Any]]) -> ProblemStatement:
        """Convert classification dict into ProblemStatement."""

        # Build device IP map for resolution
        device_map = {}
        for dev in devices:
            device_map[dev.get('ip', '')] = dev
            device_map[dev.get('hostname', '').lower()] = dev

        # Resolve device names to IPs
        resolved_ips = []
        for name in classification.get('likely_devices', []):
            key = name if name.startswith('10.') or name.startswith('192.') or name.startswith('172.') else name.lower()
            if key in device_map:
                resolved_ips.append(device_map[key]['ip'])
            else:
                # Device name not found, keep as-is (might be resolved later)
                resolved_ips.append(name)

        # Create statement
        problem = ProblemStatement(
            raw_text=raw_query,
            scope=ProblemScope(classification.get('scope', 'unknown')),
            symptom=ProblemSymptom(classification.get('symptom', 'unknown')),
            severity=ProblemSeverity(classification.get('severity', 'medium')),
            affected_devices=resolved_ips,
            affected_protocols=classification.get('likely_protocols', []),
            affected_services=classification.get('likely_services', []),
            is_intermittent=classification.get('is_intermittent', False),
            is_widespread=classification.get('is_widespread', False),
            classification_confidence=classification.get('confidence', 0.5),
            clarification_needed=classification.get('clarification', None),
        )

        logger.info(
            f"Classified: scope={problem.scope.value}, "
            f"symptom={problem.symptom.value}, "
            f"devices={len(problem.affected_devices)}, "
            f"confidence={problem.classification_confidence:.0%}"
        )

        return problem

    @staticmethod
    def _default_classification() -> Dict[str, Any]:
        """Fallback when AI classification fails."""
        return {
            'scope': 'unknown',
            'symptom': 'unknown',
            'severity': 'medium',
            'likely_devices': [],
            'likely_protocols': [],
            'likely_services': [],
            'is_intermittent': False,
            'is_widespread': False,
            'confidence': 0.3,
            'clarification': 'Could you provide more details? E.g., which devices or services are affected?',
            'reasoning': 'Unable to classify from user input'
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Integration Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def build_topology_context(topology_graph: Any) -> str:
    """Generate human-readable topology context for semantic intake."""
    if not topology_graph:
        return "No topology available."

    lines = []
    lines.append(f"Site: {topology_graph.site_name or 'Unknown'}")
    lines.append(f"Devices: {topology_graph.node_count()}")
    lines.append(f"Links: {topology_graph.link_count()}")

    # List device roles
    roles_count = {}
    for node in topology_graph.nodes.values():
        role = node.role.value
        roles_count[role] = roles_count.get(role, 0) + 1

    if roles_count:
        role_str = ", ".join([f"{count} {role}" for role, count in sorted(roles_count.items())])
        lines.append(f"Composition: {role_str}")

    return " | ".join(lines)
