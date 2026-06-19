"""
core/knowledge/mcp/mcp_client.py
================================
Lightweight HTTP-transport MCP client.

Only what we need for knowledge lookup:
  - initialize handshake
  - tools/list
  - tools/call

No heavy SDK dependency — pure JSON-RPC over HTTP using `requests`.
This keeps NetBrain portable to Streamlit Cloud (no npx/node required).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

logger = logging.getLogger("NetBrain.Knowledge.MCP.Client")


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class MCPTool:
    """One MCP tool exposed by a server."""
    name: str = ""
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPCallResult:
    """Result of one tools/call invocation."""
    ok: bool = False
    content: List[Dict[str, Any]] = field(default_factory=list)   # raw content blocks
    text:    str = ""                                              # concatenated text
    error:   Optional[str] = None
    raw:     Dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# MCP HTTP Client
# ═══════════════════════════════════════════════════════════════════════════════

class MCPHttpClient:
    """
    Minimal MCP client over plain HTTP JSON-RPC.

    Usage:
        c = MCPHttpClient("https://devnet.cisco.com/v1/foundation-search-mcp/mcp")
        c.initialize()
        tools = c.list_tools()
        result = c.call_tool("search_meraki_apis", {"query": "show ospf"})
    """

    PROTOCOL_VERSION = "2025-03-26"
    DEFAULT_TIMEOUT  = 15

    def __init__(
        self,
        endpoint_url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.endpoint_url = endpoint_url
        self.headers      = headers or {}
        self.timeout      = timeout
        self._req_id      = 0
        self._id_lock     = threading.Lock()
        self._initialized = False
        self._cached_tools: Optional[List[MCPTool]] = None

    # ── JSON-RPC helpers ──────────────────────────────────────────────────────

    def _next_id(self) -> int:
        with self._id_lock:
            self._req_id += 1
            return self._req_id

    def _post(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not REQUESTS_OK:
            return {"error": {"message": "requests library not installed"}}

        body = {
            "jsonrpc": "2.0",
            "id":      self._next_id(),
            "method":  method,
        }
        if params is not None:
            body["params"] = params

        h = {
            "Content-Type": "application/json",
            "Accept":       "application/json, text/event-stream",
            "User-Agent":   "NetBrain-AI/1.0",
        }
        h.update(self.headers)

        try:
            r = requests.post(
                self.endpoint_url,
                headers=h,
                data=json.dumps(body),
                timeout=self.timeout,
            )
            if r.status_code not in (200, 202):
                return {"error": {"message": f"HTTP {r.status_code}: {r.text[:200]}"}}

            # Most MCP servers reply with application/json
            ct = r.headers.get("Content-Type", "")
            if "application/json" in ct:
                return r.json()
            # Some servers use text/event-stream — extract the first data: line
            if "event-stream" in ct or r.text.startswith("data:"):
                return self._parse_sse(r.text)
            # Fallback — try JSON anyway
            try:
                return r.json()
            except Exception:
                return {"error": {"message": f"Unexpected response: {r.text[:200]}"}}

        except Exception as exc:
            logger.debug(f"MCP POST failed: {exc}")
            return {"error": {"message": str(exc)}}

    @staticmethod
    def _parse_sse(text: str) -> Dict[str, Any]:
        """Parse a Server-Sent Events stream — pick the first JSON data block."""
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    return json.loads(payload)
                except Exception:
                    continue
        return {"error": {"message": "no parseable SSE data"}}

    # ── Public MCP methods ────────────────────────────────────────────────────

    def initialize(self) -> bool:
        """One-time MCP handshake. Returns True on success."""
        if self._initialized:
            return True

        params = {
            "protocolVersion": self.PROTOCOL_VERSION,
            "clientInfo": {
                "name":    "NetBrain-AI",
                "version": "1.0",
            },
            "capabilities": {},
        }
        resp = self._post("initialize", params)
        if "error" in resp:
            logger.warning(f"MCP init failed: {resp['error']}")
            return False

        result = resp.get("result", {})
        proto = result.get("protocolVersion", "")
        if proto:
            logger.info(f"MCP init OK with protocol {proto}")

        # Send notifications/initialized to complete handshake
        try:
            self._post("notifications/initialized", {})
        except Exception:
            pass

        self._initialized = True
        return True

    def list_tools(self, force_refresh: bool = False) -> List[MCPTool]:
        """List all tools exposed by this MCP server."""
        if self._cached_tools is not None and not force_refresh:
            return self._cached_tools

        if not self.initialize():
            return []

        resp = self._post("tools/list", {})
        if "error" in resp:
            logger.warning(f"MCP list_tools failed: {resp['error']}")
            return []

        tools_raw = resp.get("result", {}).get("tools", [])
        tools = [
            MCPTool(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools_raw
        ]
        self._cached_tools = tools
        return tools

    def call_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> MCPCallResult:
        """Invoke one tool with the given arguments."""
        if not self.initialize():
            return MCPCallResult(ok=False, error="initialize failed")

        resp = self._post(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )
        if "error" in resp:
            return MCPCallResult(ok=False, error=str(resp["error"]), raw=resp)

        result = resp.get("result", {})
        content = result.get("content", []) or []
        # Collect text blocks
        text_parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and block.get("text"):
                    text_parts.append(block["text"])
                elif block.get("type") == "resource" and isinstance(block.get("resource"), dict):
                    text_parts.append(str(block["resource"]))

        return MCPCallResult(
            ok=not result.get("isError", False),
            content=content,
            text="\n".join(text_parts),
            error=None if not result.get("isError") else "tool returned error",
            raw=resp,
        )

    # ── Health ────────────────────────────────────────────────────────────────

    def is_reachable(self) -> bool:
        """Quick ping — try initialize, return True if reachable."""
        try:
            return self.initialize()
        except Exception:
            return False
