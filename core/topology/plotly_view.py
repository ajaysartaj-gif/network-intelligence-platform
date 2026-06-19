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
    edge_x, edge_y = [], []
    edge_label_x, edge_label_y, edge_label_text = [], [], []
    for link in graph.links:
        a = graph.nodes.get(link.device_a_ip)
        b = graph.nodes.get(link.device_b_ip)
        if not a or not b:
            continue
        edge_x += [a.x, b.x, None]
        edge_y += [a.y, b.y, None]
        edge_label_x.append((a.x + b.x) / 2)
        edge_label_y.append((a.y + b.y) / 2)
        edge_label_text.append(f"{link.device_a_port} ↔ {link.device_b_port} ({link.protocol})")

    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(color="#64748b", width=1.5),
        hoverinfo="skip", showlegend=False,
    ))

    fig.add_trace(go.Scatter(
        x=edge_label_x, y=edge_label_y, mode="markers",
        marker=dict(size=1, color="rgba(0,0,0,0)"),
        text=edge_label_text, hoverinfo="text", showlegend=False,
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

    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False, autorange="reversed"),   # layer 0 (firewall) at top
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=40, b=20),
        height=520,
    )
    return fig
