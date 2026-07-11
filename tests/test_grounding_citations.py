"""
Tests for three real gaps found and fixed in the RAG/MCP grounding layer:

1. LocalEmbedder._ensure_loaded() used to only catch ImportError for a
   MISSING sentence-transformers package. When sentence-transformers IS
   installed but its own dependency chain (torch) is an incompatible
   version, a raw NameError/AttributeError from deep inside torch's
   internals propagated uncaught, surfacing everywhere as a cryptic
   one-liner ("name 'nn' is not defined") with no indication of the real,
   fixable cause. Now caught and re-raised as a clear, actionable
   RuntimeError.

2. corpus/general/*.txt (real, researched prose for VXLAN/EVPN, PIM, QoS,
   MPLS L3VPN, EIGRP, VRRP, IPv6 ND/SLAAC, 802.1X) sat on disk unused in
   production -- only tests/test_general_corpus.py ever ingested it, into
   an isolated temp store nothing else could query. pipelines.
   ensure_general_corpus_ingested() + IntentEngine._rag_context_for()
   wiring makes it actually reachable by a live troubleshooting session.

3. Grounding (RAG hits, vendor-doc/MCP results) genuinely executes but
   never left a visible trace in the final report -- a user had no way to
   tell whether their conclusion was informed by real documentation.
   IntentEngine._ground()'s new self._last_grounding_citations +
   engine.py's _record_grounding_citations() surface this in
   session.knowledge_sources, the same place every compiled-signature
   citation already appears.
"""
import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest

from core.knowledge.base import ConfidenceLevel
from core.knowledge.rag.embedder import LocalEmbedder
from core.vendor import VendorGateway
from core.troubleshooting import TroubleshootingEngine, TSConfig


class Dev:
    def __init__(self, ip, hostname="R1"):
        self.ip, self.hostname, self.device_type = ip, hostname, "cisco_ios"


# ── embedder failure mode ─────────────────────────────────────────────────
def test_embedder_converts_broken_dependency_import_into_clear_runtime_error(monkeypatch):
    """Simulates the exact failure shape this environment's torch<2.4 vs
    sentence-transformers conflict produces: sentence-transformers IS
    importable at the module level (no ImportError), but loading fails
    with an unrelated-looking exception deep in its own dependency chain."""
    embedder = LocalEmbedder()

    def _broken_import(name, *a, **k):
        if name == "sentence_transformers":
            raise NameError("name 'nn' is not defined")
        return real_import(name, *a, **k)

    import builtins
    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", _broken_import)

    with pytest.raises(RuntimeError) as exc_info:
        embedder._ensure_loaded()
    msg = str(exc_info.value)
    assert "torch" in msg.lower()
    assert "NameError" in msg
    assert "name 'nn' is not defined" in msg


def test_embedder_still_raises_clear_error_for_genuinely_missing_package(monkeypatch):
    """The original, narrower case (package not installed at all) must
    keep working exactly as before."""
    embedder = LocalEmbedder()

    def _missing_import(name, *a, **k):
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *a, **k)

    import builtins
    real_import = builtins.__import__
    monkeypatch.setattr(builtins, "__import__", _missing_import)

    with pytest.raises(RuntimeError) as exc_info:
        embedder._ensure_loaded()
    assert "pip install sentence-transformers" in str(exc_info.value)


# ── general corpus ingestion ──────────────────────────────────────────────
def test_ensure_general_corpus_ingested_ingests_all_files_with_healthy_embedder(tmp_path):
    from core.knowledge.enterprise.knowledge_layer import EnterpriseKnowledgeLayer
    from core.knowledge.enterprise.pipelines import ensure_general_corpus_ingested
    from core.knowledge.rag.embedder import FakeEmbedder
    from core.knowledge.rag.rag_engine import RAGEngine

    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name="test")
    layer = EnterpriseKnowledgeLayer(rag=rag)
    summary = ensure_general_corpus_ingested(layer=layer)
    assert summary["errors"] == []
    assert summary["ingested"] == 8   # vxlan_evpn, multicast_pim, qos, mpls_l3vpn, eigrp, vrrp, ipv6_nd_slaac, port_security_dot1x


def test_ensure_general_corpus_ingested_is_idempotent(tmp_path):
    """Re-ingesting unchanged files must be a cheap no-op (content-hash
    dedup), not duplicate versions -- the same contract
    live_retriever.ensure_corpus_ingested() relies on for "safe to call
    on every request"."""
    from core.knowledge.enterprise.knowledge_layer import EnterpriseKnowledgeLayer
    from core.knowledge.enterprise.pipelines import ensure_general_corpus_ingested
    from core.knowledge.rag.embedder import FakeEmbedder
    from core.knowledge.rag.rag_engine import RAGEngine

    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name="test2")
    layer = EnterpriseKnowledgeLayer(rag=rag)
    first = ensure_general_corpus_ingested(layer=layer)
    second = ensure_general_corpus_ingested(layer=layer)
    assert first["ingested"] == 8
    assert second["ingested"] == 0   # unchanged content -> deduped, not re-ingested


def test_ensure_general_corpus_ingested_degrades_gracefully_when_embedding_fails(monkeypatch):
    """In an environment where the real embedder can't load (this
    session's own torch<2.4 conflict), ingestion must fail per-file with
    a clear reason, never crash the whole call."""
    from core.knowledge.enterprise.pipelines import ensure_general_corpus_ingested

    summary = ensure_general_corpus_ingested()   # uses the REAL (broken, in this env) embedder
    assert summary["ingested"] == 0
    assert len(summary["errors"]) > 0
    assert all("torch" in e.lower() for e in summary["errors"])


# ── grounding citations surface in the report ────────────────────────────
def _make_ai():
    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Resolve the OSPF neighbor stuck in ExStart."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([])
        if "normalized diagnostic OPERATION" in prompt:
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""
    return ai


def test_rag_grounding_hit_is_cited_in_the_final_report(monkeypatch):
    import core.intent_engine as ie_mod

    class FakeHit:
        def __init__(self, source, title, text):
            self.source, self.title, self.text = source, title, text

    fake_orch = MagicMock()
    fake_orch.rag_query.return_value = [FakeHit("best_practice:qos.txt", "QoS Troubleshooting", "...")]
    fake_orch.lookup.return_value = None
    monkeypatch.setattr(ie_mod, "get_orchestrator", lambda: fake_orch)

    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai(), devices=devices, gateway=gw, config=TSConfig(max_steps=1))
    report = eng.run("why is the OSPF neighbor stuck in ExStart")
    assert any(src.startswith("RAG corpus: best_practice:qos.txt") for src in report.session.knowledge_sources)


def test_vendor_doc_mcp_hit_is_cited_in_the_final_report(monkeypatch):
    import core.intent_engine as ie_mod

    class FakeCitation:
        confidence = ConfidenceLevel.HIGH
        source_url = "https://developer.cisco.com/example"
        source_title = "Cisco DevNet: OSPF ExStart Troubleshooting"
        source_name = "devnet_content_mcp"

    class FakeEntry:
        citation = FakeCitation()
        description = "A real Cisco doc about OSPF MTU mismatches causing ExStart."

    fake_orch = MagicMock()
    fake_orch.rag_query.return_value = []
    fake_orch.lookup.return_value = FakeEntry()
    monkeypatch.setattr(ie_mod, "get_orchestrator", lambda: fake_orch)

    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai(), devices=devices, gateway=gw, config=TSConfig(max_steps=1))
    report = eng.run("why is the OSPF neighbor stuck in ExStart")
    assert any("Cisco DevNet: OSPF ExStart Troubleshooting" in src for src in report.session.knowledge_sources)


def test_no_grounding_hit_cites_nothing_not_a_fabricated_source(monkeypatch):
    """Absence of a real hit must not produce a fake citation."""
    import core.intent_engine as ie_mod
    fake_orch = MagicMock()
    fake_orch.rag_query.return_value = []
    fake_orch.lookup.return_value = None
    monkeypatch.setattr(ie_mod, "get_orchestrator", lambda: fake_orch)

    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_make_ai(), devices=devices, gateway=gw, config=TSConfig(max_steps=1))
    report = eng.run("why is the OSPF neighbor stuck in ExStart")
    assert not any("RAG corpus" in src or "vendor doc/MCP" in src for src in report.session.knowledge_sources)
