"""
core/topology/export/vdx_exporter.py
=====================================
Exports a TopologyGraph as a Visio-compatible .vdx file.

Format note: this generates the legacy VDX (flat single-file XML)
format rather than the modern .vsdx (zipped OOXML) format. Modern
Visio (2013/2016/2019/365) still opens .vdx files directly via
File -> Open -- it's long-standing documented backward compatibility,
not a hack. The reason for choosing VDX over hand-rolling a .vsdx:
.vsdx is a multi-part zip archive with several interdependent XML
relationship files, and there is no actively-maintained pure-Python
library that can CREATE one from scratch (the `vsdx` PyPI package
can only edit an existing .vsdx template file). VDX is a single,
much simpler XML schema that can be generated reliably.

Shapes (router/switch/AP/firewall boxes) and links (connector lines)
are both real Visio shapes -- fully selectable, movable, and editable
once opened, not a flattened image.

Page size is computed per-topology via recommended_canvas_size() --
a small lab diagram gets a normal 13x7.5in page, a 70+ device site
gets a proportionally larger page (capped at 50in), kept consistent
with the PPTX/PDF exporters.
"""
from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
from typing import Optional

from core.topology.topology_models import TopologyGraph, DeviceRole
from core.topology.export.coords import compute_canvas_positions
from core.topology.layout import recommended_canvas_size
from core.topology.interface_naming import abbreviate_interface

logger = logging.getLogger("NetBrain.Topology.Export.VDX")

NODE_W_IN = 1.7
NODE_H_IN = 0.65

VDX_NS = "http://schemas.microsoft.com/visio/2003/core"


def _hex_to_rgb_fn(hex_str: str) -> str:
    h = hex_str.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"RGB({r},{g},{b})"


def export_topology_to_vdx(graph: TopologyGraph) -> Optional[bytes]:
    """Build a .vdx file in memory and return its bytes."""
    if not graph.nodes:
        return None

    page_w_in, page_h_in = recommended_canvas_size(graph)

    positions = compute_canvas_positions(
        graph,
        canvas_width_in=page_w_in,
        canvas_height_in=page_h_in - 0.9,
        margin_in=0.9,
    )

    def flip_y(top_left_y: float) -> float:
        """VDX page origin is bottom-left, y increases upward -- flip from our top-left convention."""
        return page_h_in - 0.9 - top_left_y

    shape_id = 1
    xml_parts = []

    # -- Link shapes first (drawn behind nodes visually, doesn't matter in VDX z-order much) --
    for link in graph.links:
        if link.device_a_ip not in positions or link.device_b_ip not in positions:
            continue
        ax, ay = positions[link.device_a_ip]
        bx, by = positions[link.device_b_ip]
        ax_c = ax + NODE_W_IN / 2
        ay_c = flip_y(ay + NODE_H_IN / 2)
        bx_c = bx + NODE_W_IN / 2
        by_c = flip_y(by + NODE_H_IN / 2)

        pin_x = (ax_c + bx_c) / 2
        pin_y = (ay_c + by_c) / 2
        width = max(abs(bx_c - ax_c), 0.01)
        height = max(abs(by_c - ay_c), 0.01)
        # Local geometry: start/end relative to box bottom-left (0,0)..(width,height)
        local_start_x = 0 if ax_c <= bx_c else width
        local_start_y = 0 if ay_c <= by_c else height
        local_end_x = width if ax_c <= bx_c else 0
        local_end_y = height if ay_c <= by_c else 0

        xml_parts.append(f"""
        <Shape ID="{shape_id}" Type="Shape">
          <XForm>
            <PinX>{pin_x:.4f}</PinX>
            <PinY>{pin_y:.4f}</PinY>
            <Width>{width:.4f}</Width>
            <Height>{height:.4f}</Height>
          </XForm>
          <Line>
            <LineColor>{_hex_to_rgb_fn("#64748b")}</LineColor>
            <LineWeight>0.015</LineWeight>
          </Line>
          <Geom IX="0">
            <NoFill>1</NoFill>
            <NoLine>0</NoLine>
            <MoveTo IX="1"><X>{local_start_x:.4f}</X><Y>{local_start_y:.4f}</Y></MoveTo>
            <LineTo IX="2"><X>{local_end_x:.4f}</X><Y>{local_end_y:.4f}</Y></LineTo>
          </Geom>
        </Shape>""")
        shape_id += 1

        # Port-label text shape near the link midpoint
        label_text = f"{abbreviate_interface(link.device_a_port)} - {abbreviate_interface(link.device_b_port)}".replace("&", "and")
        xml_parts.append(f"""
        <Shape ID="{shape_id}" Type="Shape">
          <XForm>
            <PinX>{pin_x:.4f}</PinX>
            <PinY>{pin_y + 0.12:.4f}</PinY>
            <Width>1.4</Width>
            <Height>0.2</Height>
          </XForm>
          <Line><LineWeight>0</LineWeight><LinePattern>0</LinePattern></Line>
          <Fill><FillPattern>0</FillPattern></Fill>
          <Char IX="0"><Size>0.09</Size><Color>RGB(71,85,105)</Color></Char>
          <Para IX="0"><HorzAlign>1</HorzAlign></Para>
          <Text>{_xml_escape(label_text)}</Text>
        </Shape>""")
        shape_id += 1

    # -- Node shapes --
    for ip, node in graph.nodes.items():
        if ip not in positions:
            continue
        px, py = positions[ip]
        pin_x = px + NODE_W_IN / 2
        pin_y = flip_y(py + NODE_H_IN / 2)
        ip_display = ip if not ip.startswith("unknown:") else "(no IP)"
        label = f"{node.label()}\n{ip_display}"

        xml_parts.append(f"""
        <Shape ID="{shape_id}" Type="Shape">
          <XForm>
            <PinX>{pin_x:.4f}</PinX>
            <PinY>{pin_y:.4f}</PinY>
            <Width>{NODE_W_IN}</Width>
            <Height>{NODE_H_IN}</Height>
          </XForm>
          <Fill>
            <FillForegnd>{_hex_to_rgb_fn(node.role.color)}</FillForegnd>
            <FillPattern>1</FillPattern>
          </Fill>
          <Line>
            <LineColor>RGB(255,255,255)</LineColor>
            <LineWeight>0.01</LineWeight>
          </Line>
          <Geom IX="0">
            <NoFill>0</NoFill>
            <NoLine>0</NoLine>
            <MoveTo IX="1"><X>0</X><Y>0</Y></MoveTo>
            <LineTo IX="2"><X>{NODE_W_IN}</X><Y>0</Y></LineTo>
            <LineTo IX="3"><X>{NODE_W_IN}</X><Y>{NODE_H_IN}</Y></LineTo>
            <LineTo IX="4"><X>0</X><Y>{NODE_H_IN}</Y></LineTo>
            <LineTo IX="5"><X>0</X><Y>0</Y></LineTo>
          </Geom>
          <Char IX="0"><Size>0.12</Size><Color>RGB(255,255,255)</Color><Style>17</Style></Char>
          <Para IX="0"><HorzAlign>1</HorzAlign></Para>
          <Text>{_xml_escape(label)}</Text>
        </Shape>""")
        shape_id += 1

    # -- Legend entries (small colored squares + text, bottom-left of page) --
    legend_x = 0.4
    legend_y = 0.35
    for role in (DeviceRole.ROUTER, DeviceRole.SWITCH, DeviceRole.ACCESS_POINT, DeviceRole.FIREWALL):
        xml_parts.append(f"""
        <Shape ID="{shape_id}" Type="Shape">
          <XForm><PinX>{legend_x:.4f}</PinX><PinY>{legend_y:.4f}</PinY><Width>0.16</Width><Height>0.16</Height></XForm>
          <Fill><FillForegnd>{_hex_to_rgb_fn(role.color)}</FillForegnd><FillPattern>1</FillPattern></Fill>
          <Line><LineWeight>0</LineWeight><LinePattern>0</LinePattern></Line>
          <Geom IX="0">
            <NoFill>0</NoFill><NoLine>1</NoLine>
            <MoveTo IX="1"><X>0</X><Y>0</Y></MoveTo>
            <LineTo IX="2"><X>0.16</X><Y>0</Y></LineTo>
            <LineTo IX="3"><X>0.16</X><Y>0.16</Y></LineTo>
            <LineTo IX="4"><X>0</X><Y>0.16</Y></LineTo>
            <LineTo IX="5"><X>0</X><Y>0</Y></LineTo>
          </Geom>
        </Shape>""")
        shape_id += 1
        xml_parts.append(f"""
        <Shape ID="{shape_id}" Type="Shape">
          <XForm><PinX>{legend_x + 0.55:.4f}</PinX><PinY>{legend_y:.4f}</PinY><Width>1.0</Width><Height>0.2</Height></XForm>
          <Line><LineWeight>0</LineWeight><LinePattern>0</LinePattern></Line>
          <Fill><FillPattern>0</FillPattern></Fill>
          <Char IX="0"><Size>0.1</Size><Color>RGB(30,41,59)</Color></Char>
          <Para IX="0"><HorzAlign>0</HorzAlign></Para>
          <Text>{role.value.replace("_", " ").title()}</Text>
        </Shape>""")
        shape_id += 1
        legend_x += 1.8

    shapes_xml = "\n".join(xml_parts)

    title = _xml_escape(f"Network Topology - {graph.site_name} ({graph.city}, {graph.country})")

    full_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<VisioDocument xmlns="{VDX_NS}" xml:space="preserve">
  <DocumentSettings TopLevel="1">
    <GlueSettings>9</GlueSettings>
    <SnapSettings>295</SnapSettings>
  </DocumentSettings>
  <Pages>
    <Page ID="0" NameU="Page-1" Name="Page-1">
      <PageSheet>
        <PageProps>
          <PageWidth>{page_w_in}</PageWidth>
          <PageHeight>{page_h_in}</PageHeight>
        </PageProps>
      </PageSheet>
      <Shapes>
        <Shape ID="0" Type="Shape">
          <XForm><PinX>{page_w_in/2:.4f}</PinX><PinY>{page_h_in - 0.3:.4f}</PinY><Width>{page_w_in - 0.8}</Width><Height>0.4</Height></XForm>
          <Line><LineWeight>0</LineWeight><LinePattern>0</LinePattern></Line>
          <Fill><FillPattern>0</FillPattern></Fill>
          <Char IX="0"><Size>0.22</Size><Color>RGB(30,41,59)</Color><Style>17</Style></Char>
          <Para IX="0"><HorzAlign>0</HorzAlign></Para>
          <Text>{title}</Text>
        </Shape>
{shapes_xml}
      </Shapes>
    </Page>
  </Pages>
</VisioDocument>"""

    # Self-validate as well-formed XML before returning -- catch any
    # generation bugs here rather than handing the operator a broken file.
    try:
        ET.fromstring(full_xml)
    except ET.ParseError as exc:
        logger.error(f"Generated VDX XML is not well-formed: {exc}")
        return None

    return full_xml.encode("utf-8")


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
    )
