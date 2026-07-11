"""
core/knowledge/doc_downloader/versa_source.py
==============================================
Downloads real PDFs from docs.versa-networks.com — the one sample site
that turned out to be genuinely, openly crawlable: its robots.txt
explicitly declares a Crawl-delay, publishes a sitemap, and Allows its own
file-attachment endpoint (/@api/deki/files/). This module honors all of
that: robots.txt is parsed (not assumed), the declared crawl-delay is
slept between every request, and only URLs the sitemap itself lists are
visited.

Every page on this MindTouch/NiCE-based portal renders its own "Save as
PDF" export link (/@api/deki/pages/<id>/pdf/<title>.pdf) — a feature the
site provides to any visitor, not a hidden or reconstructed URL. This
module fetches that page, extracts that exact link, and downloads it.
Nothing here bypasses anything the site doesn't already offer for free.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import urllib.robotparser
from typing import List, Optional
from xml.etree import ElementTree as ET

from core.knowledge.doc_downloader.classify import classify_doc_type, safe_filename
from core.knowledge.doc_downloader.manifest import DownloadManifest, ManifestEntry

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

logger = logging.getLogger("NetBrain.Knowledge.DocDownloader.Versa")

BASE_URL = "https://docs.versa-networks.com"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
USER_AGENT = "Mozilla/5.0 (compatible; NetworkIntelligencePlatform-DocBot/1.0; +respectful, low-volume, robots.txt-compliant)"

_PDF_LINK_RE = re.compile(r'href="([^"]*@api/deki/pages/\d+/pdf/[^"]+\.pdf[^"]*)"', re.I)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.I)


def _load_robots() -> urllib.robotparser.RobotFileParser:
    """Fetched and parsed exactly ONCE per run() call, then reused for
    every URL checked — the original per-URL version re-fetched robots.txt
    on every single call, including for URLs skipped via the manifest,
    which meant a re-run that skips through hundreds of already-downloaded
    entries was issuing hundreds of redundant robots.txt requests to be
    "polite" about a decision it had already made the first time.

    Deliberately does NOT use RobotFileParser.read() — verified directly
    that it uses bare urllib.request, which fails with an SSL certificate
    verification error in this environment (unrelated to the site: plain
    urllib doesn't pick up the same CA bundle the `requests` package
    does). RobotFileParser.read() only catches urllib.error.HTTPError
    internally, so that SSL failure propagated as a raw exception — caught
    by a blanket except here, but that silently left the parser in its
    NEVER-SUCCESSFULLY-READ state, which RobotFileParser.can_fetch() itself
    then interprets as deny-everything (it checks self.last_checked,
    which read() only sets on a successful parse) — the exact opposite of
    the "fail open" this module intends, and a real bug caught in a live
    run (every URL silently started reporting can_fetch()==False after
    this function was refactored to run once per call instead of once per
    URL). Fetching the text via `requests` (already proven working
    throughout this module) and feeding it to rp.parse() directly sidesteps
    the SSL issue entirely."""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{BASE_URL}/robots.txt")
    if REQUESTS_OK:
        try:
            resp = requests.get(f"{BASE_URL}/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=15)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            elif resp.status_code in (401, 403):
                rp.disallow_all = True
            else:
                rp.allow_all = True   # matches RobotFileParser.read()'s own 4xx handling
        except Exception:
            rp.allow_all = True   # fail OPEN on a genuine fetch error — this site's own
                                  # robots.txt is permissive; a transient local failure
                                  # to confirm that is not grounds to assume denial
    else:
        rp.allow_all = True
    return rp


def _crawl_delay_of(rp: urllib.robotparser.RobotFileParser, default: float = 5.0) -> float:
    try:
        delay = rp.crawl_delay(USER_AGENT) or rp.crawl_delay("*")
        return float(delay) if delay else default
    except Exception:
        return default


def _can_fetch(rp: urllib.robotparser.RobotFileParser, url: str) -> bool:
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True   # fail open on a robots.txt read error, not closed — matches
                       # the site's own permissive posture rather than assuming denial


def fetch_sitemap_urls(limit: Optional[int] = None) -> List[str]:
    if not REQUESTS_OK:
        return []
    resp = requests.get(SITEMAP_URL, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]
    return urls[:limit] if limit else urls


def _discover_pdf_link(page_url: str, session: "requests.Session") -> Optional[tuple]:
    """Returns (pdf_url, page_title) if this page's own PDF export link is
    found, else None."""
    resp = session.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if resp.status_code != 200:
        return None
    text = resp.text
    m = _PDF_LINK_RE.search(text)
    if not m:
        return None
    pdf_path = m.group(1)
    pdf_url = pdf_path if pdf_path.startswith("http") else f"{BASE_URL}/{pdf_path.lstrip('/')}"
    title_m = _TITLE_RE.search(text)
    title = title_m.group(1).strip() if title_m else page_url.rsplit("/", 1)[-1]
    return pdf_url, title


def run(out_root: str, limit: int = 20) -> dict:
    """Downloads up to `limit` PDFs from docs.versa-networks.com into
    out_root/versa/<doc_type>/, deduped against the shared manifest.
    Deliberately bounded by default — this is a new capability being run
    for the first time; a small proven batch first, a larger run only by
    deliberately raising `limit`, never an unbounded full-site crawl by
    default."""
    summary = {"vendor": "versa", "downloaded": 0, "skipped": 0, "errors": []}
    if not REQUESTS_OK:
        summary["errors"].append("requests package not available")
        return summary

    manifest = DownloadManifest(out_root)
    rp = _load_robots()
    crawl_delay = _crawl_delay_of(rp)
    logger.info("Versa crawl-delay from robots.txt: %.1fs", crawl_delay)

    try:
        urls = fetch_sitemap_urls()
    except Exception as exc:
        summary["errors"].append(f"sitemap fetch failed: {exc}")
        return summary

    session = requests.Session()
    attempted = 0
    for url in urls:
        if attempted >= limit:
            break
        if manifest.has(url):
            summary["skipped"] += 1
            continue
        if not _can_fetch(rp, url):
            continue
        attempted += 1
        try:
            found = _discover_pdf_link(url, session)
            time.sleep(crawl_delay)
            if not found:
                continue
            pdf_url, title = found
            pdf_resp = session.get(pdf_url, headers={"User-Agent": USER_AGENT}, timeout=30)
            time.sleep(crawl_delay)
            if pdf_resp.status_code != 200 or not pdf_resp.content:
                summary["errors"].append(f"{pdf_url}: HTTP {pdf_resp.status_code}")
                continue
            doc_type = classify_doc_type(title=title, path=url)
            dest_dir = os.path.join(out_root, "versa", doc_type)
            os.makedirs(dest_dir, exist_ok=True)
            # Filename includes a short hash of the URL, not just the page
            # title — caught in a real run: this portal reuses generic
            # titles like "Installation - Versa Networks" across multiple,
            # unrelated sections, so title alone collided and the second
            # page's download silently overwrote the first's (same class
            # of bug fixed in cisco_devnet_source.py). The full URL path
            # is inherently unique per page; an 8-char hash of it keeps
            # that uniqueness guarantee without the unreadably long
            # full-path-as-filename this used before.
            url_tag = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
            filename = safe_filename(f"{title}_{url_tag}", fallback=f"versa_doc_{attempted}_{url_tag}")
            dest_path = os.path.join(dest_dir, filename)
            with open(dest_path, "wb") as f:
                f.write(pdf_resp.content)
            sha256 = hashlib.sha256(pdf_resp.content).hexdigest()
            manifest.record(ManifestEntry(
                source_url=url, vendor="versa", doc_type=doc_type,
                title=title, local_path=dest_path, sha256=sha256))
            summary["downloaded"] += 1
            logger.info("Downloaded [%s] %s -> %s", doc_type, title, dest_path)
        except Exception as exc:
            summary["errors"].append(f"{url}: {exc}")
    return summary
