"""
Network Intelligence Copilot Engine
====================================
Standalone copilot chat interface with device integration,
image upload, and AI modes. Keeps app.py clean.
"""

import streamlit as st
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


def initialize_session_state():
    """Initialize all copilot-related session state."""
    if "copilot_chat_messages" not in st.session_state:
        st.session_state["copilot_chat_messages"] = []
    if "copilot_selected_devices" not in st.session_state:
        st.session_state["copilot_selected_devices"] = []
    if "copilot_uploaded_image" not in st.session_state:
        st.session_state["copilot_uploaded_image"] = None
    if "copilot_ai_mode" not in st.session_state:
        st.session_state["copilot_ai_mode"] = None


def load_approved_devices() -> List[Any]:
    """Load approved devices from the discovery engine."""
    try:
        from core.device_discovery import get_discovery_engine
        _disc = get_discovery_engine()
        return _disc.get_approved() or []
    except Exception as _e:
        logger.warning(f"Failed to load approved devices: {_e}")
        return []


def render_copilot_page(call_ai_fn):
    """
    Main copilot page renderer.
    
    Args:
        call_ai_fn: Function to call AI (from app.py)
    """
    initialize_session_state()
    
    # Load devices
    approved_devs = load_approved_devices()
    
    # ── CSS Styling ────────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    .copilot-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 70vh;
        padding: 40px 20px;
        text-align: center;
    }
    .copilot-logo {
        width: 120px;
        height: 120px;
        background: linear-gradient(135deg, #3b82f6, #2563eb);
        border-radius: 32px;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 60px;
        margin-bottom: 40px;
        box-shadow: 0 20px 60px rgba(37, 99, 235, 0.3);
    }
    .copilot-title {
        font-size: 42px;
        font-weight: 800;
        color: #f0f4fa;
        letter-spacing: -0.02em;
        margin: 0 0 16px 0;
        line-height: 1.1;
    }
    .copilot-subtitle {
        font-size: 18px;
        color: #8b95a8;
        margin: 0 0 48px 0;
        max-width: 600px;
        line-height: 1.6;
    }
    
    /* ── Compact Input Bar ── */
    .copilot-input-bar {
        width: 100%;
        max-width: 900px;
        background: #0e151f;
        border: 1px solid #243043;
        border-radius: 14px;
        padding: 12px 16px;
        display: flex;
        align-items: center;
        gap: 12px;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
    
    .copilot-btn-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        background: rgba(37, 99, 235, 0.1);
        border: 1px solid rgba(37, 99, 235, 0.3);
        border-radius: 10px;
        cursor: pointer;
        font-size: 18px;
        transition: all 0.2s ease;
        color: #2563eb;
    }
    .copilot-btn-icon:hover {
        background: rgba(37, 99, 235, 0.2);
        border-color: rgba(37, 99, 235, 0.5);
    }
    
    .copilot-option-box {
        background: #141d2a;
        border: 1px solid #243043;
        border-radius: 10px;
        padding: 8px 14px;
        font-size: 13px;
        color: #f0f4fa;
        display: flex;
        align-items: center;
        gap: 8px;
        white-space: nowrap;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    .copilot-option-box:hover {
        border-color: #2563eb;
        background: #1a2737;
    }
    
    .copilot-chevron {
        font-size: 16px;
        color: #5d6b7e;
        cursor: pointer;
    }
    
    .copilot-input-field {
        flex: 1;
        background: transparent;
        border: none;
        color: #f0f4fa;
        font-size: 15px;
        outline: none;
    }
    .copilot-input-field::placeholder {
        color: #5d6b7e;
    }
    
    .copilot-send-btn {
        background: linear-gradient(135deg, #2563eb, #3b82f6);
        border: none;
        border-radius: 10px;
        padding: 10px 20px;
        color: white;
        font-weight: 600;
        font-size: 14px;
        cursor: pointer;
        transition: all 0.2s ease;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
    }
    .copilot-send-btn:hover {
        background: linear-gradient(135deg, #1d4ed8, #2563eb);
        box-shadow: 0 6px 20px rgba(37, 99, 235, 0.35);
    }
    .copilot-send-btn:active {
        transform: scale(0.98);
    }
    
    /* ── Chat Display ── */
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

    # ── Compact Input Bar with Inline Controls ──────────────────────────────────
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    
    _input_container = st.container()
    with _input_container:
        # Row with inline controls
        _bar_col1, _bar_col2, _bar_col3, _bar_col4 = st.columns([0.5, 1.2, 1.2, 4])
        
        # Button 1: Upload Image
        with _bar_col1:
            if st.button("➕", key="cp_btn_add", use_container_width=True,
                        help="Upload image"):
                st.session_state["cp_show_upload"] = not st.session_state.get("cp_show_upload", False)
        
        # Button 2: AI Mode
        with _bar_col2:
            _ai_mode = st.session_state.get("copilot_ai_mode", "Net Config")
            if st.button(f"⚙️ {_ai_mode}", key="cp_btn_mode", use_container_width=True,
                        help="Select AI mode"):
                st.session_state["cp_show_mode"] = not st.session_state.get("cp_show_mode", False)
        
        # Button 3: Devices
        with _bar_col3:
            _dev_count = len(st.session_state.get("copilot_selected_devices", []))
            if st.button(f"🖧 Devices ({_dev_count})", key="cp_btn_devs", use_container_width=True,
                        help="Select devices"):
                st.session_state["cp_show_devs"] = not st.session_state.get("cp_show_devs", False)
    
    # ── Show Upload Modal ───────────────────────────────────────────────────────
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
            st.success(f"✅ {_uploaded_file.name} uploaded (Max 200MB)")
            st.session_state["cp_show_upload"] = False
    
    # ── Show Mode Selector Modal ────────────────────────────────────────────────
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
    
    # ── Show Device Selector Modal ──────────────────────────────────────────────
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
            
            # Filter devices
            _filtered_devices = approved_devs
            if _device_search.strip():
                _search_lower = _device_search.lower()
                _filtered_devices = [
                    d for d in approved_devs
                    if _search_lower in (d.hostname or "").lower() or _search_lower in d.ip.lower()
                ]
            
            st.caption(f"Found: {len(_filtered_devices)} device(s)")
            
            # Device multiselect
            _device_options = [f"{d.hostname or d.ip} ({d.ip})" for d in _filtered_devices]
            _selected_labels = st.multiselect(
                label="device_multi_select",
                label_visibility="collapsed",
                options=_device_options,
                default=st.session_state.get("copilot_selected_devices", []),
                key="copilot_device_multiselect_modal",
            )
            
            if _selected_labels:
                st.session_state["copilot_selected_devices"] = _selected_labels
                st.success(f"✅ {len(_selected_labels)} device(s) selected")
                if st.button("Done", key="cp_close_devs"):
                    st.session_state["cp_show_devs"] = False
                    st.rerun()

    # ── Input + Send Row ────────────────────────────────────────────────────────
    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
    _input_col, _send_col = st.columns([5, 1])
    
    with _input_col:
        _input_text = st.text_input(
            label="copilot_input",
            label_visibility="collapsed",
            placeholder="What do you want to do today in your network?",
            key="copilot_main_input",
        )
    
    with _send_col:
        _send_clicked = st.button("→", key="cp_send", use_container_width=True)

    # ── Process Input & Call AI ────────────────────────────────────────────────
    if _send_clicked and _input_text and _input_text.strip():
        _q = _input_text.strip()
        
        # Add user message
        st.session_state["copilot_chat_messages"].append({
            "role": "user",
            "content": _q,
        })

        # Build AI context
        _context_parts = []
        
        if st.session_state.get("copilot_ai_mode"):
            _context_parts.append(f"AI Mode: {st.session_state['copilot_ai_mode']}")
        
        if st.session_state.get("copilot_selected_devices"):
            _dev_list = ", ".join(st.session_state["copilot_selected_devices"])
            _context_parts.append(f"Target devices: {_dev_list}")
        
        if st.session_state.get("copilot_uploaded_image"):
            _img_name = st.session_state["copilot_uploaded_image"].name
            _context_parts.append(f"[Image: {_img_name}]")

        _context_str = " | ".join(_context_parts)
        
        _system_prompt = f"""You are Network Intelligence Copilot, an expert network operations AI.

{_context_str}

Provide technically accurate, concise responses. Include specific CLI commands when relevant.
For configuration tasks, show step-by-step guidance. Be professional and enterprise-grade."""

        _full_prompt = f"{_system_prompt}\n\nUser: {_q}\n\nCopilot:"

        with st.spinner("✨ Network Copilot is thinking…"):
            try:
                _ai_reply = call_ai_fn(_full_prompt)
            except Exception as _e:
                _ai_reply = f"❌ Error: {str(_e)}"

        # Add AI response
        st.session_state["copilot_chat_messages"].append({
            "role": "assistant",
            "content": _ai_reply,
        })

        st.rerun()

    # ── Display Chat History ───────────────────────────────────────────────────
    if st.session_state["copilot_chat_messages"]:
        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)
        st.markdown("---")
        st.markdown("### 💬 Conversation")
        
        for _msg in st.session_state["copilot_chat_messages"]:
            if _msg["role"] == "user":
                st.markdown(f"""
                <div class="copilot-msg-user">
                    <div class="copilot-msg-label">👤 You</div>
                    <div class="copilot-msg-text">{_msg['content']}</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="copilot-msg-ai">
                    <div class="copilot-msg-label">🤖 Copilot</div>
                    <div class="copilot-msg-text">{_msg['content']}</div>
                </div>
                """, unsafe_allow_html=True)
        
        # Clear button
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        _clear_col1, _clear_col2, _clear_col3 = st.columns([2, 1, 2])
        with _clear_col2:
            if st.button("🗑 Clear", key="cp_clear_all", use_container_width=True):
                st.session_state["copilot_chat_messages"] = []
                st.session_state["copilot_selected_devices"] = []
                st.session_state["copilot_uploaded_image"] = None
                st.session_state["copilot_ai_mode"] = None
                st.session_state["cp_show_upload"] = False
                st.session_state["cp_show_mode"] = False
                st.session_state["cp_show_devs"] = False
                st.rerun()
