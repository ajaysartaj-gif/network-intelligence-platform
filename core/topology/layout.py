"""
core/topology/layout.py
========================
Computes (x, y) coordinates for every node in a TopologyGraph so it can
be drawn — by the interactive Plotly view, and reused as-is for the
PPTX/PDF/Visio exporters (one layout, every output format stays in sync).

Strategy: hierarchical-by-role layout with parent-anchored ordering and
row-wrapping, so it scales from a 2-device lab to a 100+ device site
(e.g. 2 core switches -> 20 distribution switches -> 50 APs) without
nodes overlapping or the canvas becoming an unreadably long single row.

  - Firewalls at the top (layer 0), routers next, switches next,
    access points/phones at the bottom -- same role-based tiers as before.
  - WITHIN a layer, each node's preferred horizontal position is the
    average x of the parent(s) it's linked to in the layer above --
    so a distribution switch's APs visually cluster under that switch
    instead of being scattered in arbitrary order. A left-to-right
    sweep then enforces minimum spacing so nothing overlaps.
  - If a layer has more nodes than fit in one readable row (default
    cap: 14), it wraps into multiple sub-rows within that layer's
    vertical band -- same idea as wrapping text, applied to a tier of
    same-role devices, so 50 APs become a compact grid instead of one
    10,000-unit-wide line.
  - recommended_canvas_size() reports back how big a canvas (in inches)
    is needed to fit the computed layout without compressing nodes --
    used by every exporter so a small lab and a 100-device site each
    get an appropriately sized diagram, not a fixed one-size box.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, List, Tuple

from core.topology.topology_models import TopologyGraph, DeviceRole

logger = logging.getLogger("NetBrain.Topology.Layout")


LAYER_HEIGHT = 200       # vertical spacing between role tiers (router/switch/AP)
ROW_HEIGHT = 110         # vertical spacing between wrapped sub-rows within ONE tier
NODE_SPACING = 220       # horizontal spacing between adjacent nodes in a row
MAX_NODES_PER_ROW = 14   # wrap threshold -- keeps a single row readable at any scale


def compute_layout(graph: TopologyGraph) -> None:
    """
    Mutates graph.nodes in place, setting .x and .y on every TopologyNode.
    """
    if not graph.nodes:
        return

    # Group nodes by role layer (0=firewall ... bottom=AP/phone)
    layers: Dict[int, List[str]] = {}
    for ip, node in graph.nodes.items():
        layers.setdefault(node.role.layer, []).append(ip)

    # Adjacency map for parent-lookup (undirected -- a node's "parent" is
    # whichever neighbor already has a position, found while we process
    # layers top-to-bottom).
    neighbors: Dict[str, List[str]] = {}
    for link in graph.links:
        if link.device_a_ip in graph.nodes and link.device_b_ip in graph.nodes:
            neighbors.setdefault(link.device_a_ip, []).append(link.device_b_ip)
            neighbors.setdefault(link.device_b_ip, []).append(link.device_a_ip)

    positions: Dict[str, float] = {}     # ip -> x (filled in as we go, top-down)
    node_layer_row: Dict[str, Tuple[int, int]] = {}  # ip -> (layer_idx, row_idx)

    for layer_idx in sorted(layers.keys()):
        ips_in_layer = layers[layer_idx]

        if not positions:
            # Top tier -- no parent context yet, just use a stable order.
            ips_in_layer.sort(key=lambda ip: graph.nodes[ip].label())
        else:
            def preferred_x(ip: str) -> float:
                parent_xs = [positions[n] for n in neighbors.get(ip, []) if n in positions]
                return sum(parent_xs) / len(parent_xs) if parent_xs else 0.0
            ips_in_layer.sort(key=preferred_x)

        # Wrap into multiple rows if this tier has too many nodes for one
        # readable row (e.g. 50 APs), preserving the parent-clustered order
        # so adjacent items in the same row are still related devices.
        n = len(ips_in_layer)
        num_rows = max(1, math.ceil(n / MAX_NODES_PER_ROW))
        per_row = math.ceil(n / num_rows)

        for row_idx in range(num_rows):
            row_ips = ips_in_layer[row_idx * per_row: (row_idx + 1) * per_row]
            if not row_ips:
                continue

            # Anchor the row's center on the average preferred x of its
            # members (when available) so wrapped rows still drift toward
            # their actual parents left-to-right, rather than every row
            # re-centering at 0 and losing that alignment.
            if positions:
                anchors = [
                    sum(positions[n] for n in neighbors.get(ip, []) if n in positions)
                    / max(1, len([n for n in neighbors.get(ip, []) if n in positions]))
                    for ip in row_ips if any(n in positions for n in neighbors.get(ip, []))
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

    # Layout units -> inches: NODE_SPACING units should map to roughly
    # 2 inches of real spacing (node box width + a visible gap).
    units_to_inches = 2.0 / NODE_SPACING

    width_in = max(13.0, span_x * units_to_inches + 3.0)    # +margins
    height_in = max(7.5, span_y * units_to_inches + 3.5)    # +margins/title

    width_in = min(width_in, max_dimension_in)
    height_in = min(height_in, max_dimension_in)
    return width_in, height_in
