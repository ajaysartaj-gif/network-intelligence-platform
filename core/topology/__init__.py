"""
NetBrain Network Topology System
=================================
Builds site-wise network topology diagrams from real CDP/LLDP discovery,
with AI chat and PPTX/PDF/Visio export.

Public API:
  - build_topology_for_site(), list_available_sites() — core/topology_engine.py
  - TopologyGraph, TopologyNode, TopologyLink, DeviceRole — models
  - TopologyChatEngine — AI Q&A over a built graph
  - export_topology_to_pptx/_pdf/_vdx — export/
"""
from core.topology.topology_models import (
    TopologyGraph, TopologyNode, TopologyLink, DeviceRole,
)
from core.topology.topology_engine import build_topology_for_site, list_available_sites
from core.topology.topology_cache import get_topology_cache
from core.topology.chat import TopologyChatEngine
from core.topology.export import (
    export_topology_to_pptx,
    export_topology_to_pdf,
    export_topology_to_vdx,
)

__all__ = [
    "TopologyGraph",
    "TopologyNode",
    "TopologyLink",
    "DeviceRole",
    "build_topology_for_site",
    "list_available_sites",
    "get_topology_cache",
    "TopologyChatEngine",
    "export_topology_to_pptx",
    "export_topology_to_pdf",
    "export_topology_to_vdx",
]
