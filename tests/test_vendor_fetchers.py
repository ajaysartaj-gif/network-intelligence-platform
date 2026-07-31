"""
Regression for a real, previously-silent production gap: a user asked why
their tool couldn't reach authoritative vendor docs the way a general web
search can. Investigation found the live vendor-doc web-fetch mechanism
(core/knowledge/fetchers/*.py, wired into the live troubleshooting engine's
grounding path via core/intent_engine.py's _vendor_doc_context) was fully
implemented and correctly wired in — but its ONE data source, DuckDuckGo's
keyless HTML search endpoint, now reliably returns HTTP 202 (an anti-bot
challenge, not real results) for automated requests, and the old code
treated that identically to "searched fine, found nothing" — swallowed at
DEBUG level, in 9 near-identical copy-pasted implementations, with zero
visible indication anywhere that live doc lookups had been silently
non-functional across every vendor.

Given "if this gonna improve my tool in reality then go for it" (the user's
own words), the follow-up fix replaces the dead-end keyless DDG scrape with
a real, key-based search API as the PRIMARY path, falling back to the
(largely non-functional) DDG scrape only when no key is configured — so a
deployment with a real key gets real results again, and one without still
degrades exactly as before rather than breaking harder. Tavily (not Brave,
whose free tier was killed in Feb 2026 and now requires a card on file) was
chosen for a genuinely card-free 1,000-credit/month tier.

This file locks in: (1) the fix's central behavior — a blocked search
raises SearchBackendBlocked, caught by fetch() and logged at WARNING, not
silently swallowed; (2) the de-duplication — all 9 vendor fetchers now
share ONE _duckduckgo_search implementation instead of 9 copies that would
each need the same fix applied by hand; (3) the Tavily-first / DDG-fallback
behavior of _web_search, the new shared entry point every vendor's
search_candidates() calls.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core.knowledge.fetchers.base_fetcher import SearchBackendBlocked, VendorFetcher
from core.knowledge.fetchers.cisco_fetcher import CiscoFetcher
from core.knowledge.fetchers.juniper_fetcher import JuniperFetcher
from core.knowledge.fetchers.arista_fetcher import AristaFetcher
from core.knowledge.fetchers.paloalto_fetcher import PaloAltoFetcher
from core.knowledge.fetchers.fortinet_fetcher import FortinetFetcher
from core.knowledge.fetchers.aruba_fetcher import ArubaFetcher
from core.knowledge.fetchers.huawei_fetcher import HuaweiFetcher
from core.knowledge.fetchers.dell_fetcher import DellFetcher
from core.knowledge.fetchers.extreme_fetcher import ExtremeFetcher

ALL_FETCHER_CLASSES = [
    CiscoFetcher, JuniperFetcher, AristaFetcher, PaloAltoFetcher, FortinetFetcher,
    ArubaFetcher, HuaweiFetcher, DellFetcher, ExtremeFetcher,
]


def test_every_vendor_fetcher_shares_the_same_search_implementation():
    """The 9x duplication (each vendor carrying its own byte-identical
    _duckduckgo_search) is exactly why this bug needed 9 separate fixes
    before this change -- now there is exactly one implementation."""
    for cls in ALL_FETCHER_CLASSES:
        assert cls._duckduckgo_search is VendorFetcher._duckduckgo_search, cls
        assert cls._web_search is VendorFetcher._web_search, cls
        assert cls._tavily_search is VendorFetcher._tavily_search, cls
        assert cls.DDG_SEARCH_URL == VendorFetcher.DDG_SEARCH_URL


class _FakeResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


@pytest.fixture(autouse=True)
def _no_tavily_key_by_default(monkeypatch):
    """Every test in this file that doesn't explicitly configure a key
    must exercise the DDG-fallback path deterministically, regardless of
    whatever's actually set in the environment running the suite."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    monkeypatch.setattr(base_fetcher_module, "_get_secret", lambda name: "")


def test_non_200_search_response_raises_search_backend_blocked(monkeypatch):
    """The real, confirmed-by-hand behavior today: DuckDuckGo's HTML
    endpoint returns 202 (an anti-bot interstitial) instead of 200 for
    automated requests -- this must be distinguishable from "0 results"."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    monkeypatch.setattr(
        base_fetcher_module, "requests",
        type("R", (), {"get": staticmethod(lambda *a, **k: _FakeResponse(202))}))
    fetcher = CiscoFetcher()
    with pytest.raises(SearchBackendBlocked):
        fetcher._duckduckgo_search("show ip ospf neighbor")


def test_fetch_catches_search_backend_blocked_and_returns_none_not_an_exception(monkeypatch, caplog):
    """fetch() must not let SearchBackendBlocked escape uncaught (it would
    have crashed the live troubleshooting engine's grounding call), and
    must log it at WARNING so it's visible -- not silently swallowed at
    DEBUG like the old per-vendor except-clauses did."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    monkeypatch.setattr(
        base_fetcher_module, "requests",
        type("R", (), {"get": staticmethod(lambda *a, **k: _FakeResponse(202))}))
    fetcher = CiscoFetcher()
    import logging
    with caplog.at_level(logging.WARNING):
        result = fetcher.fetch("show ip ospf neighbor", platform="ios-xe")
    assert result is None
    assert any("unavailable" in r.message for r in caplog.records), caplog.records


def test_successful_search_still_returns_real_candidates(monkeypatch):
    """The happy path must still work once the search backend is healthy
    -- this fix only changes how failure is handled, not success."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    html = (
        '<html><body>'
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.cisco.com'
        '%2Fc%2Fen%2Fus%2Ftd%2Fdocs%2Fsomething.html">Cisco Command Reference</a>'
        '</body></html>'
    )
    monkeypatch.setattr(
        base_fetcher_module, "requests",
        type("R", (), {"get": staticmethod(lambda *a, **k: _FakeResponse(200, html))}))
    fetcher = CiscoFetcher()
    results = fetcher._duckduckgo_search("show ip ospf neighbor")
    assert results == [("https://www.cisco.com/c/en/us/td/docs/something.html",
                        "Cisco Command Reference")]


def test_web_search_falls_back_to_ddg_when_no_key_configured(monkeypatch):
    """No TAVILY_API_KEY at all -> _web_search must go straight to the DDG
    scrape (the pre-existing, largely non-functional but harmless-to-try
    fallback), never touching the Tavily endpoint."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        return _FakeResponse(200, "<html><body></body></html>")

    monkeypatch.setattr(base_fetcher_module, "requests", type("R", (), {"get": staticmethod(fake_get)}))
    fetcher = CiscoFetcher()
    fetcher._web_search("show ip ospf neighbor")
    assert len(calls) == 1
    assert "duckduckgo.com" in calls[0]


def test_web_search_uses_tavily_when_key_configured(monkeypatch):
    """A configured key must be tried FIRST, and its real results trusted
    -- this is the actual fix the user asked for: a durable, genuinely
    free, working replacement for the dead DDG scrape."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    monkeypatch.setattr(base_fetcher_module, "_get_secret", lambda name: "fake-tavily-key")
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(200, json_data={
            "results": [
                {"url": "https://www.cisco.com/c/en/us/td/docs/real-page.html",
                 "title": "Real Cisco Doc", "content": "..."},
            ],
        })

    monkeypatch.setattr(base_fetcher_module, "requests", type("R", (), {"post": staticmethod(fake_post)}))
    fetcher = CiscoFetcher()
    results = fetcher._web_search("show ip ospf neighbor")
    assert results == [("https://www.cisco.com/c/en/us/td/docs/real-page.html", "Real Cisco Doc")]
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert "api.tavily.com" in url
    assert kwargs["headers"]["Authorization"] == "Bearer fake-tavily-key"
    # Narrows results server-side to this fetcher's own trusted domain,
    # instead of relying only on "site:cisco.com" embedded in query text.
    assert kwargs["json"]["include_domains"] == ["cisco.com"]


def test_tavily_api_failure_raises_search_backend_blocked_not_silent_empty(monkeypatch):
    """A bad key / rate limit / outage on the REAL search API must be just
    as visible as a blocked DDG scrape -- not a second silent failure
    mode now that there are two possible search backends."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    monkeypatch.setattr(base_fetcher_module, "_get_secret", lambda name: "fake-tavily-key")
    monkeypatch.setattr(
        base_fetcher_module, "requests",
        type("R", (), {"post": staticmethod(lambda *a, **k: _FakeResponse(401))}))
    fetcher = CiscoFetcher()
    with pytest.raises(SearchBackendBlocked):
        fetcher._web_search("show ip ospf neighbor")


# ── ingest_via_search_and_extract: the user's explicit architecture ────────
# "Do not use Tavily Extract as a runtime dependency for every query.
# Instead ... Search + Extract used only for knowledge ingestion ...
# During troubleshooting, always query the local knowledge first ...
# Keep the existing HTML parser as a fallback during the migration."

def test_ingest_returns_none_without_a_key_so_caller_falls_back_to_old_parser():
    """No TAVILY_API_KEY at all -> the new ingestion path must return None
    (not raise, not attempt any network call) so its callers fall
    straight through to the old fetch() HTML-parse path."""
    fetcher = CiscoFetcher()
    assert fetcher.ingest_via_search_and_extract("show ip ospf neighbor", "ios-xe") is None


def test_ingest_end_to_end_search_then_extract_then_normalize(monkeypatch):
    """The real new pipeline: Search finds a trusted URL, Extract pulls
    its content, and the result is normalized into a KnowledgeEntry with
    real citation info -- ready to persist into the local knowledge
    store by whichever caller invoked this (orchestrator cache, or the
    RAG-feeding ingestion pipeline)."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    monkeypatch.setattr(base_fetcher_module, "_get_secret", lambda name: "fake-tavily-key")

    def fake_post(url, json=None, **kwargs):
        if "search" in url:
            return _FakeResponse(200, json_data={"results": [
                {"url": "https://www.cisco.com/c/en/us/td/docs/real-page.html",
                 "title": "Real Cisco Doc"},
            ]})
        assert "extract" in url
        assert json["urls"] == ["https://www.cisco.com/c/en/us/td/docs/real-page.html"]
        return _FakeResponse(200, json_data={"results": [
            {"url": "https://www.cisco.com/c/en/us/td/docs/real-page.html",
             "raw_content": "show ip ospf neighbor displays OSPF neighbor adjacency state."},
        ]})

    monkeypatch.setattr(base_fetcher_module, "requests", type("R", (), {"post": staticmethod(fake_post)}))
    fetcher = CiscoFetcher()
    entry = fetcher.ingest_via_search_and_extract("show ip ospf neighbor", "ios-xe")
    assert entry is not None
    assert "OSPF neighbor adjacency" in entry.description
    assert entry.citation.source_url == "https://www.cisco.com/c/en/us/td/docs/real-page.html"
    assert entry.citation.vendor == "cisco"


def test_orchestrator_web_fetch_prefers_new_ingestion_falls_back_to_old_fetch(monkeypatch):
    """The actual call site the live troubleshooting engine reaches
    (KnowledgeOrchestrator._web_fetch, only invoked after cache+RAG both
    miss): must try the new Search+Extract ingestion first, and only fall
    back to the old fetch() when that returns None."""
    from core.knowledge.orchestrator import KnowledgeOrchestrator
    import core.knowledge.orchestrator as orchestrator_module

    calls = []

    class _FakeFetcher:
        def ingest_via_search_and_extract(self, command, platform):
            calls.append("new")
            return None  # simulate no key / nothing found -> must fall back

        def fetch(self, command, platform):
            calls.append("old")
            return "old-path-result"

    monkeypatch.setattr(orchestrator_module, "get_fetcher", lambda vendor: _FakeFetcher())
    orch = KnowledgeOrchestrator(enable_rag=False, enable_mcp=False)
    result = orch._web_fetch("cisco", "show ip ospf neighbor", "ios-xe")
    assert calls == ["new", "old"]
    assert result == "old-path-result"


def test_ingest_via_search_and_extract_skips_untrusted_domains(monkeypatch):
    """A candidate URL search_candidates() itself would already exclude
    (e.g. not cisco.com) must never reach Extract -- _is_trusted_url
    gates ingestion exactly like it already gates the old fetch() path."""
    import core.knowledge.fetchers.base_fetcher as base_fetcher_module
    monkeypatch.setattr(base_fetcher_module, "_get_secret", lambda name: "fake-tavily-key")
    calls = []

    def fake_post(url, json=None, **kwargs):
        calls.append(url)
        if "search" in url:
            # search_candidates() itself already filters to cisco.com, so
            # this models an empty result rather than a bypass attempt.
            return _FakeResponse(200, json_data={"results": []})
        return _FakeResponse(200, json_data={"results": []})

    monkeypatch.setattr(base_fetcher_module, "requests", type("R", (), {"post": staticmethod(fake_post)}))
    fetcher = CiscoFetcher()
    entry = fetcher.ingest_via_search_and_extract("show ip ospf neighbor", "ios-xe")
    assert entry is None
    assert not any("extract" in c for c in calls), "must not call Extract with zero trusted candidates"
