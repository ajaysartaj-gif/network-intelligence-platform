"""
core/knowledge/doc_downloader/paloalto_source.py
=================================================
Downloads real documentation from pan.dev — Palo Alto Networks' actual
developer documentation site (Docusaurus-based), found during a follow-up
evaluation. Deliberately NOT the same site as paloaltonetworks.com
(disallows its own real content paths) or live.paloaltonetworks.com
(returns 403) — pan.dev is a different subdomain, a real, modern API/SDK
docs portal with its own sitemap and no robots.txt at all (a 404 on
/robots.txt, the standard "no restrictions declared" case, same as
treating an absent robots.txt as permissive anywhere else).

No PDF export feature exists here (unlike Versa's MindTouch portal) — each
page's real content lives in a static <article> element, confirmed
directly against a real page. Saved as markdown, same honest labeling
already used for Cisco's DevNet MCP content: this is real, substantive
API/config documentation, just not a scanned/authored PDF file.
"""
from __future__ import annotations

import hashlib
import logging
import os
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

try:
    from bs4 import BeautifulSoup
    BS4_OK = True
except ImportError:
    BS4_OK = False

logger = logging.getLogger("NetBrain.Knowledge.DocDownloader.PaloAlto")

BASE_URL = "https://pan.dev"
SITEMAP_URL = f"{BASE_URL}/sitemap.xml"
USER_AGENT = "Mozilla/5.0 (compatible; NetworkIntelligencePlatform-DocBot/1.0; +respectful, low-volume, robots.txt-compliant)"

# pan.dev's sitemap covers many product lines (Prisma Access, Terraform,
# Strata Cloud Manager, SD-WAN, ...) — narrowed to paths under network
# security / firewall-relevant sections, matching this tool's actual scope,
# rather than pulling in every SDK/Terraform-provider page indiscriminately.
DEFAULT_PATH_FILTERS = ("/swfw/", "/access/", "/terraform/panos/")


def _load_robots() -> urllib.robotparser.RobotFileParser:
    """Same pattern as versa_source/fortinet_source: fetched via `requests`
    to avoid RobotFileParser.read()'s own urllib.request SSL issue in this
    environment. pan.dev has no robots.txt at all (confirmed: 404) — the
    standard "no restrictions declared" case, treated as open exactly like
    an absent robots.txt is treated anywhere else on the web."""
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(f"{BASE_URL}/robots.txt")
    if REQUESTS_OK:
        try:
            resp = requests.get(f"{BASE_URL}/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=15)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp.allow_all = True   # no robots.txt published -> no restriction declared
        except Exception:
            rp.allow_all = True
    else:
        rp.allow_all = True
    return rp


def _can_fetch(rp: urllib.robotparser.RobotFileParser, url: str) -> bool:
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def fetch_sitemap_urls(path_filters: Optional[List[str]] = None) -> List[str]:
    if not REQUESTS_OK:
        return []
    resp = requests.get(SITEMAP_URL, headers={"User-Agent": USER_AGENT}, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text]
    if path_filters:
        urls = [u for u in urls if any(f in u for f in path_filters)]
    return urls


def _extract_article(html: str) -> Optional[tuple]:
    """Returns (title, text) from the page's <article> content, or None
    if bs4 isn't available or no article element is present."""
    if not BS4_OK:
        return None
    soup = BeautifulSoup(html, "html.parser")
    article = soup.find("article")
    if not article:
        return None
    title_tag = soup.find("title")
    h1 = article.find("h1")
    title = (h1.get_text(strip=True) if h1 else
            title_tag.get_text(strip=True) if title_tag else "Untitled")
    text = article.get_text("\n", strip=True)
    return title, text


def run(out_root: str, limit: int = 20, path_filters: Optional[List[str]] = None) -> dict:
    """Downloads up to `limit` pages from pan.dev into
    out_root/paloalto/<doc_type>/ as markdown. Bounded by default."""
    summary = {"vendor": "paloalto", "downloaded": 0, "skipped": 0, "errors": []}
    if not REQUESTS_OK:
        summary["errors"].append("requests package not available")
        return summary
    if not BS4_OK:
        summary["errors"].append("beautifulsoup4 package not available")
        return summary

    manifest = DownloadManifest(out_root)
    rp = _load_robots()
    session = requests.Session()

    try:
        urls = fetch_sitemap_urls(path_filters if path_filters is not None else list(DEFAULT_PATH_FILTERS))
    except Exception as exc:
        summary["errors"].append(f"sitemap fetch failed: {exc}")
        return summary

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
            resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
            time.sleep(1.0)   # no crawl-delay declared; still pace requests
            if resp.status_code != 200:
                summary["errors"].append(f"{url}: HTTP {resp.status_code}")
                continue
            extracted = _extract_article(resp.text)
            if not extracted:
                continue
            title, text = extracted
            if not text.strip():
                continue

            doc_type = classify_doc_type(title=title, path=url)
            dest_dir = os.path.join(out_root, "paloalto", doc_type)
            os.makedirs(dest_dir, exist_ok=True)
            url_tag = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
            filename = safe_filename(f"{title}_{url_tag}", fallback=f"paloalto_doc_{attempted}_{url_tag}", ext=".md")
            dest_path = os.path.join(dest_dir, filename)
            content = f"# {title}\n\nSource: {url}\n\n{text}\n"
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(content)

            sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
            manifest.record(ManifestEntry(
                source_url=url, vendor="paloalto", doc_type=doc_type,
                title=title, local_path=dest_path, sha256=sha256))
            summary["downloaded"] += 1
            logger.info("Downloaded [%s] %s -> %s", doc_type, title, dest_path)
        except Exception as exc:
            summary["errors"].append(f"{url}: {exc}")
    return summary
