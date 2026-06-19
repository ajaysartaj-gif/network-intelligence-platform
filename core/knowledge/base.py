"""
core/knowledge/base.py
======================
Foundation for the NetBrain Knowledge System.

Defines the data contracts every layer uses:
  - Citation        : provenance metadata (source, URL, confidence)
  - KnowledgeEntry  : one piece of knowledge (command + syntax + examples)
  - ConfidenceLevel : HIGH / MEDIUM / LOW / UNVERIFIED
  - KnowledgeSource : abstract base for any source (cache, web, RAG, MCP later)
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("NetBrain.Knowledge")


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
    }
    return mapping.get(dt, dt)
