"""
core/topology/layout.py
========================
Computes (x, y) coordinates for every node in a TopologyGraph so it can
be drawn — by the interactive Plotly view, and reused as-is for the
PPTX/PDF/Visio exporters (one layout, every output format stays in sync).

Strategy: hierarchical-by-role layout.
  - Firewalls at the top (layer 0)
  - Routers next (layer 1)
  - Switches below that (layer 2)
  - Access points / phones at the bottom (layer 3)
Within a layer, nodes are spread evenly left-to-right. If networkx is
available, a spring layout pass is used to reduce edge crossings within
each layer before the final hierarchical y-snap; if networkx is missing,
falls back to simple even spacing (still fully functional, just less
optimized visually).
"""
from __future__ import annotations

import logging
from typing import Dict, List

from core.topology.topology_models import TopologyGraph, DeviceRole

logger = logging.getLogger("NetBrain.Topology.Layout")

try:
    import networkx as nx
    NETWORKX_OK = True
except ImportError:
    NETWORKX_OK = False


LAYER_HEIGHT = 200     # vertical spacing between role layers
NODE_SPACING = 220     # horizontal spacing between nodes in the same layer


def compute_layout(graph: TopologyGraph) -> None:
    """
    Mutates graph.nodes in place, setting .x and .y on every TopologyNode.
    """
    if not graph.nodes:
        return

    # Group nodes by role layer
    layers: Dict[int, List[str]] = {}
    for ip, node in graph.nodes.items():
        layer = node.role.layer
        layers.setdefault(layer, []).append(ip)

    # Optional: use networkx spring layout WITHIN each layer to order nodes
    # so that connected nodes end up closer together horizontally (fewer
    # crossing lines), before snapping to the fixed hierarchical y per layer.
    ordering: Dict[str, float] = {}
    if NETWORKX_OK:
        try:
            g = nx.Graph()
            for ip in graph.nodes:
                g.add_node(ip)
            for link in graph.links:
                if link.device_a_ip in graph.nodes and link.device_b_ip in graph.nodes:
                    g.add_edge(link.device_a_ip, link.device_b_ip)
            pos = nx.spring_layout(g, seed=42, k=1.2)
            ordering = {ip: float(p[0]) for ip, p in pos.items()}
        except Exception as exc:
            logger.debug(f"networkx spring_layout failed, using even spacing: {exc}")
            ordering = {}

    for layer_idx in sorted(layers.keys()):
        ips_in_layer = layers[layer_idx]
        # Sort by spring-layout x position if available, else keep stable order
        if ordering:
            ips_in_layer.sort(key=lambda ip: ordering.get(ip, 0.0))

        n = len(ips_in_layer)
        total_width = (n - 1) * NODE_SPACING
        start_x = -total_width / 2

        for i, ip in enumerate(ips_in_layer):
            node = graph.nodes[ip]
            node.x = start_x + i * NODE_SPACING
            node.y = layer_idx * LAYER_HEIGHT
