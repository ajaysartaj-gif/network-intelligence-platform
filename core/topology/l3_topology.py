"""
core/topology/l3_topology.py
==============================
Compares the PHYSICAL topology (CDP/LLDP adjacency, from discovery.py)
against the L3 subnet data collected per device (from l3_discovery.py)
to determine, for each physical link, whether the two ends actually
agree on an IP subnet.

This is the core value of the Logical (L3) view: a cable can be
physically connected and CDP/LLDP-visible while the IP addressing on
either end is broken, unconfigured, or simply on different subnets --
something a purely physical topology view cannot show, per Cisco
Meraki's own documented rationale for shipping a separate L3 topology
view (verified via Meraki's public docs during research for this
feature): a missing L3 connection between two CDP-adjacent nodes is
itself a diagnostic signal, not just a different picture of the same
facts.

Deliberately computed on demand from TopologyGraph rather than stored
on TopologyLink -- this mirrors the same reasoning behind the earlier
topology cache fix (build_topology_for_site recomputes layout fresh on
every cache hit): L3 status is cheap, pure-function-derived from data
already on the graph, so storing it as a static field risks it going
stale if interface_subnets data changes without the link itself being
re-discovered.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from core.topology.discovery import normalize_interface_name
from core.topology.topology_models import TopologyGraph


@dataclass
class L3LinkStatus:
    status: str = "unknown"     # "matched" | "mismatched" | "unknown"
    a_subnet: str = ""          # subnet found on device_a's port, if any
    b_subnet: str = ""          # subnet found on device_b's port, if any


def compute_l3_status(graph: TopologyGraph) -> Dict[int, L3LinkStatus]:
    """
    Returns a dict keyed by the link's position in graph.links (stable
    for the lifetime of one render call, since this is computed fresh
    immediately before use and graph.links isn't mutated in between).
    """
    out: Dict[int, L3LinkStatus] = {}

    for idx, link in enumerate(graph.links):
        node_a = graph.nodes.get(link.device_a_ip)
        node_b = graph.nodes.get(link.device_b_ip)

        a_subnet = ""
        b_subnet = ""
        if node_a is not None:
            a_port = normalize_interface_name(link.device_a_port)
            a_subnet = node_a.interface_subnets.get(a_port, "")
        if node_b is not None:
            b_port = normalize_interface_name(link.device_b_port)
            b_subnet = node_b.interface_subnets.get(b_port, "")

        if not a_subnet or not b_subnet:
            # One or both ends have no L3 data for this port -- could be
            # an unsupported vendor, a port with no IP configured, or L3
            # discovery simply not having run for that device. This is
            # a valid, honest state distinct from "mismatched": we are
            # not claiming a problem exists, only that we can't confirm
            # either way.
            out[idx] = L3LinkStatus(status="unknown", a_subnet=a_subnet, b_subnet=b_subnet)
        elif a_subnet == b_subnet:
            out[idx] = L3LinkStatus(status="matched", a_subnet=a_subnet, b_subnet=b_subnet)
        else:
            out[idx] = L3LinkStatus(status="mismatched", a_subnet=a_subnet, b_subnet=b_subnet)

    return out
