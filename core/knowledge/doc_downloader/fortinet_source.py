"""
core/knowledge/doc_downloader/fortinet_source.py
=================================================
Downloads real PDFs from docs.fortinet.com — found genuinely open during
evaluation: its own robots.txt has no blanket "Disallow: /" for unnamed
agents (only a handful of specific archived-product paths and dynamic
query-string URLs are excluded, plus three named crawlers explicitly
blocked), and declares Crawl-delay: 2. Confirmed directly against real
pages: every guide page embeds a direct, S3-hosted "Download PDF" link
(fortinetweb.s3.amazonaws.com/docs.fortinet.com/v2/attachments/.../*.pdf)
— a feature the site provides to any visitor, not a reconstructed URL.

No sitemap.xml is published for this subdomain (unlike Versa), so this
module seeds from each product's own listing page (e.g.
/product/fortigate/7.4.0), which links out to every guide under that
product/version — the same page a human visitor would browse from.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
import urllib.robotparser
from typing import List, Optional

from core.knowledge.doc_downloader.classify import classify_doc_type, safe_filename
from core.knowledge.doc_downloader.manifest import DownloadManifest, ManifestEntry

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

logger = logging.getLogger("AI Net Studio.Knowledge.DocDownloader.Fortinet")

BASE_URL = "https://docs.fortinet.com"
USER_AGENT = "Mozilla/5.0 (compatible; NetworkIntelligencePlatform-DocBot/1.0; +respectful, low-volume, robots.txt-compliant)"

# Seed product/version listing pages — each links out to every guide under
# it (administration guide, CLI reference, best practices, ...). Kept
# small and explicit rather than attempting to enumerate Fortinet's
# entire product catalogue on a first pass.
DEFAULT_SEED_PAGES = [
    f"{BASE_URL}/product/fortigate/7.4.0",
    f"{BASE_URL}/product/fortimanager/7.4.0",
]

_DOC_LINK_RE = re.compile(r'href="(/document/[^"]+)"', re.I)
_PDF_LINK_RE = re.compile(r'href="([^"]*fortinetweb\.s3\.amazonaws\.com[^"]*\.pdf)"', re.I)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.I)


def _load_robots() -> urllib.robotparser.RobotFileParser:
    """Same approach as versa_source._load_robots(): fetched via `requests`
    (not RobotFileParser.read()'s own urllib.request, which fails on an
    SSL certificate error in this environment) and parsed once per run."""
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
                rp.allow_all = True
        except Exception:
            rp.allow_all = True
    else:
        rp.allow_all = True
    return rp


def _crawl_delay_of(rp: urllib.robotparser.RobotFileParser, default: float = 2.0) -> float:
    try:
        delay = rp.crawl_delay(USER_AGENT) or rp.crawl_delay("*")
        return float(delay) if delay else default
    except Exception:
        return default


def _can_fetch(rp: urllib.robotparser.RobotFileParser, url: str) -> bool:
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _discover_doc_links(seed_url: str, session: "requests.Session") -> List[str]:
    resp = session.get(seed_url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if resp.status_code != 200:
        return []
    paths = sorted(set(_DOC_LINK_RE.findall(resp.text)))
    return [p if p.startswith("http") else f"{BASE_URL}{p}" for p in paths]


def _discover_pdf_link(doc_url: str, session: "requests.Session") -> Optional[tuple]:
    resp = session.get(doc_url, headers={"User-Agent": USER_AGENT}, timeout=20)
    if resp.status_code != 200:
        return None
    m = _PDF_LINK_RE.search(resp.text)
    if not m:
        return None
    title_m = _TITLE_RE.search(resp.text)
    title = title_m.group(1).strip() if title_m else doc_url.rsplit("/", 1)[-1]
    return m.group(1), title


def run(out_root: str, limit: int = 20, seed_pages: Optional[List[str]] = None) -> dict:
    """Downloads up to `limit` PDFs from docs.fortinet.com into
    out_root/fortinet/<doc_type>/. Bounded by default — same "prove it in
    a small batch first" discipline as versa_source.run()."""
    summary = {"vendor": "fortinet", "downloaded": 0, "skipped": 0, "errors": []}
    if not REQUESTS_OK:
        summary["errors"].append("requests package not available")
        return summary

    manifest = DownloadManifest(out_root)
    rp = _load_robots()
    crawl_delay = _crawl_delay_of(rp)
    logger.info("Fortinet crawl-delay from robots.txt: %.1fs", crawl_delay)

    session = requests.Session()
    seed_pages = seed_pages if seed_pages is not None else DEFAULT_SEED_PAGES

    doc_urls: List[str] = []
    for seed in seed_pages:
        if not _can_fetch(rp, seed):
            continue
        try:
            doc_urls.extend(_discover_doc_links(seed, session))
            time.sleep(crawl_delay)
        except Exception as exc:
            summary["errors"].append(f"{seed}: {exc}")
    doc_urls = sorted(set(doc_urls))

    attempted = 0
    for url in doc_urls:
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
            dest_dir = os.path.join(out_root, "fortinet", doc_type)
            os.makedirs(dest_dir, exist_ok=True)
            # Same fix already applied to versa_source.py: a short hash of
            # the page's own unique URL guarantees a distinct filename
            # even if two guides happen to render the same <title>.
            url_tag = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
            filename = safe_filename(f"{title}_{url_tag}", fallback=f"fortinet_doc_{attempted}_{url_tag}")
            dest_path = os.path.join(dest_dir, filename)
            with open(dest_path, "wb") as f:
                f.write(pdf_resp.content)
            sha256 = hashlib.sha256(pdf_resp.content).hexdigest()
            manifest.record(ManifestEntry(
                source_url=url, vendor="fortinet", doc_type=doc_type,
                title=title, local_path=dest_path, sha256=sha256))
            summary["downloaded"] += 1
            logger.info("Downloaded [%s] %s -> %s", doc_type, title, dest_path)
        except Exception as exc:
            summary["errors"].append(f"{url}: {exc}")
    return summary
