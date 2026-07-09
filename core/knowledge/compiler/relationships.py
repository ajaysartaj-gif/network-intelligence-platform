"""
core/knowledge/compiler/relationships.py
==========================================
Relationship Compiler — deterministic rules over a list of already-
canonicalized NormalizedObjects, producing core.knowledge_graph
GraphRelationship instances (reusing that exact class — no parallel edge
type is introduced). Each rule is a small, independent, pure function, same
"one rule, one function" shape as the extractor registry in
semantic_analyzer.py.

Rules are deliberately modest: only relationships with a direct, checkable
basis in the objects' own attributes are emitted (e.g. an interface that
literally names a VRF it forwards for). Speculative edges (e.g. "this error
CAUSES that state") are NOT invented here — that kind of correlation is a
reasoning-layer concern (core.intelligence.reasoning), not a deterministic
compiler concern.
"""
from __future__ import annotations

from typing import Callable, List

from core.knowledge_graph import GraphRelationship, RelationType
from core.vendor.models import NormalizedObject

RelationshipRule = Callable[[List[NormalizedObject]], List[GraphRelationship]]


def _by_type(objects: List[NormalizedObject], type_: str) -> List[NormalizedObject]:
    return [o for o in objects if o.type == type_]


def _same_device(a: NormalizedObject, b: NormalizedObject) -> bool:
    return (a.device or "") == (b.device or "")


def rule_interface_belongs_to_vrf(objects: List[NormalizedObject]) -> List[GraphRelationship]:
    out = []
    vrfs = _by_type(objects, "vrf")
    for iface in _by_type(objects, "interface"):
        vrf_name = iface.get("vrf")
        if not vrf_name:
            continue
        for vrf in vrfs:
            if vrf.get("name") == vrf_name and _same_device(iface, vrf):
                out.append(GraphRelationship(iface.id, vrf.id, RelationType.BELONGS_TO.value))
    return out


def rule_interface_uses_acl(objects: List[NormalizedObject]) -> List[GraphRelationship]:
    out = []
    acls = _by_type(objects, "acl")
    for iface in _by_type(objects, "interface"):
        acl_ref = iface.get("acl_ref")
        if not acl_ref:
            continue
        for acl in acls:
            if acl.get("acl_name") == acl_ref and _same_device(iface, acl):
                out.append(GraphRelationship(iface.id, acl.id, RelationType.USES.value))
    return out


def rule_security_rule_implements_acl(objects: List[NormalizedObject]) -> List[GraphRelationship]:
    out = []
    acls = _by_type(objects, "acl")
    for sec in _by_type(objects, "security_rule"):
        acl_ref = sec.get("acl_ref")
        if not acl_ref:
            continue
        for acl in acls:
            if acl.get("acl_name") == acl_ref and _same_device(sec, acl):
                out.append(GraphRelationship(sec.id, acl.id, RelationType.IMPLEMENTS.value))
    return out


def rule_interface_uses_qos_policy(objects: List[NormalizedObject]) -> List[GraphRelationship]:
    out = []
    policies = _by_type(objects, "qos")
    for iface in _by_type(objects, "interface"):
        policy_name = iface.get("qos_policy")
        if not policy_name:
            continue
        for pol in policies:
            if pol.get("name") == policy_name and _same_device(iface, pol):
                out.append(GraphRelationship(iface.id, pol.id, RelationType.USES.value))
    return out


def rule_vlan_contains_interface(objects: List[NormalizedObject]) -> List[GraphRelationship]:
    out = []
    vlans = _by_type(objects, "vlan")
    for iface in _by_type(objects, "interface"):
        vlan_id = iface.get("vlan")
        if vlan_id is None:
            continue
        for vlan in vlans:
            if vlan.get("id") == vlan_id and _same_device(iface, vlan):
                out.append(GraphRelationship(vlan.id, iface.id, RelationType.CONTAINS.value))
    return out


def rule_protocol_contains_neighbor(objects: List[NormalizedObject]) -> List[GraphRelationship]:
    """Every neighbor discovered in the same compile is attributed to every
    protocol stanza compiled alongside it on the same device — a coarse but
    honest link (we don't have per-neighbor protocol tagging from the
    neighbor-row regex alone; refining this is future work, not invented
    here as a false precision)."""
    out = []
    protocols = _by_type(objects, "protocol")
    for nbr in _by_type(objects, "neighbor"):
        for proto in protocols:
            if _same_device(nbr, proto):
                out.append(GraphRelationship(proto.id, nbr.id, RelationType.CONTAINS.value))
    return out


RULES: List[RelationshipRule] = [
    rule_interface_belongs_to_vrf,
    rule_interface_uses_acl,
    rule_security_rule_implements_acl,
    rule_interface_uses_qos_policy,
    rule_vlan_contains_interface,
    rule_protocol_contains_neighbor,
]


def derive_relationships(objects: List[NormalizedObject]) -> List[GraphRelationship]:
    """Run every registered rule. A failing rule is skipped, not fatal —
    same resilience convention as the extractor registry."""
    import logging
    logger = logging.getLogger("NetBrain.Knowledge.Compiler.Relationships")
    out: List[GraphRelationship] = []
    for rule in RULES:
        try:
            out.extend(rule(objects))
        except Exception as exc:
            logger.warning(f"Relationship rule {rule.__name__} failed: {exc}")
    return out
