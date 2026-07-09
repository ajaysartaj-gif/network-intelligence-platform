"""
core/knowledge/compiler/canonicalizer.py
==========================================
Canonical Object Generator — maps a SemanticFinding onto the EXISTING
canonical object model (core/vendor/models.py::NormalizedObject/ObjectType).

No new object-model class is introduced here. Every reserved provenance
key this module stamps into NormalizedObject.attributes (_confidence,
_source_doc_id, _vendor, _extracted_by, _compiler_version, _hash) is just a
dict entry — NormalizedObject's shape is untouched, so every existing
consumer (TroubleshootingEngine, VendorGateway, live vendor adapters) keeps
working exactly as before; they simply never see these keys because they
only ever look up the attribute names they already know about.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

from core.knowledge.compiler.identity import normalize_interface_name, normalize_protocol_name
from core.knowledge.compiler.semantic_analyzer import SemanticFinding
from core.vendor.models import NormalizedObject, ObjectType

COMPILER_VERSION = "nkc-semantic-compiler/0.1"

# finding.kind -> ObjectType (or a bare string for concepts with no existing
# enum member — NormalizedObject.type is documented as accepting either;
# adding a whole enum member for every fine-grained kind would be premature
# taxonomy-building ahead of real need).
_KIND_TO_TYPE: Dict[str, Any] = {
    "interface": ObjectType.INTERFACE,
    "protocol": ObjectType.PROTOCOL,
    "neighbor": ObjectType.NEIGHBOR,
    "timer": "timer",
    "acl_rule": ObjectType.ACL,
    "acl": ObjectType.ACL,
    "vrf": ObjectType.VRF,
    "vlan": ObjectType.VLAN,
    "qos_class_map": ObjectType.QOS,
    "qos_policy_map": ObjectType.QOS,
    "nat_pool": ObjectType.NAT,
    "nat_rule": ObjectType.NAT,
    "security_rule": ObjectType.SECURITY_RULE,
    "state": "state",
    "error": ObjectType.EVENT,
    "warning": ObjectType.EVENT,
}

# Findings that are evidence ABOUT relationships, not objects in their own
# right — canonicalizer skips them; relationships.py derives edges directly
# from the objects' own attributes (interface.vrf, interface.acl_ref, ...).
_NON_OBJECT_KINDS = {"dependency"}


def _short_hash(*parts: Any) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:12]


def _primary_key(kind: str, attrs: Dict[str, Any]) -> str:
    """Derive a stable identifying key for an object from its attributes.
    Falls back to a short content hash when no natural key exists, so ids
    are always deterministic (same input -> same id) without collisions."""
    if kind == "interface":
        return normalize_interface_name(attrs.get("name", "")) or _short_hash(attrs)
    if kind == "protocol":
        return f"{normalize_protocol_name(attrs.get('protocol',''))}:{attrs.get('process_id','')}"
    if kind == "neighbor":
        return attrs.get("neighbor_ip", "") or _short_hash(attrs)
    if kind == "timer":
        return f"{attrs.get('context','')}:{attrs.get('timer_type','')}"
    if kind in ("acl_rule", "acl"):
        return f"{attrs.get('acl_name','')}:{_short_hash(attrs.get('action',''), attrs.get('rule',''))}"
    if kind == "vrf":
        return attrs.get("name", "") or _short_hash(attrs)
    if kind == "vlan":
        return str(attrs.get("id", "")) or _short_hash(attrs)
    if kind in ("qos_class_map", "qos_policy_map"):
        return attrs.get("name", "") or _short_hash(attrs)
    if kind == "nat_pool":
        return attrs.get("name", "") or _short_hash(attrs)
    if kind == "nat_rule":
        return _short_hash(attrs.get("rule", ""))
    if kind == "security_rule":
        return (attrs.get("interface") or attrs.get("zone_pair") or "") + ":" + _short_hash(attrs)
    if kind == "state":
        return attrs.get("subject", "") or _short_hash(attrs)
    if kind in ("error", "warning"):
        return _short_hash(attrs.get("message", "") or attrs.get("code", ""))
    return _short_hash(kind, attrs)


def finding_to_object(
    finding: SemanticFinding,
    *,
    device: str = "",
    source_doc_id: str = "",
    vendor: str = "",
    extracted_by: str = "deterministic",
    confidence: Optional[float] = None,
) -> Optional[NormalizedObject]:
    """
    Map one SemanticFinding onto a NormalizedObject. Returns None for
    finding kinds that are relationship evidence rather than objects
    (see _NON_OBJECT_KINDS) — callers should filter Nones out, not treat
    them as errors.
    """
    if finding.kind in _NON_OBJECT_KINDS:
        return None

    obj_type = _KIND_TO_TYPE.get(finding.kind, finding.kind)
    type_str = obj_type.value if isinstance(obj_type, ObjectType) else str(obj_type)

    key = _primary_key(finding.kind, finding.attributes)
    obj_id = f"{device or 'unknown'}:{type_str}:{key}"

    if confidence is None:
        # Deterministic extraction is trusted more than an (unimplemented
        # here, reserved for future) LLM fallback path.
        confidence = 0.9 if extracted_by == "deterministic" else 0.5

    attributes: Dict[str, Any] = dict(finding.attributes)
    # Normalize the identity-bearing field itself (not just the id) so two
    # objects that merge because their normalized key collides (Gi0/1 vs
    # GigabitEthernet0/1) also agree on the attribute VALUE — otherwise
    # merge_attributes would see two different "name" values for the same
    # id and flag a false conflict.
    if finding.kind == "interface" and attributes.get("name"):
        attributes["name"] = normalize_interface_name(attributes["name"])
    if finding.kind == "protocol" and attributes.get("protocol"):
        attributes["protocol"] = normalize_protocol_name(attributes["protocol"])
    attributes.update({
        "_confidence": confidence,
        "_source_doc_id": source_doc_id,
        "_vendor": vendor,
        "_extracted_by": extracted_by,
        "_compiler_version": COMPILER_VERSION,
        "_source_line": finding.line,
        "_extractor": finding.extractor,
    })
    attributes["_hash"] = _short_hash(type_str, obj_id, sorted(
        (k, v) for k, v in attributes.items() if not k.startswith("_")
    ))

    return NormalizedObject(type=type_str, id=obj_id, device=device or "", attributes=attributes)
