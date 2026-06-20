"""
core/topology/layout.py
========================
Computes (x, y) coordinates for every node in a TopologyGraph so it can
be drawn -- by the interactive Plotly view, and reused as-is for the
PPTX/PDF/Visio exporters (one layout, every output format stays in sync).

Strategy: graph-structure-driven hierarchical layout. Earlier versions
of this module assigned each node's vertical tier purely from its
DEVICE ROLE (firewall > router > switch > AP). That works for a clean
enterprise hierarchy, but breaks down completely the moment multiple
devices share the same role -- e.g. an all-router lab, a flat ISP
backbone, a mesh of switches -- because every node lands in the SAME
role-tier and the algorithm has no signal left except alphabetical
order, producing a straight line that reflects nothing about how the
devices are actually connected.

Fixed by deriving the tier from ACTUAL graph connectivity instead:
  - Each connected component gets a root -- the node with the lowest
    role.layer (firewall/router are conventionally "most core"),
    tie-broken by highest degree (most links) when role doesn't
    differentiate, which is how a real engineer would identify the
    core of an all-router topology too.
  - A breadth-first search from that root assigns every other node a
    tier equal to its real hop-distance, so a star/hub topology fans
    out visibly, a mesh lays out by actual shortest-path structure,
    and a genuine chain still renders as a line -- because at that
    point it IS one, not because of incidental name sorting.
  - WITHIN a tier, each node's preferred horizontal position is the
    average x of the parent(s) it's linked to one tier up, and a
    left-to-right sweep enforces minimum spacing so nothing overlaps.
  - A tier with more nodes than fit in one readable row (default cap:
    14) wraps into multiple sub-rows, so 50 APs become a compact grid
    instead of one extremely wide line.
  - recommended_canvas_size() reports how big a canvas (in inches) is
    needed to fit the computed layout without compressing nodes -- used
    by every exporter so a small lab and a 100-device site each render
    at an appropriate scale instead of one fixed-size box.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from typing import Dict, List, Set, Tuple

from core.topology.topology_models import TopologyGraph, DeviceRole

logger = logging.getLogger("NetBrain.Topology.Layout")


LAYER_HEIGHT = 200       # vertical spacing between tiers
ROW_HEIGHT = 110         # vertical spacing between wrapped sub-rows within ONE tier
NODE_SPACING = 220       # horizontal spacing between adjacent nodes in a row
MAX_NODES_PER_ROW = 14   # wrap threshold -- keeps a single row readable at any scale


def _build_neighbor_map(graph: TopologyGraph) -> Dict[str, Set[str]]:
    neighbors: Dict[str, Set[str]] = {}
    for link in graph.links:
        if link.device_a_ip in graph.nodes and link.device_b_ip in graph.nodes:
            neighbors.setdefault(link.device_a_ip, set()).add(link.device_b_ip)
            neighbors.setdefault(link.device_b_ip, set()).add(link.device_a_ip)
    return neighbors


def _assign_graph_tiers(graph: TopologyGraph, neighbors: Dict[str, Set[str]]) -> Dict[str, int]:
    """
    BFS-based tiering driven by ACTUAL connectivity, not assumed role
    hierarchy. Handles disconnected components (each gets its own root)
    and cycles/redundant links (standard BFS visited-tracking) without
    special-casing. Role is used only to pick which node starts each
    component's BFS -- firewalls/routers are conventionally "most core"
    when multiple candidates are otherwise equal, with node DEGREE as
    the tie-break once role no longer differentiates (e.g. a lab where
    every device is a router) -- the same way an engineer would eyeball
    "which device is the hub here" from the topology itself.
    """
    tier_of: Dict[str, int] = {}
    remaining: Set[str] = set(graph.nodes.keys())

    while remaining:
        root = min(
            remaining,
            key=lambda ip: (graph.nodes[ip].role.layer, -len(neighbors.get(ip, ())))
        )
        tier_of[root] = 0
        remaining.discard(root)
        q = deque([root])
        while q:
            cur = q.popleft()
            for nb in sorted(neighbors.get(cur, ())):
                if nb in remaining:
                    tier_of[nb] = tier_of[cur] + 1
                    remaining.discard(nb)
                    q.append(nb)

    return tier_of


def compute_layout(graph: TopologyGraph) -> None:
    """
    Mutates graph.nodes in place, setting .x and .y on every TopologyNode.
    """
    if not graph.nodes:
        return

    neighbors = _build_neighbor_map(graph)
    tier_of = _assign_graph_tiers(graph, neighbors)

    layers: Dict[int, List[str]] = {}
    for ip in graph.nodes:
        layers.setdefault(tier_of[ip], []).append(ip)

    positions: Dict[str, float] = {}
    node_layer_row: Dict[str, Tuple[int, int]] = {}

    for layer_idx in sorted(layers.keys()):
        ips_in_layer = layers[layer_idx]

        if not positions:
            # Top tier(s) -- no parent context yet, stable alphabetical order.
            ips_in_layer.sort(key=lambda ip: graph.nodes[ip].label())
        else:
            def preferred_x(ip: str) -> float:
                parent_xs = [positions[n] for n in neighbors.get(ip, ()) if n in positions]
                return sum(parent_xs) / len(parent_xs) if parent_xs else 0.0
            ips_in_layer.sort(key=preferred_x)

        # Wrap into multiple rows if this tier has too many nodes for one
        # readable row, preserving the parent-clustered order so adjacent
        # items in the same row are still related devices.
        n = len(ips_in_layer)
        num_rows = max(1, math.ceil(n / MAX_NODES_PER_ROW))
        per_row = math.ceil(n / num_rows)

        for row_idx in range(num_rows):
            row_ips = ips_in_layer[row_idx * per_row: (row_idx + 1) * per_row]
            if not row_ips:
                continue

            if positions:
                anchors = [
                    sum(positions[n] for n in neighbors.get(ip, ()) if n in positions)
                    / max(1, len([n for n in neighbors.get(ip, ()) if n in positions]))
                    for ip in row_ips if any(n in positions for n in neighbors.get(ip, ()))
                ]
                row_center = sum(anchors) / len(anchors) if anchors else 0.0
            else:
                row_center = 0.0

            row_n = len(row_ips)
            total_width = (row_n - 1) * NODE_SPACING
            start_x = row_center - total_width / 2

            for i, ip in enumerate(row_ips):
                x = start_x + i * NODE_SPACING
                positions[ip] = x
                node_layer_row[ip] = (layer_idx, row_idx)

    for ip, node in graph.nodes.items():
        layer_idx, row_idx = node_layer_row[ip]
        node.x = positions[ip]
        node.y = layer_idx * LAYER_HEIGHT + row_idx * ROW_HEIGHT


def recommended_canvas_size(
    graph: TopologyGraph,
    max_dimension_in: float = 50.0,
) -> Tuple[float, float]:
    """
    Returns (width_in, height_in) sized to fit the computed layout
    without compressing nodes, used by every exporter (PPTX/PDF/VDX)
    and the interactive view so a 4-device lab and a 100-device site
    each render at an appropriate scale instead of a fixed 13x7.5 box.

    Capped at max_dimension_in (default 50") to stay safely under
    PowerPoint's hard 56" slide-dimension limit, which all three
    exporters share so the diagram looks identical across formats.
    """
    if not graph.nodes:
        return 13.0, 7.5

    xs = [n.x for n in graph.nodes.values()]
    ys = [n.y for n in graph.nodes.values()]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)

    units_to_inches = 2.0 / NODE_SPACING

    width_in = max(13.0, span_x * units_to_inches + 3.0)
    height_in = max(7.5, span_y * units_to_inches + 3.5)

    width_in = min(width_in, max_dimension_in)
    height_in = min(height_in, max_dimension_in)
    return width_in, height_in
