"""
NRIE · Address Domain · Specifications
======================================

Composable read predicates (Specification pattern). They describe *which*
knowledge to select; they never mutate or allocate. Used by query handlers and
repositories to filter without leaking business rules into either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Specification:
    predicate: Callable[[Any], bool]

    def is_satisfied_by(self, candidate: Any) -> bool:
        return bool(self.predicate(candidate))

    def __and__(self, other: "Specification") -> "Specification":
        return Specification(lambda c: self.is_satisfied_by(c) and other.is_satisfied_by(c))

    def __or__(self, other: "Specification") -> "Specification":
        return Specification(lambda c: self.is_satisfied_by(c) or other.is_satisfied_by(c))

    def __invert__(self) -> "Specification":
        return Specification(lambda c: not self.is_satisfied_by(c))


# ── ready-made specifications (read-only selection helpers) ──────────────────
def by_level(level: str) -> Specification:
    return Specification(lambda e: getattr(getattr(e, "level", None), "value", None) == level)


def children_of(parent_id: str) -> Specification:
    return Specification(
        lambda e: getattr(e, "parent_id", None) is not None
        and e.parent_id.value == parent_id)


def by_resource_type(rtype: str) -> Specification:
    return Specification(
        lambda r: getattr(getattr(r, "resource_type", None), "value", None) == rtype)


def by_purpose(purpose: str) -> Specification:
    return Specification(lambda r: getattr(r, "purpose", "") == purpose)


def by_kind(kind: str) -> Specification:
    return Specification(lambda k: getattr(k, "kind", "") == kind)
