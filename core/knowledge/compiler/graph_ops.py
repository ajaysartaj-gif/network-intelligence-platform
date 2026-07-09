"""
core/knowledge/compiler/graph_ops.py
=======================================
Graph API surface — pure functions over the EXISTING
core.knowledge_graph.KnowledgeGraph. No new graph class is introduced.

export_graph()/import_graph() are JSON-serializable snapshots of the
in-memory graph — enough for "support snapshots" without adopting a graph
database (real persistence is roadmap-gated on actual scale need, per
docs/nkc_architecture_blueprint.md Part 4.4/13).
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from core.knowledge.compiler.identity import merge_attributes
from core.knowledge_graph import GraphRelationship, KnowledgeGraph


def export_graph(graph: KnowledgeGraph) -> Dict[str, Any]:
    """JSON-serializable snapshot of a KnowledgeGraph."""
    return {
        "nodes": [
            {"node_id": n.node_id, "label": n.label, "attributes": n.attributes}
            for n in graph.nodes.values()
        ],
        "relationships": [
            {"source": r.source, "target": r.target, "relationship_type": r.relationship_type,
             "weight": r.weight, "metadata": r.metadata}
            for r in graph.relationships
        ],
    }


def import_graph(data: Dict[str, Any]) -> KnowledgeGraph:
    """Rebuilds a KnowledgeGraph from an export_graph()-shaped dict, via the
    existing add_node/add_relationship (so idempotency/validation on those
    methods applies here too, not a separate deserialization path)."""
    graph = KnowledgeGraph()
    for n in data.get("nodes", []):
        graph.add_node(n["node_id"], n["label"], n.get("attributes"))
    for r in data.get("relationships", []):
        graph.add_relationship(r["source"], r["target"], r["relationship_type"],
                               r.get("weight", 1.0), r.get("metadata"))
    return graph


def optimize_graph(graph: KnowledgeGraph) -> Dict[str, int]:
    """
    De-duplicates graph.relationships by exact (source, target,
    relationship_type) and rebuilds adjacency. A cleanup pass for graphs
    built before KnowledgeGraph.add_relationship became idempotent, or
    assembled by direct list manipulation (bypassing add_relationship)
    rather than through the API.
    """
    seen: Dict[Tuple[str, str, str], GraphRelationship] = {}
    removed = 0
    deduped: List[GraphRelationship] = []
    for rel in graph.relationships:
        key = (rel.source, rel.target, rel.relationship_type)
        if key in seen:
            removed += 1
            continue
        seen[key] = rel
        deduped.append(rel)

    graph.relationships = deduped
    graph.adjacency = {node_id: [] for node_id in graph.nodes}
    for rel in deduped:
        graph.adjacency.setdefault(rel.source, []).append((rel.target, rel))

    return {"relationships_removed": removed, "relationships_remaining": len(deduped)}


def diff_graph(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """Compares two export_graph()-shaped snapshots. Returns added/removed
    node ids, node ids whose attributes changed, and added/removed
    relationship triples — the basis for entity-level incremental
    compilation reporting."""
    before_nodes = {n["node_id"]: n for n in before.get("nodes", [])}
    after_nodes = {n["node_id"]: n for n in after.get("nodes", [])}

    added_nodes = [nid for nid in after_nodes if nid not in before_nodes]
    removed_nodes = [nid for nid in before_nodes if nid not in after_nodes]
    changed_nodes = [
        nid for nid in after_nodes
        if nid in before_nodes and after_nodes[nid]["attributes"] != before_nodes[nid]["attributes"]
    ]

    def _rel_key(r: Dict[str, Any]) -> Tuple[str, str, str]:
        return (r["source"], r["target"], r["relationship_type"])

    before_rels = {_rel_key(r) for r in before.get("relationships", [])}
    after_rels = {_rel_key(r) for r in after.get("relationships", [])}

    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "changed_nodes": changed_nodes,
        "added_relationships": [list(k) for k in (after_rels - before_rels)],
        "removed_relationships": [list(k) for k in (before_rels - after_rels)],
    }


def merge_into_graph(graph: KnowledgeGraph, objects: List[Any]) -> Tuple[List[Any], List[Any]]:
    """
    Publishes objects into `graph`. If an object's id already exists as a
    node (from a PRIOR compile against this same graph), its attributes are
    merged via identity.merge_attributes rather than blindly overwritten —
    this is what makes recompiling a slightly-changed source additive
    rather than destructive. Returns (published_objects, merge_issues);
    the latter uses the same Issue shape as validation.py (imported lazily
    to avoid a circular import).
    """
    from core.knowledge.compiler.validation import Issue

    published = []
    issues = []
    for obj in objects:
        existing = graph.nodes.get(obj.id)
        if existing is not None:
            merged_attrs, conflicts = merge_attributes(existing.attributes, obj.attributes)
            merged_attrs["_merge_count"] = int(existing.attributes.get("_merge_count", 1)) + 1
            graph.add_node(obj.id, obj.type, merged_attrs)
            for key in conflicts:
                issues.append(Issue(
                    severity="warning", code="merged_conflict",
                    message=f"Object '{obj.id}' has a differing value for '{key}' vs. "
                            f"the already-published node; both preserved in _conflicting_values",
                    object_id=obj.id))
        else:
            graph.add_node(obj.id, obj.type, obj.attributes)
        published.append(obj)
    return published, issues


def merge_two_graphs(a: KnowledgeGraph, b: KnowledgeGraph) -> KnowledgeGraph:
    """Unions two KnowledgeGraph instances into a new graph: nodes merged
    via identity.merge_attributes on id collision, relationships deduped by
    add_relationship's own idempotency. The 'Knowledge Merging' entry point
    for combining separately-compiled sources (e.g. an RFC-derived graph and
    a config-derived graph)."""
    merged = KnowledgeGraph()
    for source_graph in (a, b):
        for node in source_graph.nodes.values():
            if node.node_id in merged.nodes:
                combined_attrs, _ = merge_attributes(merged.nodes[node.node_id].attributes, node.attributes)
                merged.add_node(node.node_id, node.label, combined_attrs)
            else:
                merged.add_node(node.node_id, node.label, dict(node.attributes))
        for rel in source_graph.relationships:
            merged.add_relationship(rel.source, rel.target, rel.relationship_type,
                                    rel.weight, dict(rel.metadata))
    return merged
