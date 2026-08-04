"""
OSPF Protocol Reasoner

Applies OSPF state machine knowledge to diagnose problems.
Implements RFC 2328 adjacency formation logic.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from enum import Enum

from diagnostics.parsers.ospf import (
    OSPFNeighbor,
    OSPFInterface,
    OSPFConfig,
    NeighborState,
    NetworkType,
)


class RootCauseCategory(Enum):
    """Categories of OSPF problems."""
    AREA_MISMATCH = "Area mismatch"
    NETWORK_TYPE_MISMATCH = "Network type mismatch"
    MTU_MISMATCH = "MTU mismatch"
    AUTHENTICATION_FAILURE = "Authentication failure"
    HELLO_DEAD_TIMER_MISMATCH = "Hello/Dead timer mismatch"
    PASSIVE_INTERFACE = "Passive interface configured"
    NETWORK_NOT_ADVERTISED = "Network not advertised in OSPF"
    INTERFACE_DOWN = "Interface down"
    OSPF_DISABLED = "OSPF not running"
    UNKNOWN = "Unknown issue"


@dataclass
class Evidence:
    """A piece of evidence supporting or refuting a hypothesis."""
    description: str
    confidence: float  # 0.0 to 1.0
    source: str  # e.g., "show ip ospf neighbor", "show ip ospf interface"
    supports_cause: bool


@dataclass
class RootCauseHypothesis:
    """A potential root cause with supporting evidence."""
    cause: RootCauseCategory
    confidence: float  # 0.0 to 1.0
    description: str
    evidence: List[Evidence] = field(default_factory=list)
    discriminating_signals: List[str] = field(default_factory=list)
    verification_commands: List[str] = field(default_factory=list)
    recommended_fix: Optional[str] = None
    rollback_commands: List[str] = field(default_factory=list)


@dataclass
class DiagnosticResult:
    """Result of OSPF diagnostic."""
    hypotheses: List[RootCauseHypothesis]  # Ranked by confidence
    primary_cause: Optional[RootCauseHypothesis]
    confidence: float  # Confidence in primary cause
    summary: str
    evidence_collected: List[str]
    missing_evidence: List[str]
    next_command: Optional[str]


class OSPFReasoner:
    """OSPF protocol reasoner.

    Implements RFC 2328 knowledge to diagnose OSPF problems.
    """

    def diagnose(
        self,
        neighbors: List[OSPFNeighbor],
        interfaces: Dict[str, OSPFInterface],
        config: OSPFConfig,
        problem_statement: str,
    ) -> DiagnosticResult:
        """
        Diagnose OSPF problem.

        Args:
            neighbors: Parsed OSPF neighbors
            interfaces: Parsed OSPF interfaces
            config: Parsed OSPF configuration
            problem_statement: Engineer's description of the problem

        Returns:
            DiagnosticResult with ranked hypotheses
        """
        hypotheses = []

        # Analyze current neighbor states
        stuck_states = self._find_stuck_neighbors(neighbors)

        # If neighbors are EXSTART
        if stuck_states.get("EXSTART"):
            hypotheses.extend(
                self._diagnose_exstart(neighbors, interfaces, config, stuck_states)
            )

        # If neighbors are in INIT
        elif stuck_states.get("INIT"):
            hypotheses.extend(
                self._diagnose_init(neighbors, interfaces, config, stuck_states)
            )

        # If no neighbors at all
        elif not neighbors:
            hypotheses.extend(self._diagnose_no_neighbors(neighbors, interfaces, config))

        # Sort by confidence
        hypotheses.sort(key=lambda h: h.confidence, reverse=True)

        # Build result
        primary = hypotheses[0] if hypotheses else None
        confidence = primary.confidence if primary else 0.0

        return DiagnosticResult(
            hypotheses=hypotheses,
            primary_cause=primary,
            confidence=confidence,
            summary=self._summarize(primary),
            evidence_collected=self._get_evidence_sources(neighbors, interfaces, config),
            missing_evidence=self._get_missing_evidence(hypotheses),
            next_command=self._recommend_next_command(primary, hypotheses),
        )

    def _find_stuck_neighbors(self, neighbors: List[OSPFNeighbor]) -> Dict[str, int]:
        """Find neighbors in non-FULL states."""
        stuck = {}
        for neighbor in neighbors:
            state = neighbor.state.value
            stuck[state] = stuck.get(state, 0) + 1
        return stuck

    def _diagnose_exstart(
        self,
        neighbors: List[OSPFNeighbor],
        interfaces: Dict[str, OSPFInterface],
        config: OSPFConfig,
        stuck_states: Dict[str, int],
    ) -> List[RootCauseHypothesis]:
        """Diagnose EXSTART issues (stuck in DB exchange).

        RFC 2328: EXSTART means DBD exchange starting.
        If stuck here, one of:
        1. Area mismatch (will never exchange)
        2. Network type mismatch (will never exchange)
        3. MTU mismatch (exchange starts but fails)
        4. Authentication failure
        """
        hypotheses = []

        # Hypothesis 1: Area Mismatch
        # Evidence: neighbors in EXSTART, config shows different areas
        hypotheses.append(
            RootCauseHypothesis(
                cause=RootCauseCategory.AREA_MISMATCH,
                confidence=0.85,
                description="Neighbors stuck in EXSTART; likely area configuration mismatch on connecting interface",
                evidence=[
                    Evidence(
                        description="Neighbor(s) in EXSTART state",
                        confidence=0.9,
                        source="show ip ospf neighbor",
                        supports_cause=True,
                    ),
                    Evidence(
                        description="OSPF area configuration present",
                        confidence=0.7,
                        source="show running-config",
                        supports_cause=True,
                    ),
                ],
                discriminating_signals=[
                    "ospf network type",
                    "ospf interface area",
                    "neighbor area",
                ],
                verification_commands=[
                    "show ip ospf interface",
                    "show ip ospf neighbor detail",
                    "show running-config | section ospf",
                ],
                recommended_fix="Ensure both sides of OSPF adjacency are in the same area. Example: 'interface Gi0/0' -> 'ip ospf area 0'",
                rollback_commands=["no ip ospf area X"],
            )
        )

        # Hypothesis 2: Network Type Mismatch
        # Evidence: interfaces with different network types
        hypotheses.append(
            RootCauseHypothesis(
                cause=RootCauseCategory.NETWORK_TYPE_MISMATCH,
                confidence=0.80,
                description="OSPF network type mismatch on one or both sides of the adjacency",
                evidence=[
                    Evidence(
                        description="EXSTART state indicates DB exchange problem",
                        confidence=0.8,
                        source="show ip ospf neighbor",
                        supports_cause=True,
                    ),
                ],
                discriminating_signals=["ospf network type"],
                verification_commands=[
                    "show ip ospf interface",
                    "show running-config | inc ip ospf network",
                ],
                recommended_fix="Ensure matching network types: 'interface Gi0/0' -> 'ip ospf network broadcast' (or point-to-point)",
                rollback_commands=["no ip ospf network"],
            )
        )

        # Hypothesis 3: MTU Mismatch
        # Evidence: stuck in EXSTART but both sides agree on type/area
        hypotheses.append(
            RootCauseHypothesis(
                cause=RootCauseCategory.MTU_MISMATCH,
                confidence=0.60,
                description="Interface MTU mismatch preventing DBD fragment exchange",
                evidence=[
                    Evidence(
                        description="EXSTART state with both sides likely in agreement on area/type",
                        confidence=0.6,
                        source="show ip ospf neighbor",
                        supports_cause=True,
                    ),
                ],
                discriminating_signals=["interface mtu", "ospf mtu"],
                verification_commands=[
                    "show interface GigabitEthernet0/0 | include MTU",
                    "show ip ospf interface | include MTU",
                ],
                recommended_fix="Ensure MTU is consistent (typically 1500 bytes). Check physical interface MTU matches neighbor.",
                rollback_commands=["no mtu"],
            )
        )

        return hypotheses

    def _diagnose_init(
        self,
        neighbors: List[OSPFNeighbor],
        interfaces: Dict[str, OSPFInterface],
        config: OSPFConfig,
        stuck_states: Dict[str, int],
    ) -> List[RootCauseHypothesis]:
        """Diagnose INIT issues (stuck waiting for neighbor HELLO).

        Stuck in INIT means:
        - We received a HELLO from neighbor
        - We're waiting for neighbor to receive our HELLO
        - Or we're receiving HELLOs but responding with wrong parameters
        """
        hypotheses = []

        # Hypothesis 1: Hello/Dead Timer Mismatch
        hypotheses.append(
            RootCauseHypothesis(
                cause=RootCauseCategory.HELLO_DEAD_TIMER_MISMATCH,
                confidence=0.70,
                description="Hello/Dead timer mismatch preventing neighbor discovery",
                evidence=[
                    Evidence(
                        description="Neighbor in INIT state",
                        confidence=0.85,
                        source="show ip ospf neighbor",
                        supports_cause=True,
                    ),
                ],
                discriminating_signals=["hello interval", "dead interval"],
                verification_commands=[
                    "show ip ospf interface",
                    "show running-config | inc ospf",
                ],
                recommended_fix="Ensure hello/dead intervals match (default: hello=10, dead=40). Adjust on interface if needed.",
                rollback_commands=["no ip ospf hello-interval", "no ip ospf dead-interval"],
            )
        )

        return hypotheses

    def _diagnose_no_neighbors(
        self,
        neighbors: List[OSPFNeighbor],
        interfaces: Dict[str, OSPFInterface],
        config: OSPFConfig,
    ) -> List[RootCauseHypothesis]:
        """Diagnose no neighbor adjacencies found."""
        hypotheses = []

        # Hypothesis 1: Passive Interface
        hypotheses.append(
            RootCauseHypothesis(
                cause=RootCauseCategory.PASSIVE_INTERFACE,
                confidence=0.75,
                description="Interface configured as passive, preventing neighbor adjacency",
                evidence=[
                    Evidence(
                        description="No OSPF neighbors discovered",
                        confidence=0.9,
                        source="show ip ospf neighbor",
                        supports_cause=True,
                    ),
                ],
                discriminating_signals=["passive interface"],
                verification_commands=[
                    "show ip ospf",
                    "show running-config | inc passive",
                ],
                recommended_fix="Remove passive interface configuration if adjacency is needed. 'no passive-interface Gi0/0'",
                rollback_commands=["passive-interface Gi0/0"],
            )
        )

        # Hypothesis 2: Network Not Advertised
        hypotheses.append(
            RootCauseHypothesis(
                cause=RootCauseCategory.NETWORK_NOT_ADVERTISED,
                confidence=0.70,
                description="Interface network not included in OSPF network statements",
                evidence=[
                    Evidence(
                        description="No neighbors on interface",
                        confidence=0.8,
                        source="show ip ospf neighbor",
                        supports_cause=True,
                    ),
                ],
                discriminating_signals=["network statement", "ospf area"],
                verification_commands=[
                    "show running-config | section ospf",
                    "show ip ospf interface",
                ],
                recommended_fix="Add network statement for the interface subnet. 'network 10.0.1.0 0.0.0.255 area 0'",
                rollback_commands=["no network"],
            )
        )

        return hypotheses

    def _summarize(self, primary: Optional[RootCauseHypothesis]) -> str:
        """Generate human-readable summary."""
        if not primary:
            return "Unable to determine root cause from available evidence."
        return f"{primary.cause.value} ({primary.confidence:.0%} confidence): {primary.description}"

    def _get_evidence_sources(
        self, neighbors, interfaces, config
    ) -> List[str]:
        """List evidence already collected."""
        sources = []
        if neighbors:
            sources.append("show ip ospf neighbor")
        if interfaces:
            sources.append("show ip ospf interface")
        if config.router_id:
            sources.append("show running-config")
        return sources

    def _get_missing_evidence(self, hypotheses: List[RootCauseHypothesis]) -> List[str]:
        """Identify what evidence would help narrow diagnosis."""
        if not hypotheses:
            return ["show ip ospf neighbor", "show ip ospf interface", "show running-config"]

        # Collect all discriminating signals from top hypotheses
        needed = set()
        for h in hypotheses[:3]:  # Top 3
            needed.update(h.discriminating_signals)

        return sorted(list(needed))

    def _recommend_next_command(
        self, primary: Optional[RootCauseHypothesis], hypotheses: List[RootCauseHypothesis]
    ) -> Optional[str]:
        """Recommend the next diagnostic command to run."""
        if not primary:
            return "show ip ospf neighbor"

        # Use discriminating signals from primary cause
        if primary.verification_commands:
            return primary.verification_commands[0]

        return None
