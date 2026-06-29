"""
NRIE · Knowledge · Memory (descriptor)
======================================
Declares WHAT the address domain remembers and WHICH existing memory store backs
each layer. This is a descriptor that REUSES the platform Memory Platform — it
does not implement a new memory engine.
"""
from __future__ import annotations
from typing import Dict

# logical memory layer -> backing store table (see infrastructure/persistence.py)
MEMORY_LAYERS: Dict[str, str] = {
    "enterprise_memory": "nrie_enterprise",
    "resource_memory": "nrie_resource",
    "business_context_memory": "nrie_business_context",
    "organizational_memory": "nrie_org_knowledge",
}

# what each layer is responsible for remembering (documentation knowledge)
MEMORY_RESPONSIBILITY: Dict[str, str] = {
    "enterprise_memory": "organization → floor hierarchy and ownership",
    "resource_memory": "resource inventory, lifecycle, utilization, status",
    "business_context_memory": "business meaning attached to resources/nodes",
    "organizational_memory": "standards, decisions, lessons, runbooks, policies",
}
