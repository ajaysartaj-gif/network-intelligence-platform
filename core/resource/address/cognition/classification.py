"""
NRIE · Cognition · Classification
=================================
Deterministic resource classification + criticality/purpose assessment derived
ENTIRELY from the ResourceContextBundle (the single source of context). No
planning, allocation, or AI. Pure functions — independently testable.
"""
from __future__ import annotations

from typing import Dict

from ..context.models import ResourceContextBundle
from ..knowledge.taxonomy import category_of

# purpose → coarse class (reused vocabulary, not networking allocation)
_PURPOSE_CLASS = {
    "user_lan": "access", "voice": "access", "guest": "access", "iot": "access",
    "ot": "secure", "cctv": "secure", "firewall_ha": "secure", "mgmt": "secure",
    "wan_p2p": "transport", "transit": "transport", "loopback": "transport",
}


def classify(bundle: ResourceContextBundle) -> Dict[str, str]:
    r = bundle.resource
    return {
        "resource_type": r.resource_type,
        "category": category_of(r.resource_type),
        "purpose_class": _PURPOSE_CLASS.get(r.purpose, "unclassified"),
        "purpose": r.purpose or "unspecified",
    }


def assess_criticality(bundle: ResourceContextBundle) -> str:
    """Criticality from BUSINESS context in the bundle (not re-derived)."""
    b = bundle.business
    if b.risk_classification in ("high", "severe") or b.criticality in ("high", "critical"):
        return "high"
    if b.criticality == "normal" and not b.services.get("ot"):
        return "normal"
    return b.criticality or "normal"
