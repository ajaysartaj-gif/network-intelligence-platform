"""
Regression for the follow-up to the Tavily Search+Extract ingestion pipeline:
the user's explicit direction was "decouple ingestion from live troubleshooting
... prioritize local cache/RAG only. If a knowledge miss occurs, either (a)
perform background ingestion while returning the best available answer, or
(b) make this behavior configurable (online vs. offline mode)."

This implements (a) as the default (lookup()'s `blocking=False`) plus (b) as
an explicit escape hatch (AI_NET_STUDIO_OFFLINE_MODE) for environments that
must never make an outbound call at all. This file locks in: a live
(non-blocking) lookup never waits on tier 3's network round-trip, the
background fetch still persists into the cache for the next lookup, explicit
callers can still opt into the old fully-synchronous behavior, and offline
mode disables tier 3 entirely regardless of blocking.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core.knowledge.orchestrator as orchestrator_module
from core.knowledge.orchestrator import KnowledgeOrchestrator


class _NoCacheHit:
    """Minimal stand-in for KnowledgeCacheDB.get() always missing, so every
    lookup() call in these tests reaches tier 3 deterministically."""
    def get(self, vendor, command, platform):
        return None

    def upsert(self, entry):
        self.last_upserted = entry
        return True


def _bare_orchestrator(monkeypatch):
    """A KnowledgeOrchestrator with RAG/MCP disabled and a cache that
    always misses, so tier 3 is reached predictably without any of this
    session's other knowledge sources getting in the way."""
    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _NoCacheHit()
    monkeypatch.setattr(orchestrator_module, "_offline_mode", lambda: False)
    return orch


def test_default_lookup_never_blocks_on_web_fetch(monkeypatch):
    """The actual fix: a live (default) lookup() call must return WITHOUT
    waiting for tier 3's network round-trip, even if that round-trip would
    take a long time."""
    orch = _bare_orchestrator(monkeypatch)
    release = threading_event = __import__("threading").Event()

    def slow_web_fetch(vendor, command, platform):
        threading_event.wait(timeout=5)  # would block a synchronous caller
        return None

    monkeypatch.setattr(orch, "_web_fetch", slow_web_fetch)

    start = time.monotonic()
    result = orch.lookup("cisco", "show ip ospf neighbor", "ios-xe")
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"lookup() blocked for {elapsed:.2f}s waiting on tier 3"
    assert result.citation.confidence.value == "unverified" or result is not None
    threading_event.set()  # let the background thread finish cleanly


def test_background_ingest_persists_into_cache_for_next_lookup(monkeypatch):
    """Automatic knowledge growth must still happen -- just not on the
    critical path. A successful background fetch must reach cache.upsert()
    once the background thread completes."""
    orch = _bare_orchestrator(monkeypatch)
    import core.knowledge.base as kb

    fake_entry = kb.KnowledgeEntry.unverified("cisco", "show ip ospf neighbor", "test")
    monkeypatch.setattr(orch, "_web_fetch", lambda vendor, command, platform: fake_entry)

    orch.lookup("cisco", "show ip ospf neighbor", "ios-xe")
    # Background work is async -- give the shared pool a moment to finish.
    for _ in range(50):
        if getattr(orch.cache, "last_upserted", None) is not None:
            break
        time.sleep(0.05)
    assert orch.cache.last_upserted is fake_entry


def test_blocking_true_preserves_old_synchronous_behavior(monkeypatch):
    """Explicit ingestion callers (vendor-doc CLI, a scheduled refresh) must
    still be able to get a real, immediate answer by opting in."""
    orch = _bare_orchestrator(monkeypatch)
    import core.knowledge.base as kb

    fake_entry = kb.KnowledgeEntry.unverified("cisco", "show ip ospf neighbor", "test")
    monkeypatch.setattr(orch, "_web_fetch", lambda vendor, command, platform: fake_entry)

    result = orch.lookup("cisco", "show ip ospf neighbor", "ios-xe", blocking=True)
    assert result is fake_entry
    assert orch.cache.last_upserted is fake_entry


def test_offline_mode_disables_tier3_entirely_regardless_of_blocking(monkeypatch):
    """AI_NET_STUDIO_OFFLINE_MODE must block BOTH the background path and
    an explicit blocking=True call -- a genuine "never touch the network"
    guarantee, not just a default that can be bypassed."""
    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _NoCacheHit()
    monkeypatch.setattr(orchestrator_module, "_offline_mode", lambda: True)
    calls = []
    monkeypatch.setattr(orch, "_web_fetch", lambda *a, **k: calls.append(1) or None)
    monkeypatch.setattr(orch, "_kick_off_background_ingest", lambda *a, **k: calls.append("bg"))

    orch.lookup("cisco", "show ip ospf neighbor", "ios-xe", blocking=False)
    orch.lookup("cisco", "show ip ospf neighbor", "ios-xe", blocking=True)
    assert calls == [], f"tier 3 was reached despite offline mode: {calls}"
