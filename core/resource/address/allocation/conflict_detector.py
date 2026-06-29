"""
NRIE · Allocation · Conflict Detector
=====================================
Detects address conflicts (overlap / duplicate) using the standard library
ipaddress module. Pure functions; no allocation decisions, no deployment.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class Conflict:
    kind: str          # overlap | duplicate
    candidate: str
    existing: str


def _net(cidr: str):
    return ipaddress.ip_network(str(cidr), strict=False)


def detect(candidate_cidr: str, existing_cidrs: Iterable[str]) -> List[Conflict]:
    cand = _net(candidate_cidr)
    out: List[Conflict] = []
    for ex in existing_cidrs:
        try:
            exn = _net(ex)
        except ValueError:
            continue
        if cand == exn:
            out.append(Conflict("duplicate", str(cand), str(exn)))
        elif cand.overlaps(exn):
            out.append(Conflict("overlap", str(cand), str(exn)))
    return out


def has_conflict(candidate_cidr: str, existing_cidrs: Iterable[str]) -> bool:
    return len(detect(candidate_cidr, existing_cidrs)) > 0
