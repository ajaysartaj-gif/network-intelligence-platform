"""
NRIE · Infrastructure · Persistence
===================================
Backing stores for the four memory layers. These REUSE the platform Memory
Platform base (core.intelligence.memory.store.MemoryStore) — dual SQLite/Postgres,
consolidation and decay come for free. No business logic; just typed tables +
JSON payloads keyed by entity id.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from core.intelligence.memory.store import MemoryStore


class _JsonStore(MemoryStore):
    """Common helpers: persist a payload under a key, read rows back."""
    semantic = False

    def put(self, key: str, summary: str, payload: Dict[str, Any], **fields) -> str:
        return self.learn(key, summary, extra={"payload": payload}, **fields)

    def get_payload(self, key: str) -> Dict[str, Any]:
        row = self._by_key(key)
        return self._payload(row) if row else {}

    def rows(self) -> List[Dict[str, Any]]:
        return self._be.query(f"SELECT * FROM {self.table}")

    def where(self, **equals: Any) -> List[Dict[str, Any]]:
        if not equals:
            return self.rows()
        clause = " AND ".join(f"{k}=?" for k in equals)
        return self._be.query(
            f"SELECT * FROM {self.table} WHERE {clause}", tuple(equals.values()))

    @staticmethod
    def _payload(row: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return json.loads(row.get("extra") or "{}").get("payload", {})
        except Exception:
            return {}

    def payloads(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self._payload(r) for r in rows]


class EnterpriseStore(_JsonStore):
    table = "nrie_enterprise"
    columns = (("level", "TEXT"), ("parent", "TEXT"))


class ResourceStore(_JsonStore):
    table = "nrie_resource"
    columns = (("rtype", "TEXT"), ("hierarchy_ref", "TEXT"))


class BusinessContextStore(_JsonStore):
    table = "nrie_business_context"
    columns = (("attached_to", "TEXT"),)


class KnowledgeStore(_JsonStore):
    table = "nrie_org_knowledge"
    columns = (("kind", "TEXT"),)
