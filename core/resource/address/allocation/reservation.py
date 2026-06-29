"""
NRIE · Allocation · Reservation
===============================
Soft reservations of address space (intent to set aside). Reuses the domain
Reservation entity and the Pool aggregate; records nothing on devices. No carving
beyond recording the reserved block.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..domain.entities import Reservation
from ..domain.value_objects import Identifier, ResourceStatus


@dataclass
class ReservationBook:
    """In-memory reservation ledger keyed by pool (audit lives in memory layer)."""
    _by_pool: Dict[str, List[Reservation]] = field(default_factory=dict)

    def reserve(self, pool_id: str, *, reserved_for: str, size_hint_hosts: int = 0,
                cidr: str = "") -> Reservation:
        r = Reservation(id=Identifier.new("rsv"), pool_id=Identifier(pool_id),
                        reserved_for=reserved_for, size_hint_hosts=size_hint_hosts,
                        status=ResourceStatus.RESERVED)
        if cidr:
            r.metadata = r.metadata.merged(cidr=cidr)
        self._by_pool.setdefault(pool_id, []).append(r)
        return r

    def reserved_cidrs(self, pool_id: str) -> List[str]:
        return [r.metadata.get("cidr") for r in self._by_pool.get(pool_id, [])
                if r.metadata.get("cidr")]

    def for_pool(self, pool_id: str) -> List[Reservation]:
        return list(self._by_pool.get(pool_id, []))
