from __future__ import annotations

import html
from datetime import datetime
from typing import Callable, Dict, List, Optional

import streamlit as st


def _safe_text(value: object) -> str:
    """Safely escape user-visible text."""
    return html.escape(str(value or ""))


def _init_copilot_state() -> None:
    """Initialize Network Copilot session state."""
    defaults = {
        "ni_copilot_messages": [],
        "ni_copilot_input": "",
        "ni_copilot_active_page": "Copilot",
        "ni_copilot_user_email": "ajaysartaj@gmail.com",
        "ni_copilot_user_role": "Network Admin",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _inject_network_copilot_css() -> None:
    """Inject professional Network Intelligence Copilot styling."""

    st.markdown(
        """
<style>
/* ------------------------------------------------------------------
   Hide Streamlit default shell
------------------------------------------------------------------ */
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"],
#MainMenu,
header,
footer {
    display: none !important;
}

[data-testid="stAppViewContainer"] {
    background: #020617 !important;
}

[data-testid="stSidebar"] {
    display: none !important;
}

[data-testid="block-container"] {
    padding: 0 !important;
    max-width: 100% !important;
}

/* ------------------------------------------------------------------
   Root layout
------------------------------------------------------------------ */
.ni-shell {
    min-height: 100vh;
    width: 100%;
    display: grid;
    grid-template-columns: 252px minmax(0, 1fr);
    background:
        radial-gradient(circle at 58% 35%, rgba(14, 165, 233, 0.08), transparent 28%),
        radial-gradient(circle at 70% 42%, rgba(37, 99, 235, 0.06), transparent 32%),
        #020617;
    color: #f8fafc;
    font-family:
        Inter,
        ui-sans-serif,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

/* ------------------------------------------------------------------
   Sidebar
------------------------------------------------------------------ */
.ni-sidebar {
    min-height: 100vh;
    background: #050817;
    border-right: 1px solid rgba(148, 163, 184, 0.14);
    display: flex;
    flex-direction: column;
}

.ni-brand {
    height: 72px;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 0 14px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.10);
}

.ni-brand-icon {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    background: linear-gradient(135deg, #38bdf8, #2563eb);
    display: grid;
    place-items: center;
    color: white;
    font-size: 23px;
    box-shadow:
        0 14px 34px rgba(37, 99, 235, 0.35),
        inset 0 1px 0 rgba(255, 255, 255, 0.25);
}

.ni-brand-title {
    font-size: 18px;
    line-height: 20px;
    font-weight: 800;
    letter-spacing: -0.035em;
    color: #f8fafc;
}

.ni-brand-subtitle {
    margin-top: 5px;
    font-size: 10px;
    line-height: 12px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: #64748b;
}

.ni-nav {
    flex: 1;
    padding: 14px 12px;
    overflow-y: auto;
}

.ni-nav-section {
    margin: 20px 8px 9px;
    color: #475569;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.28em;
    text-transform: uppercase;
}

.ni-nav-item {
    height: 42px;
    padding: 0 12px;
    margin: 3px 0;
    border-radius: 8px;
    color: #94a3b8;
    display: flex;
    align-items: center;
    gap: 13px;
    font-size: 14px;
    font-weight: 650;
    border: 1px solid transparent;
}

.ni-nav-item svg {
    flex: 0 0 auto;
    width: 18px;
    height: 18px;
    color: #94a3b8;
}

.ni-nav-item-active {
    color: #f8fafc;
    background: linear-gradient(90deg, rgba(14, 165, 233, 0.20), rgba(37, 99, 235, 0.08));
    border-color: rgba(14, 165, 233, 0.32);
    box-shadow:
        0 0 0 1px rgba(14, 165, 233, 0.10),
        0 12px 32px rgba(14, 165, 233, 0.08);
}

.ni-nav-item-active svg {
    color: #67e8f9;
}

.ni-nav-ai-badge {
    margin-left: auto;
    height: 24px;
    min-width: 30px;
    border-radius: 7px;
    background: rgba(14, 165, 233, 0.18);
    color: #67e8f9;
    font-size: 10px;
    font-weight: 900;
    display: grid;
    place-items: center;
}

.ni-user-card {
    border-top: 1px solid rgba(148, 163, 184, 0.13);
    padding: 16px 13px 15px;
}

.ni-user-email {
    font-size: 13px;
    font-weight: 800;
    color: #f8fafc;
    line-height: 18px;
}

.ni-user-role {
    color: #64748b;
    font-size: 12px;
    margin-top: 1px;
}

.ni-signout-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 12px;
}

.ni-signout {
    flex: 1;
    height: 36px;
    border-radius: 8px;
    background: #111827;
    color: #cbd5e1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 9px;
    font-size: 14px;
    font-weight: 650;
}

.ni-collapse {
    width: 30px;
    height: 36px;
    color: #64748b;
    display: grid;
    place-items: center;
}

/* ------------------------------------------------------------------
   Main area
------------------------------------------------------------------ */
.ni-main {
    min-height: 100vh;
    position: relative;
    display: grid;
    place-items: center;
    padding: 28px 32px;
}

.ni-copilot-center {
    width: min(768px, calc(100vw - 320px));
    margin-top: -42px;
    display: flex;
    flex-direction: column;
    align-items: center;
}

.ni-hero-icon {
    width: 80px;
    height: 80px;
    border-radius: 23px;
    display: grid;
    place-items: center;
    background: linear-gradient(135deg, #4fc3f7, #1d4ed8);
    color: #ffffff;
    font-size: 42px;
    box-shadow:
        0 24px 60px rgba(14, 165, 233, 0.25),
        0 0 72px rgba(34, 211, 238, 0.13),
        inset 0 1px 0 rgba(255, 255, 255, 0.25);
}

.ni-title {
    margin-top: 24px;
    color: #f8fafc;
    font-size: clamp(30px, 3vw, 38px);
    line-height: 1.05;
    font-weight: 900;
    letter-spacing: -0.065em;
    text-align: center;
}

.ni-subtitle {
    margin-top: 18px;
    color: #a8b3c7;
    font-size: 16px;
    font-weight: 520;
    text-align: center;
}

.ni-search-shell {
    width: 100%;
    margin-top: 42px;
    height: 74px;
    border-radius: 15px;
    border: 1px solid rgba(148, 163, 184, 0.18);
    background: #111827;
    box-shadow:
        0 20px 60px rgba(0, 0, 0, 0.24),
        inset 0 1px 0 rgba(255, 255, 255, 0.04);
    display: grid;
    grid-template-columns: 1fr 62px;
    align-items: center;
    padding: 0 15px 0 28px;
}

.ni-input-fake {
    color: #64748b;
    font-size: 16px;
    font-weight: 520;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

/* Streamlit form styling */
.ni-streamlit-form {
    width: 100%;
    margin-top: 42px;
}

.ni-streamlit-form [data-testid="stForm"] {
    border: 0 !important;
    padding: 0 !important;
}

.ni-streamlit-form [data-testid="stHorizontalBlock"] {
    gap: 0.75rem !important;
}

.ni-streamlit-form div[data-testid="stTextInput"] {
    margin: 0 !important;
}

.ni-streamlit-form div[data-testid="stTextInput"] > label {
    display: none !important;
}

.ni-streamlit-form div[data-testid="stTextInput"] input {
    height: 74px !important;
    border-radius: 15px !important;
    border: 1px solid rgba(148, 163, 184, 0.20) !important;
    background: #111827 !important;
    color: #f8fafc !important;
    padding: 0 22px !important;
    font-size: 16px !important;
    font-weight: 520 !important;
    box-shadow:
        0 20px 60px rgba(0, 0, 0, 0.24),
        inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
}

.ni-streamlit-form div[data-testid="stTextInput"] input::placeholder {
    color: #64748b !important;
    opacity: 1 !important;
}

.ni-streamlit-form div[data-testid="stTextInput"] input:focus {
    border-color: rgba(14, 165, 233, 0.42) !important;
    box-shadow:
        0 0 0 3px rgba(14, 165, 233, 0.10),
        0 20px 60px rgba(0, 0, 0, 0.24) !important;
}

.ni-streamlit-form div[data-testid="stButton"] button {
    height: 74px !important;
    min-width: 62px !important;
    border-radius: 15px !important;
    background: linear-gradient(135deg, rgba(14, 165, 233, 0.48), rgba(37, 99, 235, 0.62)) !important;
    color: #93c5fd !important;
    border: 1px solid rgba(14, 165, 233, 0.20) !important;
    font-size: 28px !important;
    font-weight: 700 !important;
    box-shadow: none !important;
}

.ni-streamlit-form div[data-testid="stButton"] button:hover {
    background: linear-gradient(135deg, #0ea5e9, #2563eb) !important;
    color: white !important;
    border-color: rgba(125, 211, 252, 0.45) !important;
}

/* ------------------------------------------------------------------
   Conversation panel
------------------------------------------------------------------ */
.ni-chat {
    width: 100%;
    margin-top: 28px;
    display: flex;
    flex-direction: column;
    gap: 12px;
}

.ni-message {
    border-radius: 14px;
    padding: 14px 16px;
    border: 1px solid rgba(148, 163, 184, 0.14);
    background: rgba(15, 23, 42, 0.70);
    color: #cbd5e1;
    font-size: 14px;
    line-height: 1.6;
}

.ni-message-user {
    background: rgba(14, 165, 233, 0.10);
    border-color: rgba(14, 165, 233, 0.25);
}

.ni-message-ai {
    background: rgba(17, 24, 39, 0.88);
}

.ni-message-meta {
    color: #64748b;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-weight: 800;
    margin-bottom: 7px;
}

.ni-suggestion-grid {
    width: 100%;
    margin-top: 22px;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 12px;
}

.ni-suggestion {
    border: 1px solid rgba(148, 163, 184, 0.13);
    background: rgba(15, 23, 42, 0.50);
    border-radius: 14px;
    padding: 13px 14px;
    color: #94a3b8;
    font-size: 13px;
    font-weight: 620;
}

.ni-suggestion-title {
    color: #e2e8f0;
    font-size: 13px;
    font-weight: 800;
    margin-bottom: 4px;
}

.ni-bottom-badge {
    position: absolute;
    right: 30px;
    bottom: 22px;
    height: 34px;
    padding: 0 14px;
    border-radius: 7px;
    background: #ffffff;
    color: #020617;
    font-size: 12px;
    font-weight: 900;
    display: flex;
    align-items: center;
    gap: 7px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.22);
}

/* ------------------------------------------------------------------
   Responsive
------------------------------------------------------------------ */
@media (max-width: 920px) {
    .ni-shell {
        grid-template-columns: 1fr;
    }

    .ni-sidebar {
        display: none;
    }

    .ni-main {
        padding: 28px 18px;
    }

    .ni-copilot-center {
        width: min(760px, calc(100vw - 36px));
    }

    .ni-suggestion-grid {
        grid-template-columns: 1fr;
    }

    .ni-bottom-badge {
        display: none;
    }
}
</style>
        """,
        unsafe_allow_html=True,
    )


def _icon_brain() -> str:
    return "🧠"


def _svg_icon(name: str) -> str:
    icons = {
        "brain": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M9 3a3 3 0 0 0-3 3v1.1A4 4 0 0 0 4 14a4 4 0 0 0 4 4h1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
<path d="M15 3a3 3 0 0 1 3 3v1.1A4 4 0 0 1 20 14a4 4 0 0 1-4 4h-1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
<path d="M9 3v18M15 3v18M9 9H7M15 9h2M9 14H7M15 14h2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "dashboard": """
<svg viewBox="0 0 24 24" fill="none">
<rect x="4" y="5" width="16" height="11" rx="1.5" stroke="currentColor" stroke-width="1.8"/>
<path d="M9 20h6M12 16v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "shield": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M12 3 19 6v5c0 4.8-3 8.5-7 10-4-1.5-7-5.2-7-10V6l7-3Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
</svg>
""",
        "rocket": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M14 4c2.8.3 4.7 2.2 5 5l-5.7 5.7-4-4L14 4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
<path d="M8 13 5 16v3h3l3-3M14 4l-2 6M19 9l-6 2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "topology": """
<svg viewBox="0 0 24 24" fill="none">
<rect x="4" y="4" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.8"/>
<rect x="15" y="4" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.8"/>
<rect x="9.5" y="15" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.8"/>
<path d="M9 6.5h6M7 9l3.5 6M17 9l-3.5 6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "history": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M5 12h14M12 9v6" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "compliance": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M12 3 18 5.5v6c0 3.8-2.4 7-6 8.5-3.6-1.5-6-4.7-6-8.5v-6L12 3Z" stroke="currentColor" stroke-width="1.8"/>
<path d="m9 12 2 2 4-5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""",
        "incident": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M12 4 21 20H3L12 4Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
<path d="M12 9v5M12 17h.01" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "workflow": """
<svg viewBox="0 0 24 24" fill="none">
<rect x="4" y="5" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.8"/>
<rect x="15" y="5" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.8"/>
<rect x="9.5" y="15" width="5" height="5" rx="1" stroke="currentColor" stroke-width="1.8"/>
<path d="M9 7.5h6M12 10v5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "observability": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M4 13h3l2-6 4 12 2-6h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""",
        "devices": """
<svg viewBox="0 0 24 24" fill="none">
<rect x="4" y="5" width="16" height="5" rx="1.2" stroke="currentColor" stroke-width="1.8"/>
<rect x="4" y="14" width="16" height="5" rx="1.2" stroke="currentColor" stroke-width="1.8"/>
<path d="M7 7.5h.01M7 16.5h.01" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>
</svg>
""",
        "admin": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z" stroke="currentColor" stroke-width="1.8"/>
<path d="M4 12h2M18 12h2M12 4v2M12 18v2M6.4 6.4l1.4 1.4M16.2 16.2l1.4 1.4M17.6 6.4l-1.4 1.4M7.8 16.2l-1.4 1.4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
</svg>
""",
        "logout": """
<svg viewBox="0 0 24 24" fill="none">
<path d="M10 6H6v12h4M14 8l4 4-4 4M18 12H9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""",
        "chevron": """
<svg viewBox="0 0 24 24" fill="none">
<path d="m14 7-5 5 5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
""",
    }
    return icons.get(name, icons["dashboard"])


def _nav_item(label: str, icon: str, active: bool = False, badge: Optional[str] = None) -> str:
    active_class = " ni-nav-item-active" if active else ""
    badge_html = f'<span class="ni-nav-ai-badge">{_safe_text(badge)}</span>' if badge else ""
    return f"""
<div class="ni-nav-item{active_class}">
    {_svg_icon(icon)}
    <span>{_safe_text(label)}</span>
    {badge_html}
</div>
"""


def _render_sidebar() -> None:
    email = st.session_state.get("ni_copilot_user_email", "ajaysartaj@gmail.com")
    role = st.session_state.get("ni_copilot_user_role", "Network Admin")

    st.markdown(
        f"""
<aside class="ni-sidebar">
    <div class="ni-brand">
        <div class="ni-brand-icon">{_icon_brain()}</div>
        <div>
            <div class="ni-brand-title">NetBrain AI</div>
            <div class="ni-brand-subtitle">Network Intelligence</div>
        </div>
    </div>

    <nav class="ni-nav">
        {_nav_item("Copilot", "brain", active=True, badge="AI")}
        {_nav_item("Dashboard", "dashboard")}

        <div class="ni-nav-section">Analysis</div>
        {_nav_item("Risk Analysis", "shield")}
        {_nav_item("Deployment", "rocket")}
        {_nav_item("Topology", "topology")}
        {_nav_item("Change History", "history")}
        {_nav_item("Compliance", "compliance")}

        <div class="ni-nav-section">Operations</div>
        {_nav_item("Incidents", "incident")}
        {_nav_item("Workflows", "workflow")}
        {_nav_item("Observability", "observability")}
        {_nav_item("Devices", "devices")}

        <div class="ni-nav-section">System</div>
        {_nav_item("Admin", "admin")}
    </nav>

    <div class="ni-user-card">
        <div class="ni-user-email">{_safe_text(email)}</div>
        <div class="ni-user-role">{_safe_text(role)}</div>

        <div class="ni-signout-row">
            <div class="ni-signout">
                {_svg_icon("logout")}
                <span>Sign Out</span>
            </div>
            <div class="ni-collapse">
                {_svg_icon("chevron")}
            </div>
        </div>
    </div>
</aside>
        """,
        unsafe_allow_html=True,
    )


def _render_messages() -> None:
    messages: List[Dict[str, str]] = st.session_state.get("ni_copilot_messages", [])

    if not messages:
        st.markdown(
            """
<div class="ni-suggestion-grid">
    <div class="ni-suggestion">
        <div class="ni-suggestion-title">Analyze risk</div>
        Validate OSPF, BGP, VLAN, ACL, or firewall policy changes before deployment.
    </div>
    <div class="ni-suggestion">
        <div class="ni-suggestion-title">Troubleshoot</div>
        Ask why a site, router, tunnel, neighbor, or service is degraded.
    </div>
    <div class="ni-suggestion">
        <div class="ni-suggestion-title">Deploy safely</div>
        Generate a plan, rollback, and verification commands before approval.
    </div>
</div>
            """,
            unsafe_allow_html=True,
        )
        return

    st.markdown('<div class="ni-chat">', unsafe_allow_html=True)

    for msg in messages[-8:]:
        role = msg.get("role", "assistant")
        content = _safe_text(msg.get("content", ""))
        timestamp = _safe_text(msg.get("timestamp", ""))

        if role == "user":
            st.markdown(
                f"""
<div class="ni-message ni-message-user">
    <div class="ni-message-meta">You · {timestamp}</div>
    {content}
</div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"""
<div class="ni-message ni-message-ai">
    <div class="ni-message-meta">Network Intelligence Copilot · {timestamp}</div>
    {content}
</div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("</div>", unsafe_allow_html=True)


def _fallback_ai_response(prompt: str) -> str:
    """Fallback response when no AI callable is passed."""
    cleaned = prompt.strip()

    if not cleaned:
        return "Please describe what you want to analyze, validate, deploy, or troubleshoot."

    return (
        "I can help analyze this request. For a production workflow, I would review the "
        "affected device, protocol, intended change, current telemetry, known incidents, "
        "RAG runbooks, MCP/vendor references, risk score, rollback plan, and verification commands."
    )


def render_network_copilot_page(
    call_ai: Optional[Callable[[str], str]] = None,
    user_email: str = "ajaysartaj@gmail.com",
    user_role: str = "Network Admin",
) -> None:
    """
    Render the professional Network Intelligence Copilot page.

    Usage from app.py:

        from workspaces.network_copilot import render_network_copilot_page

        if workspace == "copilot":
            render_network_copilot_page(call_ai=call_ai)
            st.stop()
    """

    _init_copilot_state()
    _inject_network_copilot_css()

    st.session_state["ni_copilot_user_email"] = user_email
    st.session_state["ni_copilot_user_role"] = user_role

    st.markdown('<div class="ni-shell">', unsafe_allow_html=True)

    _render_sidebar()

    st.markdown(
        f"""
<main class="ni-main">
    <section class="ni-copilot-center">
        <div class="ni-hero-icon">{_icon_brain()}</div>
        <div class="ni-title">Network Intelligence Copilot</div>
        <div class="ni-subtitle">
            Describe what you want to analyze, validate, deploy, or troubleshoot.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="ni-streamlit-form">', unsafe_allow_html=True)

    with st.form("network_intelligence_copilot_form", clear_on_submit=True):
        input_col, button_col = st.columns([12, 1])

        with input_col:
            prompt = st.text_input(
                "Network Intelligence Copilot input",
                placeholder="Analyze OSPF changes in Branch-101...",
                label_visibility="collapsed",
            )

        with button_col:
            submitted = st.form_submit_button("›")

    st.markdown("</div>", unsafe_allow_html=True)

    if submitted and prompt.strip():
        now = datetime.utcnow().strftime("%H:%M UTC")

        st.session_state["ni_copilot_messages"].append(
            {
                "role": "user",
                "content": prompt.strip(),
                "timestamp": now,
            }
        )

        ai_func = call_ai or _fallback_ai_response

        try:
            answer = ai_func(prompt.strip())
        except Exception as exc:
            answer = f"AI engine error: {exc}"

        st.session_state["ni_copilot_messages"].append(
            {
                "role": "assistant",
                "content": answer,
                "timestamp": datetime.utcnow().strftime("%H:%M UTC"),
            }
        )

        st.rerun()

    _render_messages()

    st.markdown(
        """
    </section>

    <div class="ni-bottom-badge">
        <span style="font-size:18px;font-weight:900;">b</span>
        <span>Made in Bolt</span>
    </div>
</main>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    st.set_page_config(
        page_title="Network Intelligence Copilot",
        page_icon="🧠",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    render_network_copilot_page()
