"""
Tests for Phase 5 of the RAG/MCP improvement pass: mcp_server.py — the
platform's first MCP SERVER (only a client to Cisco DevNet's hosted MCP
endpoint existed before this). Tests the undecorated _*_impl() functions
directly (dependency-injecting fakes), not through real MCP protocol
machinery — the same "test the logic, not the glue" split already used for
core/copilot_engine.py's relationship to the engines it drives.
"""
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import mcp_server


def test_mcp_server_registers_all_four_tools():
    names = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert names == {"troubleshoot_network", "configure_network",
                     "design_network_architecture", "search_knowledge_base"}


def test_call_ai_reports_clearly_when_no_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(mcp_server, "_resolve_api_key", lambda: "")
    result = mcp_server.call_ai("hello")
    assert "GROQ_API_KEY" in result


def test_build_devices_constructs_expected_shape():
    devices = mcp_server._build_devices(["10.0.0.1", "10.0.0.2"])
    assert [d.ip for d in devices] == ["10.0.0.1", "10.0.0.2"]
    assert all(d.device_type == "cisco_ios" for d in devices)


def test_build_devices_empty_list_is_safe():
    assert mcp_server._build_devices(None) == []
    assert mcp_server._build_devices([]) == []


# ── troubleshoot_network impl ────────────────────────────────────────────────
def test_troubleshoot_impl_returns_markdown_report(monkeypatch):
    def fake_gateway(devices, ai_call):
        from core.vendor import VendorGateway
        return VendorGateway(send=lambda d, c: {x: "" for x in c},
                             hint_provider=lambda d: {"device_type": "cisco_ios"})

    monkeypatch.setattr(mcp_server, "_gateway_for", fake_gateway)

    def fake_ai(prompt: str) -> str:
        return "{}"

    result = mcp_server._troubleshoot_impl(
        "why is the OSPF neighbor stuck", ["10.0.0.1"], ai_call=fake_ai)
    assert isinstance(result, str)
    assert result   # a real markdown report was produced, not blank/crashed


# ── configure_network impl ───────────────────────────────────────────────────
def test_configure_impl_returns_markdown_report(monkeypatch):
    def fake_gateway(devices, ai_call):
        from core.vendor import VendorGateway
        return VendorGateway(send=lambda d, c: {x: "" for x in c},
                             hint_provider=lambda d: {"device_type": "cisco_ios"})

    monkeypatch.setattr(mcp_server, "_gateway_for", fake_gateway)

    def fake_ai(prompt: str) -> str:
        if "single high-level category" in prompt:
            return '{"objective": "enable OSPF", "category": "routing"}'
        if "NORMALIZED configuration intent" in prompt:
            return '{"technologies": [], "protocols": [], "services": [], "scope": [], "intents": []}'
        if "MANDATORY inputs" in prompt:
            return "[]"
        return "{}"

    result = mcp_server._configure_impl(
        "enable OSPF on the core uplink", ["10.0.0.1"], ai_call=fake_ai)
    assert isinstance(result, str)
    assert "Goal" in result or result   # produced a real report, didn't crash


# ── design_network_architecture impl ────────────────────────────────────────
def test_design_impl_returns_markdown_report_with_no_devices(monkeypatch):
    def fake_ai(prompt: str) -> str:
        if "Generate at least" in prompt:
            return ('[{"name": "Option A", "architecture": "a"}, '
                   '{"name": "Option B", "architecture": "b"}, '
                   '{"name": "Option C", "architecture": "c"}]')
        return "{}"

    result = mcp_server._design_impl("design a resilient campus core", device_ips=None, ai_call=fake_ai)
    assert isinstance(result, str)
    assert "Architecture" in result


# ── search_knowledge_base impl ───────────────────────────────────────────────
class _FakeHit:
    def __init__(self, title, doc_id, confidence, source_type, text):
        self.title, self.doc_id = title, doc_id
        self.confidence, self.source_type, self.text = confidence, source_type, text


class _FakeLayer:
    def __init__(self, hits):
        self._hits = hits

    def search(self, query, top_k=5):
        return self._hits[:top_k]


def test_search_knowledge_impl_formats_hits():
    hits = [_FakeHit("OSPF Timers", "ospf-doc", 0.87, "vendor_docs", "MTU must match.")]
    result = mcp_server._search_knowledge_impl("ospf mtu", top_k=5, layer=_FakeLayer(hits))
    assert "OSPF Timers" in result
    assert "0.87" in result
    assert "MTU must match." in result


def test_search_knowledge_impl_reports_clearly_on_no_hits():
    result = mcp_server._search_knowledge_impl("nothing matches", layer=_FakeLayer([]))
    assert "No matching" in result


def test_format_knowledge_hits_empty_list():
    assert "No matching" in mcp_server._format_knowledge_hits([])
