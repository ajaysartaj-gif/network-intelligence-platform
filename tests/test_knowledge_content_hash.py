"""
Regression for the final piece of the knowledge-ingestion redesign: every
ingested document should carry full provenance metadata (source URL, vendor,
version/OS, retrieval timestamp, content hash, expiry/TTL, confidence), and
a refresh should compare content hashes and skip re-ingesting an unchanged
document -- avoiding unnecessary cache churn and (via
EnterpriseKnowledgeLayer.ingest's pre-existing dedup) unnecessary re-embedding.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.base import Citation, ConfidenceLevel, KnowledgeEntry
from core.knowledge.cache.cache_db import KnowledgeCacheDB


def _entry(vendor="cisco", command="show ip ospf neighbor", platform="ios-xe",
           description="OSPF neighbor states.", syntax="show ip ospf neighbor", **kw):
    return KnowledgeEntry(
        vendor=vendor, platform=platform, command=command,
        syntax=syntax, description=description,
        citation=Citation(source_url="https://www.cisco.com/real-page.html",
                          vendor=vendor, confidence=ConfidenceLevel.HIGH),
        **kw,
    )


def test_content_hash_is_auto_computed_when_not_supplied():
    e = _entry()
    assert e.content_hash
    assert e.content_hash == e.compute_content_hash()


def test_identical_content_produces_identical_hash():
    a = _entry()
    b = _entry()
    assert a.content_hash == b.content_hash


def test_different_content_produces_different_hash():
    a = _entry(description="OSPF neighbor states.")
    b = _entry(description="A completely different description.")
    assert a.content_hash != b.content_hash


def test_explicit_content_hash_is_preserved_not_recomputed():
    """DB row reconstruction must keep the hash it was actually persisted
    with, not silently recompute a new one."""
    e = KnowledgeEntry(vendor="cisco", command="x", description="y",
                       content_hash="deadbeef")
    assert e.content_hash == "deadbeef"


def test_cache_persists_and_returns_content_hash():
    with tempfile.TemporaryDirectory() as d:
        db = KnowledgeCacheDB(db_path=os.path.join(d, "knowledge.db"))
        entry = _entry()
        assert db.upsert(entry)
        got = db.get("cisco", "show ip ospf neighbor", "ios-xe")
        assert got is not None
        assert got.content_hash == entry.content_hash


def test_touch_updates_verified_at_without_changing_content_hash():
    with tempfile.TemporaryDirectory() as d:
        db = KnowledgeCacheDB(db_path=os.path.join(d, "knowledge.db"))
        entry = _entry()
        db.upsert(entry)
        before = db.get("cisco", "show ip ospf neighbor", "ios-xe")

        assert db.touch("cisco", "show ip ospf neighbor", "ios-xe")
        after = db.get("cisco", "show ip ospf neighbor", "ios-xe")
        assert after.content_hash == before.content_hash


def test_touch_returns_false_when_no_row_exists():
    with tempfile.TemporaryDirectory() as d:
        db = KnowledgeCacheDB(db_path=os.path.join(d, "knowledge.db"))
        assert db.touch("cisco", "nonexistent command", "ios-xe") is False


def test_migration_adds_content_hash_column_to_a_pre_existing_db():
    """A DB created before this column existed must still work -- the
    ALTER TABLE migration in _init_schema is exercised on every startup,
    not just fresh installs."""
    import sqlite3
    with tempfile.TemporaryDirectory() as d:
        db_path = os.path.join(d, "knowledge.db")
        # Simulate a pre-existing DB from before content_hash existed.
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE knowledge_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor TEXT NOT NULL, platform TEXT DEFAULT '',
                command TEXT NOT NULL, syntax TEXT DEFAULT '',
                description TEXT DEFAULT '', example_output TEXT DEFAULT '',
                min_version TEXT DEFAULT '', source_url TEXT DEFAULT '',
                source_title TEXT DEFAULT '', source_name TEXT DEFAULT '',
                source_type TEXT DEFAULT '', confidence TEXT DEFAULT 'unverified',
                fetched_at TEXT NOT NULL, verified_at TEXT NOT NULL,
                ttl_days INTEGER DEFAULT 90, hit_count INTEGER DEFAULT 0,
                UNIQUE(vendor, platform, command)
            );
        """)
        conn.commit()
        conn.close()

        db = KnowledgeCacheDB(db_path=db_path)  # triggers migration in __init__
        entry = _entry()
        assert db.upsert(entry)
        got = db.get("cisco", "show ip ospf neighbor", "ios-xe")
        assert got.content_hash == entry.content_hash


def test_orchestrator_persist_touches_when_content_unchanged(monkeypatch):
    """The actual efficiency fix: identical content on a refetch must call
    cache.touch(), not cache.upsert() -- confirming a refresh really does
    skip re-ingesting unchanged documents."""
    from core.knowledge.orchestrator import KnowledgeOrchestrator

    calls = []

    class _FakeCache:
        def get(self, vendor, command, platform):
            return None
        def upsert(self, entry):
            calls.append(("upsert", entry))
            return True
        def touch(self, vendor, command, platform):
            calls.append(("touch", vendor, command, platform))
            return True

    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _FakeCache()

    existing = _entry()
    fresh = _entry()  # identical content -> identical hash
    orch._persist_fetch_result("cisco", "show ip ospf neighbor", "ios-xe", fresh, existing)
    assert calls == [("touch", "cisco", "show ip ospf neighbor", "ios-xe")]


def test_orchestrator_persist_upserts_when_content_changed(monkeypatch):
    from core.knowledge.orchestrator import KnowledgeOrchestrator

    calls = []

    class _FakeCache:
        def get(self, vendor, command, platform):
            return None
        def upsert(self, entry):
            calls.append("upsert")
            return True
        def touch(self, vendor, command, platform):
            calls.append("touch")
            return True

    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _FakeCache()

    existing = _entry(description="old content")
    fresh = _entry(description="genuinely new content")
    orch._persist_fetch_result("cisco", "show ip ospf neighbor", "ios-xe", fresh, existing)
    assert calls == ["upsert"]


def test_orchestrator_persist_upserts_on_first_fetch_no_existing(monkeypatch):
    from core.knowledge.orchestrator import KnowledgeOrchestrator

    calls = []

    class _FakeCache:
        def upsert(self, entry):
            calls.append("upsert")
            return True

    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _FakeCache()

    fresh = _entry()
    orch._persist_fetch_result("cisco", "show ip ospf neighbor", "ios-xe", fresh, None)
    assert calls == ["upsert"]


# ── Canonical document identity (Gap 2 fix) ─────────────────────────────────
# Real validation against live vendor docs found candidate selection isn't
# stable across independent ingestion runs: search ranking can surface a
# DIFFERENT (but equally valid) page for the same command, which made a
# plain hash comparison report a false "content changed" when really a
# different source had just been picked. source_doc_id scopes the
# comparison to "was this the SAME page" first.

def test_normalize_document_url_strips_query_and_fragment_and_trailing_slash():
    from core.knowledge.base import normalize_document_url
    assert (normalize_document_url("https://Example.com/Path/?utm=1#section")
            == normalize_document_url("https://example.com/Path/"))


def test_normalize_document_url_different_paths_are_different_documents():
    from core.knowledge.base import normalize_document_url
    a = normalize_document_url("https://docs.example.com/page-a")
    b = normalize_document_url("https://docs.example.com/page-b")
    assert a != b


def test_source_doc_id_auto_computed_from_citation_url():
    e = _entry()
    assert e.source_doc_id
    from core.knowledge.base import normalize_document_url
    assert e.source_doc_id == normalize_document_url(e.citation.source_url)


def test_different_canonical_document_is_treated_as_new_source_not_a_change(monkeypatch):
    """The actual Gap 2 fix: existing content came from URL A; the fresh
    fetch's search picked URL B for the same command (real, observed
    behavior). Even if their hashes happen to differ, this must be
    persisted as a new source -- never logged/treated as "document A's
    content changed", since A was never re-examined at all."""
    from core.knowledge.orchestrator import KnowledgeOrchestrator

    calls = []

    class _FakeCache:
        def upsert(self, entry):
            calls.append(("upsert", entry.source_doc_id))
            return True
        def touch(self, vendor, command, platform):
            calls.append(("touch",))
            return True

    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _FakeCache()

    existing = KnowledgeEntry(
        vendor="cisco", command="show ospf neighbor", platform="junos",
        syntax="x", description="Page A content",
        citation=Citation(source_url="https://www.juniper.net/documentation/page-a.html",
                          vendor="cisco", confidence=ConfidenceLevel.HIGH),
    )
    fresh = KnowledgeEntry(
        vendor="cisco", command="show ospf neighbor", platform="junos",
        syntax="x", description="Page B content (different real doc page)",
        citation=Citation(source_url="https://www.juniper.net/documentation/page-b.html",
                          vendor="cisco", confidence=ConfidenceLevel.HIGH),
    )
    assert existing.source_doc_id != fresh.source_doc_id  # sanity: genuinely different documents

    orch._persist_fetch_result("cisco", "show ospf neighbor", "junos", fresh, existing)
    assert calls == [("upsert", fresh.source_doc_id)], calls


def test_same_canonical_document_same_hash_still_touches():
    """The SAME page, re-ingested, with byte-identical content -- must
    still be recognized as unchanged (this is the case that already
    worked before Gap 2's fix; confirming source_doc_id scoping didn't
    regress it)."""
    from core.knowledge.orchestrator import KnowledgeOrchestrator

    calls = []

    class _FakeCache:
        def upsert(self, entry):
            calls.append("upsert")
            return True
        def touch(self, vendor, command, platform):
            calls.append("touch")
            return True

    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _FakeCache()

    existing = _entry()
    fresh = _entry()  # identical URL, identical content
    orch._persist_fetch_result("cisco", "show ip ospf neighbor", "ios-xe", fresh, existing)
    assert calls == ["touch"]


def test_same_canonical_document_different_hash_is_a_real_content_change():
    """The SAME page, but its actual content differs from what's cached --
    this genuinely is "the document changed", and must still upsert."""
    from core.knowledge.orchestrator import KnowledgeOrchestrator

    calls = []

    class _FakeCache:
        def upsert(self, entry):
            calls.append("upsert")
            return True
        def touch(self, vendor, command, platform):
            calls.append("touch")
            return True

    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    orch.cache = _FakeCache()

    existing = _entry(description="old content")
    fresh = _entry(description="the same real page, but updated content")
    assert existing.source_doc_id == fresh.source_doc_id  # sanity: same document
    orch._persist_fetch_result("cisco", "show ip ospf neighbor", "ios-xe", fresh, existing)
    assert calls == ["upsert"]
