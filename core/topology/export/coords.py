"""
core/topology/export/coords.py
===============================
Shared coordinate transform used by every exporter (PPTX, PDF, Visio).

Converts the graph's internal (x, y) layout units into a normalized
canvas in INCHES with a TOP-LEFT origin (y increases downward — the
same convention python-pptx uses natively). Exporters whose backend
uses a bottom-left origin (reportlab, Visio/VDX) flip y locally when
they actually draw, keeping this shared function backend-agnostic.

Using one shared transform means all three export formats show the
exact same layout — nodes in the same relative position, every time.
"""
from __future__ import annotations

from typing import Dict, Tuple

from core.topology.topology_models import TopologyGraph


def compute_canvas_positions(
    graph: TopologyGraph,
    canvas_width_in: float = 13.0,
    canvas_height_in: float = 7.0,
    margin_in: float = 0.8,
) -> Dict[str, Tuple[float, float]]:
    """
    Return {ip: (x_inches, y_inches)} with top-left origin, fitted into
    a canvas_width_in x canvas_height_in box (minus margins on all sides).
    """
    if not graph.nodes:
        return {}

    xs = [n.x for n in graph.nodes.values()]
    ys = [n.y for n in graph.nodes.values()]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    span_x = (max_x - min_x) or 1.0
    span_y = (max_y - min_y) or 1.0

    usable_w = canvas_width_in - 2 * margin_in
    usable_h = canvas_height_in - 2 * margin_in

    out: Dict[str, Tuple[float, float]] = {}
    for ip, node in graph.nodes.items():
        norm_x = (node.x - min_x) / span_x          # 0..1
        norm_y = (node.y - min_y) / span_y           # 0..1
        px = margin_in + norm_x * usable_w
        py = margin_in + norm_y * usable_h            # top-left origin, y grows downward
        out[ip] = (px, py)
    return out
