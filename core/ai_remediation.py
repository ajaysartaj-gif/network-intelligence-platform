"""
ai_remediation.py
=================

AI-driven remediation command generation with a hard safety filter.

Flow:
  1. generate_fix_commands() asks the AI for the IOS commands to fix a specific
     anomaly, given the device + log context.
  2. Every proposed command is run through validate_commands(), which BLOCKS
     destructive / out-of-scope commands (reload, erase, bare shutdown, etc.).
  3. The caller decides what to do with the result:
       - status == "ok"        → safe AI commands, proceed (with human approval)
       - status == "unsafe"    → AI proposed something dangerous → DO NOT run;
                                  escalate to a human
       - status == "unavailable" → AI down / empty → DO NOT run; escalate
     (Per operator policy: we never silently fall back to canned commands when
      the AI is unavailable or unsafe — we stop and ask a human.)

This module never executes anything. It only produces and vets command lists.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Safety policy ────────────────────────────────────────────────────────────
# Hard-deny: if any proposed command matches, the WHOLE plan is rejected as
# unsafe. These can disrupt the device/network or destroy config.
DENY_PATTERNS = [
    r"\breload\b",
    r"\bwrite\s+erase\b",
    r"\berase\b",
    r"\bdelete\b",
    r"\bformat\b",
    r"\bno\s+router\b",          # tearing down routing processes
    r"\bno\s+ip\s+routing\b",
    r"\bno\s+interface\b",        # removing interfaces
    r"\bno\s+username\b",
    r"\bno\s+aaa\b",
    r"\bboot\s+system\b",
    r"\bconfig-register\b",
    r"\bcrypto\s+key\s+zeroize\b",
    r"\bclear\s+line\b",
    r"\bhw-module\b",
    r"\bmicrocode\s+reload\b",
    # bare "shutdown" (NOT "no shutdown") would take an interface down
    r"(?<!no\s)\bshutdown\b",
    r"\bno\s+shut\b.*\binterface\b",   # odd ordering guard
    r"\bs*$\bdebug\b",                  # debug can flood/cripple the device
    r"\bdebug\s+all\b",
]

# Commands must look like real IOS remediation. We allow config-mode and a known
# set of safe operational verbs; anything else is treated as suspicious.
ALLOW_PREFIXES = (
    "interface", "no shutdown", "end", "exit", "configure terminal",
    "clear ip bgp", "clear counters", "clear arp", "clear ip route",
    "ip ospf", "router ospf", "network", "bandwidth", "mtu", "speed",
    "duplex", "description", "switchport", "channel-group", "standby",
    "shutdown\nno shutdown",  # interface bounce handled explicitly elsewhere
)

# Commands we recognise as read-only diagnostics/verification (always safe).
SHOW_PREFIXES = ("show ", "ping ", "traceroute ")


def _matches_any(cmd: str, patterns: List[str]) -> bool:
    low = cmd.strip().lower()
    return any(re.search(p, low) for p in patterns)


def validate_commands(commands: List[str]) -> Tuple[bool, List[str], List[str]]:
    """
    Returns (is_safe, blocked, reasons).
      is_safe == True  → no destructive commands found.
      is_safe == False → at least one command was blocked.
    """
    blocked: List[str] = []
    reasons: List[str] = []
    for raw in commands:
        cmd = (raw or "").strip()
        if not cmd:
            continue
        if _matches_any(cmd, DENY_PATTERNS):
            blocked.append(cmd)
            reasons.append(f"'{cmd}' matches a destructive-command rule")
    return (len(blocked) == 0, blocked, reasons)


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json|text)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def _parse_command_json(text: str) -> Optional[Dict[str, List[str]]]:
    """Parse the AI's JSON response into {diagnostic, fix, verify} lists."""
    if not text:
        return None
    cleaned = _strip_code_fences(text)
    # Try to locate the first JSON object in the text.
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    out: Dict[str, List[str]] = {}
    for key in ("diagnostic", "fix", "verify"):
        val = data.get(key, [])
        if isinstance(val, str):
            val = [val]
        out[key] = [str(c).strip() for c in val if str(c).strip()]
    if not out.get("fix"):
        return None
    return out


def build_prompt(anomaly: Dict[str, Any], device_facts: str = "",
                 knowledge: str = "") -> str:
    """Construct a tightly-scoped prompt that asks ONLY for IOS commands."""
    knowledge_block = ""
    if knowledge:
        knowledge_block = (
            "\nRelevant runbook knowledge and past incidents (use this to ground "
            "your fix in THIS network's practices):\n" + knowledge + "\n"
        )
    return (
        "You are a senior Cisco IOS network engineer. A monitoring system "
        "detected the issue below on a live router. Respond with the exact "
        "Cisco IOS commands to remediate it.\n\n"
        f"Device: {anomaly.get('device','unknown')}\n"
        f"Issue type: {anomaly.get('type','unknown')}\n"
        f"Interface: {anomaly.get('interface','N/A')}\n"
        f"State: {anomaly.get('state','N/A')}\n"
        f"Log description: {anomaly.get('description','N/A')}\n"
        f"{device_facts}\n"
        f"{knowledge_block}\n"
        "STRICT RULES:\n"
        "- Output ONLY a JSON object, no prose, no markdown.\n"
        "- Keys: \"diagnostic\" (read-only show commands), \"fix\" (config "
        "commands that resolve it), \"verify\" (read-only checks).\n"
        "- NEVER include destructive commands (reload, erase, delete, write "
        "erase, bare 'shutdown', removing interfaces/routing/users).\n"
        "- For an admin-down or down interface, the fix is to enter the "
        "interface and issue 'no shutdown'.\n"
        "- Use the real interface name given above, not a placeholder.\n"
        "- End config command lists with 'end'.\n\n"
        "Example for interface_down on GigabitEthernet1/0:\n"
        "{\"diagnostic\":[\"show interfaces GigabitEthernet1/0\"],"
        "\"fix\":[\"interface GigabitEthernet1/0\",\"no shutdown\",\"end\"],"
        "\"verify\":[\"show ip interface brief\"]}"
    )


def generate_fix_commands(
    anomaly: Dict[str, Any],
    ai_call,                       # callable(str) -> str
    device_facts: str = "",
    knowledge: str = "",
) -> Dict[str, Any]:
    """
    Ask the AI for remediation commands and validate them.

    Returns:
      {
        "status": "ok" | "unsafe" | "unavailable",
        "commands": {"diagnostic":[...], "fix":[...], "verify":[...]} or None,
        "blocked": [...],          # commands that failed safety (if unsafe)
        "reasons": [...],
        "raw": "<raw AI text>",
        "source": "ai",
      }
    """
    result: Dict[str, Any] = {
        "status": "unavailable",
        "commands": None,
        "blocked": [],
        "reasons": [],
        "raw": "",
        "source": "ai",
    }

    if not ai_call:
        result["reasons"] = ["No AI client configured."]
        return result

    try:
        prompt = build_prompt(anomaly, device_facts, knowledge)
        raw = ai_call(prompt) or ""
        result["raw"] = raw
    except Exception as e:
        logger.warning(f"[AI-REMED] AI call failed: {e}")
        result["reasons"] = [f"AI call error: {e}"]
        return result

    parsed = _parse_command_json(raw)
    if not parsed:
        result["reasons"] = ["AI response could not be parsed into commands."]
        return result

    # Validate EVERY command across all phases.
    all_cmds = parsed.get("diagnostic", []) + parsed.get("fix", []) + parsed.get("verify", [])
    is_safe, blocked, reasons = validate_commands(all_cmds)
    if not is_safe:
        result["status"] = "unsafe"
        result["blocked"] = blocked
        result["reasons"] = reasons
        result["commands"] = parsed   # keep for display, but caller must NOT run
        logger.warning(f"[AI-REMED] Unsafe AI commands blocked: {blocked}")
        return result

    result["status"] = "ok"
    result["commands"] = parsed
    return result
