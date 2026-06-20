"""
core/topology/interface_naming.py
==================================
Abbreviates verbose interface names (FastEthernet0/0 -> Fa0/0,
GigabitEthernet1/0/1 -> Gi1/0/1) for compact display on topology
diagrams, where full Cisco IOS-style names eat up canvas space fast.

Mappings verified against Cisco's own documented short names (Cisco
community / Cisco IOS-XR interface help text), not guessed -- this is
the same "Fa/Gi/Te" convention shown by `show interface ?` on real
devices. Anything that doesn't match a known verbose prefix (already-
short names like Juniper's ge-0/0/0, or an unrecognized format) is
returned unchanged rather than guessed at.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# (verbose prefix, abbreviation) -- checked longest-first so e.g.
# "TenGigabitEthernet" doesn't get accidentally caught by a shorter
# unrelated prefix. Core Ethernet-speed family verified via Cisco
# documentation; Serial/Loopback/Vlan/etc. are long-standing standard
# IOS conventions.
_INTERFACE_ABBREVIATIONS: List[Tuple[str, str]] = [
    ("twentyfivegigabitethernet", "Twe"),
    ("twentyfivegige", "Twe"),
    ("hundredgigabitethernet", "Hu"),
    ("hundredgige", "Hu"),
    ("fortygigabitethernet", "Fo"),
    ("fortygige", "Fo"),
    ("tengigabitethernet", "Te"),
    ("tengige", "Te"),
    ("fivegigabitethernet", "Fi"),
    ("twogigabitethernet", "Tw"),
    ("gigabitethernet", "Gi"),
    ("fastethernet", "Fa"),
    ("ethernet", "Et"),
    ("port-channel", "Po"),
    ("portchannel", "Po"),
    ("loopback", "Lo"),
    ("tunnel", "Tu"),
    ("serial", "Se"),
    ("vlan", "Vl"),
    ("management", "Ma"),
]
# Sort longest-prefix-first so e.g. "tengigabitethernet" is tried
# before any shorter prefix that could otherwise match part of it.
_INTERFACE_ABBREVIATIONS.sort(key=lambda pair: -len(pair[0]))


def abbreviate_interface(name: str) -> str:
    """
    Convert a verbose interface name to its standard short form,
    preserving the slot/port numbering exactly. Returns the input
    unchanged if it doesn't match a known verbose prefix (e.g. it's
    already abbreviated, or it's a non-Cisco style like Juniper's
    ge-0/0/0 which is already compact).

    Examples:
        FastEthernet0/0      -> Fa0/0
        GigabitEthernet1/0/1 -> Gi1/0/1
        TenGigabitEthernet2/1 -> Te2/1
        Fa0/0                -> Fa0/0   (already short, unchanged)
        ge-0/0/0              -> ge-0/0/0  (Juniper-style, unchanged)
    """
    if not name:
        return name

    stripped = name.strip()
    lower = stripped.lower()

    for prefix, abbrev in _INTERFACE_ABBREVIATIONS:
        if lower.startswith(prefix):
            rest = stripped[len(prefix):]
            return f"{abbrev}{rest}"

    return stripped
