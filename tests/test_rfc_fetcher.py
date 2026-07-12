"""
Tests for core/knowledge/fetchers/rfc_fetcher.py — in particular a real
bug caught while building core/knowledge/doc_downloader/rfc_source.py:
RFC 2328 (OSPF v2, this tool's own most relevant spec) is 524,985 bytes,
just over the previous MAX_PAGE_SIZE cap of 500,000, so it silently
failed here on every attempt despite fetching fine at the HTTP level.
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.fetchers import rfc_fetcher


def _fake_response(status_code=200, body=b""):
    resp = MagicMock()
    resp.status_code = status_code
    # iter_content is a generator in real requests; chunk it similarly here.
    chunk_size = 8192
    resp.iter_content.return_value = iter(
        body[i:i + chunk_size] for i in range(0, len(body), chunk_size)
    ) if body else iter([])
    return resp


def test_fetch_rfc_accepts_a_real_world_large_rfc_like_2328(monkeypatch):
    """Regression test for the exact bug: a body just over the OLD 500,000
    byte cap (524,985, RFC 2328's real size) must now succeed."""
    body = ("\n\nOSPF Version 2\n" + ("x" * 524_970)).encode("utf-8")
    monkeypatch.setattr(rfc_fetcher.requests, "get", lambda *a, **k: _fake_response(200, body))

    result = rfc_fetcher.fetch_rfc_text(2328)
    assert result is not None
    assert len(result["content"]) > 500_000


def test_fetch_rfc_still_rejects_something_genuinely_pathological(monkeypatch):
    """The cap isn't removed, just corrected — a body far beyond any real
    RFC's size must still be rejected."""
    body = b"x" * 3_000_000
    monkeypatch.setattr(rfc_fetcher.requests, "get", lambda *a, **k: _fake_response(200, body))

    result = rfc_fetcher.fetch_rfc_text(9999)
    assert result is None


def test_fetch_rfc_returns_none_on_http_error(monkeypatch):
    monkeypatch.setattr(rfc_fetcher.requests, "get", lambda *a, **k: _fake_response(404, b""))
    assert rfc_fetcher.fetch_rfc_text(999999) is None


def test_fetch_rfc_extracts_title_from_body(monkeypatch):
    # Mirrors a real RFC's shape: a non-blank boilerplate header line (so
    # .strip() doesn't remove the leading blank-line separator the title
    # regex actually keys off) followed by a blank line, the title, another
    # blank line, then the body.
    body = "Network Working Group\n\nOSPF Version 2\n\nAbstract\n\nThis memo documents...".encode("utf-8")
    monkeypatch.setattr(rfc_fetcher.requests, "get", lambda *a, **k: _fake_response(200, body))
    result = rfc_fetcher.fetch_rfc_text(2328)
    assert result["title"] == "OSPF Version 2"
