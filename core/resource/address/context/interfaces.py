"""
NRIE · Context · Interfaces
===========================
Abstractions for context construction. Consumers depend on these, not on the
concrete builder. No allocation/planning surface is exposed here.
"""
from __future__ import annotations

from typing import List, Optional, Protocol, runtime_checkable

from .models import (
    BusinessContextModel, EnterpriseContext, OrganizationalContext,
    ResourceContext, ResourceContextBundle,
)


@runtime_checkable
class ContextBuilder(Protocol):
    def build_enterprise_context(self, node: object,
                                 ancestors: Optional[List[object]] = None) -> EnterpriseContext: ...
    def build_resource_context(self, resource: object,
                               pool: Optional[object] = None) -> ResourceContext: ...
    def build_business_context(self, business_context: object) -> BusinessContextModel: ...
    def build_organizational_context(self, records: List[object],
                                     kinds: Optional[List[str]] = None) -> OrganizationalContext: ...
    def merge(self, *, domain: str, resource: ResourceContext,
              enterprise: EnterpriseContext, business: BusinessContextModel,
              organizational: OrganizationalContext) -> ResourceContextBundle: ...
