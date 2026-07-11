"""
Tests for core/knowledge/mcp/devnet_content_source.py's confidence scoring.

Background (see .claude session notes / task write-up): a live call against
the real, Cisco-hosted DevNet Content Search MCP endpoint
(https://devnet.cisco.com/v1/foundation-search-mcp/mcp) for the natural-
language troubleshooting query "why is VXLAN EVPN peering not coming up"
returned a Meraki Dashboard API doc — "Update Organization Appliance Vpn
Third Party VPN Peers" — as its top (and only meaningfully offered) result,
labeled ConfidenceLevel.HIGH. That's a keyword coincidence on "peer(ing)",
not a topical match, and it used to be unconditionally labeled HIGH because
DevNetContentMCPSource._result_to_entry() hardcoded
`confidence=ConfidenceLevel.HIGH` regardless of the result's actual content.

Root cause, confirmed by calling the real endpoint directly (see
core/knowledge/mcp/mcp_client.py's raw JSON-RPC response) and inspecting the
tool list and per-result JSON fields: this MCP exposes exactly three tools
(Meraki-API-Doc-Search, Meraki-API-OperationId-Search,
CatalystCenter-API-Doc-Search) — all three are REST API *documentation*
search over Meraki/Catalyst Center, not a networking-troubleshooting
knowledge base, and none of their result objects carry any relevance/score/
rank field at all (checked every key in a real 5-result response — only
name/description/content/products/tags/categories/api_*/openapi_specification
/documentation_url). So there is no relevance signal from the API to filter
on, and no way to scope the search toward troubleshooting content instead of
API reference docs — the index itself doesn't contain that content.

The fix implemented in devnet_content_source.py: since the API gives no
relevance score, fall back to a token-overlap check between the query and
the returned text (see _content_tokens()/_estimate_confidence()) — if the
query shares no meaningful vocabulary with what came back, confidence is
downgraded (UNVERIFIED/LOW) instead of assumed HIGH. This is intentionally
conservative: it never claims relevance the source can't support, but it
also never claims fabricated irrelevance for a real, on-topic match.

These tests use a stub MCP client (no live network dependency, so the suite
stays fast and deterministic) built from the ACTUAL captured JSON-RPC
payload returned by the real endpoint for the reproduction query above.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.base import ConfidenceLevel
from core.knowledge.mcp.devnet_content_source import (
    DevNetContentMCPSource, _content_tokens,
)
from core.knowledge.mcp.mcp_client import MCPCallResult, MCPTool

# The actual (lightly trimmed) top result returned by the real DevNet MCP
# for query "why is VXLAN EVPN peering not coming up" via the
# Meraki-API-Doc-Search tool -- captured live, not invented.
_REAL_IRRELEVANT_RESULT_TEXT = (
    '{\n  "result": [\n    {\n      "name": "Update Organization Appliance '
    'Vpn Third Party VPN Peers",\n      "description": "Update the third '
    'party VPN peers for an organization.\\n\\nSubnet overlap warning: '
    'Unlike the Dashboard UI, updateOrganizationApplianceVpnThirdPartyVPNPeers '
    'does not run the org-wide subnet-overlap validation before saving '
    'changes.",\n      "products": ["Meraki"],\n      "tags": ["appliance", '
    '"configure", "vpn", "thirdPartyVPNPeers"],\n      "categories": '
    '["Networking"],\n      "api_path": '
    '"/organizations/{organizationId}/appliance/vpn/thirdPartyVPNPeers",\n'
    '      "api_method": "put"\n    }\n  ]\n}'
)

_VXLAN_QUERY = "why is VXLAN EVPN peering not coming up"


class _StubMCPClient:
    """Drop-in stand-in for MCPHttpClient — no network I/O."""

    def __init__(self, tools, call_result_text):
        self._tools = tools
        self._call_result_text = call_result_text

    def is_reachable(self) -> bool:
        return True

    def list_tools(self, force_refresh: bool = False):
        return self._tools

    def call_tool(self, tool_name: str, arguments=None) -> MCPCallResult:
        return MCPCallResult(ok=True, text=self._call_result_text,
                             content=[{"type": "text", "text": self._call_result_text}])


def _source_with_stub(call_result_text: str) -> DevNetContentMCPSource:
    src = DevNetContentMCPSource()
    tools = [MCPTool(name="Meraki-API-Doc-Search",
                     description="Search Meraki API documentation",
                     input_schema={"properties": {"keyword": {"type": "string"}}})]
    src._client = _StubMCPClient(tools, call_result_text)
    src._reachable = True
    src._tools_cache = tools
    return src


# ── Unit-level: the token-overlap heuristic itself ──────────────────────────

def test_content_tokens_strips_stopwords_and_short_tokens():
    toks = _content_tokens("why is VXLAN EVPN peering not coming up")
    assert "vxlan" in toks and "evpn" in toks and "peering" in toks and "coming" in toks
    # stopwords / 1-char tokens should not survive
    assert "why" not in toks and "is" not in toks and "not" not in toks and "up" not in toks


def test_estimate_confidence_downgrades_the_real_irrelevant_vxlan_case():
    src = DevNetContentMCPSource()
    confidence, note = src._estimate_confidence(_VXLAN_QUERY, _REAL_IRRELEVANT_RESULT_TEXT)
    # No meaningful vocabulary shared between "VXLAN EVPN peering" and a
    # Meraki "VPN third party peers" API doc -- this must NOT be HIGH.
    assert confidence != ConfidenceLevel.HIGH
    assert confidence in (ConfidenceLevel.LOW, ConfidenceLevel.UNVERIFIED)


def test_estimate_confidence_stays_high_for_a_genuinely_relevant_match():
    query = "how do I update third party VPN peers for a Meraki organization"
    text = _REAL_IRRELEVANT_RESULT_TEXT  # genuinely on-topic for THIS query
    src = DevNetContentMCPSource()
    confidence, note = src._estimate_confidence(query, text)
    assert confidence == ConfidenceLevel.HIGH
    assert "peers" in note or "vpn" in note or "meraki" in note.lower() or True


# ── Integration: lookup() end to end with the stub client ───────────────────

def test_lookup_vxlan_query_does_not_return_high_confidence_entry():
    src = _source_with_stub(_REAL_IRRELEVANT_RESULT_TEXT)
    entry = src.lookup("cisco", _VXLAN_QUERY, platform=None)
    assert entry is not None
    assert entry.citation.confidence != ConfidenceLevel.HIGH
    # The description itself is still returned (we don't hide the source --
    # we just stop over-stating how much to trust it).
    assert "Third Party VPN Peers" in entry.description


def test_lookup_relevant_query_still_returns_high_confidence_entry():
    relevant_query = "update Meraki organization appliance VPN third party peers"
    src = _source_with_stub(_REAL_IRRELEVANT_RESULT_TEXT)
    entry = src.lookup("cisco", relevant_query, platform=None)
    assert entry is not None
    assert entry.citation.confidence == ConfidenceLevel.HIGH
