"""
tests/test_dataset_phase2.py
============================
Phase 2 Validation: Test dataset with historical incidents.

Contains realistic network troubleshooting scenarios with:
- Problem description
- Device outputs (simulated or historical)
- Expected root cause
- Success criteria
"""

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from enum import Enum

import sys
sys.path.insert(0, '/Users/traptigupta/Desktop/network-intelligence-platform')

from core.protocol_planner import Protocol


class IncidentSeverity(str, Enum):
    """Incident severity level."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class HistoricalIncident:
    """A historical incident for validation testing."""
    incident_id: str
    protocol: Protocol
    issue_type: str  # EXSTART, FLAPPING, SESSION_DOWN, etc.
    severity: IncidentSeverity

    # Problem description
    problem_description: str
    affected_devices: List[str]
    root_device: str

    # Device outputs (what the investigation will see)
    device_outputs: Dict[str, str]  # {check_name: output}

    # Expected results
    expected_root_cause: str
    expected_confidence: float  # 0.0-1.0 (e.g., 0.85)
    expected_cycles: int  # Expected number of investigation cycles

    # Success criteria
    max_cycles_allowed: int = 5
    min_confidence_required: float = 0.80
    accuracy_required: bool = True  # Root cause must match exactly

    # Optional: External knowledge that would help
    external_knowledge_helpful: List[str] = None


# ═══════════════════════════════════════════════════════════════════════════════
# TEST DATASET: OSPF Issues (Primary Focus)
# ═══════════════════════════════════════════════════════════════════════════════

OSPF_EXSTART_HELLO_MISMATCH = HistoricalIncident(
    incident_id="OSPF-001",
    protocol=Protocol.OSPF,
    issue_type="EXSTART",
    severity=IncidentSeverity.HIGH,

    problem_description=(
        "Two OSPF routers (R1 and R2) stuck in EXSTART state. "
        "They discover each other but can't exchange routing database. "
        "Network reports: 'R1 and R2 not forming full adjacency'"
    ),
    affected_devices=["router-1", "router-2"],
    root_device="router-1",

    device_outputs={
        "show_ip_ospf_neighbors": """
            Neighbor ID     Pri   State           Dead Time   Address         Interface
            10.0.0.2          1   EXSTART/DR      35          192.168.1.2     Gi0/0
        """,

        "show_ip_ospf_interface_detail_r1": """
            GigabitEthernet0/0 is up, line protocol is up
              Internet Address 192.168.1.1/24, Area 0
              Process ID 1, Router ID 10.0.0.1, Network Type BROADCAST, Cost: 1
              Hello interval is 10 sec
              Dead interval is 40 sec
              Timer intervals configured, Hello 10, Dead 40, Wait 40, Retransmit 5
              Hello due in 3 sec
              Supports Link-local Signaling (LLS)
              Cisco NSF helper support enabled
              IETF NSF helper support enabled
        """,

        "show_ip_ospf_interface_detail_r2": """
            GigabitEthernet0/0 is up, line protocol is up
              Internet Address 192.168.1.2/24, Area 0
              Process ID 1, Router ID 10.0.0.2, Network Type BROADCAST, Cost: 1
              Hello interval is 30 sec
              Dead interval is 120 sec
              Timer intervals configured, Hello 30, Dead 120, Wait 120, Retransmit 5
              Hello due in 27 sec
              Supports Link-local Signaling (LLS)
              Cisco NSF helper support enabled
              IETF NSF helper support enabled
        """,

        "show_interface_r1": """
            GigabitEthernet0/0 is up, line protocol is up (connected)
              Hardware is iGbE, address is aabb.cc00.0001
              MTU 1500 bytes, BW 1000000 Kbit/sec
              Encapsulation ARPA, loopback not set
        """,

        "show_interface_r2": """
            GigabitEthernet0/0 is up, line protocol is up (connected)
              Hardware is iGbE, address is aabb.cc00.0002
              MTU 1500 bytes, BW 1000000 Kbit/sec
              Encapsulation ARPA, loopback not set
        """,
    },

    expected_root_cause="Hello/Dead interval mismatch (R1: 10/40, R2: 30/120)",
    expected_confidence=0.92,
    expected_cycles=2,

    external_knowledge_helpful=[
        "OSPF hello/dead interval requirements",
        "Common configuration mistakes in enterprise",
        "OSPF state machine transitions"
    ]
)

OSPF_EXSTART_AREA_MISMATCH = HistoricalIncident(
    incident_id="OSPF-002",
    protocol=Protocol.OSPF,
    issue_type="EXSTART",
    severity=IncidentSeverity.HIGH,

    problem_description=(
        "OSPF neighbors discover each other but don't form full adjacency. "
        "Stuck in EXSTART state on one particular link."
    ),
    affected_devices=["router-1", "router-3"],
    root_device="router-1",

    device_outputs={
        "show_ip_ospf_neighbors": """
            Neighbor ID     Pri   State           Dead Time   Address         Interface
            10.0.0.3          1   EXSTART/-       36          192.168.2.2     Gi0/1
        """,

        "show_ip_ospf_process_r1": """
            Routing Process "ospf 1" with ID 10.0.0.1
              Router is abr
              Number of areas: 2
              Area 0
                Number of interfaces in this area is 2
              Area 1
                Number of interfaces in this area is 1 (Stub Area)
        """,

        "show_ip_ospf_process_r3": """
            Routing Process "ospf 1" with ID 10.0.0.3
              Router is abr
              Number of areas: 2
              Area 0
                Number of interfaces in this area is 1
              Area 2
                Number of interfaces in this area is 2 (Stub Area)
        """,

        "show_ip_ospf_interface_r1": """
            GigabitEthernet0/1 is up, line protocol is up
              Internet Address 192.168.2.1/24, Area 1
              Hello interval is 10 sec, Dead interval is 40 sec
        """,

        "show_ip_ospf_interface_r3": """
            GigabitEthernet0/1 is up, line protocol is up
              Internet Address 192.168.2.2/24, Area 2
              Hello interval is 10 sec, Dead interval is 40 sec
        """,
    },

    expected_root_cause="OSPF area mismatch (R1: Area 1, R3: Area 2)",
    expected_confidence=0.88,
    expected_cycles=2,

    external_knowledge_helpful=[
        "OSPF area rules (neighbors must be in same area)",
        "Stub area routing restrictions"
    ]
)

OSPF_FLAPPING_MTU = HistoricalIncident(
    incident_id="OSPF-003",
    protocol=Protocol.OSPF,
    issue_type="FLAPPING",
    severity=IncidentSeverity.CRITICAL,

    problem_description=(
        "OSPF adjacency keeps going UP then DOWN repeatedly (flapping). "
        "Logs show: 'Adjacency down: Too old retransmit from 10.0.0.4'"
    ),
    affected_devices=["router-1", "router-4"],
    root_device="router-1",

    device_outputs={
        "show_ip_ospf_neighbors": """
            Neighbor ID     Pri   State           Dead Time   Address         Interface
            10.0.0.4          1   FULL/-          31          192.168.3.2     Gi0/2
            (Note: Flapping frequently)
        """,

        "show_interface_r1": """
            GigabitEthernet0/2 is up, line protocol is up
              MTU 1500 bytes, BW 1000000 Kbit/sec
              Encapsulation ARPA
        """,

        "show_interface_r4": """
            GigabitEthernet0/2 is up, line protocol is up
              MTU 1400 bytes, BW 1000000 Kbit/sec
              Encapsulation ARPA
              Spanning Tree Protocol enabled
        """,

        "ping_r4_with_df": """
            PING 192.168.3.2 (192.168.3.2): 1500 bytes data
            Reply from 192.168.3.2: Fragmentation needed and DF set (ICMP type 3, code 4)
        """,
    },

    expected_root_cause="MTU mismatch (R1: 1500, R4: 1400) causing packet loss and adjacency flapping",
    expected_confidence=0.85,
    expected_cycles=3,

    external_knowledge_helpful=[
        "MTU impact on OSPF database exchange",
        "Path MTU discovery",
        "OSPF retransmit timeout behavior"
    ]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TEST DATASET: BGP Issues
# ═══════════════════════════════════════════════════════════════════════════════

BGP_SESSION_DOWN_AS_MISMATCH = HistoricalIncident(
    incident_id="BGP-001",
    protocol=Protocol.BGP,
    issue_type="SESSION_DOWN",
    severity=IncidentSeverity.CRITICAL,

    problem_description=(
        "BGP session between R1 and R5 won't establish. "
        "Session goes to IDLE then back to CONNECT repeatedly."
    ),
    affected_devices=["router-1", "router-5"],
    root_device="router-1",

    device_outputs={
        "show_ip_bgp_neighbors": """
            BGP neighbor is 10.0.0.5, remote AS 65000, local AS 65001
              BGP version 4, remote router ID 10.0.0.5
              BGP state = Idle, up for 0:00:00
              Last read 0:00:10, Last write 0:00:10
              Hold time is 180, keepalive interval is 60 seconds
              Configured hold time is 180, keepalive interval is 60 seconds
              *** OPTION IS DEPRECATED ***
        """,

        "show_ip_bgp_neighbors_config_r1": """
            router bgp 65001
              neighbor 10.0.0.5 remote-as 65000
        """,

        "show_ip_bgp_neighbors_config_r5": """
            router bgp 65000
              neighbor 10.0.0.1 remote-as 65000
        """,

        "ping_r5": """
            PING 10.0.0.5 (10.0.0.5): 56 data bytes
            64 bytes from 10.0.0.5: icmp_seq=0 ttl=64 time=5 ms
        """,
    },

    expected_root_cause="BGP AS number mismatch (R1: 65001, R5: 65000 configured as local AS instead of remote)",
    expected_confidence=0.90,
    expected_cycles=2,

    external_knowledge_helpful=[
        "BGP AS number matching requirements",
        "BGP OPEN message validation",
        "Common BGP configuration mistakes"
    ]
)

BGP_KEEPALIVE_LOST = HistoricalIncident(
    incident_id="BGP-002",
    protocol=Protocol.BGP,
    issue_type="SESSION_FLAPPING",
    severity=IncidentSeverity.HIGH,

    problem_description=(
        "BGP session established but drops after 60-90 seconds. "
        "Logs show: 'Hold time expired'"
    ),
    affected_devices=["router-1", "router-6"],
    root_device="router-1",

    device_outputs={
        "show_ip_bgp_neighbors": """
            BGP neighbor is 10.0.0.6, remote AS 65002
              BGP version 4, remote router ID 10.0.0.6
              BGP state = Established, up for 0:01:23
              Last read 0:00:05, Last write 0:00:08
              Hold time is 180, keepalive interval is 60 seconds
              (Session flaps frequently: Established → Idle → Connect)
        """,

        "show_ip_bgp_neighbors_r1": """
            Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
            10.0.0.6        4 65002      15      14        0    0    0 0:01:23 (flapping)
        """,

        "show_ip_bgp_neighbors_r6": """
            Neighbor        V    AS MsgRcvd MsgSent   TblVer  InQ OutQ Up/Down  State/PfxRcd
            10.0.0.1        4 65001       8       8        0    0    0 0:00:45 (idle)
        """,

        "show_interface_r1_to_r6": """
            GigabitEthernet0/3 is up, line protocol is up
              Input queue: 5000/75000/0/0 (size/max/drops/flushes)
              Output queue: 75/1000 (size/max)
              5 minute output rate 500000 bits/sec, 800 packets/sec
        """,
    },

    expected_root_cause="High packet loss on link (output queue building up) causing BGP keepalives to be dropped",
    expected_confidence=0.82,
    expected_cycles=3,

    external_knowledge_helpful=[
        "BGP keepalive/hold time interaction",
        "Impact of packet loss on BGP",
        "Interface queue monitoring"
    ]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TEST DATASET: Unknown Issues (requires external knowledge)
# ═══════════════════════════════════════════════════════════════════════════════

UNKNOWN_OSPF_ISSUE = HistoricalIncident(
    incident_id="UNKNOWN-001",
    protocol=Protocol.OSPF,
    issue_type="DEGRADATION",
    severity=IncidentSeverity.MEDIUM,

    problem_description=(
        "OSPF neighbors are FULL but routes aren't learned. "
        "No error messages in logs. Mysterious behavior."
    ),
    affected_devices=["router-1", "router-7"],
    root_device="router-1",

    device_outputs={
        "show_ip_ospf_neighbors": """
            Neighbor ID     Pri   State           Dead Time   Address         Interface
            10.0.0.7          1   FULL/DR         36          192.168.4.2     Gi0/4
        """,

        "show_ip_route_ospf": """
            (No OSPF routes learned, but neighbor is FULL)
        """,

        "show_ip_ospf_database": """
            OSPF Router with ID (10.0.0.1) (Process ID 1)
              Router Link States (Area 0)
              (Only local LSAs, no remote LSAs from 10.0.0.7)
        """,

        "show_ip_ospf_database_external": """
            (No external routes advertised by 10.0.0.7)
        """,
    },

    expected_root_cause="OSPF passive interface or stub area configured on R7, preventing route advertisement",
    expected_confidence=0.70,
    expected_cycles=3,

    external_knowledge_helpful=[
        "OSPF passive interface behavior",
        "OSPF stub/totally-stub area limitations",
        "OSPF LSA types and advertisements"
    ]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TEST DATASET COLLECTION
# ═══════════════════════════════════════════════════════════════════════════════

PHASE2_TEST_DATASET = {
    "ospf_exstart_hello_mismatch": OSPF_EXSTART_HELLO_MISMATCH,
    "ospf_exstart_area_mismatch": OSPF_EXSTART_AREA_MISMATCH,
    "ospf_flapping_mtu": OSPF_FLAPPING_MTU,
    "bgp_session_down_as_mismatch": BGP_SESSION_DOWN_AS_MISMATCH,
    "bgp_keepalive_lost": BGP_KEEPALIVE_LOST,
    "unknown_ospf_issue": UNKNOWN_OSPF_ISSUE,
}

# Categorized by difficulty
EASY_TEST_CASES = [
    "ospf_exstart_hello_mismatch",  # High-info-gain check finds it immediately
    "ospf_exstart_area_mismatch",   # Straightforward area check
]

MEDIUM_TEST_CASES = [
    "ospf_flapping_mtu",            # Requires looking at multiple indicators
    "bgp_session_down_as_mismatch",  # AS number check needed
    "bgp_keepalive_lost",            # Link quality issues
]

HARD_TEST_CASES = [
    "unknown_ospf_issue",            # Requires external knowledge
]


def get_test_case(case_id: str) -> Optional[HistoricalIncident]:
    """Get a test case by ID."""
    return PHASE2_TEST_DATASET.get(case_id)


def get_all_test_cases() -> Dict[str, HistoricalIncident]:
    """Get all test cases."""
    return PHASE2_TEST_DATASET.copy()


def get_easy_test_cases() -> Dict[str, HistoricalIncident]:
    """Get easy test cases (should converge in ≤2 cycles)."""
    return {k: PHASE2_TEST_DATASET[k] for k in EASY_TEST_CASES}


def get_medium_test_cases() -> Dict[str, HistoricalIncident]:
    """Get medium test cases (should converge in ≤3 cycles)."""
    return {k: PHASE2_TEST_DATASET[k] for k in MEDIUM_TEST_CASES}


def get_hard_test_cases() -> Dict[str, HistoricalIncident]:
    """Get hard test cases (require external knowledge)."""
    return {k: PHASE2_TEST_DATASET[k] for k in HARD_TEST_CASES}


if __name__ == "__main__":
    print(f"Phase 2 Test Dataset: {len(PHASE2_TEST_DATASET)} test cases")
    print(f"  Easy (≤2 cycles): {len(EASY_TEST_CASES)}")
    print(f"  Medium (≤3 cycles): {len(MEDIUM_TEST_CASES)}")
    print(f"  Hard (requires knowledge): {len(HARD_TEST_CASES)}")
    print("\nTest cases:")
    for case_id, case in PHASE2_TEST_DATASET.items():
        print(f"  {case_id}: {case.protocol.value} {case.issue_type} ({case.severity.value})")
