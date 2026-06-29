"""
NRIE · Lifecycle · State Machine
================================
The resource lifecycle and its allowed transitions. Pure/declarative — no audit,
persistence, or side effects (those live in the manager).
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List


class LifecycleState(str, Enum):
    PLANNED = "planned"
    RESERVED = "reserved"
    ALLOCATED = "allocated"
    CONFIGURED = "configured"
    VERIFIED = "verified"
    PRODUCTION = "production"
    EXPANDING = "expanding"
    RETIRING = "retiring"
    ARCHIVED = "archived"


# forward flow + permitted branches (expand from production, retire from most live states)
ALLOWED: Dict[LifecycleState, List[LifecycleState]] = {
    LifecycleState.PLANNED: [LifecycleState.RESERVED, LifecycleState.RETIRING],
    LifecycleState.RESERVED: [LifecycleState.ALLOCATED, LifecycleState.RETIRING],
    LifecycleState.ALLOCATED: [LifecycleState.CONFIGURED, LifecycleState.RETIRING],
    LifecycleState.CONFIGURED: [LifecycleState.VERIFIED, LifecycleState.RETIRING],
    LifecycleState.VERIFIED: [LifecycleState.PRODUCTION, LifecycleState.RETIRING],
    LifecycleState.PRODUCTION: [LifecycleState.EXPANDING, LifecycleState.RETIRING],
    LifecycleState.EXPANDING: [LifecycleState.CONFIGURED, LifecycleState.PRODUCTION,
                               LifecycleState.RETIRING],
    LifecycleState.RETIRING: [LifecycleState.ARCHIVED],
    LifecycleState.ARCHIVED: [],
}


def can_transition(src: LifecycleState, dst: LifecycleState) -> bool:
    return dst in ALLOWED.get(src, [])
