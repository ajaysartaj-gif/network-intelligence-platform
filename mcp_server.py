"""
mcp_server.py
=============
MCP (Model Context Protocol) server exposing this platform's troubleshoot/
configure/design engines and RAG knowledge base as MCP tools, so any
MCP-compatible client (Claude Desktop, other agents) can call directly into
real network operations — the same engines core/copilot_engine.py drives,
not a demo/simulation surface.

Only a CLIENT to an external MCP server existed before this
(core/knowledge/mcp/mcp_client.py, against Cisco DevNet's hosted endpoint) —
this is the platform's own server side, fully new.

Each tool's real logic lives in an undecorated _*_impl() function; the
@mcp.tool()-decorated function is a thin adapter around it. That split means
tests exercise the actual logic directly (injecting a fake ai_call/gateway/
knowledge layer) without needing the MCP protocol machinery at all — the
same "separate the engine logic from the glue" discipline already used
throughout this codebase (core/copilot_engine.py vs. the engines it drives).

Run:
    python3 mcp_server.py
Or via the MCP CLI dev inspector:
    mcp dev mcp_server.py
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("NetBrain.MCPServer")

mcp = FastMCP("network-intelligence-platform")


# ── AI call (standalone — no Streamlit dependency, unlike app.py's call_ai) ──
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_MODEL_NAME = os.environ.get("NETBRAIN_MODEL", "llama-3.3-70b-versatile")


def _resolve_api_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    try:
        from dotenv import load_dotenv
        repo_root = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(repo_root, ".env")
        if os.path.exists(env_path):
            load_dotenv(env_path, override=True)
            return os.environ.get("GROQ_API_KEY", "").strip()
    except Exception:
        pass
    return ""


def call_ai(prompt: str) -> str:
    key = _resolve_api_key()
    if not key:
        return "AI Error: GROQ_API_KEY not set in environment or .env"
    try:
        from openai import OpenAI
    except ImportError:
        return "AI Error: openai package not installed"
    try:
        client = OpenAI(api_key=key, base_url=_GROQ_BASE_URL)
        resp = client.chat.completions.create(
            model=_MODEL_NAME,
            messages=[
                {"role": "system", "content": (
                    "You are NetBrain AI — an expert autonomous network operations "
                    "system. Be concise, technical, and action-oriented.")},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800, temperature=0.1,
        )
        return resp.choices[0].message.content
    except Exception as exc:
        logger.warning(f"AI call failed: {exc}")
        return f"AI Error: {exc}"


# ── Device construction (the shape gateways/adapters read: ip/hostname/device_type) ──
class Device:
    def __init__(self, ip: str, hostname: str = "", device_type: str = "cisco_ios"):
        self.ip = ip
        self.hostname = hostname or ip
        self.device_type = device_type


def _build_devices(device_ips: List[str]) -> List[Device]:
    return [Device(ip) for ip in (device_ips or [])]


def _gateway_for(devices: List[Device], ai_call: Callable[[str], str]):
    """Reuses the platform's real SSH-backed VendorGateway builder — the
    exact same one core/copilot_engine.py's chat handlers use — rather than
    duplicating gateway-construction logic here."""
    from core.copilot_engine import _make_troubleshooting_gateway
    return _make_troubleshooting_gateway(ai_call, devices)


# ── Tool implementations (plain functions — the part tests exercise) ───────
def _troubleshoot_impl(query: str, device_ips: List[str],
                       ai_call: Callable[[str], str] = call_ai) -> str:
    from core.troubleshooting import TroubleshootingEngine, TSConfig
    devices = _build_devices(device_ips)
    gw = _gateway_for(devices, ai_call)
    eng = TroubleshootingEngine(ai_call=ai_call, devices=devices, gateway=gw,
                                config=TSConfig(max_steps=6))
    return eng.run(query).to_markdown()


def _configure_impl(query: str, device_ips: List[str], provided: Optional[Dict[str, Any]] = None,
                    ai_call: Callable[[str], str] = call_ai) -> str:
    from core.config_engine import AIConfigurationEngine
    devices = _build_devices(device_ips)
    gw = _gateway_for(devices, ai_call) if devices else None
    eng = AIConfigurationEngine(ai_call=ai_call, devices=devices, gateway=gw)
    return eng.run(query, provided=provided or {}).to_markdown()


def _design_impl(query: str, device_ips: Optional[List[str]] = None,
                 ai_call: Callable[[str], str] = call_ai) -> str:
    from core.design_engine import AIDesignEngine
    devices = _build_devices(device_ips or [])
    gw = _gateway_for(devices, ai_call) if devices else None
    eng = AIDesignEngine(ai_call=ai_call, devices=devices, gateway=gw)
    return eng.run(query).to_markdown()


def _format_knowledge_hits(hits: List[Any]) -> str:
    if not hits:
        return "No matching knowledge base entries found."
    out = []
    for h in hits:
        out.append(f"### {h.title or h.doc_id} (confidence {h.confidence:.2f}, "
                   f"source: {h.source_type})\n{h.text}")
    return "\n\n".join(out)


def _search_knowledge_impl(query: str, top_k: int = 5, layer: Optional[Any] = None) -> str:
    if layer is None:
        from core.knowledge.enterprise.knowledge_layer import get_knowledge_layer
        layer = get_knowledge_layer()
    hits = layer.search(query, top_k=top_k)
    return _format_knowledge_hits(hits)


# ── MCP tool adapters (thin — register the impl functions above) ───────────
@mcp.tool()
def troubleshoot_network(query: str, device_ips: List[str]) -> str:
    """
    Investigate a real network problem (OSPF/BGP/HSRP/VRRP/LACP/STP and
    more) on the given device IPs: connects via SSH, gathers real evidence,
    ranks root-cause hypotheses, and — only with a grounded, evidence-backed
    confirmation — proposes a vendor-syntax fix with rollback. Never
    deploys anything; returns a markdown report for human review.

    Args:
        query: the troubleshooting question, e.g. "why is the OSPF neighbor
            192.168.1.2 stuck in ExStart on Gi0/1".
        device_ips: IP addresses of the real devices to investigate.
    """
    return _troubleshoot_impl(query, device_ips)


@mcp.tool()
def configure_network(query: str, device_ips: List[str],
                      provided: Optional[Dict[str, Any]] = None) -> str:
    """
    Turn a business/technical intent ("enable OSPF on the core uplinks in
    area 0") into normalized configuration, vendor-syntax artifacts, risk/
    impact analysis, and an approval package. Asks for missing mandatory
    inputs rather than assuming them. Never deploys without explicit
    approval.

    Args:
        query: the configuration request in plain language.
        device_ips: IP addresses of the real devices in scope.
        provided: answers to previously-asked missing-input questions, if
            this is a follow-up call (field name -> value).
    """
    return _configure_impl(query, device_ips, provided)


@mcp.tool()
def design_network_architecture(query: str, device_ips: Optional[List[str]] = None) -> str:
    """
    Act as a Principal Network Architect: produce multiple scored
    architecture options (never just one), a weighted trade-off analysis,
    capacity planning, risk assessment (including SPOF), and a migration
    plan. Never outputs vendor CLI or device configuration — follow up with
    configure_network once a direction is chosen.

    Args:
        query: the design request, e.g. "design a resilient dual-datacenter
            campus core for 5k users with growth to 15k".
        device_ips: optional existing device IPs, for read-only brownfield
            capability discovery only (never used for configuration).
    """
    return _design_impl(query, device_ips)


@mcp.tool()
def search_knowledge_base(query: str, top_k: int = 5) -> str:
    """
    Search the platform's ingested knowledge base (vendor docs, RFCs,
    runbooks, best practices, past incident resolutions) with hybrid
    (semantic + keyword) search and cross-encoder re-ranking. Returns the
    top matches with their source, confidence, and content.

    Args:
        query: the question to search for.
        top_k: how many results to return.
    """
    return _search_knowledge_impl(query, top_k)


if __name__ == "__main__":
    mcp.run()
