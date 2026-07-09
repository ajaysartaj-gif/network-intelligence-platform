"""
core/knowledge/compiler/fact_conflicts.py
============================================
Conflict Detection + Resolution, for two related-but-distinct cases that
share one ConflictRecord shape (one conflict model, not two):

  1. Fact-level conflicts: two documents asserting different values for
     the same (subject, predicate) — e.g. one vendor doc says the OSPF
     default hello interval is 10s, another says 5s.
  2. Cross-device object conflicts: two devices' ALREADY-COMPILED objects
     (from core/knowledge/compiler/'s Semantic Compiler, Phase 1/2) for
     "the same" named entity (e.g. VRF CUSTOMER_A) disagree on an
     attribute (e.g. route-target) — reuses the EXISTING KnowledgeGraph
     Phase 2 already builds; no new graph or comparison engine.

Conflicts are NEVER auto-resolved by overwriting — every competing item is
retained in ConflictRecord.items; only a *preferred_index* (highest
confidence) is suggested, and callers decide whether to act on it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from core.knowledge.compiler.facts import Fact
from core.knowledge.enterprise.knowledge_layer import SOURCE_RANK

if TYPE_CHECKING:
    from core.knowledge_graph import KnowledgeGraph

_DEFAULT_RANK = 0.50

# Object types where a name/id genuinely identifies ONE entity across an
# enterprise (so cross-device comparison is meaningful) — deliberately
# excludes "acl": acl objects are per-RULE, so grouping by acl_name alone
# would flag every distinct permit/deny line as a false "conflict."
_CROSS_DEVICE_KEY_FIELD: Dict[str, str] = {
    "vrf": "name",
    "vlan": "id",
    "qos": "name",
}


@dataclass
class ConflictRecord:
    subject: str
    predicate: str
    items: List[Any]                  # List[Fact] for kind="fact"; list of dicts for "cross_device_object"
    kind: str = "fact"                 # "fact" | "cross_device_object"
    resolved: bool = False
    preferred_index: Optional[int] = None   # index into items of the highest-confidence item


def _recency_factor(timestamp: float) -> float:
    """Same decay shape as EnterpriseKnowledgeLayer._recency_factor (1.0
    fresh -> ~0.5 over a year, floor 0.4) — kept as a free function here
    since Fact confidence isn't computed through an EnterpriseKnowledgeLayer
    instance."""
    age_days = max(0.0, (time.time() - timestamp) / 86400.0)
    return max(0.4, 1.0 - min(age_days / 365.0, 1.0) * 0.5)


def fact_confidence(fact: Fact, group: List[Fact]) -> float:
    """
    Blends authority (SOURCE_RANK, reused from
    core.knowledge.enterprise.knowledge_layer — the SAME weights that rank
    document chunks), cross-source agreement (fraction of the group that
    asserts the same object value as this fact), recency, and evidence
    count (more independent sources asserting the same thing raises
    confidence, saturating at 5) — same blend STYLE as
    EnterpriseKnowledgeLayer.confidence(), generalized to facts.
    """
    rank = SOURCE_RANK.get(fact.source_type, _DEFAULT_RANK)
    recency = _recency_factor(fact.timestamp)
    agreeing = sum(1 for f in group if f.object.strip().lower() == fact.object.strip().lower())
    agreement = agreeing / len(group) if group else 0.0
    evidence_count_factor = min(1.0, len(group) / 5.0)
    score = 0.35 * rank + 0.25 * agreement + 0.20 * recency + 0.20 * evidence_count_factor
    return round(max(0.0, min(1.0, score)), 4)


def detect_fact_conflicts(facts: List[Fact]) -> List[ConflictRecord]:
    """Groups facts by (subject, predicate); >1 distinct object value in a
    group is a conflict. ALL competing facts are preserved in .items —
    never overwritten."""
    groups: Dict[str, List[Fact]] = {}
    for f in facts:
        groups.setdefault(f.key, []).append(f)

    records: List[ConflictRecord] = []
    for group in groups.values():
        distinct_values = {f.object.strip().lower() for f in group}
        if len(distinct_values) <= 1:
            continue
        scored = sorted(range(len(group)), key=lambda i: fact_confidence(group[i], group), reverse=True)
        records.append(ConflictRecord(
            subject=group[0].subject, predicate=group[0].predicate,
            items=list(group), kind="fact", resolved=False, preferred_index=scored[0]))
    return records


def detect_cross_device_conflicts(graph: "KnowledgeGraph") -> List[ConflictRecord]:
    """
    Groups the graph's ALREADY-COMPILED nodes (from Phase 1/2's
    SemanticCompiler) by (type, identifying key) with the device stripped
    out of the id, and flags when two DIFFERENT devices' objects for the
    same named entity disagree on a non-reserved attribute. Reuses the
    existing KnowledgeGraph; builds no new graph or store.
    """
    groups: Dict[tuple, List[tuple]] = {}
    for node_id, node in graph.nodes.items():
        key_field = _CROSS_DEVICE_KEY_FIELD.get(node.label)
        if not key_field:
            continue
        key_value = node.attributes.get(key_field)
        if key_value is None:
            continue
        parts = node_id.split(":", 2)
        device = parts[0] if len(parts) == 3 else ""
        groups.setdefault((node.label, str(key_value)), []).append((device, node_id, node.attributes))

    records: List[ConflictRecord] = []
    for (label, key_value), items in groups.items():
        devices = {d for d, _, _ in items}
        if len(devices) < 2:
            continue   # not a CROSS-device situation

        reference_attrs = items[0][2]
        conflicting_fields = set()
        for _, _, attrs in items[1:]:
            for k, v in attrs.items():
                if k.startswith("_") or k == _CROSS_DEVICE_KEY_FIELD[label]:
                    continue
                if k in reference_attrs and reference_attrs[k] != v:
                    conflicting_fields.add(k)

        if conflicting_fields:
            records.append(ConflictRecord(
                subject=f"{label}:{key_value}", predicate="cross_device_attribute",
                items=[{"device": d, "node_id": nid, "attributes": attrs} for d, nid, attrs in items],
                kind="cross_device_object", resolved=False, preferred_index=None))
    return records
