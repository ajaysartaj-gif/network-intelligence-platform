"""
OSPF Parser for Cisco IOS

Parses common OSPF diagnostic commands and normalizes to standard format.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum


class NeighborState(Enum):
    """OSPF neighbor FSM states."""
    DOWN = "DOWN"
    ATTEMPT = "ATTEMPT"
    INIT = "INIT"
    TWO_WAY = "2WAY"
    EXSTART = "EXSTART"
    EXCHANGE = "EXCHANGE"
    LOADING = "LOADING"
    FULL = "FULL"


class NetworkType(Enum):
    """OSPF interface network types."""
    BROADCAST = "broadcast"
    NON_BROADCAST = "non-broadcast"
    POINT_TO_POINT = "point-to-point"
    POINT_TO_MULTIPOINT = "point-to-multipoint"


@dataclass
class OSPFNeighbor:
    """Parsed OSPF neighbor."""
    neighbor_id: str
    state: NeighborState
    address: str
    interface: str
    dead_timer: Optional[int] = None
    area: Optional[str] = None


@dataclass
class OSPFInterface:
    """Parsed OSPF interface."""
    name: str
    ip_address: str
    area: str
    network_type: NetworkType
    mtu: int
    state: str  # "UP" or "DOWN"
    hello_interval: int = 10
    dead_interval: int = 40
    passive: bool = False


@dataclass
class OSPFConfig:
    """Parsed OSPF configuration."""
    router_id: Optional[str] = None
    process_id: Optional[int] = None
    areas: List[str] = None
    interfaces: Dict[str, OSPFInterface] = None

    def __post_init__(self):
        if self.areas is None:
            self.areas = []
        if self.interfaces is None:
            self.interfaces = {}


class OSPFParser:
    """Parse OSPF show commands from Cisco IOS."""

    @staticmethod
    def parse_show_ip_ospf_neighbor(output: str) -> List[OSPFNeighbor]:
        """
        Parse: show ip ospf neighbor

        Example output:
        Neighbor ID     Pri   State           Dead Time   Address         Interface
        192.168.1.1       1   FULL/BDR        00:00:39    10.0.1.1        Gi0/0
        192.168.1.2       1   EXSTART/--      00:00:00    10.0.2.1        Gi0/1
        """
        neighbors = []
        lines = output.split("\n")

        for line in lines:
            # Skip headers and empty lines
            if not line.strip() or "Neighbor ID" in line:
                continue

            # Parse neighbor line
            parts = line.split()
            if len(parts) < 5:
                continue

            try:
                neighbor_id = parts[0]
                # Priority in parts[1]
                state_str = parts[2]  # e.g., "FULL/BDR"
                state = OSPFParser._parse_neighbor_state(state_str)
                # Dead time in parts[3]
                address = parts[4]
                interface = parts[5] if len(parts) > 5 else ""

                neighbors.append(
                    OSPFNeighbor(
                        neighbor_id=neighbor_id,
                        state=state,
                        address=address,
                        interface=interface,
                    )
                )
            except (ValueError, IndexError):
                continue

        return neighbors

    @staticmethod
    def parse_show_ip_ospf_interface(output: str) -> Dict[str, OSPFInterface]:
        """
        Parse: show ip ospf interface [brief]

        Extracts MTU, network type, state, timers.
        """
        interfaces = {}
        current_interface = None
        current_data = {}

        for line in output.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Interface line: "Gi0/0 is up, line protocol is up"
            if " is " in line and ("up" in line or "down" in line):
                if current_interface and "network_type" in current_data:
                    interfaces[current_interface] = OSPFParser._build_ospf_interface(
                        current_interface, current_data
                    )
                current_interface = line.split()[0]
                current_data = {}
                continue

            # Parse key fields
            if current_interface:
                if "Internet Address" in line:
                    # "Internet Address 10.0.1.1/24, Area 0, Attached via Interface Enable"
                    match = re.search(r"Internet Address ([\d\.]+)", line)
                    if match:
                        current_data["ip"] = match.group(1)
                    match = re.search(r"Area ([\d\.]+)", line)
                    if match:
                        current_data["area"] = match.group(1)

                if "Network Type" in line:
                    # "Network Type BROADCAST, Cost: 1"
                    if "BROADCAST" in line and "NON" not in line:
                        current_data["network_type"] = NetworkType.BROADCAST
                    elif "NON_BROADCAST" in line or ("NON" in line and "BROADCAST" in line):
                        current_data["network_type"] = NetworkType.NON_BROADCAST
                    elif "POINT_TO_POINT" in line:
                        current_data["network_type"] = NetworkType.POINT_TO_POINT
                    elif "POINT_TO_MULTIPOINT" in line:
                        current_data["network_type"] = NetworkType.POINT_TO_MULTIPOINT

                if "Hello interval" in line:
                    match = re.search(r"Hello interval (\d+)", line)
                    if match:
                        current_data["hello"] = int(match.group(1))

                if "Dead interval" in line:
                    match = re.search(r"Dead interval (\d+)", line)
                    if match:
                        current_data["dead"] = int(match.group(1))

                if "Transmit Delay" in line:
                    match = re.search(r"Transmit Delay (\d+)", line)
                    if match:
                        current_data["mtu"] = int(match.group(1))

        # Save last interface
        if current_interface and "network_type" in current_data:
            interfaces[current_interface] = OSPFParser._build_ospf_interface(
                current_interface, current_data
            )

        return interfaces

    @staticmethod
    def parse_running_config_ospf(config_output: str) -> OSPFConfig:
        """
        Parse OSPF configuration from running-config.

        Extracts router ID, process ID, areas, and interface config.
        """
        config = OSPFConfig()
        lines = config_output.split("\n")
        in_ospf_config = False

        for line in lines:
            line = line.rstrip()

            # Start of OSPF config: "router ospf <pid>"
            if "router ospf" in line:
                match = re.search(r"router ospf (\d+)", line)
                if match:
                    config.process_id = int(match.group(1))
                in_ospf_config = True
                continue

            if not in_ospf_config:
                continue

            # End of OSPF config (next router or end)
            if line and not line.startswith(" ") and not line.startswith("\t"):
                in_ospf_config = False
                continue

            # Router ID
            if "router-id" in line:
                match = re.search(r"router-id ([\d\.]+)", line)
                if match:
                    config.router_id = match.group(1)

            # Network statements: "network 10.0.1.0 0.0.0.255 area 0"
            if "network" in line and "area" in line:
                match = re.search(r"area ([\d\.]+)", line)
                if match:
                    area = match.group(1)
                    if area not in config.areas:
                        config.areas.append(area)

        return config

    @staticmethod
    def _parse_neighbor_state(state_str: str) -> NeighborState:
        """Parse neighbor state from 'FULL/BDR' format."""
        state = state_str.split("/")[0].upper()

        state_map = {
            "DOWN": NeighborState.DOWN,
            "ATTEMPT": NeighborState.ATTEMPT,
            "INIT": NeighborState.INIT,
            "2WAY": NeighborState.TWO_WAY,
            "EXSTART": NeighborState.EXSTART,
            "EXCHANGE": NeighborState.EXCHANGE,
            "LOADING": NeighborState.LOADING,
            "FULL": NeighborState.FULL,
        }

        return state_map.get(state, NeighborState.DOWN)

    @staticmethod
    def _build_ospf_interface(
        name: str, data: Dict
    ) -> OSPFInterface:
        """Build OSPFInterface from parsed data."""
        return OSPFInterface(
            name=name,
            ip_address=data.get("ip", ""),
            area=data.get("area", ""),
            network_type=data.get("network_type", NetworkType.BROADCAST),
            mtu=data.get("mtu", 1500),
            state="UP" if "up" in data.get("state", "up").lower() else "DOWN",
            hello_interval=data.get("hello", 10),
            dead_interval=data.get("dead", 40),
            passive=data.get("passive", False),
        )
