"""
NRIE · Optimization · Fragmentation Detection
=============================================
Detects address-space fragmentation within a pool/space using ipaddress.
Pure analysis — recommendations only, no changes.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import List


@dataclass
class FragmentationReport:
    address_space: str
    allocated_blocks: int = 0
    free_blocks: int = 0
    largest_free_prefix: int = 0      # smallest prefixlen (largest block) free
    fragmentation_pct: float = 0.0
    notes: List[str] = field(default_factory=list)


def analyze(address_space: str, allocated_cidrs: List[str]) -> FragmentationReport:
    space = ipaddress.ip_network(address_space, strict=False)
    alloc = []
    for c in allocated_cidrs:
        try:
            alloc.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    try:
        free = list(space.address_exclude_many(alloc)) if hasattr(space, "address_exclude_many") \
            else _exclude_many(space, alloc)
    except Exception:
        free = _exclude_many(space, alloc)
    largest = min((f.prefixlen for f in free), default=space.prefixlen)
    total = space.num_addresses
    free_addr = sum(f.num_addresses for f in free)
    used = total - free_addr
    frag = round(100.0 * (len(free) - 1) / max(1, len(free)), 2) if free else 0.0
    rep = FragmentationReport(
        address_space=str(space), allocated_blocks=len(alloc), free_blocks=len(free),
        largest_free_prefix=largest, fragmentation_pct=frag)
    if len(free) > max(2, len(alloc)):
        rep.notes.append("High free-block count suggests fragmentation; consider re-packing.")
    return rep


def _exclude_many(space, blocks):
    remaining = [space]
    for b in blocks:
        nxt = []
        for r in remaining:
            if r.overlaps(b) and b.subnet_of(r):
                nxt.extend(r.address_exclude(b))
            else:
                nxt.append(r)
        remaining = nxt
    return remaining
