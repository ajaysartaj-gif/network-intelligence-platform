"""
core/topology/topology_cache.py
================================
Persists built TopologyGraph objects to disk, keyed by site, so a
rebuilt Streamlit session doesn't need to re-run CDP/LLDP discovery
on every page load. Mirrors the JSON persistence pattern already used
in core/device_discovery.py.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional

from core.topology.topology_models import TopologyGraph

logger = logging.getLogger("NetBrain.Topology.Cache")

_CACHE_FILE = ".netbrain_topology_cache.json"
_DEFAULT_TTL_MINUTES = 60   # consider a cached topology "fresh" for 1 hour
# Bump whenever a change to discovery/reconciliation alters the SHAPE of the
# stored graph (which nodes/links exist), so a graph cached on disk by older
# logic is auto-treated as stale instead of being served silently. Without
# this, a code fix that changes graph structure shows "no improvement" on a
# cache hit because the OLD graph is returned and discovery never re-runs.
# v2: hostname-based node-identity reconciliation (collapses split-identity
# duplicate nodes, e.g. "192.168.96.133" + "R2" -> one node).
# v3: approved-only topology (unapproved CDP/LLDP neighbors no longer added
# as discovered_only nodes) + per-device credentials.
_SCHEMA_VERSION = 3


def _site_key(site_name: str, city: str, country: str, region: str) -> str:
    """Composite key avoids collisions if two cities both have a site named the same."""
    return f"{region}|{country}|{city}|{site_name}"


class TopologyCache:
    def __init__(self, path: str = _CACHE_FILE):
        self._path = path
        self._lock = threading.Lock()
        self._data: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if not os.path.exists(self._path):
            return {}
        try:
            with open(self._path) as f:
                return json.load(f)
        except Exception as exc:
            logger.warning(f"Could not load topology cache: {exc}")
            return {}

    def _save(self) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2, default=str)
        except Exception as exc:
            logger.warning(f"Could not save topology cache: {exc}")

    def get(
        self,
        site_name: str, city: str, country: str, region: str,
    ) -> Optional[TopologyGraph]:
        key = _site_key(site_name, city, country, region)
        with self._lock:
            raw = self._data.get(key)
        if not raw:
            return None
        try:
            return TopologyGraph.from_dict(raw)
        except Exception as exc:
            logger.warning(f"Could not deserialize cached topology for {key}: {exc}")
            return None

    def is_fresh(
        self,
        site_name: str, city: str, country: str, region: str,
        ttl_minutes: int = _DEFAULT_TTL_MINUTES,
    ) -> bool:
        key = _site_key(site_name, city, country, region)
        with self._lock:
            raw = self._data.get(key)
        if not raw:
            return False
        # A graph cached by older discovery logic must NOT be served -- treat
        # it as stale so the next Build runs a fresh poll with current logic.
        if raw.get("_schema_version") != _SCHEMA_VERSION:
            logger.info(
                f"Cached topology for {key} is schema v{raw.get('_schema_version')} "
                f"(current v{_SCHEMA_VERSION}) -- treating as stale, will re-discover."
            )
            return False
        built_at = raw.get("built_at")
        if not built_at:
            return False
        try:
            built = datetime.fromisoformat(built_at)
            return (datetime.utcnow() - built) < timedelta(minutes=ttl_minutes)
        except Exception:
            return False

    def set(self, graph: TopologyGraph) -> None:
        key = _site_key(graph.site_name, graph.city, graph.country, graph.region)
        with self._lock:
            self._data[key] = {**graph.to_dict(), "_schema_version": _SCHEMA_VERSION}
            self._save()

    def clear(
        self,
        site_name: str, city: str, country: str, region: str,
    ) -> None:
        key = _site_key(site_name, city, country, region)
        with self._lock:
            self._data.pop(key, None)
            self._save()

    def list_cached_sites(self) -> Dict[str, dict]:
        """Return {key: {site_name, city, country, region, built_at, node_count}}."""
        with self._lock:
            out = {}
            for key, raw in self._data.items():
                out[key] = {
                    "site_name": raw.get("site_name", ""),
                    "city": raw.get("city", ""),
                    "country": raw.get("country", ""),
                    "region": raw.get("region", ""),
                    "built_at": raw.get("built_at", ""),
                    "node_count": len(raw.get("nodes", {})),
                    "link_count": len(raw.get("links", [])),
                }
            return out


# ── Singleton accessor ────────────────────────────────────────────────────────

_cache_instance: Optional[TopologyCache] = None
_cache_lock = threading.Lock()


def get_topology_cache() -> TopologyCache:
    global _cache_instance
    with _cache_lock:
        if _cache_instance is None:
            _cache_instance = TopologyCache()
        return _cache_instance
