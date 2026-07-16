"""
core/knowledge/mcp/devnet_content_source.py
===========================================
DevNet Content Search MCP — official Cisco-hosted MCP server.

Endpoint:  https://devnet.cisco.com/v1/foundation-search-mcp/mcp
Auth:      None required (free, hosted by Cisco)
Coverage:  Cisco Meraki APIs, Cisco Catalyst Center APIs (growing)

Used as a FALLBACK source — only invoked when the vendor web fetchers
return nothing useful. Web fetchers are still preferred because:
  - they cover IOS classic, NX-OS, ASA, IOS-XR (broader scope)
  - they return parsed syntax + descriptions in our cache format

The DevNet MCP fills the gap for Meraki + Catalyst Center programmability.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.knowledge.base import (
    Citation,
    ConfidenceLevel,
    KnowledgeEntry,
    KnowledgeSource,
)
from core.knowledge.cache.ttl_policy import get_ttl
from core.knowledge.mcp.mcp_client import MCPHttpClient

logger = logging.getLogger("AI Net Studio.Knowledge.MCP.DevNet")

# Generic words that appear in almost any troubleshooting question or almost
# any API-doc blurb; excluded from the relevance-overlap check below so a
# match on "is"/"not"/"up" alone can't count as evidence of topical overlap.
_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "to", "of", "in", "on", "for", "and", "or", "not", "no", "with",
    "why", "what", "how", "when", "where", "which", "do", "does", "did",
    "up", "down", "it", "its", "this", "that", "these", "those", "as",
    "at", "by", "from", "into", "than", "then", "so", "but", "if",
}


def _content_tokens(text: str) -> set:
    """Lowercased alphanumeric tokens, minus stopwords -- same tokenizer
    style as core.knowledge.enterprise.knowledge_layer._tokens(), applied
    here to compare a query against a result's own title/description."""
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
            if t not in _STOPWORDS and len(t) > 1}


class DevNetContentMCPSource(KnowledgeSource):
    """
    KnowledgeSource backed by Cisco's DevNet Content Search MCP server.
    """

    source_name = "devnet_content_mcp"
    source_type = "mcp"

    ENDPOINT_URL = "https://devnet.cisco.com/v1/foundation-search-mcp/mcp"
    SUPPORTED_VENDORS = {"cisco"}   # MCP currently scopes to Cisco platforms

    # Tool names exposed by this MCP (may evolve — we discover at runtime)
    KNOWN_TOOL_HINTS = [
        "meraki", "catalyst", "search", "api", "lookup",
    ]

    @property
    def priority(self) -> int:
        # Lower priority than web fetchers (which are 50);
        # MCP runs AFTER fetchers since you want fetchers first.
        return 70

    def __init__(self):
        self._client: Optional[MCPHttpClient] = None
        self._tools_cache: List = []
        self._reachable: Optional[bool] = None

    # ── KnowledgeSource interface ─────────────────────────────────────────────

    # This MCP's ENTIRE content coverage is Meraki + Catalyst Center
    # dashboard/programmability APIs (see module docstring) — a classic
    # CLI-managed platform (IOS, IOS-XE, NX-OS, IOS-XR, ASA) has zero real
    # coverage here by design, so querying it for one is guaranteed
    # irrelevant, not merely lower-priority. supports_vendor() alone can't
    # catch this: "cisco" is true for both a Meraki dashboard switch and a
    # classic IOS router, and _estimate_confidence()'s token-overlap
    # downgrade only labels the result low-confidence AFTER the fact — it
    # doesn't stop an irrelevant Meraki API doc from being fetched, cited,
    # and quoted in a synthesized answer for an IOS troubleshooting session
    # in the first place. A wrong/irrelevant "answer" is worse than none.
    _CLASSIC_CLI_PLATFORM_MARKERS = ("ios", "nx-os", "nxos", "asa")

    def _platform_out_of_scope(self, platform: Optional[str]) -> bool:
        p = (platform or "").lower()
        if not p:
            return False   # no platform hint at all — can't confidently exclude
        if "meraki" in p or "catalyst" in p or "dna" in p:
            return False
        return any(marker in p for marker in self._CLASSIC_CLI_PLATFORM_MARKERS)

    def supports_vendor(self, vendor: str) -> bool:
        return (vendor or "").lower() in self.SUPPORTED_VENDORS

    def lookup(
        self,
        vendor: str,
        command: str,
        platform: Optional[str] = None,
    ) -> Optional[KnowledgeEntry]:
        if not self.supports_vendor(vendor):
            return None
        if not command:
            return None
        if self._platform_out_of_scope(platform):
            return None

        # Lazy init client
        if self._client is None:
            self._client = MCPHttpClient(self.ENDPOINT_URL, timeout=12)

        # Check reachability (cached)
        if self._reachable is None:
            self._reachable = self._client.is_reachable()
            if not self._reachable:
                logger.info("DevNet MCP not reachable — skipping")

        if not self._reachable:
            return None

        # Discover available tools (cached)
        if not self._tools_cache:
            self._tools_cache = self._client.list_tools()
            if not self._tools_cache:
                return None

        # Pick best tool for this query
        tool_name = self._select_tool(command, platform)
        if not tool_name:
            return None

        # Build arguments based on tool schema
        args = self._build_arguments(tool_name, command, platform)

        result = self._client.call_tool(tool_name, args)
        if not result.ok or not result.text:
            return None

        return self._result_to_entry(command, platform, tool_name, result.text)

    # ── Tool selection logic ──────────────────────────────────────────────────

    def _select_tool(self, command: str, platform: Optional[str]) -> Optional[str]:
        """
        Pick the most relevant MCP tool for this command.
        DevNet MCP currently exposes search tools per Cisco product family.
        """
        cmd_lower = command.lower()
        platform_lower = (platform or "").lower()

        # Score each tool against the command
        best_tool = None
        best_score = 0

        for tool in self._tools_cache:
            name_lower = tool.name.lower()
            desc_lower = (tool.description or "").lower()
            score = 0

            # Strong match if platform is in tool name (e.g. "meraki" tool when device is Meraki)
            if "meraki" in platform_lower and "meraki" in name_lower:
                score += 10
            if "catalyst" in platform_lower and ("catalyst" in name_lower or "dna" in name_lower):
                score += 10
            # Generic search tools are reasonable fallbacks
            if "search" in name_lower:
                score += 3
            # Description mentioning API / docs is positive
            if any(kw in desc_lower for kw in ("api", "documentation", "reference")):
                score += 2
            # Pure intent match
            if any(kw in name_lower for kw in self.KNOWN_TOOL_HINTS):
                score += 1

            if score > best_score:
                best_score = score
                best_tool = tool.name

        return best_tool

    def _build_arguments(
        self,
        tool_name: str,
        command: str,
        platform: Optional[str],
    ) -> Dict[str, Any]:
        """
        Build arguments dict based on the tool's input schema.
        DevNet tools typically accept {"query": "..."} or {"keyword": "..."}.
        """
        # Find the tool to read its schema
        tool = next((t for t in self._tools_cache if t.name == tool_name), None)
        if not tool or not isinstance(tool.input_schema, dict):
            return {"query": command}

        properties = tool.input_schema.get("properties", {})
        args: Dict[str, Any] = {}

        # Map command into the most appropriate field
        for field_name in properties.keys():
            field_lower = field_name.lower()
            if any(kw in field_lower for kw in ("query", "keyword", "search", "term", "text")):
                args[field_name] = command
            elif "platform" in field_lower and platform:
                args[field_name] = platform
            elif "vendor" in field_lower:
                args[field_name] = "cisco"

        # If we couldn't map anything, use safe default
        if not args:
            args = {"query": command}

        return args

    # ── Result → KnowledgeEntry ───────────────────────────────────────────────

    def _estimate_confidence(self, query: str, text: str) -> Tuple[ConfidenceLevel, str]:
        """
        The DevNet Content Search MCP's tool responses (verified live against
        the real endpoint) carry no relevance/similarity score field at all —
        every result is just a JSON blob of API-doc fields (name, description,
        tags, api_path, ...) with nothing indicating how well it actually
        matches the query. Blindly labeling every response ConfidenceLevel.HIGH
        (as this used to do unconditionally) is worse than admitting
        uncertainty: it presents a keyword coincidence (e.g. a Meraki VPN
        "peers" API doc surfacing for a "VXLAN EVPN peering" question) with
        the platform's highest trust label.

        In the absence of a real relevance score from the API, fall back to
        a token-overlap check between the query and the returned result's own
        text: if none of the query's meaningful (non-stopword) words appear
        anywhere in what came back, that is strong, cheap, defensible evidence
        the result is off-topic, and confidence is downgraded accordingly
        rather than assumed to be HIGH. This never invents relevance where
        none is measurable; it only refuses to claim confidence the source
        gives us no basis for.
        """
        query_tokens = _content_tokens(query)
        result_tokens = _content_tokens(text)
        if not query_tokens or not result_tokens:
            return ConfidenceLevel.LOW, "no comparable query/result tokens"

        overlap = query_tokens & result_tokens
        ratio = len(overlap) / len(query_tokens)

        if not overlap:
            return (ConfidenceLevel.UNVERIFIED,
                    "no shared vocabulary between query and result — likely a "
                    "keyword coincidence on the underlying search, not a "
                    "topical match")
        if ratio < 0.34:
            return (ConfidenceLevel.LOW,
                    f"only weak term overlap with the query ({sorted(overlap)})")
        if ratio < 0.6:
            return (ConfidenceLevel.MEDIUM,
                    f"partial term overlap with the query ({sorted(overlap)})")
        return (ConfidenceLevel.HIGH,
                f"strong term overlap with the query ({sorted(overlap)})")

    def _result_to_entry(
        self,
        command: str,
        platform: Optional[str],
        tool_name: str,
        text: str,
    ) -> KnowledgeEntry:
        now = datetime.utcnow().isoformat()
        confidence, relevance_note = self._estimate_confidence(command, text)
        return KnowledgeEntry(
            vendor="cisco",
            platform=(platform or "").lower(),
            command=command.strip(),
            syntax="",        # MCP gives free-text; we don't try to extract syntax
            description=text[:1500],
            example_output="",
            min_version="",
            citation=Citation(
                source_name=self.source_name,
                source_type="mcp",
                source_url=self.ENDPOINT_URL,
                source_title=f"Cisco DevNet MCP · {tool_name}",
                vendor="cisco",
                confidence=confidence,
                fetched_at=now,
                notes=(f"Retrieved via Cisco-hosted MCP tool '{tool_name}' "
                       f"({relevance_note})"),
            ),
            fetched_at=now,
            verified_at=now,
            ttl_days=get_ttl("cisco"),
        )

    # ── Health ────────────────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        if self._client is None:
            self._client = MCPHttpClient(self.ENDPOINT_URL, timeout=8)
        reachable = self._client.is_reachable()
        return {
            "name":       self.source_name,
            "type":       self.source_type,
            "endpoint":   self.ENDPOINT_URL,
            "reachable":  reachable,
            "tools_count": len(self._client.list_tools()) if reachable else 0,
        }
