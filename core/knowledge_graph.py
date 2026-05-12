from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


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
