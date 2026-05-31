"""
ai_config.py
============

Natural-language → Cisco IOS configuration, with a STRICT safety filter.

Policy (chosen by the operator):
  - Preview only first; the operator approves before anything is applied.
  - Block ALL lockout / destructive commands, no exceptions.

This module never connects to a device. It only:
  1. generate_config()  → asks the AI for IOS commands from a plain-English request
  2. validate_config()  → blocks dangerous / lockout / destructive commands
The Streamlit layer handles preview + explicit approval, then hands the
validated commands to the existing NetworkFixer for execution.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Reuse the remediation deny-list and add config-specific lockout patterns.
try:
    from core.ai_remediation import DENY_PATTERNS as _BASE_DENY
except Exception:
    _BASE_DENY = []


# ── Config-specific hard-deny: lockout + destructive + identity/security ──────
# If ANY proposed command matches, the WHOLE config is rejected. No overrides.
CONFIG_DENY_PATTERNS = list(_BASE_DENY) + [
    # Lockout risks — could cut the platform's own access to the router
    r"\baccess-class\b",                 # ACL applied to VTY lines
    r"\bline\s+vty\b",                   # touching VTY config
    r"\btransport\s+input\s+none\b",
    r"\bno\s+transport\s+input\b",
    r"\blogin\s+block-for\b",
    r"\bno\s+ip\s+ssh\b",
    r"\bno\s+enable\b",
    r"\bno\s+line\b",
    r"\bservice\s+disable\b",
    # Management interface / mgmt path risks
    r"\bno\s+ip\s+address\b",            # removing an IP can strand the device
    r"\bno\s+ip\s+default-gateway\b",
    r"\bno\s+ip\s+route\b",
    # Routing-process destruction
    r"\bno\s+router\b",
    r"\bno\s+ip\s+routing\b",
    # Identity / credential changes
    r"\busername\b.*\bsecret\b",
    r"\busername\b.*\bpassword\b",
    r"\bno\s+username\b",
    r"\benable\s+secret\b",
    r"\benable\s+password\b",
    r"\baaa\b",
    r"\bno\s+aaa\b",
    r"\bsnmp-server\s+community\b",      # exposing SNMP community strings
    # Device-wide destructive
    r"\breload\b",
    r"\berase\b",
    r"\bwrite\s+erase\b",
    r"\bdelete\b",
    r"\bformat\b",
    r"\bboot\s+system\b",
    r"\bconfig-register\b",
    r"\bcrypto\s+key\s+zeroize\b",
    r"\bhostname\b",                     # renaming breaks log/device correlation
    # bare 'shutdown' on an interface (NOT 'no shutdown')
    r"(?<!no\s)\bshutdown\b",
]


def _matches_any(cmd: str, patterns: List[str]) -> bool:
    low = cmd.strip().lower()
    return any(re.search(p, low) for p in patterns)


def validate_config(commands: List[str]) -> Tuple[bool, List[str], List[str]]:
    """
    Returns (is_safe, blocked, reasons).
    is_safe is True only if NO command matches a deny pattern.
    """
    blocked: List[str] = []
    reasons: List[str] = []
    for raw in commands:
        cmd = (raw or "").strip()
        if not cmd:
            continue
        if _matches_any(cmd, CONFIG_DENY_PATTERNS):
            blocked.append(cmd)
            reasons.append(f"'{cmd}' is blocked (lockout/destructive/identity rule)")
    return (len(blocked) == 0, blocked, reasons)


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json|text)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    m = re.search(r"\{.*\}", _strip_fences(text), re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def build_prompt(request: str, device: str, device_facts: str = "") -> str:
    return (
        "You are a senior Cisco IOS engineer. Convert the operator's request "
        "into Cisco IOS commands to run on the device.\n\n"
        f"Device: {device}\n"
        f"{device_facts}\n\n"
        f"Operator request: {request}\n\n"
        "STRICT RULES:\n"
        "- Output ONLY a JSON object, no prose, no markdown.\n"
        "- Keys: \"mode\" (\"config\" for changes, or \"diagnostic\" for read-only "
        "checks like 'show'/'confirm'/'check status'), \"commands\" (ordered list "
        "of IOS commands), \"summary\" (one plain-English sentence), "
        "\"risk\" (\"low\"|\"medium\"|\"high\").\n"
        "- If the request only asks to CHECK/CONFIRM/SHOW something (not change "
        "it), set mode='diagnostic' and use read-only 'show' commands only "
        "(e.g. 'show ip interface brief', 'show interfaces Loopback0'). Do NOT "
        "enter configure terminal for diagnostics.\n"
        "- If the request CHANGES configuration, set mode='config', begin with "
        "'configure terminal' and end with 'end'.\n"
        "- NEVER produce commands that could lock out management access "
        "(no VTY ACLs, no removing IP addresses, no disabling SSH, no "
        "touching usernames/enable secrets/aaa), and NEVER destructive "
        "commands (reload, erase, delete, write erase, no router, no ip routing).\n"
        "- If a config request would require any of those, return commands: [] "
        "and explain in summary why it cannot be done safely.\n"
        "- Use real interface names; do not invent IPs unless the request gives them.\n\n"
        "Example — 'confirm the lo0 status':\n"
        "{\"mode\":\"diagnostic\",\"commands\":[\"show interfaces Loopback0\","
        "\"show ip interface brief\"],\"summary\":\"Checks the status of Loopback0.\","
        "\"risk\":\"low\"}\n"
        "Example — 'add a description to Gig1/0':\n"
        "{\"mode\":\"config\",\"commands\":[\"configure terminal\","
        "\"interface GigabitEthernet1/0\",\"description Uplink to core\",\"end\"],"
        "\"summary\":\"Sets a description on GigabitEthernet1/0.\",\"risk\":\"low\"}"
    )


def generate_config(request: str, device: str, ai_call,
                    device_facts: str = "") -> Dict[str, Any]:
    """
    Returns:
      {
        "status": "ok" | "unsafe" | "unavailable" | "empty",
        "commands": [...],        # validated config commands (if ok)
        "summary": "...",
        "risk": "low|medium|high",
        "blocked": [...],
        "reasons": [...],
        "raw": "<raw AI text>",
      }
    """
    out: Dict[str, Any] = {
        "status": "unavailable", "commands": [], "summary": "",
        "risk": "unknown", "mode": "config", "blocked": [], "reasons": [], "raw": "",
    }
    if not ai_call:
        out["reasons"] = ["No AI client configured (set OPENROUTER_API_KEY)."]
        return out
    if not request or not request.strip():
        out["status"] = "empty"
        out["reasons"] = ["Empty request."]
        return out

    try:
        raw = ai_call(build_prompt(request, device, device_facts)) or ""
        out["raw"] = raw
    except Exception as e:
        out["reasons"] = [f"AI call error: {e}"]
        return out

    data = _parse_json(raw)
    if not data:
        out["reasons"] = ["AI response could not be parsed into commands."]
        return out

    cmds = data.get("commands", [])
    if isinstance(cmds, str):
        cmds = [cmds]
    cmds = [str(c).strip() for c in cmds if str(c).strip()]
    out["summary"] = str(data.get("summary", "")).strip()
    out["risk"] = str(data.get("risk", "unknown")).strip().lower()
    out["mode"] = str(data.get("mode", "config")).strip().lower() or "config"

    if not cmds:
        out["status"] = "empty"
        out["reasons"] = [out["summary"] or "AI returned no commands (likely unsafe request)."]
        return out

    is_safe, blocked, reasons = validate_config(cmds)
    if not is_safe:
        out["status"] = "unsafe"
        out["blocked"] = blocked
        out["reasons"] = reasons
        out["commands"] = cmds      # shown for transparency; caller must NOT run
        logger.warning(f"[AI-CONFIG] Unsafe config blocked: {blocked}")
        return out

    out["status"] = "ok"
    out["commands"] = cmds
    return out
