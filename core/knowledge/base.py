"""
core/knowledge/base.py
======================
Foundation for the AI Net Studio Knowledge System.

Defines the data contracts every layer uses:
  - Citation        : provenance metadata (source, URL, confidence)
  - KnowledgeEntry  : one piece of knowledge (command + syntax + examples)
  - ConfidenceLevel : HIGH / MEDIUM / LOW / UNVERIFIED
  - KnowledgeSource : abstract base for any source (cache, web, RAG, MCP later)
"""
from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit, urlunsplit


def normalize_document_url(url: str) -> str:
    """TODAY's default strategy for computing KnowledgeEntry.source_doc_id
    (see that field's docstring for the abstraction this backs) — not the
    definition of canonical identity itself, just the only signal a
    generic web fetcher can rely on right now. Strips query string,
    fragment, and trailing slash, lowercases scheme+host, so two URLs
    differing only in a tracking parameter or a #anchor resolve to the
    SAME id; a different path is a genuinely different one.

    This strategy has a known, accepted limitation: if a vendor moves a
    page to a new URL, this treats it as a brand-new document (loses
    continuity) rather than recognizing it as the same one revised — the
    tradeoff was accepted because URL identity is the only thing
    available today, not because it's the right long-term answer. A
    future vendor-doc-ID- or semantic-identity-based strategy (see
    source_doc_id's docstring) would close that gap without needing any
    caller of this function to change."""
    if not url:
        return ""
    parts = urlsplit(url)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, "", ""))

logger = logging.getLogger("AI Net Studio.Knowledge")


# ═══════════════════════════════════════════════════════════════════════════════
# Confidence levels
# ═══════════════════════════════════════════════════════════════════════════════

class ConfidenceLevel(str, Enum):
    """How much we trust a piece of knowledge."""

    HIGH       = "high"          # Verified against vendor official docs
    MEDIUM     = "medium"        # From local cache, may be slightly stale
    LOW        = "low"           # AI-generated but partial verification
    UNVERIFIED = "unverified"    # AI training data only — could be hallucinated

    @property
    def badge(self) -> str:
        return {
            "high":       "🟢 Verified",
            "medium":     "🔵 Cached",
            "low":        "🟡 Partial",
            "unverified": "⚠️ AI Guess",
        }[self.value]

    @property
    def color(self) -> str:
        return {
            "high":       "#16a34a",
            "medium":     "#0ea5e9",
            "low":        "#eab308",
            "unverified": "#f97316",
        }[self.value]


# ═══════════════════════════════════════════════════════════════════════════════
# Citation
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Citation:
    """Provenance — where did this knowledge come from?"""

    source_name:   str = ""                       # 'cisco_fetcher', 'local_cache', 'ai_only'
    source_type:   str = ""                       # 'cache', 'web', 'rag', 'training'
    source_url:    Optional[str] = None           # actual URL if web-fetched
    source_title:  Optional[str] = None           # page title or doc name
    vendor:        Optional[str] = None           # 'cisco', 'juniper', etc.
    confidence:    ConfidenceLevel = ConfidenceLevel.UNVERIFIED
    fetched_at:    Optional[str] = None           # ISO timestamp
    notes:         str = ""                       # any additional context

    def to_markdown_badge(self) -> str:
        """Render as a compact markdown badge with optional URL."""
        badge = f"{self.confidence.badge}"
        if self.source_url and self.source_title:
            return f"{badge} · [{self.source_title}]({self.source_url})"
        if self.source_url:
            return f"{badge} · [{self.source_name}]({self.source_url})"
        if self.notes:
            return f"{badge} · {self.notes}"
        return f"{badge} · {self.source_name}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_name":  self.source_name,
            "source_type":  self.source_type,
            "source_url":   self.source_url,
            "source_title": self.source_title,
            "vendor":       self.vendor,
            "confidence":   self.confidence.value,
            "fetched_at":   self.fetched_at,
            "notes":        self.notes,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# KnowledgeEntry — one command's documentation
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class KnowledgeEntry:
    """One piece of verified network knowledge — a command and its context."""

    vendor:         str = ""                          # 'cisco', 'juniper', etc.
    platform:       str = ""                          # 'ios-xe', 'nx-os', 'junos'
    command:        str = ""                          # canonical command (e.g. 'show ip ospf neighbor')
    syntax:         str = ""                          # full syntax with options
    description:    str = ""                          # what it does
    example_output: str = ""                          # sample output (optional)
    min_version:    str = ""                          # e.g. 'IOS-XE 17.0'
    citation:       Citation = field(default_factory=Citation)
    fetched_at:     str = field(default_factory=lambda: datetime.utcnow().isoformat())
    verified_at:    str = field(default_factory=lambda: datetime.utcnow().isoformat())
    ttl_days:       int = 90
    hit_count:      int = 0
    # sha256 over the actual knowledge content (not citation/timestamps) —
    # lets a refresh compare "did the real content change" before
    # re-persisting/re-embedding it, instead of always treating a
    # re-fetch as new knowledge. Auto-computed in __post_init__ when not
    # explicitly supplied, so every construction path (fetch(), the new
    # Tavily ingestion pipeline, DB row reconstruction, the unverified()
    # fallback) gets one for free with no call-site changes.
    content_hash:   str = ""
    # An ABSTRACTION, deliberately: "the stable identity of the real-world
    # document this entry came from" — not "a normalized URL". Whatever
    # computes it just has to be internally consistent (same real
    # document -> same id, different real documents -> different ids);
    # nothing downstream (content_hash comparison scoping in
    # KnowledgeOrchestrator._persist_fetch_result, cache persistence)
    # inspects its shape or assumes it's URL-derived.
    #
    # normalize_document_url() is TODAY's default, used only because it's
    # the one signal every generic web fetcher already has. Two concrete
    # upgrade paths this field was designed to absorb without a rename or
    # a migration, whenever a source can supply something better:
    #   - a real vendor document ID (e.g. a KB/KCS article id, a doc-set
    #     + revision number) — survives the vendor moving the page to a
    #     new URL, which today's URL-based default cannot.
    #   - a semantic identity ("cisco:ios-xe:show ip ospf neighbor:
    #     command-reference") for sources with no stable URL or doc ID at
    #     all, keyed on what the knowledge is ABOUT rather than where it
    #     currently lives.
    # A caller that has one of these just passes source_doc_id= explicitly
    # at construction time — __post_init__ below only fills in the URL-
    # based default when the field is left empty, so this override path
    # already exists today with no code changes needed.
    source_doc_id:  str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = self.compute_content_hash()
        if not self.source_doc_id:
            # Default/fallback strategy only -- see source_doc_id's own
            # docstring above for why this isn't the permanent definition
            # of canonical identity.
            self.source_doc_id = normalize_document_url(self.citation.source_url or "")

    def compute_content_hash(self) -> str:
        basis = f"{self.syntax}\n{self.description}\n{self.example_output}".strip()
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()

    def is_stale(self) -> bool:
        """Check if this entry has exceeded its TTL."""
        try:
            verified = datetime.fromisoformat(self.verified_at)
            return (datetime.utcnow() - verified) > timedelta(days=self.ttl_days)
        except Exception:
            return True

    def age_days(self) -> int:
        """How old (in days) since last verification."""
        try:
            verified = datetime.fromisoformat(self.verified_at)
            return (datetime.utcnow() - verified).days
        except Exception:
            return 9999

    @classmethod
    def unverified(cls, vendor: str, command: str, reason: str = "") -> "KnowledgeEntry":
        """Build an UNVERIFIED entry for fallback (AI guess only, no source)."""
        return cls(
            vendor=vendor,
            command=command,
            description="(unverified — AI guess, no source found)",
            citation=Citation(
                source_name="ai_training_data",
                source_type="training",
                vendor=vendor,
                confidence=ConfidenceLevel.UNVERIFIED,
                notes=reason or "No documentation source available",
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "vendor":         self.vendor,
            "platform":       self.platform,
            "command":        self.command,
            "syntax":         self.syntax,
            "description":    self.description,
            "example_output": self.example_output,
            "min_version":    self.min_version,
            "citation":       self.citation.to_dict(),
            "fetched_at":     self.fetched_at,
            "verified_at":    self.verified_at,
            "ttl_days":       self.ttl_days,
            "hit_count":      self.hit_count,
            "content_hash":   self.content_hash,
            "source_doc_id":  self.source_doc_id,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Abstract KnowledgeSource
# ═══════════════════════════════════════════════════════════════════════════════

class KnowledgeSource(ABC):
    """
    Every source (cache, web fetcher, RAG, MCP later) implements this contract.
    Lets us swap or add sources without touching the orchestrator.
    """

    source_name: str = "abstract"
    source_type: str = "abstract"

    @abstractmethod
    def lookup(
        self,
        vendor: str,
        command: str,
        platform: Optional[str] = None,
    ) -> Optional[KnowledgeEntry]:
        """Return a KnowledgeEntry or None if not found."""
        raise NotImplementedError

    @abstractmethod
    def supports_vendor(self, vendor: str) -> bool:
        """Does this source have data for this vendor?"""
        raise NotImplementedError

    @property
    def priority(self) -> int:
        """Lower = checked first. Cache=10, web fetchers=50, AI fallback=99."""
        return 50

    def health_check(self) -> Dict[str, Any]:
        """Optional — report status of this source."""
        return {"name": self.source_name, "type": self.source_type, "ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# Vendor normalization helpers
# ═══════════════════════════════════════════════════════════════════════════════

NETMIKO_TO_VENDOR: Dict[str, str] = {
    "cisco_ios":       "cisco",
    "cisco_ios_xe":    "cisco",
    "cisco_xe":        "cisco",
    "cisco_nxos":      "cisco",
    "cisco_asa":       "cisco",
    "cisco_ftd":       "cisco",
    "cisco_xr":        "cisco",
    "juniper":         "juniper",
    "juniper_junos":   "juniper",
    "arista_eos":      "arista",
    "paloalto_panos":  "paloalto",
    "fortinet":        "fortinet",
    "fortinet_fortios":"fortinet",
    "huawei":          "huawei",
    "huawei_vrpv8":    "huawei",
    "aruba_os":        "aruba",
    "hp_procurve":     "aruba",
    "hp_comware":      "huawei",
    "checkpoint_gaia": "checkpoint",
    "dell_os10":       "dell",
    "dell_os9":        "dell",
    "dell_force10":    "dell",
    "dell_powerconnect": "dell",
    "extreme":         "extreme",
    "extreme_exos":    "extreme",
    "extreme_vsp":     "extreme",
    "extreme_slx":     "extreme",
}


def detect_vendor(device_type: Optional[str]) -> str:
    """Map a Netmiko device_type to a canonical vendor key."""
    if not device_type:
        return "unknown"
    return NETMIKO_TO_VENDOR.get(device_type.lower(), "unknown")


def detect_platform(device_type: Optional[str]) -> str:
    """Map a Netmiko device_type to a canonical platform key."""
    if not device_type:
        return "unknown"
    dt = device_type.lower()
    mapping = {
        "cisco_ios":       "ios",
        "cisco_ios_xe":    "ios-xe",
        "cisco_xe":        "ios-xe",
        "cisco_nxos":      "nx-os",
        "cisco_asa":       "asa",
        "cisco_xr":        "ios-xr",
        "cisco_ftd":       "ftd",
        "juniper":         "junos",
        "juniper_junos":   "junos",
        "arista_eos":      "eos",
        "paloalto_panos":  "panos",
        "fortinet":        "fortios",
        "huawei":          "vrp",
        "huawei_vrpv8":    "vrp",
        "aruba_os":        "arubaos",
        "checkpoint_gaia": "gaia",
        "dell_os10":       "os10",
        "dell_os9":        "os9",
        "dell_force10":    "ftos",
        "extreme_exos":    "exos",
        "extreme_vsp":     "voss",
    }
    return mapping.get(dt, dt)
