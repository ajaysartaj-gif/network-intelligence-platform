"""
core/topology/plotly_view.py
=============================
Builds an interactive Plotly figure from a TopologyGraph for inline
rendering in Streamlit (st.plotly_chart). Uses the exact same node
(x, y) coordinates computed by layout.py, so the interactive view
matches the PPTX/PDF/Visio exports visually.

Kept separate from app.py so the UI-glue file only calls
`build_topology_figure(graph)` and renders it — no chart-construction
logic lives in app.py itself.
"""
from __future__ import annotations

import logging
from typing import Optional

from core.topology.topology_models import TopologyGraph, DeviceRole
from core.topology.interface_naming import abbreviate_interface
from core.topology.layout import elbow_path, endpoint_label_positions, compute_link_anchor_points

logger = logging.getLogger("NetBrain.Topology.PlotlyView")

try:
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False


def build_topology_figure(graph: TopologyGraph) -> Optional["go.Figure"]:
    """Return a Plotly Figure for the given TopologyGraph, or None if empty/unavailable."""
    if not PLOTLY_OK or not graph.nodes:
        return None

    fig = go.Figure()

    # ── Edge lines (drawn first, behind markers) ──
    # Orthogonal "elbow" routing (down/across/down) and per-endpoint port
    # labels -- matches the standard tree-style Visio network diagram
    # convention (each side's own interface labeled where its cable
    # leaves that device), not a single combined midpoint label.
    # Anchor points are slotted per-device (compute_link_anchor_points)
    # so a hub with several connections doesn't have every link's near-
    # node label collide at the device's exact center coordinate.
    anchors = compute_link_anchor_points(graph)
    edge_x, edge_y = [], []
    edge_annotations = []
    for idx, link in enumerate(graph.links):
        a = graph.nodes.get(link.device_a_ip)
        b = graph.nodes.get(link.device_b_ip)
        if not a or not b or idx not in anchors:
            continue
        (ax, ay), (bx, by) = anchors[idx]
        path = elbow_path(ax, ay, bx, by)
        for px, py in path:
            edge_x.append(px)
            edge_y.append(py)
        edge_x.append(None)
        edge_y.append(None)

        (a_lx, a_ly), (b_lx, b_ly) = endpoint_label_positions(ax, ay, bx, by)
        for (lx, ly), port in (
            ((a_lx, a_ly), link.device_a_port),
            ((b_lx, b_ly), link.device_b_port),
        ):
            edge_annotations.append(dict(
                x=lx, y=ly,
                text=abbreviate_interface(port),
                showarrow=False,
                font=dict(size=9, color="#475569"),
                bgcolor="rgba(255,255,255,0.85)",
                borderpad=1,
            ))

    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(color="#64748b", width=1.5),
        hoverinfo="skip", showlegend=False,
    ))

    # ── Node markers, grouped by role for a clean legend ──
    by_role: dict = {}
    for node in graph.nodes.values():
        by_role.setdefault(node.role, []).append(node)

    for role, nodes in by_role.items():
        xs = [n.x for n in nodes]
        ys = [n.y for n in nodes]
        labels = [n.label() for n in nodes]
        hover = [
            f"{n.label()}<br>{n.ip if not n.ip.startswith('unknown:') else '(no IP)'}"
            f"<br>Role: {n.role.value}<br>Vendor: {n.vendor or 'unknown'}"
            + ("<br>⚠️ discovered only — not in approved inventory" if n.discovered_only else "")
            for n in nodes
        ]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="markers+text",
            text=[f"{role.icon} {l}" for l in labels],
            textposition="bottom center",
            hovertext=hover, hoverinfo="text",
            marker=dict(size=34, color=role.color, line=dict(width=2, color="white")),
            name=role.value.replace("_", " ").title(),
        ))

    # Dynamic height — scales with how many distinct rows the layout
    # actually produced (role tiers + any wrapped sub-rows), so a
    # 4-device lab and a 70-device site each get a sensibly sized chart
    # instead of a fixed 520px box. Plotly's own zoom/pan handles
    # anything beyond what fits on first render.
    num_row_bands = len(set(n.y for n in graph.nodes.values())) or 1
    height = max(420, min(900, 380 + num_row_bands * 85))

    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, autorange="reversed"),   # layer 0 (firewall) at top
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=40, b=20),
        height=height,
        annotations=edge_annotations,
    )
    return fig
