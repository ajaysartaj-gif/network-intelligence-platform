"""
Tests for core/knowledge/doc_downloader/ — the pdf_downloads/ population
mechanism. Network-touching parts (versa_source's live HTTP calls,
cisco_devnet_source's live MCP calls) are exercised via dependency
injection / mocking here; the actual live runs are verified separately,
manually, against the real sites (see the session's own summary for the
real downloaded files this produced).
"""
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.knowledge.doc_downloader.classify import classify_doc_type, safe_filename
from core.knowledge.doc_downloader.manifest import DownloadManifest, ManifestEntry


# ── classify_doc_type ────────────────────────────────────────────────────
def test_classify_troubleshooting_beats_configuration_when_both_present():
    """Priority-ordered matching: "Troubleshooting Configuration Guide"
    must resolve to troubleshooting, not configuration, since
    troubleshooting is checked first."""
    assert classify_doc_type(title="Troubleshooting Configuration Guide") == "troubleshooting"


def test_classify_command_reference():
    assert classify_doc_type(title="IOS Command Reference Guide") == "command_reference"
    assert classify_doc_type(path="/Secure_SD-WAN/CLI_Reference") == "command_reference"


def test_classify_data_sheet():
    assert classify_doc_type(title="Catalyst 9300 Data Sheet") == "data_sheet"


def test_classify_white_paper():
    assert classify_doc_type(title="SD-WAN Security White Paper") == "white_paper"


def test_classify_configuration_default():
    assert classify_doc_type(title="Basic SD-WAN Configuration") == "configuration"
    assert classify_doc_type(title="", path="") == "configuration"   # documented default


def test_classify_from_path_alone():
    """Versa's real sitemap paths carry the signal even with no title:
    "03_Troubleshooting" in the path must classify correctly."""
    assert classify_doc_type(path="/Secure_SD-WAN/03_Troubleshooting") == "troubleshooting"


# ── safe_filename ─────────────────────────────────────────────────────────
def test_safe_filename_sanitizes_and_extends():
    name = safe_filename("SD-WAN: Troubleshooting Guide!", fallback="doc")
    assert name.endswith(".pdf")
    assert ":" not in name and "!" not in name
    assert " " not in name


def test_safe_filename_falls_back_when_title_empty():
    assert safe_filename("", fallback="doc_1") == "doc_1.pdf"


def test_safe_filename_does_not_double_extension():
    assert safe_filename("already_named.pdf", fallback="doc") == "already_named.pdf"


# ── DownloadManifest ──────────────────────────────────────────────────────
def test_manifest_records_and_dedups(tmp_path):
    m = DownloadManifest(str(tmp_path))
    assert not m.has("https://example.com/doc")
    m.record(ManifestEntry(source_url="https://example.com/doc", vendor="versa",
                           doc_type="configuration", title="Doc", local_path="x.pdf",
                           sha256="abc123"))
    assert m.has("https://example.com/doc")
    assert len(m) == 1


def test_manifest_persists_across_instances(tmp_path):
    m1 = DownloadManifest(str(tmp_path))
    m1.record(ManifestEntry(source_url="https://example.com/a", vendor="cisco",
                            doc_type="troubleshooting", title="A", local_path="a.md",
                            sha256="hash1"))
    m2 = DownloadManifest(str(tmp_path))   # fresh instance, same root
    assert m2.has("https://example.com/a")
    assert m2.get("https://example.com/a").title == "A"


def test_manifest_by_vendor_filters_correctly(tmp_path):
    m = DownloadManifest(str(tmp_path))
    m.record(ManifestEntry(source_url="u1", vendor="versa", doc_type="configuration",
                           title="V1", local_path="v1.pdf", sha256="h1"))
    m.record(ManifestEntry(source_url="u2", vendor="cisco", doc_type="configuration",
                           title="C1", local_path="c1.md", sha256="h2"))
    versa_only = m.by_vendor("versa")
    assert set(versa_only.keys()) == {"u1"}


# ── cisco_devnet_source: mocked MCP, no real network ────────────────────
def test_cisco_devnet_source_saves_entry_and_dedups(tmp_path, monkeypatch):
    from core.knowledge.doc_downloader import cisco_devnet_source

    class FakeEntry:
        vendor = "cisco"
        platform = "meraki"
        command = "meraki wireless troubleshooting"
        syntax = "GET /networks/{id}/wireless/..."
        description = "Troubleshoot Meraki wireless client issues."
        example_output = ""
        fetched_at = "2026-07-11T00:00:00"

        class citation:
            source_title = "Meraki Wireless Troubleshooting"
            source_url = "https://developer.cisco.com/meraki/api/wireless"

    fake_source = MagicMock()
    fake_source.lookup.return_value = FakeEntry()
    monkeypatch.setattr(cisco_devnet_source, "DevNetContentMCPSource", lambda: fake_source)

    summary = cisco_devnet_source.run(str(tmp_path), topics=[("meraki wireless troubleshooting", "meraki")])
    assert summary["downloaded"] == 1
    assert summary["errors"] == []

    saved_files = list((tmp_path / "cisco" / "troubleshooting").glob("*.md"))
    assert len(saved_files) == 1
    text = saved_files[0].read_text()
    assert "Cisco DevNet Content Search MCP" in text
    assert "Meraki Wireless Troubleshooting" in text

    # second run must skip (deduped via manifest), not re-query or duplicate
    summary2 = cisco_devnet_source.run(str(tmp_path), topics=[("meraki wireless troubleshooting", "meraki")])
    assert summary2["skipped"] == 1
    assert summary2["downloaded"] == 0


def test_cisco_devnet_source_does_not_collide_when_two_topics_share_a_tool(tmp_path, monkeypatch):
    """Real bug caught in a live run: two different topics that both route
    to the same underlying DevNet MCP tool share the exact same
    entry.citation.source_title (e.g. "...Meraki-API-Doc-Search") — using
    that alone for the filename made the second topic's save silently
    overwrite the first's. The filename must be built from the topic
    (unique per call), not the shared tool-derived title."""
    from core.knowledge.doc_downloader import cisco_devnet_source

    class FakeEntry:
        vendor = "cisco"
        platform = "meraki"
        syntax = "..."
        example_output = ""
        fetched_at = "2026-07-11T00:00:00"

        def __init__(self, command):
            self.command = command

        @property
        def description(self):
            return f"Result for {self.command}"

        class citation:
            source_title = "Cisco DevNet MCP · Meraki-API-Doc-Search"   # SAME for both topics
            source_url = "https://developer.cisco.com/meraki/api"

    fake_source = MagicMock()
    fake_source.lookup.side_effect = lambda vendor, command, platform: FakeEntry(command)
    monkeypatch.setattr(cisco_devnet_source, "DevNetContentMCPSource", lambda: fake_source)

    summary = cisco_devnet_source.run(str(tmp_path), topics=[
        ("meraki dashboard API organizations", "meraki"),
        ("meraki switch port configuration API", "meraki"),
    ])
    assert summary["downloaded"] == 2
    saved_files = list((tmp_path / "cisco" / "configuration").glob("*.md"))
    assert len(saved_files) == 2, \
        f"expected 2 distinct files, got {[f.name for f in saved_files]} (a collision would leave only 1)"
    contents = {f.read_text() for f in saved_files}
    assert any("dashboard API organizations" in c for c in contents)
    assert any("switch port configuration API" in c for c in contents)


def test_cisco_devnet_source_handles_no_result_gracefully(tmp_path, monkeypatch):
    from core.knowledge.doc_downloader import cisco_devnet_source

    fake_source = MagicMock()
    fake_source.lookup.return_value = None
    monkeypatch.setattr(cisco_devnet_source, "DevNetContentMCPSource", lambda: fake_source)

    summary = cisco_devnet_source.run(str(tmp_path), topics=[("nonexistent topic", "meraki")])
    assert summary["downloaded"] == 0
    assert len(summary["errors"]) == 1


# ── versa_source: mocked HTTP, no real network ──────────────────────────
def test_versa_source_does_not_collide_when_two_pages_share_a_generic_title(tmp_path, monkeypatch):
    """Real bug caught in a live run: docs.versa-networks.com reuses
    generic page titles (e.g. "Installation - Versa Networks") across
    multiple, unrelated sections. Filename must be built from the page's
    own (inherently unique) sitemap path, not the title alone, or the
    second page's PDF silently overwrites the first's on disk."""
    from core.knowledge.doc_downloader import versa_source as v

    urls = [
        "https://docs.versa-networks.com/Getting_Started/Installation",
        "https://docs.versa-networks.com/Secure_SD-WAN/Installation",
    ]
    monkeypatch.setattr(v, "fetch_sitemap_urls", lambda limit=None: urls)
    monkeypatch.setattr(v, "_load_robots", lambda: object())
    monkeypatch.setattr(v, "_crawl_delay_of", lambda rp, default=5.0: 0.0)
    monkeypatch.setattr(v, "_can_fetch", lambda rp, url: True)
    monkeypatch.setattr(v.time, "sleep", lambda s: None)

    def fake_discover(page_url, session):
        # Both pages resolve to the SAME generic title, different page IDs.
        page_id = "100" if "Getting_Started" in page_url else "200"
        return (f"https://docs.versa-networks.com/@api/deki/pages/{page_id}/pdf/Installation.pdf",
               "Installation - Versa Networks")
    monkeypatch.setattr(v, "_discover_pdf_link", fake_discover)

    class FakeResp:
        status_code = 200
        content = b"%PDF-1.4 fake content"
    monkeypatch.setattr(v.requests, "Session", lambda: type(
        "S", (), {"get": staticmethod(lambda *a, **k: FakeResp())})())

    summary = v.run(str(tmp_path), limit=5)
    assert summary["downloaded"] == 2
    saved = list((tmp_path / "versa" / "configuration").glob("*.pdf"))
    assert len(saved) == 2, \
        f"expected 2 distinct files, got {[f.name for f in saved]} (a collision would leave only 1)"


def test_versa_source_skips_already_downloaded_urls(tmp_path, monkeypatch):
    from core.knowledge.doc_downloader import versa_source as v
    from core.knowledge.doc_downloader.manifest import DownloadManifest, ManifestEntry

    url = "https://docs.versa-networks.com/Getting_Started/Installation"
    manifest = DownloadManifest(str(tmp_path))
    manifest.record(ManifestEntry(source_url=url, vendor="versa", doc_type="configuration",
                                  title="Installation", local_path="x.pdf", sha256="h"))

    monkeypatch.setattr(v, "fetch_sitemap_urls", lambda limit=None: [url])
    monkeypatch.setattr(v, "_load_robots", lambda: object())
    monkeypatch.setattr(v, "_crawl_delay_of", lambda rp, default=5.0: 0.0)

    def _fail_if_called(rp, u):
        raise AssertionError("must not check robots.txt for an already-downloaded URL")
    monkeypatch.setattr(v, "_can_fetch", _fail_if_called)

    summary = v.run(str(tmp_path), limit=5)
    assert summary["skipped"] == 1
    assert summary["downloaded"] == 0


# ── fortinet_source: mocked HTTP, no real network ───────────────────────
def test_fortinet_source_downloads_and_classifies(tmp_path, monkeypatch):
    from core.knowledge.doc_downloader import fortinet_source as f

    seed = "https://docs.fortinet.com/product/fortigate/7.4.0"
    doc_url = "https://docs.fortinet.com/document/fortigate/7.4.0/cli-reference"

    monkeypatch.setattr(f, "_load_robots", lambda: object())
    monkeypatch.setattr(f, "_crawl_delay_of", lambda rp, default=2.0: 0.0)
    monkeypatch.setattr(f, "_can_fetch", lambda rp, url: True)
    monkeypatch.setattr(f.time, "sleep", lambda s: None)
    monkeypatch.setattr(f, "_discover_doc_links", lambda seed_url, session: [doc_url])
    monkeypatch.setattr(f, "_discover_pdf_link", lambda url, session: (
        "https://fortinetweb.s3.amazonaws.com/docs.fortinet.com/v2/attachments/x/FortiOS-7.4.0-CLI_Reference.pdf",
        "CLI Reference"))

    class FakeResp:
        status_code = 200
        content = b"%PDF-1.4 fake"
    monkeypatch.setattr(f.requests, "Session", lambda: type(
        "S", (), {"get": staticmethod(lambda *a, **k: FakeResp())})())

    summary = f.run(str(tmp_path), limit=5, seed_pages=[seed])
    assert summary["downloaded"] == 1
    saved = list((tmp_path / "fortinet" / "command_reference").glob("*.pdf"))
    assert len(saved) == 1


def test_fortinet_source_does_not_collide_on_shared_title(tmp_path, monkeypatch):
    """Same class of bug fixed in versa_source.py and
    cisco_devnet_source.py: two different doc pages must not collide into
    one file just because they render the same <title>."""
    from core.knowledge.doc_downloader import fortinet_source as f

    urls = [
        "https://docs.fortinet.com/document/fortigate/7.4.0/administration-guide",
        "https://docs.fortinet.com/document/fortimanager/7.4.0/administration-guide",
    ]
    monkeypatch.setattr(f, "_load_robots", lambda: object())
    monkeypatch.setattr(f, "_crawl_delay_of", lambda rp, default=2.0: 0.0)
    monkeypatch.setattr(f, "_can_fetch", lambda rp, url: True)
    monkeypatch.setattr(f.time, "sleep", lambda s: None)
    monkeypatch.setattr(f, "_discover_doc_links", lambda seed_url, session: urls)
    monkeypatch.setattr(f, "_discover_pdf_link", lambda url, session: (
        f"https://fortinetweb.s3.amazonaws.com/docs.fortinet.com/v2/attachments/{hash(url)}/Administration_Guide.pdf",
        "Administration Guide"))   # SAME generic title for both

    class FakeResp:
        status_code = 200
        content = b"%PDF-1.4 fake"
    monkeypatch.setattr(f.requests, "Session", lambda: type(
        "S", (), {"get": staticmethod(lambda *a, **k: FakeResp())})())

    summary = f.run(str(tmp_path), limit=5, seed_pages=["https://docs.fortinet.com/product/fortigate/7.4.0"])
    assert summary["downloaded"] == 2
    saved = list((tmp_path / "fortinet" / "configuration").glob("*.pdf"))
    assert len(saved) == 2, f"expected 2 distinct files, got {[p.name for p in saved]}"


# ── rfc_source: mocked fetcher, no real network ─────────────────────────
def test_rfc_source_downloads_and_dedups(tmp_path, monkeypatch):
    from core.knowledge.doc_downloader import rfc_source as r

    def fake_fetch(number):
        return {"title": f"RFC {number} Fake Title", "content": f"body of rfc {number}"}
    monkeypatch.setattr(r, "fetch_rfc_text", fake_fetch)

    summary = r.run(str(tmp_path), rfc_numbers=[2328, 4271])
    assert summary["downloaded"] == 2
    assert (tmp_path / "rfc" / "rfc2328.txt").read_text() == "body of rfc 2328"
    assert (tmp_path / "rfc" / "rfc4271.txt").read_text() == "body of rfc 4271"

    summary2 = r.run(str(tmp_path), rfc_numbers=[2328, 4271])
    assert summary2["skipped"] == 2
    assert summary2["downloaded"] == 0


def test_rfc_source_handles_fetch_failure_gracefully(tmp_path, monkeypatch):
    from core.knowledge.doc_downloader import rfc_source as r

    monkeypatch.setattr(r, "fetch_rfc_text", lambda number: None)
    summary = r.run(str(tmp_path), rfc_numbers=[999999])
    assert summary["downloaded"] == 0
    assert len(summary["errors"]) == 1
