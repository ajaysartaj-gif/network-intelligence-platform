from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class RelationType(str, Enum):
    """Recommended edge-type vocabulary for GraphRelationship.relationship_type.

    Optional, not enforced: relationship_type stays a plain str field so
    every existing caller (e.g. core/topology/knowledge_graph_bridge.py)
    keeps working unmodified — a str-backed enum member IS a str. New
    producers (core/knowledge/compiler/relationships.py) should use these
    values instead of inventing ad-hoc strings, so the graph accumulates a
    closed, queryable vocabulary over time rather than free text.
    """
    DEPENDS_ON = "depends_on"; USES = "uses"; IMPLEMENTS = "implements"
    CONTAINS = "contains"; CONNECTED_TO = "connected_to"
    NEIGHBOR_OF = "neighbor_of"; ROUTES_THROUGH = "routes_through"
    ADVERTISES = "advertises"; LEARNS_FROM = "learns_from"; CAUSES = "causes"
    AFFECTED_BY = "affected_by"; CONFLICTS_WITH = "conflicts_with"
    OVERRIDES = "overrides"; SUPPORTS = "supports"
    DEPRECATED_BY = "deprecated_by"; INTRODUCED_IN = "introduced_in"
    VALIDATED_BY = "validated_by"; VERIFIED_BY = "verified_by"
    RESOLVED_BY = "resolved_by"; PROTECTS = "protects"
    BELONGS_TO = "belongs_to"; RELATED_TO = "related_to"


@dataclass
class GraphNode:
    node_id: str
    label: str
    attributes: Dict[str, object] = field(default_factory=dict)


@dataclass
class GraphRelationship:
    source: str
    target: str
    relationship_type: str
    weight: float = 1.0
    metadata: Dict[str, object] = field(default_factory=dict)


class KnowledgeGraph:
    """Knowledge graph for network dependency and impact tracing."""

    def __init__(self) -> None:
        self.nodes: Dict[str, GraphNode] = {}
        self.relationships: List[GraphRelationship] = []
        self.adjacency: Dict[str, List[Tuple[str, GraphRelationship]]] = {}

    def add_node(self, node_id: str, label: str, attributes: Optional[Dict[str, object]] = None) -> None:
        self.nodes[node_id] = GraphNode(node_id=node_id, label=label, attributes=attributes or {})
        self.adjacency.setdefault(node_id, [])

    def add_relationship(
        self,
        source: str,
        target: str,
        relationship_type: str,
        weight: float = 1.0,
        metadata: Optional[Dict[str, object]] = None,
    ) -> None:
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("Both source and target nodes must exist before adding a relationship.")

        # Idempotent on the exact (source, target, relationship_type) triple:
        # calling this twice for the same edge (e.g. recompiling an unchanged
        # source, or CDP+LLDP both reporting the same neighbor) updates the
        # existing edge's weight/metadata instead of appending a duplicate.
        # Confirmed safe for the only existing caller
        # (core/topology/knowledge_graph_bridge.py) — its traversal methods
        # don't depend on duplicate-edge counts.
        for existing_target, existing_rel in self.adjacency.get(source, []):
            if existing_target == target and existing_rel.relationship_type == relationship_type:
                existing_rel.weight = weight
                existing_rel.metadata.update(metadata or {})
                return

        relationship = GraphRelationship(
            source=source,
            target=target,
            relationship_type=relationship_type,
            weight=weight,
            metadata=metadata or {},
        )
        self.relationships.append(relationship)
        self.adjacency.setdefault(source, []).append((target, relationship))

    def get_dependencies(self, node_id: str) -> List[str]:
        return [target for target, _ in self.adjacency.get(node_id, [])]

    def find_path(self, source: str, target: str) -> List[str]:
        if source not in self.nodes or target not in self.nodes:
            return []
        queue = deque([[source]])
        visited = {source}
        while queue:
            path = queue.popleft()
            current = path[-1]
            if current == target:
                return path
            for neighbor, _ in self.adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return []

    def trace_impact_chain(self, origin: str, depth: int = 3) -> Dict[str, object]:
        chain: List[str] = []
        queue = deque([(origin, 0)])
        visited = {origin}
        while queue:
            current, level = queue.popleft()
            if level > depth:
                continue
            chain.append(current)
            for neighbor, rel in self.adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, level + 1))
        return {
            "origin": origin,
            "depth": depth,
            "impact_chain": chain,
            "links": [rel.__dict__ for rel in self.relationships if rel.source in chain],
        }

    def dependency_summary(self) -> Dict[str, object]:
        return {
            "node_count": len(self.nodes),
            "relationship_count": len(self.relationships),
            "nodes": {node_id: node.label for node_id, node in self.nodes.items()},
        }
