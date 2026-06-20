"""
core/topology/export/pdf_exporter.py
=====================================
Exports a TopologyGraph as a vector PDF diagram (reportlab).

Note on "editable": PDF shapes are vector graphics (crisp at any zoom,
text stays selectable/searchable) but PDF does NOT support movable
shape objects the way PPTX/Visio do -- that's an inherent limitation of
the PDF format itself, not of this exporter. For a diagram operators
can rearrange, use the PPTX or Visio export instead.

Page size is computed per-topology via recommended_canvas_size() --
a small lab diagram gets a normal 13x7.5in page, a 70+ device site
gets a proportionally larger page (capped at 50in) so nodes never
overlap at scale, kept consistent with the PPTX/VDX exporters.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

from core.topology.topology_models import TopologyGraph, DeviceRole
from core.topology.export.coords import compute_canvas_positions
from core.topology.layout import recommended_canvas_size

logger = logging.getLogger("NetBrain.Topology.Export.PDF")

try:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.units import inch
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False


NODE_W_IN = 1.7
NODE_H_IN = 0.65


def export_topology_to_pdf(graph: TopologyGraph) -> Optional[bytes]:
    """Build a vector PDF diagram in memory and return its bytes."""
    if not REPORTLAB_OK:
        logger.warning("reportlab not installed -- PDF export unavailable")
        return None
    if not graph.nodes:
        return None

    page_w_in, page_h_in = recommended_canvas_size(graph)

    positions = compute_canvas_positions(
        graph,
        canvas_width_in=page_w_in,
        canvas_height_in=page_h_in - 0.9,
        margin_in=0.9,
    )

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w_in * inch, page_h_in * inch))

    # -- Title --
    c.setFillColor(HexColor("#1e293b"))
    c.setFont("Helvetica-Bold", 18)
    c.drawString(
        0.4 * inch, (page_h_in - 0.5) * inch,
        f"Network Topology — {graph.site_name} ({graph.city}, {graph.country})",
    )

    def to_page_xy(px_in: float, py_in: float) -> tuple:
        """
        Convert our top-left-origin (x,y) inches to reportlab's
        bottom-left-origin coordinate system.
        """
        page_x = px_in
        page_y = page_h_in - 0.9 - py_in   # flip vertically, account for title space
        return page_x, page_y

    # -- Links (drawn first, behind nodes) --
    c.setStrokeColor(HexColor("#64748b"))
    c.setLineWidth(1.5)
    for link in graph.links:
        if link.device_a_ip not in positions or link.device_b_ip not in positions:
            continue
        ax, ay = positions[link.device_a_ip]
        bx, by = positions[link.device_b_ip]
        ax_c, ay_c = to_page_xy(ax + NODE_W_IN / 2, ay + NODE_H_IN / 2)
        bx_c, by_c = to_page_xy(bx + NODE_W_IN / 2, by + NODE_H_IN / 2)
        c.line(ax_c * inch, ay_c * inch, bx_c * inch, by_c * inch)

        mid_x = (ax_c + bx_c) / 2
        mid_y = (ay_c + by_c) / 2
        c.setFillColor(HexColor("#475569"))
        c.setFont("Helvetica", 7)
        c.drawCentredString(
            mid_x * inch, mid_y * inch,
            f"{link.device_a_port} ↔ {link.device_b_port}",
        )

    # -- Nodes --
    for ip, node in graph.nodes.items():
        if ip not in positions:
            continue
        px, py = positions[ip]
        page_x, page_y_top = to_page_xy(px, py)
        # roundRect draws from bottom-left corner of the box upward
        box_bottom_y = page_y_top - NODE_H_IN

        c.setFillColor(HexColor(node.role.color))
        c.roundRect(
            page_x * inch, box_bottom_y * inch,
            NODE_W_IN * inch, NODE_H_IN * inch,
            6, fill=1, stroke=0,
        )

        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(
            (page_x + NODE_W_IN / 2) * inch,
            (box_bottom_y + NODE_H_IN * 0.58) * inch,
            f"{node.role.icon} {node.label()}",
        )
        c.setFont("Helvetica", 8)
        ip_display = ip if not ip.startswith("unknown:") else "(no IP)"
        c.drawCentredString(
            (page_x + NODE_W_IN / 2) * inch,
            (box_bottom_y + NODE_H_IN * 0.22) * inch,
            ip_display,
        )

    # -- Legend --
    legend_y = 0.4
    legend_x = 0.4
    c.setFont("Helvetica", 10)
    for role in (DeviceRole.ROUTER, DeviceRole.SWITCH, DeviceRole.ACCESS_POINT, DeviceRole.FIREWALL):
        c.setFillColor(HexColor(role.color))
        c.circle((legend_x + 0.08) * inch, (legend_y + 0.08) * inch, 0.08 * inch, fill=1, stroke=0)
        c.setFillColor(HexColor("#1e293b"))
        c.drawString((legend_x + 0.25) * inch, legend_y * inch, role.value.replace("_", " ").title())
        legend_x += 1.8

    c.save()
    return buf.getvalue()
