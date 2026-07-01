"""
Network Intelligence Copilot Engine
====================================
Standalone copilot chat interface with device integration,
image upload, and AI modes. Keeps app.py clean.
"""

import streamlit as st
import logging
from uuid import uuid4
from typing import List, Any


DEFAULT_COPILOT_SUGGESTIONS = [
    "Show me the health of all approved devices",
    "What is BGP and when should I use it?",
    "Generate OSPF config for R1 on 192.168.1.0/24",
    "What does 'show ip interface brief' output tell me?",
    "How do I configure SSH on a Cisco router?",
]

logger = logging.getLogger(__name__)


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
    if "copilot_ai_mode" not in st.session_state:
        st.session_state["copilot_ai_mode"] = None
<<<<<<< HEAD
    if "copilot_autonomous_mode" not in st.session_state:
        st.session_state["copilot_autonomous_mode"] = False
=======
    if "copilot_main_input" not in st.session_state:
        st.session_state["copilot_main_input"] = ""
    if "cp_show_upload" not in st.session_state:
        st.session_state["cp_show_upload"] = False
    if "cp_show_mode" not in st.session_state:
        st.session_state["cp_show_mode"] = False
    if "cp_show_devs" not in st.session_state:
        st.session_state["cp_show_devs"] = False
>>>>>>> d5c8488704f44e136849677d3409b5e4744a2916


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
    ai_mode: str | None = None,
    selected_devices: List[str] | None = None,
    device_context: str = "",
    conversation_history: List[dict] | None = None,
    autonomous_mode: bool = False,
) -> str:
    """Construct a rich prompt for the copilot chat using assistant-style context."""
    context_parts: List[str] = []
    if ai_mode:
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

    sys_prompt = (
        "You are Network Intelligence Copilot, an expert network operations AI. "
        "Provide technically accurate, concise responses. Include specific CLI commands when relevant. "
        "For configuration tasks, show step-by-step guidance. Be professional and enterprise-grade."
    )

    if context_parts:
        sys_prompt = f"{sys_prompt}\n\n" + "\n\n".join(context_parts)

    if history_lines:
        sys_prompt = f"{sys_prompt}\n\nConversation so far:\n" + "\n".join(history_lines)

    return f"{sys_prompt}\n\nUser question: {user_text}"


def render_copilot_page(call_ai_fn):
    """Main copilot page renderer."""
    initialize_session_state()

    approved_devs = load_approved_devices()
    conversations = st.session_state.get("copilot_conversations", [])
    active_conversation = _current_conversation()
    device_context = _load_device_context()

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
                st.rerun()
        with col_clear:
            if st.button("🗑 Clear all", use_container_width=True, key="cp_sidebar_clear"):
                st.session_state["copilot_conversations"] = []
                st.session_state["copilot_active_conversation_id"] = None
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
        st.markdown(f"**Mode:** {st.session_state.get('copilot_ai_mode', 'Net Config')}")
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
        min-height: 56vh;
        padding: 24px 20px 10px 20px;
        text-align: center;
    }
    .copilot-logo {
        width: 112px;
        height: 112px;
        background: linear-gradient(135deg, #3b82f6, #2563eb);
        border-radius: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 56px;
        margin-bottom: 28px;
        box-shadow: 0 20px 60px rgba(37, 99, 235, 0.3);
    }
    .copilot-title {
        font-size: 38px;
        font-weight: 800;
        color: #f0f4fa;
        letter-spacing: -0.02em;
        margin: 0 0 12px 0;
        line-height: 1.1;
    }
    .copilot-subtitle {
        font-size: 16px;
        color: #8b95a8;
        margin: 0 0 20px 0;
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
    .copilot-msg-ai .copilot-msg-label { color: #3fd27a; }
    .copilot-msg-text {
        color: #c8d6e8;
        line-height: 1.6;
        white-space: pre-wrap;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Hero Section ────────────────────────────────────────────────────────────
    st.markdown("""
    <div class="copilot-container">
        <div class="copilot-logo">🧠</div>
        <h1 class="copilot-title">Network Intelligence Copilot</h1>
        <p class="copilot-subtitle">Describe what you want to analyze, validate, deploy, or troubleshoot.</p>
    </div>
    """, unsafe_allow_html=True)

    if not active_conversation.get("messages"):
        st.info("Use the same assistant-style context as the AI Assistant workspace: device scope, helpful prompts, and recent conversation history are all included in the response context.")
        st.markdown("**Quick actions:**")
        quick_cols = st.columns(3)
        for idx, suggestion in enumerate(DEFAULT_COPILOT_SUGGESTIONS):
            with quick_cols[idx % 3]:
                if st.button(suggestion, key=f"cp_sg_{idx}", use_container_width=True):
                    active_conversation.setdefault("messages", []).append({"role": "user", "content": suggestion})
                    st.session_state["copilot_active_conversation_id"] = active_conversation["id"]
                    st.rerun()

    selected_ips = _normalize_selected_devices(st.session_state.get("copilot_selected_devices", []))
    scope_color = "#16a34a" if selected_ips else "#dc2626"
    if selected_ips:
        scope_names = ", ".join(selected_ips)
        scope_msg = f"🎯 AI Scope: {len(selected_ips)} device(s) selected → {scope_names}"
    else:
        scope_msg = "🛑 AI Scope: No devices selected — the copilot will stay generic until you scope it to one or more devices."

    st.markdown(
        f"<div style='background:#0c1826;border-left:3px solid {scope_color};border-radius:6px;padding:.55rem .9rem;margin:.4rem 0 .8rem 0;color:#cbd5e1;font-size:.85rem'>{scope_msg}</div>",
        unsafe_allow_html=True,
    )

    _ctrl_col1, _ctrl_col2 = st.columns([4, 1])
    with _ctrl_col1:
        st.checkbox(
            "🤖 Autonomous mode — run the diagnosis flow with verification and safe remediation guidance",
            key="copilot_autonomous_mode",
        )
    with _ctrl_col2:
        if st.button("🗑 Clear", key="cp_clear_chat", use_container_width=True):
            active_conversation["messages"] = []
            active_conversation["title"] = "New chat"
            st.rerun()

    # ── Composer Controls ─────────────────────────────────────────────────────
    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    _bar_col1, _bar_col2, _bar_col3, _bar_col4, _bar_col5 = st.columns([0.55, 1.15, 1.35, 4.5, 0.8])

    with _bar_col1:
        if st.button("➕", key="cp_btn_add", use_container_width=True, help="Upload image"):
            st.session_state["cp_show_upload"] = not st.session_state.get("cp_show_upload", False)

    with _bar_col2:
        _ai_mode = st.session_state.get("copilot_ai_mode", "Net Config")
        if st.button(f"⚙️ {_ai_mode}", key="cp_btn_mode", use_container_width=True, help="Select AI mode"):
            st.session_state["cp_show_mode"] = not st.session_state.get("cp_show_mode", False)

    with _bar_col3:
        _dev_count = len(_normalize_selected_devices(st.session_state.get("copilot_selected_devices", [])))
        if st.button(f"🖧 Devices ({_dev_count})", key="cp_btn_devs", use_container_width=True, help="Select devices"):
            st.session_state["cp_show_devs"] = not st.session_state.get("cp_show_devs", False)

    with _bar_col4:
        _input_text = st.text_area(
            label="copilot_input",
            label_visibility="collapsed",
            placeholder="What do you want to do today in your network?",
            key="copilot_main_input",
            height=180,
        )

    with _bar_col5:
        _send_clicked = st.button("Send", key="cp_send", use_container_width=True)
        _send_status = "Ready" if _input_text else "Type a message"
        st.caption(_send_status)

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
        st.markdown("### ⚙️ Select Network AI Mode")
        _modes = {
            "Net Config": "⚙️ Configure networks & services",
            "Net Fix": "🔧 Troubleshoot & fix issues",
            "Net Design": "🎨 Design network architectures",
        }
        _cols = st.columns(3)
        for idx, (mode_name, mode_desc) in enumerate(_modes.items()):
            with _cols[idx]:
                if st.button(mode_desc, key=f"cp_mode_{mode_name}", use_container_width=True):
                    st.session_state["copilot_ai_mode"] = mode_name
                    st.session_state["cp_show_mode"] = False
                    st.rerun()

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

    if _send_clicked and _input_text and _input_text.strip():
        user_text = _input_text.strip()
        conversation = _current_conversation()
        if not conversation["messages"]:
            conversation["title"] = _conversation_title_from_message(user_text)
        conversation["messages"].append({"role": "user", "content": user_text})

        selected_ips = _normalize_selected_devices(st.session_state.get("copilot_selected_devices", []))
        _context_parts = []
        if st.session_state.get("copilot_ai_mode"):
            _context_parts.append(f"AI Mode: {st.session_state['copilot_ai_mode']}")
        if selected_ips:
            _context_parts.append(f"Target devices: {', '.join(selected_ips)}")
        if st.session_state.get("copilot_uploaded_image"):
            _img_name = st.session_state["copilot_uploaded_image"].name
            _context_parts.append(f"[Image: {_img_name}]")

        _full_prompt = build_copilot_prompt(
            user_text=user_text,
            ai_mode=st.session_state.get("copilot_ai_mode"),
            selected_devices=selected_ips,
            device_context=device_context,
            conversation_history=conversation["messages"][:-1],
            autonomous_mode=st.session_state.get("copilot_autonomous_mode", False),
        )

        with st.spinner("✨ Network Copilot is thinking…"):
            try:
                ai_reply = call_ai_fn(_full_prompt)
            except Exception as _e:
                ai_reply = f"❌ Error: {str(_e)}"

        conversation["messages"].append({"role": "assistant", "content": ai_reply})
        st.rerun()

    messages = active_conversation.get("messages", [])
    if messages:
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
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
                st.markdown(f"""
                <div class="copilot-msg-ai">
                    <div class="copilot-msg-label">🤖 Copilot</div>
                    <div class="copilot-msg-text">{message['content']}</div>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        _clear_col1, _clear_col2, _clear_col3 = st.columns([2, 1, 2])
        with _clear_col2:
            if st.button("🗑 Clear", key="cp_clear_all", use_container_width=True):
                active_conversation["messages"] = []
                active_conversation["title"] = "New chat"
                st.rerun()
