"""
core/knowledge/compiler/validation.py
========================================
Validation Engine — checks compiled NormalizedObjects and GraphRelationships
before they're published into core.knowledge_graph.KnowledgeGraph.

Deliberately narrow scope (see docs/nkc_architecture_blueprint.md Part 6):
staleness and document-level duplicate detection are ALREADY handled by
core.knowledge.enterprise.knowledge_layer.EnterpriseKnowledgeLayer at the
document/chunk level. This module only covers what's genuinely new at the
OBJECT level: missing required fields, object-level duplicates/conflicts,
and broken graph references — the last one exists specifically so
KnowledgeGraph.add_relationship's ValueError (raised when a source/target
node doesn't exist) never fires from bad compiler output; it's caught here
first and reported as a normal Issue instead of an exception.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, TYPE_CHECKING

from core.knowledge_graph import GraphRelationship
from core.vendor.models import NormalizedObject

if TYPE_CHECKING:
    from core.knowledge_graph import KnowledgeGraph

# Minimal required-field map per object type. Additive — a type with no
# entry here simply isn't checked, rather than defaulting to "invalid".
REQUIRED_FIELDS: Dict[str, List[str]] = {
    "interface": ["name"],
    "protocol": ["protocol"],
    "vrf": ["name"],
    "vlan": ["id"],
    "acl": ["acl_name"],
    "qos": ["name"],
}


@dataclass
class Issue:
    severity: str          # "error" | "warning" | "info"
    code: str              # short machine-readable reason
    message: str
    object_id: str = ""
    context: Dict[str, Any] = field(default_factory=dict)


def validate_objects(objects: List[NormalizedObject]) -> List[Issue]:
    issues: List[Issue] = []
    seen_hash: Dict[str, str] = {}   # object id -> content hash (_hash attribute)

    for obj in objects:
        required = REQUIRED_FIELDS.get(obj.type, [])
        for field_name in required:
            if not obj.get(field_name):
                issues.append(Issue(
                    severity="error", code="missing_field",
                    message=f"{obj.type} object is missing required field '{field_name}'",
                    object_id=obj.id))

        this_hash = obj.get("_hash", "")
        if obj.id in seen_hash:
            if seen_hash[obj.id] == this_hash:
                issues.append(Issue(
                    severity="info", code="duplicate",
                    message=f"Object '{obj.id}' compiled more than once with identical content",
                    object_id=obj.id))
            else:
                issues.append(Issue(
                    severity="error", code="conflict",
                    message=f"Object '{obj.id}' compiled twice with DIFFERING attributes",
                    object_id=obj.id))
        else:
            seen_hash[obj.id] = this_hash

    return issues


def validate_relationships(
    objects: List[NormalizedObject],
    relationships: List[GraphRelationship],
) -> List[Issue]:
    issues: List[Issue] = []
    known_ids: Set[str] = {o.id for o in objects}
    for rel in relationships:
        if rel.source not in known_ids:
            issues.append(Issue(
                severity="error", code="broken_reference",
                message=f"Relationship '{rel.relationship_type}' has an unknown source '{rel.source}'",
                object_id=rel.source))
        if rel.target not in known_ids:
            issues.append(Issue(
                severity="error", code="broken_reference",
                message=f"Relationship '{rel.relationship_type}' has an unknown target '{rel.target}'",
                object_id=rel.target))
    return issues


# ── graph-level validation (Knowledge Graph Compiler stage) ──────────────
# Each check is its own function, composed by validate_graph() — same
# "one rule, one function" shape as the extractor/relationship-rule
# registries in semantic_analyzer.py / relationships.py.

def _detect_orphan_nodes(graph: "KnowledgeGraph") -> List[Issue]:
    """A node with no incoming or outgoing edge. Not necessarily wrong — a
    standalone fact (e.g. a VLAN definition never referenced by any
    interface in what was compiled so far) is legitimate — so this is
    'info', not an error."""
    if len(graph.nodes) <= 1:
        return []
    has_edge: Set[str] = set()
    for rel in graph.relationships:
        has_edge.add(rel.source)
        has_edge.add(rel.target)
    return [
        Issue(severity="info", code="orphan_node",
              message=f"Node '{node_id}' ({node.label}) has no relationships",
              object_id=node_id)
        for node_id, node in graph.nodes.items() if node_id not in has_edge
    ]


def _detect_cycles(graph: "KnowledgeGraph") -> List[Issue]:
    """DFS with a recursion stack over graph.adjacency. A cycle is often a
    legitimate signal (e.g. a mutual HSRP/VRRP pairing), not automatically
    invalid — reported as a warning, not an error."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node_id: WHITE for node_id in graph.nodes}
    issues: List[Issue] = []
    seen_cycles: Set[frozenset] = set()

    def dfs(node_id: str, path: List[str]) -> None:
        color[node_id] = GRAY
        path.append(node_id)
        for neighbor, _rel in graph.adjacency.get(node_id, []):
            if color.get(neighbor) == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                key = frozenset(cycle)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    issues.append(Issue(
                        severity="warning", code="cycle",
                        message=f"Dependency cycle detected: {' -> '.join(cycle)}",
                        object_id=node_id, context={"cycle": cycle}))
            elif color.get(neighbor) == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node_id] = BLACK

    for node_id in graph.nodes:
        if color[node_id] == WHITE:
            dfs(node_id, [])
    return issues


def _detect_duplicate_relationships(graph: "KnowledgeGraph") -> List[Issue]:
    """Defense-in-depth audit check: after KnowledgeGraph.add_relationship's
    idempotency fix, this should never actually trigger for graphs built
    via add_relationship — it exists for graphs assembled by direct list
    manipulation (bypassing the API) or built before the fix."""
    seen: Dict[tuple, int] = {}
    for rel in graph.relationships:
        key = (rel.source, rel.target, rel.relationship_type)
        seen[key] = seen.get(key, 0) + 1
    return [
        Issue(severity="error", code="duplicate_relationship",
              message=f"Relationship {key[0]} -{key[1]}-> {key[2]} appears {count} times",
              object_id=key[0], context={"count": count})
        for key, count in seen.items() if count > 1
    ]


def _detect_broken_references_in_graph(graph: "KnowledgeGraph") -> List[Issue]:
    """Post-hoc audit over the actual graph (defense-in-depth beyond
    validate_relationships' pre-publish check) — catches edges added via
    direct list manipulation rather than through add_relationship."""
    return [
        Issue(severity="error", code="broken_reference",
              message=f"Relationship references unknown node '{end}'", object_id=end)
        for rel in graph.relationships
        for end in (rel.source, rel.target) if end not in graph.nodes
    ]


def validate_graph(graph: "KnowledgeGraph") -> List[Issue]:
    """Graph-level validation: orphan nodes, dependency cycles, duplicate
    relationships, and broken references — composing the four checks
    above."""
    return (
        _detect_orphan_nodes(graph)
        + _detect_cycles(graph)
        + _detect_duplicate_relationships(graph)
        + _detect_broken_references_in_graph(graph)
    )
