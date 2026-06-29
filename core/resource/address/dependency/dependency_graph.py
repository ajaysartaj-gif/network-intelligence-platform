"""
NRIE · Dependency · Dependency Graph
====================================
A thin wrapper that REUSES the platform Knowledge Graph (core.knowledge_graph.
KnowledgeGraph) for storage and traversal of NRIE dependency nodes/edges. NRIE
does NOT implement its own graph — it registers resource dependency nodes into
the existing graph and queries it (get_dependencies / trace_impact_chain).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class NRIEDependencyGraph:
    def __init__(self, graph: Optional[Any] = None):
        self._kg = graph or self._new_graph()

    @staticmethod
    def _new_graph():
        try:
            from core.knowledge_graph import KnowledgeGraph
            return KnowledgeGraph()
        except Exception:
            return None

    def register_node(self, node_id: str, label: str,
                      attributes: Optional[Dict[str, Any]] = None) -> None:
        if self._kg is None:
            return
        try:
            self._kg.add_node(node_id, label, attributes or {})
        except Exception:
            pass

    def register_edge(self, source: str, target: str, relationship_type: str,
                      metadata: Optional[Dict[str, Any]] = None) -> None:
        if self._kg is None:
            return
        try:
            self._kg.add_relationship(source, target, relationship_type, metadata=metadata or {})
        except Exception:
            pass

    def dependencies_of(self, node_id: str) -> List[str]:
        if self._kg is None:
            return []
        try:
            return list(self._kg.get_dependencies(node_id) or [])
        except Exception:
            return []

    def impact_chain(self, origin: str, depth: int = 3) -> Dict[str, Any]:
        if self._kg is None:
            return {}
        try:
            return dict(self._kg.trace_impact_chain(origin, depth) or {})
        except Exception:
            return {}

    @property
    def graph(self):
        return self._kg
