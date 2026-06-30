"""
NRIE · AI · Assistant (reuses the platform Groq client)
=======================================================
Thin AI layer that REUSES the existing platform LLM (core.ai_engine.ask_ai,
Groq llama-3.3). It is always optional: every method has a deterministic result
or graceful fallback so NRIE works with or without an API key. No new LLM client
is introduced.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional


def _ask(prompt: str) -> str:
    try:
        from core.ai_engine import ask_ai
        out = ask_ai(prompt)
        if isinstance(out, str) and "unavailable" not in out.lower():
            return out
    except Exception:
        pass
    return ""


def available() -> bool:
    return bool(_ask("reply OK"))


def parse_json(prompt: str) -> Optional[Dict[str, Any]]:
    """Ask the LLM for strict JSON and parse it; None on any failure."""
    raw = _ask(prompt + "\n\nReturn ONLY a JSON object, no prose, no code fences.")
    if not raw:
        return None
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def describe_ip(ip: str, hostname: str = "", vendor: str = "",
                open_ports=None, role_hint: str = "") -> str:
    """Natural-language description of what an IP is / where it's engaged."""
    ports = ", ".join(str(p) for p in (open_ports or [])) or "none"
    ai = _ask(
        f"In one short sentence, describe what this network host most likely is and "
        f"what it is engaged in. IP={ip}, hostname='{hostname}', vendor='{vendor}', "
        f"open_ports=[{ports}], hint='{role_hint}'. Be specific and concise.")
    if ai:
        return ai.strip().split("\n")[0][:200]
    # deterministic fallback
    role = role_hint or _role_from_ports(open_ports or [], vendor, hostname)
    where = f"{hostname or ip}"
    return f"{role} ({where})" + (f", ports: {ports}" if ports != "none" else "")


def _role_from_ports(ports, vendor: str, hostname: str) -> str:
    ps = set(ports)
    if {179} & ps:
        return "Router / BGP speaker"
    if {22, 23} & ps and ("cisco" in vendor.lower() or "ios" in hostname.lower()):
        return "Network device (managed via SSH/Telnet)"
    if {80, 443} & ps:
        return "Web/application server"
    if {53} & ps:
        return "DNS server"
    if {67, 68} & ps:
        return "DHCP server"
    if {445, 139} & ps:
        return "File/SMB host"
    if {554, 8000, 37777} & ps:
        return "CCTV / camera"
    if {22} & ps:
        return "SSH-managed host"
    return "Active host"
