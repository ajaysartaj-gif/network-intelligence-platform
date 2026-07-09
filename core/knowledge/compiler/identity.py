"""
core/knowledge/compiler/identity.py
======================================
Identity Resolution Engine — prevents duplicate identities and merges
equivalent objects, deterministically.

Scope is deliberately narrow: interface-abbreviation expansion (Gi0/1 ==
GigabitEthernet0/1) is a well-known, unambiguous Cisco IOS convention, safe
to normalize. Cross-VENDOR interface equivalence (Cisco Gi0/1 vs Juniper
ge-0/0/1) is explicitly NOT attempted here — there is no syntactic mapping
between different vendors' physical numbering schemes, and asserting a
false equivalence would be a correctness bug, not a feature. Where two
vendors' devices really are the same physical link, that's a topology-
discovery fact (core.topology.l3_topology), not a lexical alias.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from core.vendor.models import NormalizedObject

_RESERVED_PREFIX = "_"

# Cisco IOS short-form -> canonical long-form interface prefixes, keyed by
# lowercase alias, valued with the CORRECTLY-CASED canonical spelling (not
# derived via a generic capitalize-first-letter — "GigabitEthernet" has an
# internal capital that a naive .capitalize() would lose).
_INTERFACE_ALIASES = {
    "gi": "GigabitEthernet", "gigabitethernet": "GigabitEthernet",
    "te": "TenGigabitEthernet", "tengigabitethernet": "TenGigabitEthernet",
    "fa": "FastEthernet", "fastethernet": "FastEthernet",
    "et": "Ethernet", "ethernet": "Ethernet",
    "lo": "Loopback", "loopback": "Loopback",
    "po": "Port-channel", "port-channel": "Port-channel",
    "tu": "Tunnel", "tunnel": "Tunnel",
    "se": "Serial", "serial": "Serial",
    "vl": "Vlan", "vlan": "Vlan",
    "mgmt": "Management", "management": "Management",
}

_PROTOCOL_ALIASES = {
    "ospfv2": "ospf", "ospfv3": "ospf", "ospf": "ospf",
    "is-is": "isis", "isis": "isis",
    "bgp": "bgp", "eigrp": "eigrp", "rip": "rip",
}


def normalize_interface_name(name: str) -> str:
    """Expand a Cisco IOS interface abbreviation to canonical long form.
    Passthrough (unchanged) for anything that doesn't match the known
    alphabetic-prefix + numeric-suffix shape — this never guesses."""
    if not name:
        return name
    i = 0
    while i < len(name) and name[i].isalpha():
        i += 1
    prefix, rest = name[:i].lower(), name[i:]
    canonical = _INTERFACE_ALIASES.get(prefix)
    if canonical is None:
        return name
    return canonical + rest


def normalize_protocol_name(name: str) -> str:
    """Canonical lowercase protocol spelling (ospfv2 -> ospf, is-is -> isis)."""
    if not name:
        return name
    return _PROTOCOL_ALIASES.get(name.lower(), name.lower())


def _short_hash(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def merge_attributes(old: Dict[str, Any], new: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """
    Merge two attribute dicts describing the SAME canonical object.
    Non-reserved keys present in both with equal values merge silently;
    present in only one, they carry over; present in both with DIFFERING
    values is a real conflict — recorded under merged["_conflicting_values"]
    (old value kept as the primary, both preserved) rather than silently
    picking one. Reserved (`_`-prefixed) provenance keys are the caller's
    responsibility (lineage bookkeeping), not merged generically here.
    """
    merged = dict(old)
    conflicts: List[str] = []
    for key, value in new.items():
        if key.startswith(_RESERVED_PREFIX):
            continue
        if key in merged and merged[key] != value:
            conflicts.append(key)
            cv = merged.setdefault("_conflicting_values", {})
            cv.setdefault(key, [merged[key]])
            if value not in cv[key]:
                cv[key].append(value)
        else:
            merged[key] = value
    return merged, conflicts


def merge_duplicate_objects(objects: List[NormalizedObject]):
    """
    Groups objects by id (after identity-normalized canonicalization has
    already made equivalent entities share an id — see canonicalizer.py's
    _primary_key) and merges each group into one object. Returns
    (merged_objects, issues) where issues is a list of
    core.knowledge.compiler.validation.Issue for any REAL attribute
    conflicts found (differing values for the same key) — imported lazily
    to avoid a circular import (validation.py doesn't depend on identity.py).
    """
    from core.knowledge.compiler.validation import Issue

    groups: Dict[str, List[NormalizedObject]] = {}
    order: List[str] = []
    for obj in objects:
        if obj.id not in groups:
            groups[obj.id] = []
            order.append(obj.id)
        groups[obj.id].append(obj)

    merged_objects: List[NormalizedObject] = []
    issues: List["Issue"] = []

    for obj_id in order:
        group = groups[obj_id]
        if len(group) == 1:
            merged_objects.append(group[0])
            continue

        base = group[0]
        merged_attrs = dict(base.attributes)
        merged_from = [merged_attrs.get("_source_doc_id", "")]
        max_confidence = float(merged_attrs.get("_confidence", 0.0) or 0.0)
        all_conflicts: List[str] = []

        for other in group[1:]:
            merged_attrs, conflicts = merge_attributes(merged_attrs, other.attributes)
            all_conflicts.extend(conflicts)
            doc_id = other.attributes.get("_source_doc_id", "")
            if doc_id and doc_id not in merged_from:
                merged_from.append(doc_id)
            max_confidence = max(max_confidence, float(other.attributes.get("_confidence", 0.0) or 0.0))

        merged_attrs["_merged_from"] = [d for d in merged_from if d]
        merged_attrs["_merge_count"] = len(group)
        merged_attrs["_confidence"] = max_confidence
        merged_attrs["_hash"] = _short_hash(base.type, obj_id, sorted(
            (k, str(v)) for k, v in merged_attrs.items() if not k.startswith("_")
        ))

        merged_objects.append(NormalizedObject(
            type=base.type, id=base.id, device=base.device, attributes=merged_attrs))

        for key in set(all_conflicts):
            issues.append(Issue(
                severity="warning", code="merged_conflict",
                message=f"Object '{obj_id}' has differing values for '{key}' across "
                        f"{len(group)} occurrences; kept as _conflicting_values",
                object_id=obj_id))

    return merged_objects, issues
