"""
NRIE · Address Domain · Policies
================================

Domain invariants expressed as small, single-purpose policy objects. They raise
on violation and are the ONLY place cross-entity structural rules live. No
allocation/planning logic — these guard the integrity of *knowledge*, not the
assignment of addresses.
"""

from __future__ import annotations

from typing import Optional

from .entities import BusinessContext, EnterpriseEntity, NetworkResource


class PolicyViolation(ValueError):
    """Raised when a domain invariant is violated."""


class ParentMustExistPolicy:
    """A non-root entity must reference a parent that has been registered."""
    def check(self, entity: EnterpriseEntity, parent: Optional[EnterpriseEntity]) -> None:
        if entity.parent_id is None:
            return  # root (organization) is allowed to have no parent
        if parent is None:
            raise PolicyViolation(
                f"parent {entity.parent_id} of '{entity.name}' does not exist")


class HierarchyLevelOrderPolicy:
    """A child's level must rank strictly below its parent's level."""
    def check(self, entity: EnterpriseEntity, parent: Optional[EnterpriseEntity]) -> None:
        if parent is None:
            return
        if entity.level.rank <= parent.level.rank:
            raise PolicyViolation(
                f"'{entity.name}' ({entity.level.value}) cannot sit under "
                f"'{parent.name}' ({parent.level.value})")


class BusinessContextAttachmentPolicy:
    """Business context must declare what it attaches to (resource or node)."""
    def check(self, ctx: BusinessContext,
              resource: Optional[NetworkResource]) -> None:
        if ctx.attached_to is None and resource is None:
            raise PolicyViolation("business context must be attached to a target")
