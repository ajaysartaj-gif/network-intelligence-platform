"""
OSPF-specific comparison context.

Extracts OSPF configuration and state into format expected by comparison engine.
"""

from typing import Dict, Any, Optional
from diagnostics.parsers.ospf import OSPFInterface, OSPFNeighbor, OSPFConfig
from diagnostics.comparison import ComparisonContext


class OSPFComparisonContext:
    """Extracts OSPF parameters relevant to specific context."""

    @staticmethod
    def neighbor_establishment(
        interface_a: Optional[OSPFInterface],
        interface_b: Optional[OSPFInterface],
        neighbor_a: Optional[OSPFNeighbor],
        neighbor_b: Optional[OSPFNeighbor],
        config_a: Optional[OSPFConfig],
        config_b: Optional[OSPFConfig],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Extract parameters relevant to neighbor establishment.

        Returns:
            (config_dict_a, config_dict_b)
        """

        config_dict_a = {}
        config_dict_b = {}

        # From interfaces
        if interface_a:
            config_dict_a["area_id"] = interface_a.area
            config_dict_a["network_type"] = interface_a.network_type.value if interface_a.network_type else None
            config_dict_a["hello_interval"] = interface_a.hello_interval
            config_dict_a["dead_interval"] = interface_a.dead_interval
            config_dict_a["mtu"] = interface_a.mtu
            config_dict_a["ip_address"] = interface_a.ip_address

        if interface_b:
            config_dict_b["area_id"] = interface_b.area
            config_dict_b["network_type"] = interface_b.network_type.value if interface_b.network_type else None
            config_dict_b["hello_interval"] = interface_b.hello_interval
            config_dict_b["dead_interval"] = interface_b.dead_interval
            config_dict_b["mtu"] = interface_b.mtu
            config_dict_b["ip_address"] = interface_b.ip_address

        # From config
        if config_a:
            config_dict_a["router_id"] = config_a.router_id
            config_dict_a["process_id"] = config_a.process_id

        if config_b:
            config_dict_b["router_id"] = config_b.router_id
            config_dict_b["process_id"] = config_b.process_id

        return config_dict_a, config_dict_b

    @staticmethod
    def bgp_peering(
        config_a: Dict[str, Any],
        config_b: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Extract parameters relevant to BGP peering.

        Returns:
            (config_dict_a, config_dict_b)
        """
        # BGP comparison not yet implemented
        return config_a, config_b
