"""
NetBrain MCP Integration
========================
Knowledge sources backed by Model Context Protocol servers.

Currently supported:
  - DevNet Content Search MCP (Cisco-official, no auth, free)

To add a new MCP source:
  1. Implement KnowledgeSource in a new file (e.g. thousandeyes_source.py)
  2. Register it in _MCP_SOURCES below
  3. The orchestrator picks it up automatically
"""
from typing import List

from core.knowledge.base import KnowledgeSource
from core.knowledge.mcp.mcp_client import MCPHttpClient, MCPTool, MCPCallResult
from core.knowledge.mcp.devnet_content_source import DevNetContentMCPSource


# ═══════════════════════════════════════════════════════════════════════════════
# Registry of MCP sources — instantiated once, shared across orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

_MCP_SOURCES: List[KnowledgeSource] = [
    DevNetContentMCPSource(),
]


def get_mcp_sources() -> List[KnowledgeSource]:
    """Return all registered MCP KnowledgeSources."""
    return _MCP_SOURCES


def get_mcp_sources_for_vendor(vendor: str) -> List[KnowledgeSource]:
    """Return MCP sources that support a given vendor."""
    return [s for s in _MCP_SOURCES if s.supports_vendor(vendor)]


__all__ = [
    "MCPHttpClient",
    "MCPTool",
    "MCPCallResult",
    "DevNetContentMCPSource",
    "get_mcp_sources",
    "get_mcp_sources_for_vendor",
]
