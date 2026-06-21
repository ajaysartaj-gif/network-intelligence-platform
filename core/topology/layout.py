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


def _compute_slot_indices(graph: TopologyGraph) -> Dict[Tuple[str, int], Tuple[int, int]]:
    """
    Coordinate-space-independent: for every (device_ip, link_index)
    pair, returns (slot_index, total_links_on_this_device) -- pure
    indexing, no units. Each renderer turns this into an actual offset
    using its own sense of spacing (layout units for the interactive
    view, a fraction of node width for the PPTX/PDF/VDX exporters).
    """
    touches: Dict[str, List[int]] = {}
    for idx, link in enumerate(graph.links):
        if link.device_a_ip in graph.nodes:
            touches.setdefault(link.device_a_ip, []).append(idx)
        if link.device_b_ip in graph.nodes:
            touches.setdefault(link.device_b_ip, []).append(idx)

    slots: Dict[Tuple[str, int], Tuple[int, int]] = {}
    for ip, link_idxs in touches.items():
        n = len(link_idxs)
        for i, idx in enumerate(link_idxs):
            slots[(ip, idx)] = (i, n)
    return slots


def compute_link_anchor_points(
    graph: TopologyGraph,
) -> Dict[int, Tuple[Tuple[float, float], Tuple[float, float]]]:
    """
    Layout-unit version (matches node.x/node.y directly) -- for every
    link, returns ((ax, ay), (bx, by)), the actual anchor point on each
    device accounting for multiple links sharing that device, so a
    hub's per-link port labels don't all collide at the device's exact
    center. Used by the interactive Plotly view. A real device has each
    cable plugged into a distinct physical port, not every link
    converging on one point.
    """
    MAX_SPREAD = 180.0   # total width the slots can fan out across, in layout units
    slots = _compute_slot_indices(graph)

    def _offset(ip: str, idx: int) -> float:
        i, n = slots.get((ip, idx), (0, 1))
        if n <= 1:
            return 0.0
        spacing = min(40.0, MAX_SPREAD / (n - 1))
        return (i - (n - 1) / 2) * spacing

    result: Dict[int, Tuple[Tuple[float, float], Tuple[float, float]]] = {}
    for idx, link in enumerate(graph.links):
        a = graph.nodes.get(link.device_a_ip)
        b = graph.nodes.get(link.device_b_ip)
        if not a or not b:
            continue
        result[idx] = (
            (a.x + _offset(link.device_a_ip, idx), a.y),
            (b.x + _offset(link.device_b_ip, idx), b.y),
        )
    return result


def compute_link_slot_fractions(graph: TopologyGraph) -> Dict[int, Tuple[float, float]]:
    """
    Inch-space-ready version -- for every link, returns
    (a_slot_fraction, b_slot_fraction), each device's own anchor offset
    as a fraction of ITS node-box width (multiply by NODE_W_IN in the
    calling exporter). Same underlying slot assignment as
    compute_link_anchor_points, just expressed relative to node width
    instead of an absolute layout-unit offset, since the PPTX/PDF/VDX
    exporters work in inches after compute_canvas_positions normalizes
    node.x/node.y into a physical page size.
    """
    MAX_SPREAD_FRACTION = 1.6   # total spread, in units of node width
    slots = _compute_slot_indices(graph)

    def _fraction(ip: str, idx: int) -> float:
        i, n = slots.get((ip, idx), (0, 1))
        if n <= 1:
            return 0.0
        step = min(0.35, MAX_SPREAD_FRACTION / (n - 1))
        return (i - (n - 1) / 2) * step

    result: Dict[int, Tuple[float, float]] = {}
    for idx, link in enumerate(graph.links):
        if link.device_a_ip not in graph.nodes or link.device_b_ip not in graph.nodes:
            continue
        result[idx] = (_fraction(link.device_a_ip, idx), _fraction(link.device_b_ip, idx))
    return result


def compute_bend_fractions(graph: TopologyGraph) -> Dict[int, float]:
    """
    For each link, the fraction (0..1) along its vertical span where
    the elbow should bend. Siblings sharing the same "uphill" parent
    (the endpoint closer to tier 0, i.e. smaller y) are staggered
    across a band instead of all bending at the exact midpoint.

    Without this, every link from one parent shares the identical
    midpoint Y (since mid_y depends only on ay/by, which are the same
    for all siblings spanning the same tier gap), collapsing into one
    visually shared horizontal "trunk". A child positioned directly
    below its parent then has NO horizontal segment at all (a pure
    vertical line), making it visually indistinguishable from a line
    that merely crosses that trunk without actually connecting to it
    -- confirmed as a real user-reported clarity issue on a 4-device
    hub topology (R2 hub with a child positioned dead-center below it,
    whose straight-through line read as ambiguous against the other
    two siblings' shared bend row), not just a theoretical concern.

    Only counts DOWNWARD sibling links (to children) when grouping --
    a node's own upward link to ITS parent is excluded, so staggering
    reflects sibling fan-out specifically rather than being thrown off
    by an unrelated uplink sharing the same node.
    """
    BAND_LOW, BAND_HIGH = 0.32, 0.68   # stay clear of either endpoint

    children_of: Dict[str, List[int]] = {}
    for idx, link in enumerate(graph.links):
        a = graph.nodes.get(link.device_a_ip)
        b = graph.nodes.get(link.device_b_ip)
        if not a or not b or a.y == b.y:
            continue   # peer link -- elbow_path draws these straight across, no bend
        parent_ip = link.device_a_ip if a.y < b.y else link.device_b_ip
        children_of.setdefault(parent_ip, []).append(idx)

    fractions: Dict[int, float] = {}
    for parent_ip, idxs in children_of.items():
        n = len(idxs)
        for i, idx in enumerate(idxs):
            fractions[idx] = 0.5 if n <= 1 else BAND_LOW + (i / (n - 1)) * (BAND_HIGH - BAND_LOW)
    return fractions


def elbow_path(
    ax: float, ay: float, bx: float, by: float, bend_fraction: float = 0.5,
) -> List[Tuple[float, float]]:
    """
    Right-angled (orthogonal) connector waypoints from A to B -- the
    standard tree/org-chart routing convention used in professional
    Visio network diagrams (down from A, across, down into B), rather
    than a direct diagonal line. Shared by the interactive view and
    all three exporters so the routing looks identical everywhere.

    bend_fraction (0..1) controls where along the vertical span the
    horizontal segment sits -- defaults to the midpoint (0.5) for
    backward compatibility, but callers should pass the staggered
    value from compute_bend_fractions() so sibling links spread across
    a band instead of collapsing onto one shared row (see that
    function's docstring for why this matters).

    Same-tier links (ay == by, e.g. a peer connection between two
    same-rank devices) just draw straight across -- there's no
    meaningful "down/across/down" for a horizontal peer link.
    """
    if ay == by:
        return [(ax, ay), (bx, by)]
    mid_y = ay + (by - ay) * bend_fraction
    return [(ax, ay), (ax, mid_y), (bx, mid_y), (bx, by)]


def endpoint_label_positions(
    ax: float, ay: float, bx: float, by: float,
    offset_fraction: float = 0.25, bend_fraction: float = 0.5,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Returns ((label_a_x, label_a_y), (label_b_x, label_b_y)) -- a point
    near EACH end of the link, positioned along that end's own segment
    of the elbow path. Matches the convention of labeling each side's
    own interface right where its cable leaves that device, rather
    than one combined label floating at the link's midpoint.

    bend_fraction must match whatever was passed to elbow_path() for
    this same link, or the label position won't align with the
    actually-drawn line.
    """
    path = elbow_path(ax, ay, bx, by, bend_fraction=bend_fraction)
    # Point near A: a fraction of the way along the FIRST segment.
    a_seg_x = path[0][0] + (path[1][0] - path[0][0]) * offset_fraction
    a_seg_y = path[0][1] + (path[1][1] - path[0][1]) * offset_fraction
    # Point near B: a fraction of the way along the LAST segment, from B's end.
    b_seg_x = path[-1][0] + (path[-2][0] - path[-1][0]) * offset_fraction
    b_seg_y = path[-1][1] + (path[-2][1] - path[-1][1]) * offset_fraction
    return (a_seg_x, a_seg_y), (b_seg_x, b_seg_y)
