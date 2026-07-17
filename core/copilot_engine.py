"""
Network Intelligence Copilot Engine
====================================
Standalone copilot chat interface with device integration,
image upload, and mode-driven AI reasoning. Keeps app.py clean.

Modes (each changes how the AI *thinks* and what the engine *does*):
  - configure    → advisory config-engineer persona (generate + validate + rollback)
  - troubleshoot → device-facing diagnostic loop via IntentEngine (root-cause → fix)
  - design       → advisory network-architect persona (topology / addressing / trade-offs)

Every assistant reply is tagged with the mode it was produced under and rendered
with a distinct badge + accent colour so the end user can see the difference.
"""

import json
import logging
import os
import re
import streamlit as st
from uuid import uuid4
from typing import List, Any, Dict, Optional

logger = logging.getLogger(__name__)

# Module-level singleton persistence backends for the three engines below —
# one JSONFileBackend instance per engine, shared across every request this
# process handles (each engine is otherwise instantiated fresh per request,
# so without an explicitly wired shared backend its "memory"/"audit trail"
# component would silently reset on every single message).
_design_memory_backend = None
_config_session_backend = None
_ts_session_backend = None


def _get_design_memory_backend():
    global _design_memory_backend
    if _design_memory_backend is None:
        from core.design_engine.memory import JSONFileBackend
        _design_memory_backend = JSONFileBackend()
    return _design_memory_backend


def _get_config_session_backend():
    global _config_session_backend
    if _config_session_backend is None:
        from core.config_engine.audit import JSONFileBackend
        _config_session_backend = JSONFileBackend()
    return _config_session_backend


def _get_ts_session_backend():
    global _ts_session_backend
    if _ts_session_backend is None:
        from core.troubleshooting.memory import JSONFileBackend
        _ts_session_backend = JSONFileBackend()
    return _ts_session_backend


# ──────────────────────────────────────────────────────────────────────────────
# MODES — single source of truth for persona, routing behaviour, and visuals
# ──────────────────────────────────────────────────────────────────────────────
MODES: Dict[str, Dict[str, Any]] = {
    "configure": {
        "key": "configure",
        "label": "Configure Network & Services",
        "short": "Configure",
        "emoji": "⚙️",
        "color": "#2563eb",
        "device_facing": False,   # advisory/generative, does not execute on its own
        "persona": (
            "You are AI Net Studio Copilot operating in CONFIGURATION mode. "
            "Think and respond strictly as a senior network configuration engineer whose job "
            "is to CONFIGURE networks and services correctly and safely. For every request: "
            "(1) restate the configuration goal in one line; "
            "(2) produce the exact device configuration needed, generated for the specific "
            "platform/vendor of the target devices in context — never invent values you can "
            "derive from context, and ask if a required value is missing; "
            "(3) give the ordered apply steps; "
            "(4) always include validation / show commands to confirm the change; "
            "(5) always include a rollback / backout plan. "
            "Prefer idempotent, least-disruptive changes. Do not drift into open-ended "
            "troubleshooting or high-level architecture unless needed to justify a config choice."
        ),
    },
    "troubleshoot": {
        "key": "troubleshoot",
        "label": "Troubleshoot & Fix",
        "short": "Troubleshoot",
        "emoji": "🔧",
        "color": "#f59e0b",
        "device_facing": True,    # runs the diagnostic/fix loop against selected devices
        "persona": (
            "You are AI Net Studio Copilot operating in TROUBLESHOOT & FIX mode. "
            "Think and respond strictly as a diagnostic network SRE performing root-cause analysis. "
            "Work the problem methodically: "
            "(1) list the most likely hypotheses ranked by probability; "
            "(2) specify the exact diagnostic show/debug commands to confirm or rule out each one; "
            "(3) interpret the evidence; "
            "(4) identify the root cause; "
            "(5) propose the minimal corrective action with the fix commands AND the commands to "
            "verify the fix afterwards. Never jump to a fix without a diagnostic path. "
            "Only ever act on devices that have been explicitly selected."
        ),
    },
    "design": {
        "key": "design",
        "label": "Design Network Architecture",
        "short": "Design",
        "emoji": "🏗️",
        "color": "#8b5cf6",
        "device_facing": False,   # advisory, never touches live devices
        "persona": (
            "You are AI Net Studio Copilot operating in DESIGN mode. "
            "Think and respond strictly as a network architect. Do NOT lead with device CLI. "
            "For every request: "
            "(1) clarify the requirements and constraints (scale, sites, redundancy, security, growth); "
            "(2) propose one or more architecture options with a clear recommendation; "
            "(3) describe the topology, the addressing / subnetting plan, the routing & switching "
            "design, redundancy and failure domains, and security segmentation; "
            "(4) lay out the trade-offs (cost, complexity, scalability) of each option; "
            "(5) give a phased implementation roadmap. Use text diagrams where they help. "
            "Stay vendor-neutral unless the target devices imply a vendor."
        ),
    },
}

DEFAULT_MODE = "configure"


def normalize_mode(value: Any) -> str:
    """Resolve any stored/legacy mode value to a canonical mode key."""
    if not value:
        return DEFAULT_MODE
    s = str(value).strip().lower()
    if s in MODES:
        return s
    if "design" in s:
        return "design"
    if "troub" in s or "fix" in s:
        return "troubleshoot"
    if "config" in s:
        return "configure"
    return DEFAULT_MODE


def get_mode(value: Any) -> Dict[str, Any]:
    return MODES[normalize_mode(value)]


# ── cross-refresh persistence ────────────────────────────────────────────
# Streamlit's st.session_state lives only as long as the browser tab's
# WebSocket connection. A hard page refresh (F5, navigating away and back)
# doesn't resume that connection — it opens a brand-new one, so Streamlit
# hands the script a completely empty session_state, same as a first-ever
# visit. Nothing about that is a bug in st.session_state; it just means
# anything the user should still see after a refresh (chat history, which
# devices were selected, which mode was active) has to live somewhere
# OTHER than session_state. Before this, it lived nowhere, so it reset to
# blank on every refresh. This mirrors the same opt-in JSONFileBackend
# pattern core/troubleshooting/memory.py and core/design_engine/memory.py
# already use for their own state.
_COPILOT_STATE_PATH = ".ai_net_studio_copilot_state.json"


def _load_persisted_copilot_state() -> Dict[str, Any]:
    try:
        if os.path.exists(_COPILOT_STATE_PATH):
            with open(_COPILOT_STATE_PATH) as f:
                return json.load(f)
    except Exception as exc:
        logger.debug("Copilot state restore skipped: %s", exc)
    return {}


def _persist_copilot_state() -> None:
    try:
        data = {
            "conversations": st.session_state.get("copilot_conversations", []),
            "active_conversation_id": st.session_state.get("copilot_active_conversation_id"),
            "selected_devices": st.session_state.get("copilot_selected_devices", []),
            "ai_mode": st.session_state.get("copilot_ai_mode"),
            "autonomous_mode": st.session_state.get("copilot_autonomous_mode", False),
        }
        with open(_COPILOT_STATE_PATH, "w") as f:
            json.dump(data, f, default=str)
    except Exception as exc:
        logger.debug("Copilot state persist skipped: %s", exc)


def _rerun() -> None:
    """st.rerun() immediately halts this script run — any state mutated
    just before it must be persisted BEFORE calling it, not after."""
    _persist_copilot_state()
    st.rerun()


def initialize_session_state():
    """Initialize all copilot-related session state. On a brand-new session
    (nothing set yet — the hard-refresh case described above) restores
    conversations/selected devices/mode/autonomous-mode from disk instead
    of resetting everything to blank."""
    if "copilot_conversations" not in st.session_state:
        restored = _load_persisted_copilot_state()
        st.session_state["copilot_conversations"] = restored.get("conversations") or []
        st.session_state["copilot_active_conversation_id"] = restored.get("active_conversation_id")
        st.session_state["copilot_selected_devices"] = restored.get("selected_devices") or []
        st.session_state["copilot_ai_mode"] = restored.get("ai_mode") or ""
        st.session_state["copilot_autonomous_mode"] = bool(restored.get("autonomous_mode"))
    if "copilot_uploaded_image" not in st.session_state:
        st.session_state["copilot_uploaded_image"] = None
    # Default to a real mode (never "None") and migrate any legacy value.
    if "copilot_ai_mode" not in st.session_state or not st.session_state.get("copilot_ai_mode"):
        st.session_state["copilot_ai_mode"] = DEFAULT_MODE
    else:
        st.session_state["copilot_ai_mode"] = normalize_mode(st.session_state["copilot_ai_mode"])
    if "copilot_autonomous_mode" not in st.session_state:
        st.session_state["copilot_autonomous_mode"] = False
    if "copilot_main_input" not in st.session_state:
        st.session_state["copilot_main_input"] = ""
    if "cp_show_upload" not in st.session_state:
        st.session_state["cp_show_upload"] = False
    if "cp_show_mode" not in st.session_state:
        st.session_state["cp_show_mode"] = False
    if "cp_show_devs" not in st.session_state:
        st.session_state["cp_show_devs"] = False
    if "copilot_action_state" not in st.session_state:
        st.session_state["copilot_action_state"] = {}


def clear_copilot_main_input() -> None:
    """Clear the composer text input without tripping Streamlit widget-state guards."""
    try:
        st.session_state.pop("copilot_main_input", None)
    except Exception:
        try:
            st.session_state["copilot_main_input"] = ""
        except Exception:
            pass


def _normalize_selected_devices(selected_devices: Any) -> List[str]:
    normalized: List[str] = []
    for item in selected_devices or []:
        if isinstance(item, str):
            value = item.strip()
            if " (" in value and value.endswith(")"):
                maybe_ip = value.rsplit("(", 1)[1][:-1]
                normalized.append(maybe_ip)
            else:
                normalized.append(value)
        elif isinstance(item, dict):
            ip = item.get("ip") or item.get("value") or ""
            if ip:
                normalized.append(str(ip))
    return normalized


def _device_label(device: Any) -> str:
    return f"{getattr(device, 'hostname', None) or device.ip} ({device.ip})"


def _conversation_title_from_message(message: str) -> str:
    clean = " ".join(message.split())
    if len(clean) <= 28:
        return clean or "New chat"
    return clean[:25] + "..."


def _conversation_snippet(conversation: dict) -> str:
    messages = conversation.get("messages", [])
    if not messages:
        return "Start a new conversation"
    last = messages[-1]
    prefix = "You: " if last.get("role") == "user" else "Copilot: "
    clean = " ".join(last.get("content", "").split())
    if len(clean) <= 32:
        return prefix + clean
    return prefix + clean[:29] + "..."


def _current_conversation():
    conversations = st.session_state.get("copilot_conversations", [])
    active_id = st.session_state.get("copilot_active_conversation_id")
    if not conversations:
        new_conversation = {
            "id": str(uuid4()),
            "title": "New chat",
            "messages": [],
        }
        conversations.append(new_conversation)
        st.session_state["copilot_conversations"] = conversations
        st.session_state["copilot_active_conversation_id"] = new_conversation["id"]
        return new_conversation

    current = next((c for c in conversations if c.get("id") == active_id), None)
    if current is None:
        current = conversations[-1]
        st.session_state["copilot_active_conversation_id"] = current["id"]
    return current


def load_approved_devices() -> List[Any]:
    """Load approved devices from the discovery engine."""
    try:
        from core.device_discovery import get_discovery_engine
        _disc = get_discovery_engine()
        return _disc.get_approved() or []
    except Exception as _e:
        logger.warning(f"Failed to load approved devices: {_e}")
        return []


def _load_device_context() -> str:
    """Build a compact device inventory context for the copilot prompt."""
    try:
        from core.device_discovery import get_discovery_engine

        disc = get_discovery_engine()
        approved_devs = disc.get_approved() or []
    except Exception as exc:
        logger.warning(f"Failed to build device context: {exc}")
        return ""

    if not approved_devs:
        return ""

    lines = []
    for device in approved_devs:
        hostname = getattr(device, "hostname", None) or getattr(device, "name", None) or device.ip
        device_type = getattr(device, "device_type", None) or "unknown"
        open_ports = getattr(device, "open_ports", None) or []
        lines.append(f"- {hostname} ({device.ip}) type={device_type} ports={open_ports}")

    return "Approved network devices:\n" + "\n".join(lines)


def build_copilot_prompt(
    user_text: str,
    ai_mode: Optional[str] = None,
    selected_devices: Optional[List[str]] = None,
    device_context: str = "",
    conversation_history: Optional[List[dict]] = None,
    autonomous_mode: bool = False,
) -> str:
    """Construct a rich, mode-aware prompt for the copilot chat."""
    context_parts: List[str] = []
    if ai_mode:
        # Preserved verbatim for backward-compatibility / observability.
        context_parts.append(f"AI Mode: {ai_mode}")

    selected = selected_devices or []
    if selected:
        context_parts.append(f"Target devices: {', '.join(selected)}")

    if device_context:
        context_parts.append(device_context)

    context_parts.append(
        "Autonomous mode: enabled" if autonomous_mode else "Autonomous mode: disabled"
    )

    history_lines: List[str] = []
    for message in (conversation_history or [])[-8:]:
        role = message.get("role", "")
        if role == "user":
            history_lines.append(f"User: {message.get('content', '')}")
        elif role == "assistant":
            history_lines.append(f"Assistant: {message.get('content', '')}")

    # Mode persona drives *how the AI thinks*. Falls back to a neutral expert.
    mode = get_mode(ai_mode) if ai_mode else None
    if mode:
        sys_prompt = mode["persona"]
    else:
        sys_prompt = (
            "You are Network Intelligence Copilot, an expert network operations AI. "
            "Provide technically accurate, concise responses. Include specific CLI commands "
            "when relevant. Be professional and enterprise-grade."
        )

    if context_parts:
        sys_prompt = f"{sys_prompt}\n\n" + "\n\n".join(context_parts)

    if history_lines:
        sys_prompt = f"{sys_prompt}\n\nConversation so far:\n" + "\n".join(history_lines)

    return f"{sys_prompt}\n\nUser question: {user_text}"


def _resolve_target_devices(approved_devs: List[Any], selected_ips: List[str]) -> List[Any]:
    """STRICT scoping: only ever return devices the user explicitly selected.

    No silent fallback to 'all approved devices'. If nothing is selected, the
    caller gets an empty list and must stay advisory / refuse to execute.
    """
    if not selected_ips:
        return []
    selected_set = set(selected_ips)
    return [dev for dev in approved_devs if getattr(dev, "ip", None) in selected_set]


def _build_intent_engine(call_ai_fn, devices: List[Any]):
    from core.intent_engine import IntentEngine

    return IntentEngine(ai_call=call_ai_fn, approved_devices=devices)


def _make_troubleshooting_gateway(call_ai_fn, devices: List[Any]):
    """Build a VendorGateway wired to the platform SSH transport + detection hints.

    The transport reuses IntentEngine's read-only SSH collector; the hint provider
    exposes whatever identity attributes a device carries so adapters can detect
    the vendor. Unknown devices fall back to the generic adapter automatically.
    """
    from core.vendor import VendorGateway

    ie = _build_intent_engine(call_ai_fn, devices)

    def send(device, cmds):
        try:
            dr = ie._ssh_collect(device, list(cmds))
        except Exception as exc:
            return {c: f"error[transport]: {exc}" for c in cmds}
        if not dr.connected:
            # _ssh_collect() never raises on a connection failure (bad
            # host/port/credentials, GNS3 tunnel down, timeout — anything)
            # — it swallows the exception into dr.error and returns
            # normally with dr.outputs == {}. Silently returning {} here
            # made every command look like it ran and simply found nothing,
            # indistinguishable from a real device reporting no state —
            # the exact "no observations collected, no explanation why"
            # symptom this was causing. Log it clearly and tag the output
            # with the SAME "error[...]:" prefix core.troubleshooting.
            # engine._ingest_output() already recognizes as "not evidence"
            # (see its `output.startswith("error[")` check), so a
            # connection failure is skipped cleanly everywhere instead of
            # being fed to the parser/LLM as if it were real CLI output.
            logger.warning("SSH connection to %s failed: %s", device.ip, dr.error)
            return {c: f"error[transport]: connection failed to {device.ip} - {dr.error}" for c in cmds}
        return dict(dr.outputs)

    def hint_provider(device):
        hints = {}
        for attr in ("device_type", "hostname", "os", "vendor", "platform",
                     "model", "sys_descr", "description", "version"):
            val = getattr(device, attr, None)
            if val:
                hints[attr] = val
        return hints

    return VendorGateway(send=send, hint_provider=hint_provider)


def _extract_provided(call_ai_fn, awaiting: List[dict], answer_text: str) -> dict:
    """Map a user's free-text answer onto the specific missing fields (ask-never-assume).
    Returns {field: value} for whatever the answer supplies; unknown fields are skipped."""
    import json as _json
    fields = ", ".join(a.get("field", "") for a in awaiting)
    prompt = (
        "The user was asked for missing configuration inputs. Map their answer to the "
        "fields. Only include fields the answer actually provides.\n\n"
        f"FIELDS: {fields}\n"
        f"QUESTIONS: {_json.dumps(awaiting)}\n"
        f"USER ANSWER: {answer_text}\n\n"
        'Return STRICT JSON only: {"<field>": "<value>"} — no prose.'
    )
    try:
        raw = (call_ai_fn(prompt) or "").strip().replace("```json", "").replace("```", "").strip()
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            data = _json.loads(raw[start:end + 1])
            return {k: v for k, v in data.items() if v not in (None, "", "null")}
    except Exception:
        pass
    return {}


def _apply_cfg(call_ai_fn, pending_state) -> List[str]:
    """Apply an APPROVED configuration package to each target device. Human-gated."""
    import re as _re
    devices = pending_state.get("devices", [])
    ip_to_dev = {getattr(d, "ip", None): d for d in devices}
    ie = _build_intent_engine(call_ai_fn, devices)
    summary: List[str] = []
    for art in pending_state.get("artifacts", []):
        dev = ip_to_dev.get(art.get("device"))
        cfg = [_re.sub(r"^\(on [^)]+\)\s*", "", c).strip()
               for c in art.get("config", []) if c and c.strip()]
        if dev is None or not cfg:
            continue
        try:
            ie._ssh_apply(dev, cfg)
            summary.append(f"✅ Applied on {getattr(dev, 'hostname', None) or dev.ip}")
        except Exception as exc:
            summary.append(f"⚠️ {getattr(dev, 'hostname', None) or dev.ip}: {exc}")
    return summary or ["ℹ️ No configuration commands resolved to apply."]


_NEIGHBOR_STATE_ROW = re.compile(
    r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s+\d+\s+"
    r"(?P<state>FULL|2-?WAY|EXSTART|EXCHANGE|LOADING|INIT|ATTEMPT|DOWN)(?:/\S+)?"
    r"\s+\S+\s+\S+\s+(?P<iface>\S+)", re.I)


def _not_full_neighbors(protocol: str, output: str) -> List[Dict[str, str]]:
    """Deterministic scan of FRESH, just-re-collected verification output for
    any OSPF neighbor not in FULL state — reuses the same neighbor-row
    vocabulary IosLikeAdapter's own parser uses (core/vendor/adapters/
    cisco_ios_like.py), so no new fragile heuristic is introduced. Returns
    structured {"ip", "state", "interface"} dicts (interface is the LOCAL
    interface facing that neighbor, the last column of a real "show ip ospf
    neighbor" row) so a caller can both warn a human AND scope a follow-up
    investigation into exactly that remaining adjacency."""
    if protocol != "ospf":
        return []
    out = []
    for m in _NEIGHBOR_STATE_ROW.finditer(output or ""):
        state = m.group("state").upper().replace("-", "")
        if state != "FULL":
            out.append({"ip": m.group("ip"), "state": state, "interface": m.group("iface")})
    return out


def _verification_state_warning(protocol: str, output: str) -> str:
    """Catches exactly the case where a fix resolves ONE neighbor but a
    second, separate adjacency on the same device is still stuck: the report
    can legitimately say "resolved" for the hypothesis that was tested, while
    the RAW verification text right below it still shows a neighbor stuck in
    a non-FULL state — something a human skimming past two similar-looking
    table rows can easily miss. This never blocks or auto-decides anything;
    it only makes an inconsistency in the evidence impossible to miss at the
    exact point the human is asked to confirm."""
    not_full = _not_full_neighbors(protocol, output)
    if not not_full:
        return ""
    total = len(_NEIGHBOR_STATE_ROW.findall(output or ""))
    details = "; ".join(f"{n['ip']} still {n['state']}" for n in not_full)
    return (f"⚠️ Verification shows {len(not_full)} of {total} neighbor(s) NOT yet FULL "
           f"({details}) — this fix may have only resolved PART of the issue.")


def _infer_protocol(text: str) -> str:
    """Minimal keyword fallback — same technique
    core.troubleshooting.engine.TroubleshootingEngine._detect_protocol uses when
    no IntentEngine-driven scenario detection is available. Good enough for
    tagging an operational-memory record; not used for any safety decision."""
    q = (text or "").lower()
    for p in ("ospf", "bgp", "eigrp", "stp", "vlan", "acl", "nat"):
        if p in q:
            return p
    return ""


def _apply_ts_fix(call_ai_fn, pending_state) -> Dict[str, Any]:
    """Apply an approved troubleshooting fix to the target device(s). Human-gated,
    and — GOVERNANCE-gated: core.governance.engine.GovernanceEngine (already
    built, previously never invoked from this path) checks compliance/
    authorization/risk/rollback readiness BEFORE any command reaches a device.
    Blocking findings (a non-compliant command, an explicit policy denial) stop
    the apply for that device entirely; non-blocking concerns (risk, missing
    rollback, simulation not performed) are surfaced as warnings, matching the
    engine's own lenient-by-design default (strict=True is a deliberate future
    step, not enabled here since no operator identity is threaded through this
    UI yet).

    Also re-collects the verification commands immediately after a successful
    apply, so the report's own verification plan is actually executed instead
    of only ever being displayed — the caller uses this to show fresh
    post-fix state and ask the user to confirm resolution (core.knowledge.
    compiler.supply_chain.NetworkIntelligenceSupplyChain.record_resolution /
    record_failed_resolution is only ever called on that explicit human
    confirmation — see _record_ts_outcome — never inferred here).

    Returns {"summary_lines": [...], "verification_output": {device_ip: text},
    "applied_any": bool}.
    """
    from core.governance.engine import get_governance_engine
    from core.governance.contract import GovernanceStatus

    devices = pending_state.get("devices", [])
    target_ip = pending_state.get("target_ip", "")
    root_cause = pending_state.get("root_cause", "")
    ie = _build_intent_engine(call_ai_fn, devices)
    # fix/rollback commands are plain config lines; strip any "(on X)" prefix defensively
    import re as _re
    cfg = [_re.sub(r"^\(on [^)]+\)\s*", "", c).strip()
           for c in pending_state.get("fix_commands", []) if c and c.strip()]
    rollback = [_re.sub(r"^\(on [^)]+\)\s*", "", c).strip()
               for c in pending_state.get("rollback_commands", []) if c and c.strip()]
    verification_cmds = [c.strip() for c in pending_state.get("verification_commands", []) if c and c.strip()]
    targets = [d for d in devices if getattr(d, "ip", None) == target_ip] or devices

    if not cfg:
        return {"summary_lines": ["ℹ️ No config commands resolved from the fix."],
               "verification_output": {}, "applied_any": False}

    gov = get_governance_engine()
    protocol = _infer_protocol(root_cause)
    summary: List[str] = []
    verification_output: Dict[str, str] = {}
    verification_warnings: Dict[str, str] = {}
    verification_targets: Dict[str, List[Dict[str, str]]] = {}
    applied_any = False
    for dev in targets:
        label = getattr(dev, "hostname", None) or dev.ip
        contract = gov.govern(device=dev.ip, commands=cfg, intent=root_cause,
                              protocol=protocol,
                              rollback_commands=rollback, strict=False)
        if contract.status in (GovernanceStatus.COMPLIANCE_FAILURE, GovernanceStatus.REJECTED):
            reasons = "; ".join(contract.blocking_conditions) or "policy denied this change."
            summary.append(f"🛑 Blocked on {label}: {reasons}")
            continue
        for w in contract.warnings:
            summary.append(f"⚠️ {label}: {w}")
        try:
            ie._ssh_apply(dev, cfg)
            summary.append(f"✅ Applied on {label}")
            applied_any = True
            if verification_cmds:
                try:
                    dr = ie._ssh_collect(dev, verification_cmds)
                    out = "\n".join(dr.outputs.values())
                    verification_output[dev.ip] = out
                    not_full = _not_full_neighbors(protocol, out)
                    if not_full:
                        verification_targets[dev.ip] = not_full
                        verification_warnings[dev.ip] = _verification_state_warning(protocol, out)
                except Exception as exc:
                    verification_output[dev.ip] = f"(verification collection failed: {exc})"
        except Exception as exc:
            summary.append(f"⚠️ {label}: {exc}")

    if not summary:
        summary = ["ℹ️ No config commands resolved to apply."]
    return {"summary_lines": summary, "verification_output": verification_output,
           "verification_warnings": verification_warnings,
           "verification_targets": verification_targets, "applied_any": applied_any}


def _record_ts_outcome(pending_state, success: bool) -> str:
    """Human-confirmed learning feedback: the ONE call site in the live runtime
    that invokes core.knowledge.compiler.supply_chain.NetworkIntelligenceSupplyChain's
    record_resolution/record_failed_resolution + learn_from_incident — all
    already built and tested (tests/test_supply_chain.py), never previously
    invoked outside their own tests. A human confirming/denying resolution
    (never an automatic keyword guess against free-text success_criteria) is
    what triggers this, so the learning system is only ever trained on ground
    truth, not a fragile inference."""
    from core.knowledge.compiler.supply_chain import NetworkIntelligenceSupplyChain

    root_cause = pending_state.get("root_cause", "")
    protocol = _infer_protocol(root_cause)
    target_ip = pending_state.get("target_ip", "")
    devices = pending_state.get("devices", [])
    device_ip = target_ip or (getattr(devices[0], "ip", "") if devices else "")
    cfg = pending_state.get("fix_commands", [])

    sc = NetworkIntelligenceSupplyChain()
    try:
        if success:
            sc.record_resolution(root_cause, device_ip, commands=cfg, protocol=protocol)
        else:
            sc.record_failed_resolution(
                root_cause, device_ip, reason="Operator reported the issue was not resolved.",
                commands=cfg, protocol=protocol)
        sc.learn_from_incident(success=success, intent=root_cause, device=device_ip,
                               protocol=protocol, commands=cfg)
    except Exception as exc:
        return f"⚠️ Outcome recorded locally, but learning update failed: {exc}"

    # Write the confirmed terminal outcome back onto the live Session object
    # itself (pass-by-reference — the same object report.to_markdown() and
    # session_memory.save() already touched), so ResolutionStatus stops
    # sitting at RESOLVED_PENDING_APPROVAL forever once a human has actually
    # confirmed whether the deployed fix worked.
    session = pending_state.get("session")
    if session is not None:
        session.close(resolved=success)
    return ("✅ Recorded as resolved — this outcome now informs future troubleshooting."
           if success else
           "📝 Recorded as unresolved — flagged for review; a recurring pattern here "
           "will be surfaced automatically.")


def _continue_investigation_if_needed(call_ai_fn, pending_state) -> Dict[str, Any]:
    """After a human answers Confirm/Deny for the fix that was just applied,
    automatically continue investigating any OTHER neighbor _apply_ts_fix's
    fresh verification found still not FULL (see _not_full_neighbors) — it
    may have an entirely different root cause than the one just fixed, and a
    human shouldn't have to notice that and manually re-type a new question.
    Read-only investigation runs immediately here, mirroring how diagnostic
    steps WITHIN one investigation already chain automatically
    (TroubleshootingEngine.run()'s plan->collect->analyze loop); deploying
    whatever fix this turns up (if any) still always requires its own
    explicit human approval via the normal "ts_fix" Deploy/Discard flow,
    exactly like every other fix in this UI — only the "notice and
    investigate" step is automatic, never "apply".

    Carries `excluded_causes` forward from pending_state and appends the
    root cause that was just tried — a real production report showed the
    fix that JUST failed verification (e.g. an MTU-mismatch fix, still
    stuck afterward) getting re-proposed identically on every subsequent
    "still not FULL" cycle, since each cycle built a completely fresh
    TroubleshootingEngine.run() with no memory that this exact cause had
    already been deployed and confirmed not to work for this exact target.
    Passing it through TroubleshootingEngine.run()'s own excluded_causes
    parameter eliminates that hypothesis outright on re-seed instead of
    letting it win again on its unchanged compiled prior.

    Returns {"messages": [chat message dicts to append],
    "next_pending_state": {} or a fresh "ts_fix" pending_state}."""
    verification_targets = pending_state.get("verification_targets") or {}
    target = next((t for targets in verification_targets.values() for t in targets), None)
    if target is None:
        return {"messages": [], "next_pending_state": {}}

    devices = pending_state.get("devices", [])
    query = (f"why is the OSPF neighbor {target['ip']} on interface "
            f"{target['interface']} stuck in {target['state']}")
    prior_root_cause = pending_state.get("root_cause", "")
    excluded_causes = list(pending_state.get("excluded_causes", []))
    if prior_root_cause and prior_root_cause not in excluded_causes:
        excluded_causes.append(prior_root_cause)
    try:
        from core.troubleshooting import TroubleshootingEngine, TSConfig
        gw = _make_troubleshooting_gateway(call_ai_fn, devices)
        tse = TroubleshootingEngine(ai_call=call_ai_fn, devices=devices, gateway=gw,
                                    config=TSConfig(max_steps=6),
                                    session_store=_get_ts_session_backend())
        report = tse.run(query, excluded_causes=excluded_causes)
    except Exception as exc:
        return {"messages": [{
            "role": "assistant",
            "content": f"⚠️ Could not continue investigating {target['ip']} ({target['interface']}): {exc}",
            "mode": "troubleshoot",
        }], "next_pending_state": {}}

    content = ("🔁 **Continuing — investigating the remaining issue "
              f"({target['ip']} on {target['interface']}, still {target['state']}):**\n\n"
              + report.to_markdown())
    messages = [{"role": "assistant", "content": content, "mode": "troubleshoot"}]

    s = report.session
    next_state: Dict[str, Any] = {}
    if s.fix and s.fix.config_commands:
        target_ip = s.goal.devices[0] if (s.goal and s.goal.devices) else ""
        next_state = {
            "kind": "ts_fix",
            "root_cause": s.fix.root_cause,
            "fix_commands": list(s.fix.config_commands),
            "rollback_commands": list(s.fix.rollback_commands),
            "verification_commands": list(s.verification.commands) if s.verification else [],
            "target_ip": target_ip,
            "devices": devices,
            "session": s,
            "excluded_causes": excluded_causes,
        }
    return {"messages": messages, "next_pending_state": next_state}


def _render_assistant_message(content: str, mode_key: Optional[str]) -> None:
    """Render an assistant bubble with a mode badge + accent so replies are distinguishable."""
    mode = get_mode(mode_key) if mode_key else None
    if mode:
        accent = mode["color"]
        badge = (
            f"<span style='background:{accent};color:#fff;border-radius:6px;"
            f"padding:1px 8px;font-size:11px;font-weight:700;margin-left:8px;'>"
            f"{mode['emoji']} {mode['short']} mode</span>"
        )
    else:
        accent = "#3fd27a"
        badge = ""
    st.markdown(f"""
    <div class="copilot-msg-ai" style="border-left-color:{accent};">
        <div class="copilot-msg-label" style="color:{accent};">🤖 Copilot {badge}</div>
        <div class="copilot-msg-text">{content}</div>
    </div>
    """, unsafe_allow_html=True)


def render_copilot_page(call_ai_fn):
    """Main copilot page renderer."""
    initialize_session_state()

    approved_devs = load_approved_devices()
    conversations = st.session_state.get("copilot_conversations", [])
    active_conversation = _current_conversation()
    device_context = _load_device_context()
    action_states = st.session_state.setdefault("copilot_action_state", {})

    main_col, right_col = st.columns([3, 1])

    with right_col:
        st.markdown("## 💬 Copilot History")
        col_new, col_clear = st.columns([1, 1])
        with col_new:
            if st.button("➕ New chat", use_container_width=True, key="cp_sidebar_new"):
                new_conversation = {
                    "id": str(uuid4()),
                    "title": "New chat",
                    "messages": [],
                }
                conversations.append(new_conversation)
                st.session_state["copilot_conversations"] = conversations
                st.session_state["copilot_active_conversation_id"] = new_conversation["id"]
                action_states[new_conversation["id"]] = {}
                _rerun()
        with col_clear:
            if st.button("🗑 Clear all", use_container_width=True, key="cp_sidebar_clear"):
                st.session_state["copilot_conversations"] = []
                st.session_state["copilot_active_conversation_id"] = None
                st.session_state["copilot_action_state"] = {}
                _rerun()

        st.markdown("---")
        if not conversations:
            st.caption("No saved chats yet")
        else:
            for conversation in conversations:
                is_active = conversation.get("id") == active_conversation.get("id")
                title = conversation.get("title", "New chat")
                snippet = _conversation_snippet(conversation)
                button_label = f"{'● ' if is_active else ''}{title}"
                if st.button(button_label, key=f"conv_{conversation['id']}", use_container_width=True):
                    st.session_state["copilot_active_conversation_id"] = conversation["id"]
                    _rerun()
                st.markdown(f"<div style='margin:0 0 10px 12px; color:#94a3b8; font-size:12px;'>{snippet}</div>", unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### ⚙️ Current context")
        _ctx_mode = get_mode(st.session_state.get("copilot_ai_mode"))
        st.markdown(
            f"**Mode:** <span style='color:{_ctx_mode['color']};font-weight:700;'>"
            f"{_ctx_mode['emoji']} {_ctx_mode['label']}</span>",
            unsafe_allow_html=True,
        )
        selected_ips = _normalize_selected_devices(st.session_state.get("copilot_selected_devices", []))
        if selected_ips:
            st.markdown(f"**Devices:** {', '.join(selected_ips)}")
        else:
            st.markdown("**Devices:** None selected")
        if st.session_state.get("copilot_uploaded_image"):
            st.markdown(f"**Image:** {st.session_state['copilot_uploaded_image'].name}")

    with main_col:
        # ── CSS Styling ────────────────────────────────────────────────────────────
        st.markdown("""
        <style>
    .copilot-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 32vh;
        padding: 18px 20px 6px 20px;
        text-align: center;
    }
    .copilot-logo {
        width: 92px;
        height: 92px;
        background: linear-gradient(135deg, #3b82f6, #2563eb);
        border-radius: 28px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 46px;
        margin-bottom: 18px;
        box-shadow: 0 20px 60px rgba(37, 99, 235, 0.3);
    }
    .copilot-title {
        font-size: 34px;
        font-weight: 800;
        color: #f0f4fa;
        letter-spacing: -0.02em;
        margin: 0 0 10px 0;
        line-height: 1.1;
    }
    .copilot-subtitle {
        font-size: 15px;
        color: #8b95a8;
        margin: 0 0 12px 0;
        max-width: 620px;
        line-height: 1.6;
    }
    .copilot-msg-user {
        background: #0e151f;
        border-left: 4px solid #2563eb;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 12px;
        font-size: 14px;
    }
    .copilot-msg-ai {
        background: #0e151f;
        border-left: 4px solid #3fd27a;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 12px;
        font-size: 14px;
    }
    .copilot-msg-label {
        font-weight: 600;
        margin-bottom: 4px;
        font-size: 12px;
    }
    .copilot-msg-user .copilot-msg-label { color: #4c8dff; }
    .copilot-msg-text {
        color: #c8d6e8;
        line-height: 1.6;
        white-space: pre-wrap;
    }

    /* ── Sticky composer: keep +, mode, devices, input & Send reachable while
       scrolling long conversations. Targets the container that holds the anchor. */
    div[data-testid="stVerticalBlock"]:has(> div.element-container div.cp-sticky-anchor) {
        position: sticky;
        top: 0.4rem;
        z-index: 999;
        background: #0b1220;
        padding: 10px 12px 6px 12px;
        border: 1px solid #1e293b;
        border-radius: 14px;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.45);
    }
    div.cp-sticky-anchor { height: 0; margin: 0; padding: 0; }
    </style>
    """, unsafe_allow_html=True)

        # ── Hero Section ────────────────────────────────────────────────────────────
        st.markdown("""
    <div class="copilot-container">
        <div class="copilot-logo">🧠</div>
        <h1 class="copilot-title">Network Intelligence Copilot</h1>
        <p class="copilot-subtitle">Pick a mode, scope your devices, and describe what you want to configure, troubleshoot, or design.</p>
    </div>
    """, unsafe_allow_html=True)

        selected_ips = _normalize_selected_devices(st.session_state.get("copilot_selected_devices", []))
        active_mode = get_mode(st.session_state.get("copilot_ai_mode"))

        # ── Sticky composer container ───────────────────────────────────────────
        composer = st.container()
        with composer:
            st.markdown("<div class='cp-sticky-anchor'></div>", unsafe_allow_html=True)

            # Device scope banner
            scope_color = "#16a34a" if selected_ips else "#dc2626"
            if selected_ips:
                scope_msg = f"🎯 AI Scope: {len(selected_ips)} device(s) selected → {', '.join(selected_ips)}"
            else:
                scope_msg = "🛑 AI Scope: No devices selected — device actions are disabled until you scope to one or more devices."
            st.markdown(
                f"<div style='background:#0c1826;border-left:3px solid {scope_color};border-radius:6px;"
                f"padding:.45rem .9rem;margin:.2rem 0 .5rem 0;color:#cbd5e1;font-size:.82rem'>{scope_msg}</div>",
                unsafe_allow_html=True,
            )

            # Autonomous toggle only matters in the device-facing troubleshoot mode
            _ctrl_col1, _ctrl_col2 = st.columns([4, 1])
            with _ctrl_col1:
                if active_mode["device_facing"]:
                    st.checkbox(
                        "🤖 Autonomous mode — run the full diagnosis loop with verification and safe remediation guidance",
                        key="copilot_autonomous_mode",
                    )
                else:
                    st.session_state["copilot_autonomous_mode"] = False
                    st.caption(f"{active_mode['emoji']} **{active_mode['label']}** — advisory mode (no device execution).")
            with _ctrl_col2:
                if st.button("🗑 Clear", key="cp_clear_chat", use_container_width=True):
                    active_conversation["messages"] = []
                    active_conversation["title"] = "New chat"
                    _rerun()

            # Composer button bar
            _bar_col1, _bar_col2, _bar_col3, _bar_col4, _bar_col5 = st.columns([0.55, 1.5, 1.35, 4.5, 0.8])

            with _bar_col1:
                if st.button("➕", key="cp_btn_add", use_container_width=True, help="Upload image"):
                    st.session_state["cp_show_upload"] = not st.session_state.get("cp_show_upload", False)

            with _bar_col2:
                if st.button(f"{active_mode['emoji']} {active_mode['short']}", key="cp_btn_mode",
                             use_container_width=True, help="Select AI mode"):
                    st.session_state["cp_show_mode"] = not st.session_state.get("cp_show_mode", False)

            with _bar_col3:
                _dev_count = len(selected_ips)
                if st.button(f"🖧 Devices ({_dev_count})", key="cp_btn_devs",
                             use_container_width=True, help="Select approved devices"):
                    st.session_state["cp_show_devs"] = not st.session_state.get("cp_show_devs", False)

            with _bar_col4:
                _input_text = st.text_area(
                    label="copilot_input",
                    label_visibility="collapsed",
                    placeholder="What do you want to do today in your network?",
                    key="copilot_main_input",
                    height=120,
                )

            with _bar_col5:
                _send_clicked = st.button("Send", key="cp_send", use_container_width=True)
                st.caption("Ready" if _input_text else "Type…")

        # ── Expandable pickers (rendered below the sticky bar, not sticky) ───────
        if st.session_state.get("cp_show_upload"):
            st.markdown("### 📸 Upload Image")
            _uploaded_file = st.file_uploader(
                label="upload_image",
                label_visibility="collapsed",
                type=["jpg", "jpeg", "png", "gif"],
                key="copilot_file_uploader",
            )
            if _uploaded_file:
                st.session_state["copilot_uploaded_image"] = _uploaded_file
                st.success(f"✅ {_uploaded_file.name} uploaded")
                st.session_state["cp_show_upload"] = False

        if st.session_state.get("cp_show_mode"):
            st.markdown("### 🧭 Select AI Mode — each makes the Copilot think differently")
            _cols = st.columns(3)
            for idx, mode_key in enumerate(("configure", "troubleshoot", "design")):
                _m = MODES[mode_key]
                is_current = normalize_mode(st.session_state.get("copilot_ai_mode")) == mode_key
                with _cols[idx]:
                    if st.button(
                        f"{_m['emoji']} {_m['label']}" + ("  ✓" if is_current else ""),
                        key=f"cp_mode_{mode_key}",
                        use_container_width=True,
                    ):
                        st.session_state["copilot_ai_mode"] = mode_key
                        st.session_state["cp_show_mode"] = False
                        _rerun()
                    st.markdown(
                        f"<div style='font-size:11px;color:#94a3b8;margin:2px 4px 8px 4px'>"
                        + (
                            "Generate configs + validation + rollback." if mode_key == "configure"
                            else "Root-cause diagnosis then fix on selected devices." if mode_key == "troubleshoot"
                            else "Architecture, addressing plan & trade-offs."
                        )
                        + "</div>",
                        unsafe_allow_html=True,
                    )

        if st.session_state.get("cp_show_devs"):
            st.markdown("### 🖧 Select Devices")
            if not approved_devs:
                st.warning("ℹ️ No approved devices yet. Go to Admin > Device to approve devices.")
            else:
                _device_search = st.text_input(
                    label="device_search",
                    label_visibility="collapsed",
                    placeholder="Search by hostname or IP...",
                    key="copilot_device_search_modal",
                )

                selected_ips = _normalize_selected_devices(st.session_state.get("copilot_selected_devices", []))
                _filtered_devices = approved_devs
                if _device_search.strip():
                    _search_lower = _device_search.lower()
                    _filtered_devices = [
                        d for d in approved_devs
                        if _search_lower in (getattr(d, "hostname", "") or "").lower() or _search_lower in d.ip.lower()
                    ]

                st.caption(f"Found: {len(_filtered_devices)} device(s)")
                for device in _filtered_devices:
                    is_checked = device.ip in selected_ips
                    new_checked = st.checkbox(
                        _device_label(device),
                        value=is_checked,
                        key=f"cp_device_{device.ip}",
                    )
                    if new_checked and device.ip not in selected_ips:
                        selected_ips.append(device.ip)
                    elif not new_checked and device.ip in selected_ips:
                        selected_ips.remove(device.ip)

                st.session_state["copilot_selected_devices"] = selected_ips
                st.caption(f"{len(selected_ips)} selected")

        # ── Submit ──────────────────────────────────────────────────────────────
        if _send_clicked and _input_text and _input_text.strip():
            user_text = _input_text.strip()
            conversation = _current_conversation()
            if not conversation["messages"]:
                conversation["title"] = _conversation_title_from_message(user_text)
            conversation["messages"].append({"role": "user", "content": user_text})

            selected_ips = _normalize_selected_devices(st.session_state.get("copilot_selected_devices", []))
            action_states[conversation["id"]] = {}
            mode_key = normalize_mode(st.session_state.get("copilot_ai_mode"))
            mode = MODES[mode_key]
            target_devices = _resolve_target_devices(approved_devs, selected_ips)
            scope_label = ", ".join(selected_ips) if selected_ips else "selected devices"

            _full_prompt = build_copilot_prompt(
                user_text=user_text,
                ai_mode=mode["label"],
                selected_devices=selected_ips,
                device_context=device_context,
                conversation_history=conversation["messages"][:-1],
                autonomous_mode=st.session_state.get("copilot_autonomous_mode", False),
            )

            ai_reply = ""
            with st.spinner(f"{mode['emoji']} Copilot ({mode['short']} mode) is thinking…"):
                try:
                    if mode["device_facing"]:
                        # Troubleshoot & Fix → confidence-driven engine, vendor-agnostic
                        # via the Universal Vendor Adapter Framework, STRICTLY on selected devices.
                        if not target_devices:
                            ai_reply = (
                                "🛑 **Troubleshoot & Fix runs directly on your devices**, so I won't "
                                "touch anything until you scope it. Open **🖧 Devices** and select at "
                                "least one approved device, then send your request again."
                            )
                        else:
                            from core.troubleshooting import TroubleshootingEngine, TSConfig
                            gw = _make_troubleshooting_gateway(call_ai_fn, target_devices)
                            tse = TroubleshootingEngine(
                                ai_call=call_ai_fn, devices=target_devices, gateway=gw,
                                config=TSConfig(max_steps=6),
                                session_store=_get_ts_session_backend(),
                            )
                            report = tse.run(user_text)
                            ai_reply = report.to_markdown()
                            s = report.session
                            if s.fix and s.fix.config_commands:
                                target_ip = s.goal.devices[0] if (s.goal and s.goal.devices) else ""
                                action_states[conversation["id"]] = {
                                    "kind": "ts_fix",
                                    "root_cause": s.fix.root_cause,
                                    "fix_commands": list(s.fix.config_commands),
                                    "rollback_commands": list(s.fix.rollback_commands),
                                    "verification_commands": list(s.verification.commands) if s.verification else [],
                                    "target_ip": target_ip,
                                    "devices": target_devices,
                                    "session": s,
                                }
                    else:
                        if mode_key == "configure":
                            # Configure Network & Services → AI Configuration Engine
                            # (business intent → normalized config → vendor artifacts →
                            # approval). Vendor-independent; nothing deploys until approved.
                            from core.config_engine import AIConfigurationEngine, ConfigStatus

                            cfg_state = st.session_state.setdefault("cfg_state", {})
                            conv_cfg = cfg_state.get(conversation["id"], {})
                            gw = _make_troubleshooting_gateway(call_ai_fn, target_devices) if target_devices else None
                            cfg_eng = AIConfigurationEngine(
                                ai_call=call_ai_fn, devices=target_devices, gateway=gw,
                                session_store=_get_config_session_backend())

                            if conv_cfg.get("awaiting"):
                                provided = dict(conv_cfg.get("provided", {}))
                                provided.update(_extract_provided(call_ai_fn, conv_cfg["awaiting"], user_text))
                                base_query = conv_cfg.get("query", user_text)
                            else:
                                provided = {}
                                base_query = user_text

                            report = cfg_eng.run(base_query, provided=provided)
                            cs = report.session
                            ai_reply = report.to_markdown()

                            if cs.status == ConfigStatus.NEEDS_INPUT:
                                cfg_state[conversation["id"]] = {
                                    "query": base_query, "provided": provided,
                                    "awaiting": [{"field": m.field, "question": m.question} for m in cs.missing],
                                }
                            else:
                                cfg_state[conversation["id"]] = {}
                                supported = [a for a in cs.artifacts if a.supported and a.config_commands]
                                if cs.status == ConfigStatus.NEEDS_APPROVAL and supported:
                                    action_states[conversation["id"]] = {
                                        "kind": "cfg_approval",
                                        "artifacts": [{"device": a.device,
                                                       "config": a.config_commands,
                                                       "rollback": a.rollback_commands} for a in supported],
                                        "devices": target_devices,
                                    }
                        else:
                            # Design Network Architecture → AI Design Engine
                            # (Principal-Architect: multiple options + recommendation;
                            # never vendor CLI/config, never troubleshooting).
                            from core.design_engine import AIDesignEngine

                            dgw = _make_troubleshooting_gateway(call_ai_fn, target_devices) if target_devices else None
                            d_eng = AIDesignEngine(ai_call=call_ai_fn, devices=target_devices, gateway=dgw,
                                                   memory_backend=_get_design_memory_backend())
                            ai_reply = d_eng.run(user_text).to_markdown()
                except Exception as _e:
                    ai_reply = f"❌ Error: {str(_e)}"

            pending_kind = action_states.get(conversation["id"], {}).get("kind")
            if not ai_reply and pending_kind == "plan":
                ai_reply = "✅ Proposed diagnostic plan created. Review the plan below."
            elif not ai_reply and pending_kind == "fix":
                ai_reply = "⚙️ Proposed fix generated. Review the fix below."
            if not ai_reply:
                ai_reply = call_ai_fn(_full_prompt)

            conversation["messages"].append({"role": "assistant", "content": ai_reply, "mode": mode_key})
            clear_copilot_main_input()
            _rerun()

        # ── Conversation ──────────────────────────────────────────────────────────
        messages = active_conversation.get("messages", [])
        if messages:
            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("### 💬 Conversation")
            for message in messages:
                if message["role"] == "user":
                    st.markdown(f"""
                    <div class="copilot-msg-user">
                        <div class="copilot-msg-label">👤 You</div>
                        <div class="copilot-msg-text">{message['content']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    _render_assistant_message(message.get("content", ""), message.get("mode"))

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

            pending_state = action_states.get(active_conversation.get("id"), {})
            if pending_state.get("kind") == "plan":
                st.markdown("### 🔎 Review proposed plan")
                from core.intent_engine import IntentEngine

                st.markdown(IntentEngine.format_plan_for_chat(pending_state["plan"], pending_state.get("citations_md", "")))
                _plan_col1, _plan_col2 = st.columns(2)
                with _plan_col1:
                    if st.button("✅ Run Plan", key=f"cp_run_plan_{active_conversation['id']}", use_container_width=True):
                        engine = _build_intent_engine(call_ai_fn, pending_state.get("devices", []))
                        result = engine.execute_plan(plan=pending_state["plan"], all_devices=pending_state.get("devices", []))
                        conversation_reply = IntentEngine.format_for_chat(result, ", ".join(_normalize_selected_devices(st.session_state.get("copilot_selected_devices", []))) or "selected devices")
                        active_conversation["messages"].append({"role": "assistant", "content": conversation_reply, "mode": "troubleshoot"})
                        if getattr(result, "needs_followup", False) and getattr(result, "next_plan", None):
                            action_states[active_conversation["id"]] = {
                                "kind": "followup",
                                "plan": result.next_plan,
                                "query": pending_state.get("query", ""),
                                "devices": pending_state.get("devices", []),
                            }
                        elif getattr(result, "needs_approval", False) and getattr(result, "fix_commands", None):
                            action_states[active_conversation["id"]] = {
                                "kind": "fix",
                                "result": result,
                                "query": pending_state.get("query", ""),
                                "devices": pending_state.get("devices", []),
                            }
                        else:
                            action_states[active_conversation["id"]] = {}
                        _rerun()
                with _plan_col2:
                    if st.button("❌ Cancel", key=f"cp_cancel_plan_{active_conversation['id']}", use_container_width=True):
                        action_states[active_conversation["id"]] = {}
                        _rerun()
            elif pending_state.get("kind") == "fix":
                st.markdown("### ⚙️ Review fix")
                from core.intent_engine import IntentEngine

                result = pending_state.get("result")
                if result:
                    st.markdown(IntentEngine.format_for_chat(result, "selected devices"))
                _fix_col1, _fix_col2 = st.columns(2)
                with _fix_col1:
                    if st.button("✅ Deploy Fix", key=f"cp_deploy_fix_{active_conversation['id']}", use_container_width=True):
                        engine = _build_intent_engine(call_ai_fn, pending_state.get("devices", []))
                        summary_lines = []
                        for dev in pending_state.get("devices", []):
                            cfg = [
                                c.replace("[CONFIG]", "").strip()
                                for c in (getattr(result, "commands_per_device", {}) or {}).get(dev.ip, getattr(result, "fix_commands", []))
                                if "[CONFIG]" in c
                            ]
                            if not cfg:
                                continue
                            try:
                                engine._ssh_apply(dev, cfg)
                                summary_lines.append(f"✅ Applied on {getattr(dev, 'hostname', None) or dev.ip}")
                            except Exception as exc:
                                summary_lines.append(f"⚠️ Apply failed on {getattr(dev, 'hostname', None) or dev.ip}: {exc}")
                        if not summary_lines:
                            summary_lines.append("ℹ️ No config commands were available to apply.")
                        active_conversation["messages"].append({"role": "assistant", "content": "\n".join(summary_lines), "mode": "troubleshoot"})
                        action_states[active_conversation["id"]] = {}
                        _rerun()
                with _fix_col2:
                    if st.button("❌ Discard", key=f"cp_discard_fix_{active_conversation['id']}", use_container_width=True):
                        action_states[active_conversation["id"]] = {}
                        _rerun()
            elif pending_state.get("kind") == "followup":
                st.markdown("### 🔁 Continue with next step")
                from core.intent_engine import IntentEngine

                st.markdown(IntentEngine.format_plan_for_chat(pending_state["plan"], ""))
                _follow_col1, _follow_col2 = st.columns(2)
                with _follow_col1:
                    if st.button("✅ Continue", key=f"cp_continue_followup_{active_conversation['id']}", use_container_width=True):
                        engine = _build_intent_engine(call_ai_fn, pending_state.get("devices", []))
                        result = engine.execute_plan(plan=pending_state["plan"], all_devices=pending_state.get("devices", []))
                        active_conversation["messages"].append({"role": "assistant", "content": IntentEngine.format_for_chat(result, "selected devices"), "mode": "troubleshoot"})
                        if getattr(result, "needs_followup", False) and getattr(result, "next_plan", None):
                            action_states[active_conversation["id"]] = {
                                "kind": "followup",
                                "plan": result.next_plan,
                                "query": pending_state.get("query", ""),
                                "devices": pending_state.get("devices", []),
                            }
                        elif getattr(result, "needs_approval", False) and getattr(result, "fix_commands", None):
                            # Final round produced a fix — surface the Deploy/Discard review
                            # instead of silently dropping it (previously cleared to {}).
                            action_states[active_conversation["id"]] = {
                                "kind": "fix",
                                "result": result,
                                "query": pending_state.get("query", ""),
                                "devices": pending_state.get("devices", []),
                            }
                        else:
                            action_states[active_conversation["id"]] = {}
                        _rerun()
                with _follow_col2:
                    if st.button("❌ Stop", key=f"cp_stop_followup_{active_conversation['id']}", use_container_width=True):
                        action_states[active_conversation["id"]] = {}
                        _rerun()
            elif pending_state.get("kind") == "ts_fix":
                st.markdown("### ⚙️ Review recommended fix")
                if pending_state.get("root_cause"):
                    st.markdown(f"**Confirmed root cause:** {pending_state['root_cause']}")
                st.markdown("**Fix (vendor syntax from adapter):**")
                st.code("\n".join(pending_state.get("fix_commands", [])))
                if pending_state.get("rollback_commands"):
                    st.markdown("**Rollback:**")
                    st.code("\n".join(pending_state["rollback_commands"]))
                if pending_state.get("verification_commands"):
                    st.markdown("**Verification (run after apply):**")
                    st.code("\n".join(pending_state["verification_commands"]))
                st.caption("⚠️ Nothing is applied until you approve.")
                _ts_col1, _ts_col2 = st.columns(2)
                with _ts_col1:
                    if st.button("✅ Deploy Fix", key=f"cp_ts_deploy_{active_conversation['id']}", use_container_width=True):
                        result = _apply_ts_fix(call_ai_fn, pending_state)
                        active_conversation["messages"].append(
                            {"role": "assistant", "content": "\n".join(result["summary_lines"]),
                            "mode": "troubleshoot"})
                        if result["verification_output"]:
                            vlines = [f"**{ip}**\n```\n{out}\n```"
                                     for ip, out in result["verification_output"].items()]
                            content = "🔍 **Post-fix verification (re-collected live):**\n\n" + "\n".join(vlines)
                            # A deterministic check on the SAME fresh text above —
                            # catches the case where a fix resolves one neighbor
                            # but a second, separate adjacency on the same device
                            # is still stuck, which is easy to miss when skimming
                            # two similar-looking table rows.
                            warnings = list(result.get("verification_warnings", {}).values())
                            if warnings:
                                content += "\n\n" + "\n".join(warnings)
                            active_conversation["messages"].append({
                                "role": "assistant", "content": content, "mode": "troubleshoot",
                            })
                        if result["applied_any"]:
                            action_states[active_conversation["id"]] = {
                                **pending_state, "kind": "ts_verify",
                                "verification_warnings": result.get("verification_warnings", {}),
                                "verification_targets": result.get("verification_targets", {}),
                            }
                        else:
                            action_states[active_conversation["id"]] = {}
                        _rerun()
                with _ts_col2:
                    if st.button("❌ Discard", key=f"cp_ts_discard_{active_conversation['id']}", use_container_width=True):
                        action_states[active_conversation["id"]] = {}
                        _rerun()
            elif pending_state.get("kind") == "ts_verify":
                st.markdown("### 🔍 Confirm the fix")
                if pending_state.get("root_cause"):
                    st.markdown(f"**Root cause addressed:** {pending_state['root_cause']}")
                verify_warnings = pending_state.get("verification_warnings") or {}
                if verify_warnings:
                    st.warning(
                        "This fix only resolved PART of the issue — the fresh verification "
                        "output above still shows at least one neighbor NOT yet FULL:\n\n"
                        + "\n".join(verify_warnings.values()))
                st.caption("Review the fresh verification output above. Your answer trains the "
                          "platform's operational memory — it is never guessed automatically.")
                _tv_col1, _tv_col2 = st.columns(2)
                with _tv_col1:
                    if st.button("✅ Confirms Fixed", key=f"cp_ts_confirm_{active_conversation['id']}", use_container_width=True):
                        msg = _record_ts_outcome(pending_state, success=True)
                        active_conversation["messages"].append(
                            {"role": "assistant", "content": msg, "mode": "troubleshoot"})
                        cont = _continue_investigation_if_needed(call_ai_fn, pending_state)
                        active_conversation["messages"].extend(cont["messages"])
                        action_states[active_conversation["id"]] = cont["next_pending_state"]
                        _rerun()
                with _tv_col2:
                    if st.button("❌ Still Broken", key=f"cp_ts_deny_{active_conversation['id']}", use_container_width=True):
                        msg = _record_ts_outcome(pending_state, success=False)
                        active_conversation["messages"].append(
                            {"role": "assistant", "content": msg, "mode": "troubleshoot"})
                        cont = _continue_investigation_if_needed(call_ai_fn, pending_state)
                        active_conversation["messages"].extend(cont["messages"])
                        action_states[active_conversation["id"]] = cont["next_pending_state"]
                        _rerun()
            elif pending_state.get("kind") == "cfg_approval":
                st.markdown("### 📦 Approve configuration deployment")
                st.markdown("The engine has prepared and validated this change. "
                            "**Nothing is applied until you approve.**")
                for art in pending_state.get("artifacts", []):
                    st.markdown(f"**{art['device']}** — config:")
                    if art.get("config"):
                        st.code("\n".join(art["config"]))
                    if art.get("rollback"):
                        st.caption("Rollback prepared:")
                        st.code("\n".join(art["rollback"]))
                _cfg_col1, _cfg_col2 = st.columns(2)
                with _cfg_col1:
                    if st.button("✅ Approve & Deploy", key=f"cp_cfg_approve_{active_conversation['id']}", use_container_width=True):
                        summary = _apply_cfg(call_ai_fn, pending_state)
                        active_conversation["messages"].append(
                            {"role": "assistant", "content": "\n".join(summary), "mode": "configure"})
                        action_states[active_conversation["id"]] = {}
                        _rerun()
                with _cfg_col2:
                    if st.button("❌ Reject", key=f"cp_cfg_reject_{active_conversation['id']}", use_container_width=True):
                        active_conversation["messages"].append(
                            {"role": "assistant", "content": "❌ Configuration rejected — nothing was applied.", "mode": "configure"})
                        action_states[active_conversation["id"]] = {}
                        _rerun()

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            _clear_col1, _clear_col2, _clear_col3 = st.columns([2, 1, 2])
            with _clear_col2:
                if st.button("🗑 Clear", key="cp_clear_all", use_container_width=True):
                    active_conversation["messages"] = []
                    active_conversation["title"] = "New chat"
                    action_states[active_conversation["id"]] = {}
                    _rerun()

    # Catch-all for state that changes via a widget's OWN key binding
    # (device-selection checkboxes, the autonomous-mode checkbox) rather
    # than through one of the explicit mutate-then-_rerun() branches above
    # — those paths update session_state and let Streamlit's own automatic
    # rerun-on-interaction carry the script to this natural end without
    # ever calling _rerun() itself, so persistence still needs to happen
    # here too.
    _persist_copilot_state()
