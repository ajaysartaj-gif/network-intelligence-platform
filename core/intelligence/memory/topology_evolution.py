"""
core/intelligence/memory/topology_evolution.py
===============================================
Topology Evolution Memory — the network's history, not just its present.

The live topology engine answers "what is connected now". An experienced
engineer also carries "what changed, and when": this link appeared last week,
that router used to be the hub, this neighbour vanished yesterday — and reaches
for that history first when something breaks, because the thing that changed is
usually the thing that broke. This memory snapshots topology over time and
computes diffs between snapshots, so root-cause analysis can correlate an
incident with a recent structural change, and Prediction can flag churn.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


def _snap_signature(nodes: List[str], links: List[Any]) -> str:
    norm_nodes = sorted(str(n).lower() for n in nodes)
    norm_links = sorted("|".join(sorted(map(str, l))) if isinstance(l, (list, tuple))
                        else str(l).lower() for l in links)
    raw = json.dumps([norm_nodes, norm_links])
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class TopologyEvolutionMemory(MemoryStore):
    table = "mem_topology_evo"
    semantic = False
    columns = (
        ("site", "TEXT"),
        ("sig", "TEXT"),
        ("nodes", "TEXT"),       # json
        ("links", "TEXT"),       # json
        ("snap_ts", "REAL"),
    )

    def snapshot(self, site: str, nodes: List[str], links: List[Any]) -> Dict[str, Any]:
        site = (site or "default").lower()
        sig = _snap_signature(nodes, links)
        prev = self._latest(site)
        # only persist a new snapshot if structure actually changed.
        if prev and prev.get("sig") == sig:
            self.reinforce(self._row_key(site, sig), by=1.0)
            return {"changed": False, "site": site, "sig": sig, "diff": {}}
        diff = self._diff(prev, nodes, links)
        key = self._row_key(site, sig + str(int(time.time())))
        self.learn(key, f"Topology snapshot {site} ({len(nodes)} nodes, {len(links)} links)",
                   confidence=0.9, site=site, sig=sig,
                   nodes=json.dumps([str(n) for n in nodes]),
                   links=json.dumps(links), snap_ts=time.time(),
                   extra={"diff": diff})
        return {"changed": True, "site": site, "sig": sig, "diff": diff}

    def _row_key(self, site: str, sig: str) -> str:
        return hashlib.sha1(f"{site}:{sig}".encode()).hexdigest()[:16]

    def _latest(self, site: str) -> Optional[Dict[str, Any]]:
        rows = self.recent(limit=1, site=site)
        return rows[0] if rows else None

    @staticmethod
    def _diff(prev: Optional[Dict[str, Any]], nodes, links) -> Dict[str, Any]:
        if not prev:
            return {"added_nodes": [str(n) for n in nodes], "removed_nodes": [],
                    "added_links": [str(l) for l in links], "removed_links": []}
        pn = set(json.loads(prev.get("nodes") or "[]"))
        pl = set(json.dumps(l, sort_keys=True) for l in json.loads(prev.get("links") or "[]"))
        cn = set(str(n) for n in nodes)
        cl = set(json.dumps(l, sort_keys=True) for l in links)
        return {"added_nodes": sorted(cn - pn), "removed_nodes": sorted(pn - cn),
                "added_links": sorted(cl - pl), "removed_links": sorted(pl - cl)}

    def recent_changes(self, site: str = "", since_s: float = 7 * 24 * 3600
                       ) -> List[Dict[str, Any]]:
        cutoff = time.time() - since_s
        rows = self.recent(limit=50, site=(site or None) and site.lower())
        out = []
        for r in rows:
            if float(r.get("snap_ts") or 0) >= cutoff:
                d = (r.get("extra") or {}).get("diff") or {}
                if any(d.get(k) for k in ("added_nodes", "removed_nodes",
                                          "added_links", "removed_links")):
                    out.append({"site": r.get("site"), "ts": r.get("snap_ts"),
                                "diff": d})
        return out
