"""
core/topology/export/pptx_exporter.py
======================================
Exports a TopologyGraph as a fully editable PowerPoint diagram —
every device is a real movable shape, every link a real connector,
not a flattened image. Opens in PowerPoint/Keynote/Google Slides with
all shapes selectable and re-positionable.
"""
from __future__ import annotations

import io
import logging
from typing import Optional

from core.topology.topology_models import TopologyGraph, DeviceRole
from core.topology.export.coords import compute_canvas_positions

logger = logging.getLogger("NetBrain.Topology.Export.PPTX")

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    PPTX_OK = True
except ImportError:
    PPTX_OK = False


SLIDE_W_IN = 13.33
SLIDE_H_IN = 7.5
NODE_W_IN  = 1.7
NODE_H_IN  = 0.65


def _hex_to_rgbcolor(hex_str: str) -> "RGBColor":
    h = hex_str.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def export_topology_to_pptx(graph: TopologyGraph) -> Optional[bytes]:
    """
    Build a .pptx file in memory and return its bytes, or None if the
    python-pptx library isn't available.
    """
    if not PPTX_OK:
        logger.warning("python-pptx not installed — PPTX export unavailable")
        return None
    if not graph.nodes:
        return None

    positions = compute_canvas_positions(
        graph,
        canvas_width_in=SLIDE_W_IN,
        canvas_height_in=SLIDE_H_IN - 0.9,   # leave room for title
        margin_in=0.9,
    )

    prs = Presentation()
    prs.slide_width = Inches(SLIDE_W_IN)
    prs.slide_height = Inches(SLIDE_H_IN)
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank layout

    # ── Title ──
    title_box = slide.shapes.add_textbox(Inches(0.4), Inches(0.15), Inches(SLIDE_W_IN - 0.8), Inches(0.6))
    tf = title_box.text_frame
    tf.text = f"Network Topology — {graph.site_name} ({graph.city}, {graph.country})"
    tf.paragraphs[0].font.size = Pt(22)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = RGBColor(0x1e, 0x29, 0x3b)

    y_offset = 0.9  # push everything below the title

    # ── Links (draw first so they sit behind node shapes) ──
    for link in graph.links:
        if link.device_a_ip not in positions or link.device_b_ip not in positions:
            continue
        ax, ay = positions[link.device_a_ip]
        bx, by = positions[link.device_b_ip]
        ax_center = ax + NODE_W_IN / 2
        bx_center = bx + NODE_W_IN / 2
        ay_center = ay + y_offset + NODE_H_IN / 2
        by_center = by + y_offset + NODE_H_IN / 2

        conn = slide.shapes.add_connector(
            MSO_CONNECTOR.STRAIGHT,
            Inches(ax_center), Inches(ay_center),
            Inches(bx_center), Inches(by_center),
        )
        conn.line.color.rgb = RGBColor(0x64, 0x74, 0x8b)
        conn.line.width = Pt(1.5)

        # Port labels at each end, small text near the node
        mid_x = (ax_center + bx_center) / 2
        mid_y = (ay_center + by_center) / 2
        label_tb = slide.shapes.add_textbox(
            Inches(mid_x - 0.6), Inches(mid_y - 0.15), Inches(1.2), Inches(0.3)
        )
        label_tf = label_tb.text_frame
        label_tf.text = f"{link.device_a_port} ↔ {link.device_b_port}"
        label_tf.paragraphs[0].font.size = Pt(8)
        label_tf.paragraphs[0].font.color.rgb = RGBColor(0x47, 0x55, 0x69)
        label_tf.paragraphs[0].alignment = PP_ALIGN.CENTER

    # ── Nodes ──
    for ip, node in graph.nodes.items():
        if ip not in positions:
            continue
        px, py = positions[ip]
        shp = slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(px), Inches(py + y_offset),
            Inches(NODE_W_IN), Inches(NODE_H_IN),
        )
        shp.fill.solid()
        shp.fill.fore_color.rgb = _hex_to_rgbcolor(node.role.color)
        shp.line.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shp.line.width = Pt(1)

        tf = shp.text_frame
        tf.word_wrap = True
        tf.text = f"{node.role.icon} {node.label()}"
        tf.paragraphs[0].font.size = Pt(11)
        tf.paragraphs[0].font.bold = True
        tf.paragraphs[0].font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER

        p2 = tf.add_paragraph()
        p2.text = ip if not ip.startswith("unknown:") else "(no IP reported)"
        p2.font.size = Pt(8)
        p2.font.color.rgb = RGBColor(0xF0, 0xF0, 0xF0)
        p2.alignment = PP_ALIGN.CENTER

    # ── Legend ──
    legend_y = SLIDE_H_IN - 0.5
    legend_x = 0.4
    for role in (DeviceRole.ROUTER, DeviceRole.SWITCH, DeviceRole.ACCESS_POINT, DeviceRole.FIREWALL):
        dot = slide.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(legend_x), Inches(legend_y), Inches(0.18), Inches(0.18)
        )
        dot.fill.solid()
        dot.fill.fore_color.rgb = _hex_to_rgbcolor(role.color)
        dot.line.fill.background()

        lbl = slide.shapes.add_textbox(Inches(legend_x + 0.22), Inches(legend_y - 0.05), Inches(1.5), Inches(0.3))
        lbl.text_frame.text = role.value.replace("_", " ").title()
        lbl.text_frame.paragraphs[0].font.size = Pt(10)
        legend_x += 1.8

    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
