"""
core/protocol_planner.py
========================
Protocol-aware investigation planner.

Current (broken): Generic LLM plans generic checks
New (fixed): Protocol-specific planner for OSPF, BGP, IS-IS, etc.

Generates investigation plans that follow protocol specifications and prerequisites.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class Protocol(str, Enum):
    """Supported routing protocols."""
    OSPF = "ospf"
    BGP = "bgp"
    IS_IS = "is_is"
    EIGRP = "eigrp"
    RIP = "rip"
    UNKNOWN = "unknown"


@dataclass
class DiagnosticCheck:
    """A single diagnostic check to run."""
    name: str  # "Check OSPF hello interval"
    command: str  # "show ip ospf interface brief"
    priority: int  # 1=highest (run first), 10=lowest
    info_gain: float  # 0.0-1.0 (how much does this reduce hypothesis space?)
    estimated_time_sec: float  # How long does this check take?
    expected_in_healthy_state: str  # "hello=10" or "state=FULL"
    eliminates_hypotheses: List[str] = None  # Which hypotheses does this check eliminate?
    description: str = ""


@dataclass
class InvestigationPlan:
    """Plan for investigating an issue."""
    protocol: Protocol
    issue_type: str  # "EXSTART", "FLAPPING", "DEGRADATION", etc.
    root_device: str  # Starting device
    affected_devices: List[str]

    # Investigation phases
    prerequisite_checks: List[DiagnosticCheck]  # Must pass before proceeding
    primary_checks: List[DiagnosticCheck]  # Main diagnostic checks
    secondary_checks: List[DiagnosticCheck]  # If primary inconclusive
    vendor_specific_checks: List[DiagnosticCheck]  # For specific vendor quirks

    # Expected outcomes
    expected_duration_sec: float
    confidence_threshold: float  # When to stop investigating
    high_info_gain_checks: List[str]  # Names of checks that eliminate many hypotheses

    # Knowledge requirements
    protocol_knowledge_needed: List[str]
    vendor_knowledge_needed: List[str]
    enterprise_knowledge_needed: List[str]


class OSPFProtocolPlanner:
    """Plan investigations for OSPF issues."""

    def __init__(self):
        self.protocol = Protocol.OSPF
        logger.info("OSPFProtocolPlanner initialized")

    def plan_for_exstart(self, root_device: str, neighbor_device: str) -> InvestigationPlan:
        """Plan investigation for OSPF EXSTART state.

        OSPF EXSTART means:
        - Neighbors discovered each other
        - They're now exchanging OSPF database
        - Something is preventing full adjacency

        Root causes (in order of likelihood):
        1. Hello/Dead interval mismatch (40% of cases)
        2. Subnet/Area mismatch (30% of cases)
        3. MTU mismatch (15% of cases)
        4. OSPF disabled on interface (10% of cases)
        5. Authentication mismatch (5% of cases)
        """

        plan = InvestigationPlan(
            protocol=Protocol.OSPF,
            issue_type="EXSTART",
            root_device=root_device,
            affected_devices=[root_device, neighbor_device],

            # PREREQUISITE CHECKS (run first, must pass)
            prerequisite_checks=[
                DiagnosticCheck(
                    name="Verify OSPF enabled",
                    command="show ip protocols | include ospf",
                    priority=1,
                    info_gain=0.95,  # High info gain: protocol either enabled or not
                    estimated_time_sec=1,
                    expected_in_healthy_state="ospf process running",
                    eliminates_hypotheses=["OSPF disabled globally"],
                    description="Verify OSPF routing process is active"
                ),
                DiagnosticCheck(
                    name="Verify interface is up",
                    command="show interface | include status",
                    priority=2,
                    info_gain=0.85,
                    estimated_time_sec=1,
                    expected_in_healthy_state="up, line protocol up",
                    eliminates_hypotheses=["Interface down"],
                    description="Interface must be up for OSPF"
                ),
                DiagnosticCheck(
                    name="Verify OSPF enabled on interface",
                    command="show ip ospf interface brief",
                    priority=3,
                    info_gain=0.90,
                    estimated_time_sec=1,
                    expected_in_healthy_state="interface listed in OSPF",
                    eliminates_hypotheses=["OSPF not enabled on interface"],
                    description="OSPF must be enabled on the interface"
                ),
            ],

            # PRIMARY CHECKS (main diagnostic checks)
            primary_checks=[
                DiagnosticCheck(
                    name="Compare OSPF hello/dead intervals",
                    command="show ip ospf interface detail",
                    priority=1,
                    info_gain=0.88,  # Very high: mismatch explains EXSTART
                    estimated_time_sec=2,
                    expected_in_healthy_state="hello=10, dead=40",
                    eliminates_hypotheses=["Hello/Dead mismatch (40% likelihood)"],
                    description="Hello interval (default 10s) and Dead interval (default 40s) must match both ends"
                ),
                DiagnosticCheck(
                    name="Verify subnet and area match",
                    command="show ip ospf neighbor",
                    priority=2,
                    info_gain=0.75,  # High: area/subnet mismatch explains issues
                    estimated_time_sec=2,
                    expected_in_healthy_state="neighbor in same area",
                    eliminates_hypotheses=["Area mismatch (30% likelihood)"],
                    description="Neighbors must be in same area and subnet"
                ),
                DiagnosticCheck(
                    name="Check interface MTU",
                    command="show interface | include mtu",
                    priority=3,
                    info_gain=0.60,  # Medium: MTU issues can cause EXSTART
                    estimated_time_sec=1,
                    expected_in_healthy_state="mtu=1500",
                    eliminates_hypotheses=["MTU mismatch (15% likelihood)"],
                    description="MTU must support OSPF packets (typically 1500+)"
                ),
                DiagnosticCheck(
                    name="Verify authentication (if configured)",
                    command="show ip ospf interface | include authentication",
                    priority=4,
                    info_gain=0.70,
                    estimated_time_sec=1,
                    expected_in_healthy_state="auth disabled or matching type/password",
                    eliminates_hypotheses=["Authentication mismatch (5% likelihood)"],
                    description="Authentication must match if enabled"
                ),
            ],

            # SECONDARY CHECKS (if primary inconclusive)
            secondary_checks=[
                DiagnosticCheck(
                    name="Check for input queue drops",
                    command="show interface | include 'input drops'",
                    priority=5,
                    info_gain=0.40,
                    estimated_time_sec=1,
                    expected_in_healthy_state="0 input drops",
                    eliminates_hypotheses=[],
                    description="Input queue drops can prevent OSPF packets"
                ),
                DiagnosticCheck(
                    name="Check OSPF packet loss",
                    command="debug ip ospf adj",
                    priority=6,
                    info_gain=0.50,
                    estimated_time_sec=3,
                    expected_in_healthy_state="Hello packets exchanged",
                    eliminates_hypotheses=[],
                    description="Verify Hello packets are being sent/received"
                ),
                DiagnosticCheck(
                    name="Check for access lists blocking OSPF",
                    command="show access-list | include ospf",
                    priority=7,
                    info_gain=0.65,
                    estimated_time_sec=1,
                    expected_in_healthy_state="OSPF traffic not blocked",
                    eliminates_hypotheses=["ACL blocking OSPF"],
                    description="Access lists can block OSPF protocol 89"
                ),
            ],

            # VENDOR-SPECIFIC CHECKS
            vendor_specific_checks=[
                DiagnosticCheck(
                    name="Check Cisco IOS OSPF priority (if applicable)",
                    command="show ip ospf interface | include Priority",
                    priority=8,
                    info_gain=0.30,
                    estimated_time_sec=1,
                    expected_in_healthy_state="priority >= 0",
                    eliminates_hypotheses=[],
                    description="Cisco IOS specific OSPF priority setting"
                ),
            ],

            # Metadata
            expected_duration_sec=15,  # Total expected time
            confidence_threshold=0.85,  # Stop when 85% confident
            high_info_gain_checks=["Compare OSPF hello/dead intervals", "Verify subnet and area match"],

            protocol_knowledge_needed=[
                "OSPF state machine (DOWN → INIT → 2-WAY → EXSTART → EXCHANGE → LOADING → FULL)",
                "OSPF hello/dead intervals (default 10/40)",
                "OSPF area types and restrictions",
                "OSPF MTU requirements"
            ],

            vendor_knowledge_needed=[
                "Cisco IOS OSPF implementation quirks",
                "Juniper Junos OSPF specifics",
                "Arista EOS OSPF defaults"
            ],

            enterprise_knowledge_needed=[
                "Common OSPF EXSTART issues in our network",
                "How often hello/dead mismatches occur",
                "Which areas are we using and restrictions"
            ]
        )

        return plan

    def plan_for_flapping(self, root_device: str) -> InvestigationPlan:
        """Plan investigation for OSPF neighbor flapping (going UP/DOWN repeatedly)."""

        plan = InvestigationPlan(
            protocol=Protocol.OSPF,
            issue_type="FLAPPING",
            root_device=root_device,
            affected_devices=[root_device],

            prerequisite_checks=[
                DiagnosticCheck(
                    name="Check interface stability",
                    command="show interface status | include down",
                    priority=1,
                    info_gain=0.80,
                    estimated_time_sec=1,
                    expected_in_healthy_state="interface up",
                    eliminates_hypotheses=["Physical interface down"],
                ),
            ],

            primary_checks=[
                DiagnosticCheck(
                    name="Check for input/output errors on interface",
                    command="show interface | include errors",
                    priority=1,
                    info_gain=0.85,
                    estimated_time_sec=1,
                    expected_in_healthy_state="0 errors",
                    eliminates_hypotheses=["Interface errors causing loss"],
                ),
                DiagnosticCheck(
                    name="Check OSPF retransmit timeout",
                    command="show ip ospf neighbors detail",
                    priority=2,
                    info_gain=0.70,
                    estimated_time_sec=2,
                    expected_in_healthy_state="no timeout messages",
                    eliminates_hypotheses=["Retransmit timeout due to packet loss"],
                ),
                DiagnosticCheck(
                    name="Check output queue depth",
                    command="show interface | include queue",
                    priority=3,
                    info_gain=0.75,
                    estimated_time_sec=1,
                    expected_in_healthy_state="queue drops=0",
                    eliminates_hypotheses=["Output queue drops"],
                ),
                DiagnosticCheck(
                    name="Check for packet loss on link",
                    command="ping -c 100 neighbor | include loss",
                    priority=4,
                    info_gain=0.80,
                    estimated_time_sec=3,
                    expected_in_healthy_state="0% packet loss",
                    eliminates_hypotheses=["Packet loss causing retransmit"],
                ),
            ],

            secondary_checks=[
                DiagnosticCheck(
                    name="Check interface MTU configuration",
                    command="show interface | include mtu",
                    priority=5,
                    info_gain=0.60,
                    estimated_time_sec=1,
                    expected_in_healthy_state="mtu=1500",
                    eliminates_hypotheses=["MTU causing packet loss"],
                ),
            ],

            vendor_specific_checks=[],

            expected_duration_sec=12,
            confidence_threshold=0.80,
            high_info_gain_checks=["Check for input/output errors on interface", "Check for packet loss on link"],

            protocol_knowledge_needed=[
                "OSPF retransmit mechanism and timeout behavior",
                "Packet loss impact on OSPF adjacency",
                "OSPF exponential backoff"
            ],
            vendor_knowledge_needed=[],
            enterprise_knowledge_needed=[]
        )

        return plan

    def plan_for_degradation(self, root_device: str) -> InvestigationPlan:
        """Plan investigation for OSPF route quality degradation."""

        plan = InvestigationPlan(
            protocol=Protocol.OSPF,
            issue_type="DEGRADATION",
            root_device=root_device,
            affected_devices=[root_device],

            prerequisite_checks=[
                DiagnosticCheck(
                    name="Verify neighbors are FULL",
                    command="show ip ospf neighbors",
                    priority=1,
                    info_gain=0.90,
                    estimated_time_sec=1,
                    expected_in_healthy_state="state=FULL",
                    eliminates_hypotheses=["Incomplete adjacency"],
                ),
                DiagnosticCheck(
                    name="Verify routes are learned",
                    command="show ip route ospf",
                    priority=2,
                    info_gain=0.85,
                    estimated_time_sec=1,
                    expected_in_healthy_state="routes present",
                    eliminates_hypotheses=["No routes learned"],
                ),
            ],

            primary_checks=[
                DiagnosticCheck(
                    name="Check OSPF metric/cost configuration",
                    command="show ip ospf interface",
                    priority=1,
                    info_gain=0.75,
                    estimated_time_sec=2,
                    expected_in_healthy_state="cost matches interface speed",
                    eliminates_hypotheses=["Incorrect OSPF cost"],
                ),
                DiagnosticCheck(
                    name="Check for OSPF metric/default route conflicts",
                    command="show ip route | include default",
                    priority=2,
                    info_gain=0.70,
                    estimated_time_sec=1,
                    expected_in_healthy_state="default route has good metric",
                    eliminates_hypotheses=["Default route override"],
                ),
                DiagnosticCheck(
                    name="Check OSPF area type (stub/not-so-stubby)",
                    command="show ip ospf",
                    priority=3,
                    info_gain=0.65,
                    estimated_time_sec=1,
                    expected_in_healthy_state="area type standard",
                    eliminates_hypotheses=["Stub area restrictions"],
                ),
                DiagnosticCheck(
                    name="Check for route redistribution issues",
                    command="show ip ospf redistribution",
                    priority=4,
                    info_gain=0.60,
                    estimated_time_sec=1,
                    expected_in_healthy_state="no redistribution filtering",
                    eliminates_hypotheses=["Route filtering"],
                ),
            ],

            secondary_checks=[],
            vendor_specific_checks=[],

            expected_duration_sec=10,
            confidence_threshold=0.80,
            high_info_gain_checks=["Check OSPF metric/cost configuration"],

            protocol_knowledge_needed=[
                "OSPF metric calculation and path selection",
                "OSPF area types and their restrictions",
                "Route redistribution in OSPF"
            ],
            vendor_knowledge_needed=[],
            enterprise_knowledge_needed=[]
        )

        return plan


class BGPProtocolPlanner:
    """Plan investigations for BGP issues."""

    def __init__(self):
        self.protocol = Protocol.BGP
        logger.info("BGPProtocolPlanner initialized")

    def plan_for_flapping(self, local_device: str, neighbor_ip: str) -> InvestigationPlan:
        """Plan investigation for BGP session flapping (going UP/DOWN repeatedly)."""

        plan = InvestigationPlan(
            protocol=Protocol.BGP,
            issue_type="FLAPPING",
            root_device=local_device,
            affected_devices=[local_device, neighbor_ip],

            prerequisite_checks=[
                DiagnosticCheck(
                    name="Verify TCP connectivity on port 179",
                    command="netstat -an | grep 179",
                    priority=1,
                    info_gain=0.85,
                    estimated_time_sec=1,
                    expected_in_healthy_state="TCP state established",
                    eliminates_hypotheses=["TCP connectivity issue"],
                ),
                DiagnosticCheck(
                    name="Verify neighbor is reachable",
                    command=f"ping {neighbor_ip}",
                    priority=2,
                    info_gain=0.80,
                    estimated_time_sec=2,
                    expected_in_healthy_state="replies received",
                    eliminates_hypotheses=["Neighbor unreachable"],
                ),
            ],

            primary_checks=[
                DiagnosticCheck(
                    name="Check for link packet loss (BGP keepalives)",
                    command="ping -c 100 neighbor | include loss",
                    priority=1,
                    info_gain=0.85,
                    estimated_time_sec=3,
                    expected_in_healthy_state="0% packet loss",
                    eliminates_hypotheses=["Packet loss on link"],
                ),
                DiagnosticCheck(
                    name="Check output queue depth and drops",
                    command="show interface | include queue",
                    priority=2,
                    info_gain=0.80,
                    estimated_time_sec=1,
                    expected_in_healthy_state="queue depth low, drops=0",
                    eliminates_hypotheses=["Output queue drops"],
                ),
                DiagnosticCheck(
                    name="Check BGP keepalive/hold time mismatch",
                    command="show ip bgp neighbors detail",
                    priority=3,
                    info_gain=0.75,
                    estimated_time_sec=2,
                    expected_in_healthy_state="keepalive/hold match",
                    eliminates_hypotheses=["Keepalive/hold time mismatch"],
                ),
                DiagnosticCheck(
                    name="Check for BGP configuration changes",
                    command="show run | include neighbor",
                    priority=4,
                    info_gain=0.60,
                    estimated_time_sec=1,
                    expected_in_healthy_state="config unchanged",
                    eliminates_hypotheses=["Config changes"],
                ),
            ],

            secondary_checks=[
                DiagnosticCheck(
                    name="Check for route flapping",
                    command="show ip bgp dampening",
                    priority=5,
                    info_gain=0.50,
                    estimated_time_sec=1,
                    expected_in_healthy_state="no route flaps",
                    eliminates_hypotheses=[],
                ),
            ],

            vendor_specific_checks=[],

            expected_duration_sec=12,
            confidence_threshold=0.85,
            high_info_gain_checks=["Check for link packet loss (BGP keepalives)", "Check output queue depth and drops"],

            protocol_knowledge_needed=[
                "BGP keepalive/hold time interaction",
                "BGP session establishment and maintenance",
                "Impact of packet loss on BGP"
            ],
            vendor_knowledge_needed=[],
            enterprise_knowledge_needed=[]
        )

        return plan

    def plan_for_session_down(self, local_device: str, neighbor_ip: str) -> InvestigationPlan:
        """Plan investigation for BGP session down."""
        plan = InvestigationPlan(
            protocol=Protocol.BGP,
            issue_type="SESSION_DOWN",
            root_device=local_device,
            affected_devices=[local_device, neighbor_ip],

            prerequisite_checks=[
                DiagnosticCheck(
                    name="Verify BGP process enabled",
                    command="show ip protocols | include bgp",
                    priority=1,
                    info_gain=0.95,
                    estimated_time_sec=1,
                    expected_in_healthy_state="bgp running",
                    eliminates_hypotheses=["BGP disabled globally"],
                ),
                DiagnosticCheck(
                    name="Verify neighbor is reachable",
                    command=f"ping {neighbor_ip}",
                    priority=2,
                    info_gain=0.90,
                    estimated_time_sec=2,
                    expected_in_healthy_state="replies received",
                    eliminates_hypotheses=["Neighbor unreachable"],
                ),
            ],

            primary_checks=[
                DiagnosticCheck(
                    name="Check BGP neighbor status",
                    command="show ip bgp neighbors",
                    priority=1,
                    info_gain=0.85,
                    estimated_time_sec=2,
                    expected_in_healthy_state="state=Established",
                    eliminates_hypotheses=["Session down"],
                ),
                DiagnosticCheck(
                    name="Verify BGP local AS and remote AS",
                    command="show ip bgp neighbors detail",
                    priority=2,
                    info_gain=0.80,
                    estimated_time_sec=2,
                    expected_in_healthy_state="local-as matches, remote-as matches",
                    eliminates_hypotheses=["AS number mismatch"],
                ),
                DiagnosticCheck(
                    name="Check TCP port 179 connectivity",
                    command="netstat -an | grep 179",
                    priority=3,
                    info_gain=0.75,
                    estimated_time_sec=1,
                    expected_in_healthy_state="tcp established",
                    eliminates_hypotheses=["TCP connectivity issue"],
                ),
            ],

            secondary_checks=[],
            vendor_specific_checks=[],

            expected_duration_sec=10,
            confidence_threshold=0.85,
            high_info_gain_checks=["Check BGP neighbor status", "Verify BGP local AS and remote AS"],

            protocol_knowledge_needed=[
                "BGP state machine (IDLE → CONNECT → ACTIVE → OPENSENT → OPENCONFIRM → ESTABLISHED)",
                "BGP neighbor discovery and hello mechanism",
                "BGP AS number matching requirements"
            ],
            vendor_knowledge_needed=[],
            enterprise_knowledge_needed=[]
        )

        return plan


class ProtocolPlanner:
    """Main protocol planner factory."""

    def __init__(self):
        self.ospf_planner = OSPFProtocolPlanner()
        self.bgp_planner = BGPProtocolPlanner()
        logger.info("ProtocolPlanner initialized")

    def plan_investigation(self,
                          protocol: Protocol,
                          issue_type: str,
                          root_device: str,
                          affected_devices: List[str],
                          neighbor_device: Optional[str] = None) -> Optional[InvestigationPlan]:
        """Generate protocol-aware investigation plan.

        Parameters
        ----------
        protocol : Protocol
            Which protocol to investigate (OSPF, BGP, etc.)
        issue_type : str
            What kind of issue (EXSTART, FLAPPING, SESSION_DOWN, etc.)
        root_device : str
            Starting device
        affected_devices : List[str]
            All affected devices
        neighbor_device : str, optional
            Neighbor device (for peer-based issues)

        Returns
        -------
        InvestigationPlan or None
            Investigation plan, or None if not supported
        """

        logger.info(f"Planning investigation: {protocol.value} {issue_type} on {root_device}")

        try:
            if protocol == Protocol.OSPF:
                if issue_type.upper() == "EXSTART":
                    return self.ospf_planner.plan_for_exstart(root_device, neighbor_device or "unknown")
                elif issue_type.upper() == "FLAPPING":
                    return self.ospf_planner.plan_for_flapping(root_device)
                elif issue_type.upper() == "DEGRADATION":
                    return self.ospf_planner.plan_for_degradation(root_device)

            elif protocol == Protocol.BGP:
                if issue_type.upper() == "SESSION_DOWN":
                    return self.bgp_planner.plan_for_session_down(root_device, neighbor_device or "unknown")
                elif issue_type.upper() == "FLAPPING" or issue_type.upper() == "SESSION_FLAPPING":
                    return self.bgp_planner.plan_for_flapping(root_device, neighbor_device or "unknown")

            logger.warning(f"No plan for {protocol.value} / {issue_type}")
            return None

        except Exception as e:
            logger.error(f"Error planning investigation: {e}")
            return None

    def get_checks_sorted_by_priority(self, plan: InvestigationPlan) -> List[DiagnosticCheck]:
        """Get all checks sorted by priority.

        Order:
        1. Prerequisites (must pass first)
        2. Primary checks (by info_gain/time ratio)
        3. Secondary checks
        4. Vendor specific
        """

        all_checks = (
            plan.prerequisite_checks +
            plan.primary_checks +
            plan.secondary_checks +
            plan.vendor_specific_checks
        )

        # Primary checks sorted by info_gain/time ratio
        primary_sorted = sorted(
            plan.primary_checks,
            key=lambda c: c.info_gain / (c.estimated_time_sec + 0.1),
            reverse=True
        )

        return (
            plan.prerequisite_checks +  # Prerequisites first (in order)
            primary_sorted +  # Primary by info gain
            plan.secondary_checks +
            plan.vendor_specific_checks
        )

    def print_plan(self, plan: InvestigationPlan) -> str:
        """Generate human-readable investigation plan."""
        report = "🔍 INVESTIGATION PLAN\n"
        report += "=" * 70 + "\n\n"

        report += f"Protocol: {plan.protocol.value.upper()}\n"
        report += f"Issue Type: {plan.issue_type}\n"
        report += f"Root Device: {plan.root_device}\n"
        report += f"Affected Devices: {', '.join(plan.affected_devices)}\n"
        report += f"Expected Duration: ~{plan.expected_duration_sec}s\n\n"

        report += "PREREQUISITE CHECKS (must pass first):\n"
        report += "─" * 70 + "\n"
        for i, check in enumerate(plan.prerequisite_checks, 1):
            report += f"{i}. {check.name}\n"
            report += f"   Command: {check.command}\n"
            report += f"   Info Gain: {check.info_gain:.0%} | Time: {check.estimated_time_sec}s\n"
            report += f"   Expected: {check.expected_in_healthy_state}\n\n"

        report += "PRIMARY CHECKS (sorted by info gain/time ratio):\n"
        report += "─" * 70 + "\n"
        primary_sorted = sorted(
            plan.primary_checks,
            key=lambda c: c.info_gain / (c.estimated_time_sec + 0.1),
            reverse=True
        )
        for i, check in enumerate(primary_sorted, 1):
            ratio = check.info_gain / (check.estimated_time_sec + 0.1)
            report += f"{i}. {check.name} [ratio: {ratio:.2f}]\n"
            report += f"   Command: {check.command}\n"
            report += f"   Eliminates: {', '.join(check.eliminates_hypotheses or [])}\n\n"

        report += f"\nHigh-Info-Gain Checks: {', '.join(plan.high_info_gain_checks)}\n"
        report += f"Confidence Threshold: {plan.confidence_threshold:.0%}\n"

        return report
