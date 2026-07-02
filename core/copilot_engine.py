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

import logging
import streamlit as st
from uuid import uuid4
from typing import List, Any, Dict, Optional

logger = logging.getLogger(__name__)


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
            "You are NetBrain Copilot operating in CONFIGURATION mode. "
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
            "You are NetBrain Copilot operating in TROUBLESHOOT & FIX mode. "
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
            "You are NetBrain Copilot operating in DESIGN mode. "
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


def initialize_session_state():
    """Initialize all copilot-related session state."""
    if "copilot_conversations" not in st.session_state:
        st.session_state["copilot_conversations"] = []
    if "copilot_active_conversation_id" not in st.session_state:
        st.session_state["copilot_active_conversation_id"] = None
    if "copilot_selected_devices" not in st.session_state:
        st.session_state["copilot_selected_devices"] = []
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
                st.rerun()
        with col_clear:
            if st.button("🗑 Clear all", use_container_width=True, key="cp_sidebar_clear"):
                st.session_state["copilot_conversations"] = []
                st.session_state["copilot_active_conversation_id"] = None
                st.session_state["copilot_action_state"] = {}
                st.rerun()

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
                    st.rerun()
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
                    st.rerun()

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
                        st.rerun()
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
                        # Troubleshoot & Fix → run the diagnostic loop, STRICTLY on selected devices.
                        if not target_devices:
                            ai_reply = (
                                "🛑 **Troubleshoot & Fix runs directly on your devices**, so I won't "
                                "touch anything until you scope it. Open **🖧 Devices** and select at "
                                "least one approved device, then send your request again."
                            )
                        elif st.session_state.get("copilot_autonomous_mode", False):
                            engine = _build_intent_engine(call_ai_fn, target_devices)
                            intent_result = engine.run_autonomous(
                                query=user_text,
                                devices=target_devices,
                                max_rounds=4,
                                auto_fix=False,
                            )
                            if hasattr(engine, "format_for_chat"):
                                ai_reply = engine.format_for_chat(intent_result, scope_label)
                        else:
                            engine = _build_intent_engine(call_ai_fn, target_devices)
                            intent_result = engine.propose_plan(query=user_text, devices=target_devices)
                            if hasattr(engine, "format_for_chat"):
                                ai_reply = engine.format_for_chat(intent_result, scope_label)
                            if intent_result.plan_pending and intent_result.plan:
                                action_states[conversation["id"]] = {
                                    "kind": "plan",
                                    "plan": intent_result.plan,
                                    "query": user_text,
                                    "devices": target_devices,
                                    "citations_md": getattr(intent_result, "citations_md", ""),
                                }
                                ai_reply = "✅ Proposed diagnostic plan created. Review the plan below."
                            elif intent_result.needs_approval and intent_result.fix_commands:
                                action_states[conversation["id"]] = {
                                    "kind": "fix",
                                    "result": intent_result,
                                    "query": user_text,
                                    "devices": target_devices,
                                }
                                ai_reply = "⚙️ Proposed fix generated. Review the fix below."
                    else:
                        # Configure / Design → advisory, generative persona answer.
                        ai_reply = call_ai_fn(_full_prompt)
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
            st.rerun()

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
                        st.rerun()
                with _plan_col2:
                    if st.button("❌ Cancel", key=f"cp_cancel_plan_{active_conversation['id']}", use_container_width=True):
                        action_states[active_conversation["id"]] = {}
                        st.rerun()
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
                        st.rerun()
                with _fix_col2:
                    if st.button("❌ Discard", key=f"cp_discard_fix_{active_conversation['id']}", use_container_width=True):
                        action_states[active_conversation["id"]] = {}
                        st.rerun()
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
                        st.rerun()
                with _follow_col2:
                    if st.button("❌ Stop", key=f"cp_stop_followup_{active_conversation['id']}", use_container_width=True):
                        action_states[active_conversation["id"]] = {}
                        st.rerun()

            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            _clear_col1, _clear_col2, _clear_col3 = st.columns([2, 1, 2])
            with _clear_col2:
                if st.button("🗑 Clear", key="cp_clear_all", use_container_width=True):
                    active_conversation["messages"] = []
                    active_conversation["title"] = "New chat"
                    action_states[active_conversation["id"]] = {}
                    st.rerun()
