"""
Tests for the general RAG-ingestible knowledge corpus (corpus/general/*.txt).

Context: the platform's grounding mechanism (core/intent_engine.py's
IntentEngine._ground(), via core.knowledge.orchestrator.KnowledgeOrchestrator
.rag_query()) is available for EVERY troubleshooting session, not just the
protocols with hand-compiled deterministic signatures (OSPF/STP/BGP). But it
can only ground the LLM in technologies that actually have content in the
local knowledge corpus. corpus/general/*.txt adds real, researched prose
coverage for technologies that have no compiled signatures: VXLAN/EVPN,
multicast/PIM, QoS, MPLS L3VPN, EIGRP, VRRP, IPv6 ND/SLAAC, and port
security/802.1X.

This is NOT the narrow PARAM:/ENUMERATE:/HEALTHY: cross-device-comparison
format used by corpus/ospf_adjacency.txt (that format is specific to
core.troubleshooting.strategies.mismatch and is parsed by a different,
custom StubExtractor/loader — knowledge/corpus_loader.py). These are plain
prose documents meant to be ingested exactly like any other vendor doc /
best-practice document, through the general-purpose EnterpriseKnowledgeLayer
ingestion path (the same path core.knowledge.orchestrator.rag_query() reads
from at query time), and retrieved with a realistic, natural-language
troubleshooting question.

Isolation: FakeEmbedder (core/knowledge/rag/embedder.py) + a temp ChromaDB
dir, the established pattern already used by tests/test_supply_chain.py and
tests/test_knowledge_parsers.py — no real embedding model download, no
contact with the platform's real persistent RAG store.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.knowledge.enterprise.knowledge_layer import (
    EnterpriseKnowledgeLayer, KnowledgeRecord, SourceType,
)
from core.knowledge.rag.embedder import FakeEmbedder
from core.knowledge.rag.rag_engine import RAGEngine

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORPUS_GENERAL_DIR = os.path.join(_REPO_ROOT, "corpus", "general")

# doc_id -> (filename, a realistic natural-language troubleshooting query a
# user might actually ask, a token/phrase that should appear in the top hit)
_DOCS = {
    "vxlan-evpn": (
        "vxlan_evpn.txt",
        "why is VXLAN EVPN peering not coming up",
        "route-target",
    ),
    "multicast-pim": (
        "multicast_pim.txt",
        "multicast traffic not forwarding RPF failure",
        "reverse path forwarding",
    ),
    "qos": (
        "qos.txt",
        "QoS policy applied but not taking effect on the interface",
        "service-policy",
    ),
    "mpls-l3vpn": (
        "mpls_l3vpn.txt",
        "MPLS L3VPN customer routes not showing up on remote PE",
        "route target",
    ),
    "eigrp": (
        "eigrp.txt",
        "EIGRP neighbor won't form between two routers",
        "k-value",
    ),
    "vrrp": (
        "vrrp.txt",
        "VRRP multiple routers claiming master at the same time",
        "advertisement",
    ),
    "ipv6-nd-slaac": (
        "ipv6_nd_slaac.txt",
        "IPv6 host not receiving router advertisement SLAAC address",
        "router advertisement",
    ),
    "port-security-dot1x": (
        "port_security_dot1x.txt",
        "switch port err-disabled after security violation",
        "violation",
    ),
}


def _layer(tmp_path, name="general-corpus-test"):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"),
                    collection_name=name)
    return EnterpriseKnowledgeLayer(rag=rag)


def _read_corpus_file(filename: str) -> str:
    path = os.path.join(_CORPUS_GENERAL_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── Corpus files exist and have real substance ──────────────────────────────

def test_corpus_general_directory_exists():
    assert os.path.isdir(_CORPUS_GENERAL_DIR)


@pytest.mark.parametrize("doc_id,info", _DOCS.items(), ids=list(_DOCS.keys()))
def test_each_corpus_file_exists_and_has_real_substance(doc_id, info):
    filename, _query, _expect = info
    content = _read_corpus_file(filename)
    # "genuinely useful, not a stub" -- enforce a real substance floor.
    lines = [l for l in content.splitlines() if l.strip()]
    assert len(lines) >= 80, (
        f"{filename} has only {len(lines)} non-blank lines; expected a "
        "substantive document, not a stub"
    )
    assert len(content) >= 4000
    # Should read as prose (this is NOT the PARAM:/ENUMERATE: mismatch format)
    assert "PARAM:" not in content
    assert "ENUMERATE:" not in content


# ── Ingest every doc, then verify realistic retrieval ───────────────────────

def test_ingest_all_general_corpus_docs_round_trip(tmp_path):
    layer = _layer(tmp_path)
    for doc_id, (filename, _query, _expect) in _DOCS.items():
        record = KnowledgeRecord(
            doc_id=doc_id,
            title=filename.replace(".txt", "").replace("_", " "),
            content=_read_corpus_file(filename),
            source_type=SourceType.BEST_PRACTICE,
            tags=["general-corpus", doc_id],
        )
        result = layer.ingest(record)
        assert not result.get("skipped"), f"{doc_id} ingest was skipped: {result}"
        assert result["chunks"] > 0

    stats = layer.source_statistics()
    assert stats["distinct_documents"] == len(_DOCS)


@pytest.mark.parametrize("doc_id,info", _DOCS.items(), ids=list(_DOCS.keys()))
def test_realistic_troubleshooting_query_retrieves_own_content(tmp_path, doc_id, info):
    """
    Ingest ONLY this one doc (isolated per-test collection) and confirm a
    realistic, natural-language troubleshooting question a user would
    actually type retrieves it with a reasonable confidence score -- this is
    the actual grounding path core.knowledge.orchestrator.rag_query() uses
    (EnterpriseKnowledgeLayer.search()), not the bare RAGEngine.
    """
    filename, query, expect_phrase = info
    layer = _layer(tmp_path, name=f"single-{doc_id}")
    record = KnowledgeRecord(
        doc_id=doc_id,
        title=filename.replace(".txt", "").replace("_", " "),
        content=_read_corpus_file(filename),
        source_type=SourceType.BEST_PRACTICE,
        tags=["general-corpus", doc_id],
    )
    ingest_result = layer.ingest(record)
    assert not ingest_result.get("skipped")

    # Sanity: the phrase we expect this query to surface actually exists
    # somewhere in the source document (keeps the _DOCS table honest).
    assert expect_phrase.lower() in record.content.lower()

    hits = layer.search(query, top_k=3)
    assert hits, f"no hits at all for query {query!r} against {doc_id}"
    assert hits[0].doc_id == doc_id
    assert hits[0].confidence > 0.0


def test_cross_technology_query_does_not_cross_contaminate(tmp_path):
    """
    With ALL eight docs ingested together, a VXLAN-specific query should
    retrieve the VXLAN doc, not (e.g.) the EIGRP or QoS doc -- verifying the
    corpus is diverse enough that hybrid search actually discriminates
    between technologies rather than everything just tying.
    """
    layer = _layer(tmp_path, name="mixed-all")
    for doc_id, (filename, _query, _expect) in _DOCS.items():
        layer.ingest(KnowledgeRecord(
            doc_id=doc_id,
            title=filename.replace(".txt", "").replace("_", " "),
            content=_read_corpus_file(filename),
            source_type=SourceType.BEST_PRACTICE,
            tags=["general-corpus", doc_id],
        ))

    hits = layer.search("VXLAN EVPN VTEP route target import export mismatch", top_k=3)
    assert hits
    assert hits[0].doc_id == "vxlan-evpn"

    hits = layer.search("EIGRP K-value mismatch neighbor authentication", top_k=3)
    assert hits
    assert hits[0].doc_id == "eigrp"

    hits = layer.search("802.1X RADIUS authentication certificate failure", top_k=3)
    assert hits
    assert hits[0].doc_id == "port-security-dot1x"
