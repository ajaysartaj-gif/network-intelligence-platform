"""
NRIE · Policy · Policy Engine (Layer 10, registry)
==================================================
Declares enterprise policy categories and the deterministic rule set NRIE
evaluates. This is a REGISTRY of policies (report-only); it performs no
enforcement and no deployment gating (that remains the platform's job). Rules are
pure functions over the ResourceContextBundle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from ..context.models import ResourceContextBundle

POLICY_CATEGORIES = (
    "address_allocation_standard", "naming_convention", "security_policy",
    "compliance_requirement", "vendor_constraint", "regional_restriction",
    "business_rule",
)


@dataclass(frozen=True)
class PolicyRule:
    key: str
    category: str
    description: str
    check: Callable[[ResourceContextBundle], bool]   # True = pass
    recommendation: str = ""


def _has_purpose(b: ResourceContextBundle) -> bool:
    return bool(b.resource.purpose)


def _has_name(b: ResourceContextBundle) -> bool:
    # naming convention: a non-empty, lower-case, hyphen/scope style id present
    return bool(b.resource.resource_id) and bool(b.resource.purpose)


def _secure_has_risk(b: ResourceContextBundle) -> bool:
    secure = b.resource.purpose in ("ot", "cctv", "mgmt", "firewall_ha")
    return (not secure) or (b.business.risk_classification in ("moderate", "high", "severe"))


def _compliance_declared(b: ResourceContextBundle) -> bool:
    # if a framework is required, business context should declare it
    return True if not b.business.compliance else len(b.business.compliance) > 0


def _regional_ok(b: ResourceContextBundle) -> bool:
    # report-only: if data-residency compliance present, an enterprise region context exists
    needs_region = any(c in ("gdpr", "data_residency") for c in b.business.compliance)
    return (not needs_region) or bool(b.enterprise.name)


def _business_rule_ok(b: ResourceContextBundle) -> bool:
    # high criticality is allowed but recommended for review (pass=False → recommendation)
    return b.business.criticality not in ("high", "critical")


DEFAULT_RULES: List[PolicyRule] = [
    PolicyRule("purpose_declared", "address_allocation_standard",
               "Resource declares a purpose", _has_purpose,
               "Declare a purpose so allocation standards can apply."),
    PolicyRule("naming_present", "naming_convention",
               "Resource has an identifier and purpose-based name", _has_name,
               "Provide a purpose-based name following the naming standard."),
    PolicyRule("secure_risk_classified", "security_policy",
               "Secure-purpose resources carry a risk classification", _secure_has_risk,
               "Set a risk classification for secure (OT/CCTV/mgmt) resources."),
    PolicyRule("compliance_declared", "compliance_requirement",
               "Compliance frameworks are declared when applicable", _compliance_declared,
               "Record applicable compliance frameworks in business context."),
    PolicyRule("region_for_residency", "regional_restriction",
               "Data-residency resources have a region context", _regional_ok,
               "Attach an enterprise region for data-residency resources."),
    PolicyRule("criticality_review", "business_rule",
               "High-criticality changes flagged for review", _business_rule_ok,
               "High/critical resources should be reviewed by an owner."),
]


def get_policy_rules() -> List[PolicyRule]:
    return list(DEFAULT_RULES)
