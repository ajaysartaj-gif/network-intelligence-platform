"""
NRIE · Optimization · Route Summarization Opportunities
=======================================================
Detects aggregatable subnet groups and proposes supernets. Recommendations only.
Reuses ipaddress.collapse_addresses; no route configuration is generated.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import List


@dataclass
class SummarizationProposal:
    aggregate: str
    members: List[str] = field(default_factory=list)
    routes_saved: int = 0


def propose(cidrs: List[str]) -> List[SummarizationProposal]:
    nets = []
    for c in cidrs:
        try:
            nets.append(ipaddress.ip_network(c, strict=False))
        except ValueError:
            continue
    collapsed = list(ipaddress.collapse_addresses(nets)) if nets else []
    proposals: List[SummarizationProposal] = []
    for agg in collapsed:
        members = [str(n) for n in nets if n.subnet_of(agg)]
        if len(members) > 1:
            proposals.append(SummarizationProposal(
                aggregate=str(agg), members=members, routes_saved=len(members) - 1))
    return proposals
