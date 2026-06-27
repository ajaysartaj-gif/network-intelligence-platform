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

# Rollback undo commands — allows "no router …" but still blocks lockout/destructive.
ROLLBACK_DENY_PATTERNS = [
    r"\baccess-class\b",
    r"\bline\s+vty\b",
    r"\bline\s+con\b",
    r"\bline\s+aux\b",
    r"\btransport\s+input\s+none\b",
    r"\bno\s+transport\s+input\b",
    r"\blogin\s+block-for\b",
    r"\bno\s+ip\s+ssh\b",
    r"\bno\s+enable\b",
    r"\bno\s+line\b",
    r"\bno\s+ip\s+routing\b",
    r"\busername\b",
    r"\benable\s+secret\b",
    r"\benable\s+password\b",
    r"\baaa\b",
    r"\bno\s+aaa\b",
    r"\bsnmp-server\s+community\b",
    r"\breload\b",
    r"\berase\b",
    r"\bwrite\s+erase\b",
    r"\bdelete\b",
    r"\bformat\b",
    r"\bboot\s+system\b",
    r"\bconfig-register\b",
    r"\bhostname\b",
    r"\bcrypto\s+key\s+zeroize\b",
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


def validate_rollback(commands: List[str]) -> Tuple[bool, List[str], List[str]]:
    """Rollback may use 'no router …' etc.; still block lockout/destructive lines."""
    blocked: List[str] = []
    reasons: List[str] = []
    for raw in commands:
        cmd = (raw or "").strip()
        if not cmd:
            continue
        if _matches_any(cmd, ROLLBACK_DENY_PATTERNS):
            blocked.append(cmd)
            reasons.append(f"'{cmd}' is blocked for rollback (lockout/destructive rule)")
    return (len(blocked) == 0, blocked, reasons)


def _finalize_rollback_plan(
    config_cmds: List[str],
    rollback_cmds: List[str],
    explanation: str,
) -> Tuple[List[str], str]:
    """Ensure a safe rollback plan exists; auto-generate inverse if AI omitted or unsafe."""
    try:
        from core.config_rollback import inverse_ios_deploy_commands
    except ImportError:
        inverse_ios_deploy_commands = None  # type: ignore

    if not rollback_cmds and inverse_ios_deploy_commands:
        rollback_cmds = inverse_ios_deploy_commands(config_cmds)
        explanation = explanation or "Auto-generated: removes each command from the configuration plan."

    if rollback_cmds:
        safe, blocked, _reasons = validate_rollback(rollback_cmds)
        if not safe and inverse_ios_deploy_commands:
            rollback_cmds = inverse_ios_deploy_commands(config_cmds)
            note = "AI rollback contained blocked commands; using auto-generated undo."
            explanation = f"{explanation} {note}".strip() if explanation else note

    return rollback_cmds, explanation


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


NETBRAIN_ENGINE_PREAMBLE = """You are NetBrain, a CCIE-level Network Intelligence Engine.

Your job is NOT to generate generic Cisco configurations. Your job is to understand
the network before making decisions.

INPUTS PROVIDED:
- User intent (operator request)
- Device inventory and fleet topology
- Parsed device CLI data (interfaces, routes, CDP/LLDP, logging)

FIRST ANALYZE (internal reasoning — reflect conclusions in network_analysis):
1. Device role (Core, Distribution, Access, Edge, Firewall, WAN, Branch).
2. Logical topology and neighbor relationships.
3. Transit links, LAN segments, loopbacks, VLANs, routing domains.
4. Existing protocols (OSPF, EIGRP, BGP, STP, HSRP, VRRP).
5. Risks, conflicts, missing best practices, configuration drift.

THEN EXECUTE:
- Infer reasonable assumptions from topology — never ask for data already supplied.
- Enterprise best practices; preserve working configuration (additive only).
- Topology-aware config only — correct interfaces, correct router-id, passive-interface
  strategy, interface descriptions when applicable.
- Include verification commands.

NEVER:
- Textbook/lab examples unrelated to supplied data.
- Ask for topology inferable from device data.
- Remove unrelated configuration.
- Enable protocols on wrong interfaces.

OUTPUT: JSON only (no markdown fences). Keys:
- mode: "config" | "diagnostic"
- network_analysis: concise bullets (role, neighbors, protocols, transit links, risks)
- assumptions: string array (empty if none)
- commands: ordered IOS config/exec lines (configure terminal … end for config)
- rollback: ordered IOS lines that UNDO commands[] if deploy is rolled back
- rollback_explanation: plain English — what rollback removes and expected result
- verify: read-only validation commands (show/ping)
- risk_assessment: one line (severity + brief reason)
- risk: low | medium | high (same severity as risk_assessment)

For mode=config you MUST include rollback and rollback_explanation.
Rollback must be the precise inverse of commands[] (e.g. "no router ospf 1" if you add OSPF).
Rollback may use "no …" forms; only undo what commands[] adds — never unrelated removals.
"""


def format_netbrain_response(res: Dict[str, Any], device_name: str, device_ip: str) -> str:
    """Render NetBrain output (analysis, config, rollback, verify, risk) for the UI."""
    header = f"## {device_name} ({device_ip})\n"

    if res.get("plain_answer"):
        return header + res["plain_answer"]

    if res.get("status") == "unsafe":
        lines = [header, "### 6. Risk Assessment", "❌ **Blocked** — unsafe commands detected"]
        for r in res.get("reasons", []):
            lines.append(f"- {r}")
        if res.get("blocked"):
            lines.append("\n**Blocked commands:**")
            lines.extend(f"- `{c}`" for c in res["blocked"])
        return "\n".join(lines)

    if res.get("status") not in ("ok",) or not res.get("commands"):
        reason = res.get("summary") or "; ".join(res.get("reasons", ["No commands generated."]))
        return header + reason

    analysis = res.get("network_analysis") or res.get("summary") or "—"
    assumptions = res.get("assumptions") or []
    config_cmds = [
        c for c in res.get("commands", [])
        if not c.lower().startswith("show ")
        and c.lower() not in ("configure terminal", "conf t", "end", "exit")
    ]
    rollback = res.get("rollback") or []
    rollback_explanation = res.get("rollback_explanation") or ""
    rollback_display = [
        c for c in rollback
        if c.lower() not in ("configure terminal", "conf t", "end", "exit")
    ]
    verify = res.get("verify") or [
        c for c in res.get("commands", []) if c.lower().startswith("show ")
    ]
    risk = res.get("risk_assessment") or res.get("risk", "unknown")

    rollback_section = []
    if rollback_explanation:
        rollback_section.append(rollback_explanation)
    if rollback_display:
        rollback_section.append("```\n" + "\n".join(rollback_display) + "\n```")
    if not rollback_section:
        rollback_section.append("_No rollback plan (diagnostic-only or no changes)._")

    parts = [
        header,
        "### 1. Network Analysis",
        analysis,
        "### 2. Assumptions",
        "\n".join(f"- {a}" for a in assumptions) if assumptions else "_None — data sufficient._",
        "### 3. Configuration Plan",
        "```\n" + "\n".join(config_cmds) + "\n```" if config_cmds else "_No configuration changes._",
        "### 4. Rollback Plan",
        "\n\n".join(rollback_section),
        "### 5. Verification Commands",
        "```\n" + "\n".join(verify) + "\n```" if verify else "_N/A_",
        "### 6. Risk Assessment",
        str(risk),
    ]
    return "\n".join(parts)


def build_inventory_summary(devs) -> str:
    """Compact fleet inventory for NetBrain prompt context."""
    lines = []
    for d in devs:
        lines.append(
            f"- {(d.hostname or d.ip)} @ {d.ip} type={getattr(d, 'device_type', 'unknown')}"
        )
    return "\n".join(lines)


def collect_device_context(
    dev,
    disc=None,
    log_store=None,
    per_device_char_limit: int = 6000,
) -> str:
    """Assemble structured network intelligence inputs from login/diagnostic sessions."""
    lines = [
        "--- DEVICE INVENTORY ---",
        f"hostname={dev.hostname or dev.ip}",
        f"mgmt_ip={dev.ip}",
        f"device_type={dev.device_type}",
        f"open_ports={dev.open_ports}",
    ]
    if disc:
        sess = disc.get_session(dev.ip)
        if sess:
            if sess.device_hostname and sess.device_hostname != dev.ip:
                lines[1] = f"hostname={sess.device_hostname}"
            if sess.output:
                lines.append("--- PARSED DEVICE DATA (interfaces / routes / CDP / topology) ---")
                lines.append(sess.output[:per_device_char_limit])
    if log_store:
        try:
            hist = log_store.get_all_logs(dev.ip)
            for entry in (hist.get("ai_history") or [])[-2:]:
                sm = entry.get("summary") or entry.get("note") or ""
                if sm:
                    lines.append(f"[prior session] {sm[:400]}")
        except Exception:
            pass
    return "\n".join(lines)


def build_fleet_topology_context(scoped_devs, disc=None, log_store=None) -> str:
    """Cross-device context so the model can infer neighbor links."""
    if len(scoped_devs) < 2:
        return ""
    blocks = ["--- TOPOLOGY GRAPH (selected fleet) ---"]
    for dev in scoped_devs:
        name = dev.hostname or dev.ip
        blocks.append(f"## {name} @ {dev.ip}")
        # Lighter slice per peer for fleet map
        blocks.append(collect_device_context(dev, disc, log_store, per_device_char_limit=2000))
    return "\n\n".join(blocks)


def build_prompt(
    request: str,
    device: str,
    device_facts: str = "",
    fleet_context: str = "",
    inventory_summary: str = "",
) -> str:
    ctx_block = device_facts.strip() or (
        "(No live CLI data — use Login on this device first so NetBrain can analyze "
        "interfaces, routes, and CDP/LLDP before generating config.)"
    )
    fleet_block = f"\n{fleet_context}\n" if fleet_context.strip() else ""
    inv_block = f"\n--- USER DEVICE INVENTORY ---\n{inventory_summary}\n" if inventory_summary else ""
    return (
        f"{NETBRAIN_ENGINE_PREAMBLE}\n\n"
        f"TARGET DEVICE: {device}\n"
        f"{inv_block}\n"
        f"DEVICE DATA:\n{ctx_block}\n"
        f"{fleet_block}\n"
        f"USER INTENT: {request}\n\n"
        "SAFETY (hard deny — commands:[] if required):\n"
        "- No VTY ACLs, credential/AAA/hostname changes, reload/erase/delete,\n"
        "  no router removal, no ip routing disable, no bare shutdown, no mgmt IP removal.\n\n"
        "Read-only intent: mode=diagnostic, commands=show/ping only, verify=[], rollback=[].\n"
        "Change intent: mode=config, populate all sections including rollback + rollback_explanation.\n"
    )


def generate_config(
    request: str,
    device: str,
    ai_call,
    device_facts: str = "",
    fleet_context: str = "",
    inventory_summary: str = "",
) -> Dict[str, Any]:
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
        "status": "unavailable", "commands": [], "rollback": [], "verify": [], "summary": "",
        "network_analysis": "", "risk_assessment": "", "rollback_explanation": "",
        "assumptions": [], "risk": "unknown", "mode": "config",
        "blocked": [], "reasons": [], "raw": "",
    }
    if not ai_call:
        out["reasons"] = ["No AI client configured (set GROQ_API_KEY in .streamlit/secrets.toml)."]
        return out
    if not request or not request.strip():
        out["status"] = "empty"
        out["reasons"] = ["Empty request."]
        return out

    # ── Deterministic configuration synthesis (single source of truth) ───────
    # For well-understood features (DNS, NTP, clock/timezone) the configuration
    # is COMPILED from vendor-authoritative templates rather than free-generated,
    # so the same intent yields identical, validated commands on every device
    # (no per-device drift, no hallucinated values like 8.4.4.4). Anything not
    # covered by a template falls through to the existing AI generation path.
    try:
        from core.intelligence.config_synthesis import (
            get_config_intelligence, parse_intent)
        _ci = get_config_intelligence()
        _intent = parse_intent(request)
        _supported = set(_ci.synth.templates.features())
        if _intent.features and set(_intent.features).issubset(_supported):
            _res = _ci.synthesize(request, [device])
            _plan = _res.plans.get(device)
            if _plan and _plan.apply_commands:
                out["status"] = "ok"
                out["mode"] = "config"
                out["commands"] = _plan.apply_commands
                out["verify"] = [c.verify_command for c in _plan.checks]
                out["rollback"] = ["no " + c for c in _plan.apply_commands
                                   if not c.lower().startswith("no ")]
                out["risk"] = "low"
                out["summary"] = (
                    "Deterministic configuration compiled from authoritative "
                    "templates for: " + ", ".join(_plan.features)
                    + ". Identical canonical commands apply on every device.")
                out["assumptions"] = _plan.warnings
                out["provenance"] = sorted(set(_plan.provenance))
                out["deterministic"] = True
                out["reasons"] = []
                return out
    except Exception:
        pass  # fall through to AI generation on any issue

    try:
        raw = ai_call(
            build_prompt(
                request, device, device_facts, fleet_context, inventory_summary,
            )
        ) or ""
        out["raw"] = raw
    except Exception as e:
        out["reasons"] = [f"AI call error: {e}"]
        return out

    data = _parse_json(raw)
    if not data:
        # AI returned prose instead of JSON — show it as a diagnostic answer
        # (happens when user asks a question rather than a config request)
        out["status"] = "ok"
        out["mode"] = "diagnostic"
        out["commands"] = []
        out["summary"] = raw.strip()[:500]
        out["risk"] = "low"
        out["reasons"] = []
        # Signal to UI that this is a plain-text AI answer, not commands
        out["plain_answer"] = raw.strip()
        return out

    cmds = data.get("commands", [])
    if isinstance(cmds, str):
        cmds = [cmds]
    cmds = [str(c).strip() for c in cmds if str(c).strip()]
    out["summary"] = str(data.get("summary", "")).strip()
    out["network_analysis"] = str(
        data.get("network_analysis") or data.get("summary") or ""
    ).strip()
    out["risk_assessment"] = str(
        data.get("risk_assessment") or data.get("risk") or ""
    ).strip()
    out["risk"] = str(data.get("risk", "unknown")).strip().lower()
    out["mode"] = str(data.get("mode", "config")).strip().lower() or "config"
    assumptions = data.get("assumptions", [])
    if isinstance(assumptions, str):
        assumptions = [assumptions] if assumptions else []
    out["assumptions"] = [str(a).strip() for a in assumptions if str(a).strip()]
    verify = data.get("verify", [])
    if isinstance(verify, str):
        verify = [verify]
    out["verify"] = [str(v).strip() for v in verify if str(v).strip()]

    rollback = data.get("rollback", [])
    if isinstance(rollback, str):
        rollback = [rollback]
    rollback = [str(r).strip() for r in rollback if str(r).strip()]
    out["rollback_explanation"] = str(data.get("rollback_explanation", "")).strip()

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
    if out["mode"] == "config":
        rollback, out["rollback_explanation"] = _finalize_rollback_plan(
            cmds, rollback, out["rollback_explanation"],
        )
    out["rollback"] = rollback
    return out
