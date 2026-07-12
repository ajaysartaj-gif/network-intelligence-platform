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
import os
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


# ── pdf_downloads/ ingestion ──────────────────────────────────────────────
def _real_pdf_downloads_file_count() -> int:
    """Counts real, INGESTIBLE files currently on disk under pdf_downloads/
    (excluding .gitkeep/README/manifest, and anything over
    core.knowledge.parsers.MAX_FILE_SIZE_BYTES, which ensure_pdf_downloads_
    ingested() correctly skips rather than hangs on -- e.g. docs.fortinet.
    com's 133MB consolidated FortiOS guide). Computed at test time rather
    than hardcoded, since this corpus grows as core.knowledge.doc_downloader
    downloads more (77 on disk / 76 ingestible at the time this bridge was
    built, but neither number is fixed)."""
    from core.knowledge.parsers import MAX_FILE_SIZE_BYTES

    root = os.path.join(ROOT, "pdf_downloads")
    count = 0
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn in (".gitkeep", "README.md", ".manifest.json"):
                continue
            fpath = os.path.join(dirpath, fn)
            if os.path.getsize(fpath) > MAX_FILE_SIZE_BYTES:
                continue
            count += 1
    return count


def test_ensure_pdf_downloads_ingested_ingests_all_real_files_with_healthy_embedder(tmp_path):
    """pdf_downloads/ (core.knowledge.doc_downloader's real, live-verified
    Cisco/Versa/Fortinet/Palo Alto/RFC corpus) must actually reach the
    store rag_query() queries -- the exact gap this bridge closes."""
    from core.knowledge.enterprise.knowledge_layer import EnterpriseKnowledgeLayer
    from core.knowledge.enterprise.pipelines import ensure_pdf_downloads_ingested
    from core.knowledge.rag.embedder import FakeEmbedder
    from core.knowledge.rag.rag_engine import RAGEngine

    expected = _real_pdf_downloads_file_count()
    assert expected > 0, "pdf_downloads/ has no real files to test against -- run the downloader first"

    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name="pdftest")
    layer = EnterpriseKnowledgeLayer(rag=rag)
    summary = ensure_pdf_downloads_ingested(layer=layer)
    assert summary["errors"] == []
    assert summary["ingested"] == expected


def test_ensure_pdf_downloads_ingested_is_idempotent(tmp_path):
    from core.knowledge.enterprise.knowledge_layer import EnterpriseKnowledgeLayer
    from core.knowledge.enterprise.pipelines import ensure_pdf_downloads_ingested
    from core.knowledge.rag.embedder import FakeEmbedder
    from core.knowledge.rag.rag_engine import RAGEngine

    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name="pdftest2")
    layer = EnterpriseKnowledgeLayer(rag=rag)
    first = ensure_pdf_downloads_ingested(layer=layer)
    second = ensure_pdf_downloads_ingested(layer=layer)
    assert first["ingested"] == _real_pdf_downloads_file_count()
    assert second["ingested"] == 0   # unchanged content -> deduped, not re-ingested


def test_ensure_pdf_downloads_ingested_degrades_gracefully_when_embedding_fails():
    """Same discipline as ensure_general_corpus_ingested(): a broken
    embedder must fail per-file with a clear reason, never crash the
    whole call."""
    from core.knowledge.enterprise.pipelines import ensure_pdf_downloads_ingested

    summary = ensure_pdf_downloads_ingested()   # uses the REAL (broken, in this env) embedder
    assert summary["ingested"] == 0
    assert len(summary["errors"]) > 0
    assert all("torch" in e.lower() for e in summary["errors"])


def test_ensure_pdf_downloads_ingested_handles_missing_directory_cleanly(tmp_path, monkeypatch):
    """If pdf_downloads/ doesn't exist at all (e.g. a fresh clone before
    ever running the downloader), this must return cleanly, not error."""
    import core.knowledge.enterprise.pipelines as pipelines_mod
    monkeypatch.setattr(pipelines_mod, "_REPO_ROOT", str(tmp_path))
    summary = pipelines_mod.ensure_pdf_downloads_ingested()
    assert summary == {"ingested": 0, "skipped": 0, "errors": []}


def _synthesis_ai(inner_ai):
    """Wraps an existing AI mock, additionally recognizing
    Reasoner.synthesize_answer()'s own prompt shape and returning a
    distinguishable, fake-but-plausible synthesized answer citing
    multiple sources -- so tests can assert the synthesis call actually
    happened and reached the report, without needing a real LLM."""
    def ai(prompt: str) -> str:
        if "synthesizing ONE short, coherent answer" in prompt:
            return "NAT translates private addresses to public ones [1], and Cisco devices support four NAT types [2]."
        return inner_ai(prompt)
    return ai


# ── multi-source answer synthesis ───────────────────────────────────────
def test_multi_source_hits_produce_a_synthesized_answer_in_the_report(monkeypatch):
    """The direct analogue of a user's own Google AI Overview screenshot:
    multiple real sources (here, a RAG hit AND a vendor doc/MCP hit,
    matching Google's "Cisco Systems +2") must be synthesized into ONE
    cited answer, not just listed separately in knowledge_sources."""
    import core.intent_engine as ie_mod

    class FakeHit:
        def __init__(self, source, title, text):
            self.source, self.title, self.text = source, title, text

    class FakeCitation:
        confidence = ConfidenceLevel.HIGH
        source_url = "https://developer.cisco.com/example"
        source_title = "Cisco DevNet: NAT Configuration"
        source_name = "devnet_content_mcp"

    class FakeEntry:
        citation = FakeCitation()
        description = "Cisco devices implement NAT in four distinct ways: static, dynamic, PAT, and overload."

    fake_orch = MagicMock()
    fake_orch.rag_query.return_value = [FakeHit("vendor_docs:versa_nat.pdf", "Versa NAT Configuration",
                                                "NAT maps private IP addresses to public ones.")]
    fake_orch.lookup.return_value = FakeEntry()
    monkeypatch.setattr(ie_mod, "get_orchestrator", lambda: fake_orch)

    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_synthesis_ai(_make_ai()), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=1))
    report = eng.run("tell me about cisco nat")
    s = report.session

    assert s.synthesized_answer, "expected a non-empty synthesized answer with real sources present"
    assert "[1]" in s.synthesized_answer and "[2]" in s.synthesized_answer
    # Both source labels are still present in the flat list too — synthesis
    # is additive, not a replacement for the existing citation mechanism.
    assert any(src.startswith("RAG corpus:") for src in s.knowledge_sources)
    assert any("Cisco DevNet: NAT Configuration" in src for src in s.knowledge_sources)
    assert "🔎 Synthesized Answer" in report.to_markdown()
    assert s.synthesized_answer in report.to_markdown()
    assert report.to_dict()["synthesized_answer"] == s.synthesized_answer


def test_no_synthesized_answer_when_nothing_was_actually_retrieved(monkeypatch):
    """Same discipline as the existing no-fabricated-citation test: zero
    real hits must mean zero synthesized answer, never an invented one."""
    import core.intent_engine as ie_mod
    fake_orch = MagicMock()
    fake_orch.rag_query.return_value = []
    fake_orch.lookup.return_value = None
    monkeypatch.setattr(ie_mod, "get_orchestrator", lambda: fake_orch)

    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_synthesis_ai(_make_ai()), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=1))
    report = eng.run("why is the OSPF neighbor stuck in ExStart")
    assert report.session.synthesized_answer == ""
    assert "🔎 Synthesized Answer" not in report.to_markdown()


def test_grounding_materials_accumulate_across_both_grounder_calls_without_duplicating(monkeypatch):
    """run() calls _grounder(...) twice (initial probe + before fix
    generation) -- the SAME RAG hit surfacing both times must be counted
    once, not fed into synthesize_answer() twice."""
    import core.intent_engine as ie_mod

    class FakeHit:
        def __init__(self, source, title, text):
            self.source, self.title, self.text = source, title, text

    fake_orch = MagicMock()
    fake_orch.rag_query.return_value = [FakeHit("rfc:rfc2663.txt", "NAT Terminology and Considerations", "...")]
    fake_orch.lookup.return_value = None
    monkeypatch.setattr(ie_mod, "get_orchestrator", lambda: fake_orch)

    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Resolve the OSPF neighbor stuck in ExStart."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([{"statement": "MTU mismatch between OSPF neighbors", "prior": 0.5}])
        if "normalized diagnostic OPERATION" in prompt:
            return json.dumps([])
        if "Interpret this device output" in prompt:
            return json.dumps({"facts": [], "impacts": []})
        return ""

    devices = [Dev("10.0.0.1")]
    gw = VendorGateway(send=lambda d, cmds: {c: "" for c in cmds},
                       hint_provider=lambda d: {"device_type": "cisco_ios"})
    eng = TroubleshootingEngine(ai_call=_synthesis_ai(ai), devices=devices, gateway=gw,
                                config=TSConfig(max_steps=3, patience=1))
    eng.run("why is the OSPF neighbor stuck in ExStart")
    materials = getattr(eng, "_grounding_materials", [])
    matches = [m for m in materials if m["title"] == "NAT Terminology and Considerations"]
    assert len(matches) == 1, f"expected exactly one deduped entry, got {len(matches)}"


# ── Reasoner.synthesize_answer() unit tests ─────────────────────────────
def test_synthesize_answer_returns_empty_for_no_materials():
    from core.troubleshooting.reasoning import Reasoner

    calls = {"n": 0}

    def ai(prompt: str) -> str:
        calls["n"] += 1
        return "should never be reached"

    reasoner = Reasoner(ai)
    result = reasoner.synthesize_answer("tell me about cisco nat", [])
    assert result == ""
    assert calls["n"] == 0, "must not call the LLM at all when there are no real sources"


def test_synthesize_answer_includes_all_sources_in_the_prompt():
    from core.troubleshooting.reasoning import Reasoner

    captured = {}

    def ai(prompt: str) -> str:
        captured["prompt"] = prompt
        return "synthesized text"

    reasoner = Reasoner(ai)
    materials = [
        {"source": "RAG: vendor_docs:versa_nat.pdf", "title": "Versa NAT Configuration", "text": "NAT maps..."},
        {"source": "CISCO doc/MCP", "title": "Cisco DevNet: NAT Configuration", "text": "Cisco NAT types..."},
    ]
    result = reasoner.synthesize_answer("tell me about cisco nat", materials)
    assert result == "synthesized text"
    prompt = captured["prompt"]
    assert "[1] Source: RAG: vendor_docs:versa_nat.pdf" in prompt
    assert "[2] Source: CISCO doc/MCP" in prompt
    assert "tell me about cisco nat" in prompt


def test_intent_engine_ensure_pdf_downloads_ingested_is_called_from_rag_context_for(monkeypatch):
    """Confirms the wiring itself: _rag_context_for() must call the new
    ingestion bridge, not just have it exist unused (the exact class of
    bug this whole fix addresses)."""
    import core.intent_engine as ie_mod

    called = {"n": 0}

    def fake_ensure(self):
        called["n"] += 1
    monkeypatch.setattr(ie_mod.IntentEngine, "_ensure_pdf_downloads_ingested", fake_ensure)

    fake_orch = MagicMock()
    fake_orch.rag_query.return_value = []
    monkeypatch.setattr(ie_mod, "get_orchestrator", lambda: fake_orch)

    ie = ie_mod.IntentEngine.__new__(ie_mod.IntentEngine)
    ie._last_grounding_citations = []
    ie._rag_context_for("why is the OSPF neighbor stuck in ExStart")
    assert called["n"] == 1
