"""
NetBrain AI — Autonomous Network Intelligence Platform
Streamlit app — main entry point
"""

import streamlit as st
import pandas as pd
import json, time
from datetime import datetime

# ── Page config MUST be first ──────────────────────────────
st.set_page_config(
    page_title="NetBrain AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "NetBrain AI — Autonomous Network Intelligence Platform v1.0"}
)

# ── Engine import ──────────────────────────────────────────
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from engines.core import (
    init_db, system_status, full_pipeline, run_multi_device_query,
    extract_entities, rag_search, ingest_document, get_devices,
    add_device, get_incidents, call_claude, get_rag_collection,
    CLAUDE_OK, NETMIKO_OK, SPACY_OK, RAG_OK
)

# ── Init DB on first run ───────────────────────────────────
init_db()

# ── Global CSS ─────────────────────────────────────────────
st.markdown("""
<style>
/* ── fonts ── */
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@400;500&family=Fraunces:wght@600;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* ── sidebar ── */
[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #d9dde6;
    padding-top: 0 !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { font-size: 12px; }

/* ── top bar brand ── */
.brand-header {
    background: linear-gradient(135deg, #0a1628, #0f2042);
    border-radius: 12px; padding: 14px 18px;
    margin-bottom: 16px; display: flex; align-items: center; gap: 12px;
}
.brand-icon { font-size: 28px; }
.brand-name { font-family:'Fraunces',serif; font-size:20px; font-weight:700; color:#fff; }
.brand-sub  { font-size:11px; color:rgba(255,255,255,.45); letter-spacing:.8px; font-family:'DM Mono',monospace; }

/* ── status pills ── */
.pill-row { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:12px; }
.pill { font-size:11px; padding:3px 9px; border-radius:20px; font-family:'DM Mono',monospace; font-weight:500; display:inline-block; }
.pill-on  { background:#d4f0e1; color:#14613a; border:1px solid #a0dfc0; }
.pill-off { background:#fad5d2; color:#8b1a1a; border:1px solid #f0a0a0; }
.pill-sim { background:#fde8b8; color:#7a4a00; border:1px solid #f0c070; }

/* ── metric cards ── */
.metric-row { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:16px; }
.metric-card {
    background:#fff; border:1px solid #d9dde6; border-radius:12px;
    padding:16px; box-shadow:0 1px 4px rgba(15,27,45,.06);
    border-bottom:3px solid #ccc;
}
.mc-green { border-bottom-color:#1e8f55; }
.mc-red   { border-bottom-color:#c0392b; }
.mc-blue  { border-bottom-color:#0077cc; }
.mc-amber { border-bottom-color:#b06a00; }
.mc-label { font-size:10px; font-weight:600; color:#7a8799; letter-spacing:.5px; text-transform:uppercase; font-family:'DM Mono',monospace; }
.mc-value { font-family:'Fraunces',serif; font-size:28px; font-weight:700; margin:4px 0 2px; line-height:1; }
.mc-meta  { font-size:12px; color:#7a8799; }
.mcv-green { color:#14613a; } .mcv-red { color:#8b1a1a; }
.mcv-blue  { color:#1e4080; } .mcv-amber { color:#7a4a00; }

/* ── AI insight bar ── */
.ai-bar {
    background:linear-gradient(135deg,#f0f5fd,#fff);
    border:1px solid #c8d9f5; border-radius:12px;
    padding:14px 16px; margin-bottom:16px;
    display:flex; gap:12px; align-items:flex-start;
}
.ai-bar-icon {
    width:34px; height:34px; border-radius:8px; flex-shrink:0;
    background:linear-gradient(135deg,#3b74d0,#0077cc);
    display:flex; align-items:center; justify-content:center;
    font-size:16px;
}
.ai-bar-label { font-size:10px; font-weight:600; color:#0077cc; letter-spacing:1px; text-transform:uppercase; font-family:'DM Mono',monospace; margin-bottom:3px; }
.ai-bar-text  { font-size:13px; color:#0f1b2d; line-height:1.6; }

/* ── chat bubbles ── */
.chat-user { background:#0077cc; color:#fff; border-radius:12px 12px 2px 12px; padding:10px 14px; margin:4px 0; display:inline-block; max-width:85%; font-size:13px; }
.chat-ai   { background:#fff; border:1px solid #d9dde6; border-radius:12px 12px 12px 2px; padding:10px 14px; margin:4px 0; display:inline-block; max-width:92%; font-size:13px; box-shadow:0 1px 4px rgba(15,27,45,.06); }
.chat-meta { font-size:10px; color:#7a8799; font-family:'DM Mono',monospace; margin-top:4px; display:flex; gap:6px; flex-wrap:wrap; }
.cm-pill   { padding:1px 6px; border-radius:10px; background:#e4edfc; color:#1e4080; }
.cm-pill-g { background:#d4f0e1; color:#14613a; }
.cm-pill-p { background:#e8d9fa; color:#4a2080; }
.cm-pill-t { background:#d0f0f5; color:#0e5460; }

/* ── device cards ── */
.dev-card { background:#fff; border:1px solid #d9dde6; border-radius:10px; padding:12px; box-shadow:0 1px 3px rgba(15,27,45,.05); }
.dev-ok   { border-left:4px solid #1e8f55; }
.dev-warn { border-left:4px solid #b06a00; }
.dev-err  { border-left:4px solid #c0392b; }
.dev-hostname { font-family:'DM Mono',monospace; font-size:13px; font-weight:600; color:#0f1b2d; }
.dev-output { font-family:'DM Mono',monospace; font-size:11px; background:#0a1628; color:#7dd3a8; padding:8px; border-radius:6px; margin-top:6px; white-space:pre-wrap; max-height:120px; overflow-y:auto; line-height:1.7; }

/* ── entity tags ── */
.ent-tag { font-size:11px; padding:2px 7px; border-radius:10px; border:1px solid #d9dde6; color:#4a5568; font-family:'DM Mono',monospace; display:inline-block; margin:2px; }

/* ── rag chunk ── */
.rag-chunk { background:#fff; border:1px solid #d9dde6; border-radius:10px; padding:12px; margin-bottom:10px; box-shadow:0 1px 3px rgba(15,27,45,.04); }
.rag-src   { font-size:10px; font-weight:600; color:#0e5460; font-family:'DM Mono',monospace; margin-bottom:5px; }
.rag-body  { font-size:12px; color:#4a5568; line-height:1.7; }

/* ── section header ── */
.sec-hdr { font-family:'Fraunces',serif; font-size:18px; font-weight:700; color:#0f1b2d; margin-bottom:4px; }
.sec-sub  { font-size:13px; color:#4a5568; margin-bottom:16px; }

/* ── streamlit tweaks ── */
div[data-testid="stButton"] button {
    border-radius: 8px !important; font-family:'DM Sans',sans-serif !important;
    font-weight: 500 !important;
}
div[data-testid="stTextInput"] input, div[data-testid="stTextArea"] textarea {
    border-radius: 8px !important;
}
div[data-testid="stSelectbox"] { border-radius: 8px !important; }
.stAlert { border-radius: 10px !important; }
div[data-testid="stExpander"] { border-radius: 10px !important; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════
if "chat_history"    not in st.session_state: st.session_state.chat_history    = []
if "chat_messages"   not in st.session_state: st.session_state.chat_messages   = []
if "persona"         not in st.session_state: st.session_state.persona         = "noc"
if "mdq_results"     not in st.session_state: st.session_state.mdq_results     = None
if "nlp_results"     not in st.session_state: st.session_state.nlp_results     = None
if "rag_results"     not in st.session_state: st.session_state.rag_results     = []
if "active_page"     not in st.session_state: st.session_state.active_page     = "Overview"

# ══════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════
with st.sidebar:
    # Brand
    st.markdown("""
    <div class="brand-header">
      <div class="brand-icon">🧠</div>
      <div>
        <div class="brand-name">NetBrain AI</div>
        <div class="brand-sub">Network Intelligence</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # System status
    status = system_status()
    c_ok  = "pill-on"  if status["claude"]   else "pill-off"
    n_ok  = "pill-on"  if status["netmiko"]  else "pill-sim"
    s_ok  = "pill-on"  if status["spacy"]    else "pill-off"
    r_ok  = "pill-on"  if status["rag"]      else "pill-off"
    n_lbl = "Netmiko ✓" if status["netmiko"] else "Netmiko ⚡ Sim"
    st.markdown(f"""
    <div class="pill-row">
      <span class="pill {c_ok}">Claude {'✓' if status['claude'] else '✗'}</span>
      <span class="pill {n_ok}">{n_lbl}</span>
      <span class="pill {s_ok}">NLP {'✓' if status['spacy'] else '✗'}</span>
      <span class="pill {r_ok}">RAG {'✓' if status['rag'] else '✗'}</span>
    </div>
    """, unsafe_allow_html=True)

    # Persona selector
    st.markdown("**AI Persona**")
    persona_opts = {"🎓 CCNA Mode": "ccna", "🖥 NOC Engineer": "noc", "🏗 Architect": "arch"}
    chosen = st.radio("", list(persona_opts.keys()), index=1, label_visibility="collapsed")
    st.session_state.persona = persona_opts[chosen]

    st.divider()

    # Navigation
    st.markdown("**Operations**")
    pages_ops = ["Overview", "Topology", "Alerts & Outages", "Troubleshooting", "Automation", "Compliance", "Security Ops"]
    for p in pages_ops:
        if st.button(p, key=f"nav_{p}", use_container_width=True):
            st.session_state.active_page = p

    st.markdown("**AI Intelligence**")
    pages_ai = ["AI Assistant", "Multi-Device Query ⚡", "NLP Engine 🧬", "RAG Knowledge 📚", "CLI Assistant", "Network Design", "Digital Twin", "Voice Ops"]
    for p in pages_ai:
        if st.button(p, key=f"nav_{p}", use_container_width=True):
            st.session_state.active_page = p

    st.markdown("**Learning**")
    pages_learn = ["Learning Hub", "Device Manager"]
    for p in pages_learn:
        if st.button(p, key=f"nav_{p}", use_container_width=True):
            st.session_state.active_page = p

    st.markdown("**Business**")
    pages_biz = ["Executive View", "FinOps & Cost"]
    for p in pages_biz:
        if st.button(p, key=f"nav_{p}", use_container_width=True):
            st.session_state.active_page = p

    st.divider()
    # Health
    st.markdown("**Platform Health**")
    st.progress(0.97)
    st.caption("97% · All systems nominal")
    st.caption("NetBrain AI v1.0 · Streamlit")


# ══════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════
def ai_bar(label, text):
    st.markdown(f"""
    <div class="ai-bar">
      <div class="ai-bar-icon">🧠</div>
      <div>
        <div class="ai-bar-label">{label}</div>
        <div class="ai-bar-text">{text}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def metric_row(metrics):
    """metrics: list of (label, value, meta, color_class, value_class)"""
    cols = st.columns(len(metrics))
    for col, (label, value, meta, card_cls, val_cls) in zip(cols, metrics):
        with col:
            st.markdown(f"""
            <div class="metric-card {card_cls}">
              <div class="mc-label">{label}</div>
              <div class="mc-value {val_cls}">{value}</div>
              <div class="mc-meta">{meta}</div>
            </div>
            """, unsafe_allow_html=True)


def render_chat_message(role, content, meta=None):
    if role == "user":
        st.markdown(f'<div style="text-align:right"><span class="chat-user">{content}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="chat-ai">{content}</div>', unsafe_allow_html=True)
        if meta:
            pills = ""
            if meta.get("persona_used"):   pills += f'<span class="cm-pill cm-pill-g">Persona: {meta["persona_used"]}</span>'
            if meta.get("rag_sources"):    pills += f'<span class="cm-pill cm-pill-t">📚 RAG: {", ".join(meta["rag_sources"][:2])}</span>'
            if meta.get("similar_incidents"): pills += f'<span class="cm-pill">💡 Past: {meta["similar_incidents"][0]}</span>'
            ents = meta.get("entities",{})
            if ents.get("protocols"):      pills += f'<span class="cm-pill cm-pill-p">🧬 {", ".join(ents["protocols"][:3])}</span>'
            if meta.get("type") == "device_query": pills += f'<span class="cm-pill">⚡ {meta.get("devices_queried",0)} devices</span>'
            if pills:
                st.markdown(f'<div class="chat-meta">{pills}</div>', unsafe_allow_html=True)


def quick_prompt(label, prompt):
    if st.button(label, use_container_width=True, key=f"qp_{label}"):
        st.session_state.chat_messages.append({"role":"user","content":prompt,"meta":None})
        with st.spinner("🧠 Thinking…"):
            result = full_pipeline(prompt, st.session_state.persona, st.session_state.chat_history)
        st.session_state.chat_messages.append({"role":"assistant","content":result["response"],"meta":result})
        st.session_state.chat_history.append({"role":"user","content":prompt})
        st.session_state.chat_history.append({"role":"assistant","content":result["response"]})
        st.session_state.active_page = "AI Assistant"
        st.rerun()


# ══════════════════════════════════════════════════════════
# PAGES
# ══════════════════════════════════════════════════════════
page = st.session_state.active_page

# ─────────────────────────────────── OVERVIEW ─────────────
if page == "Overview":
    st.markdown('<div class="sec-hdr">Network Overview</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">847 managed devices · Real-time telemetry · Last sync 12s ago</div>', unsafe_allow_html=True)

    ai_bar("AI Insight · NLP + RAG + Incident Memory",
           "<strong>BGP session flapping</strong> on <code>PE-MUM-01 → AS65002</code> — 3 flaps/hr. "
           "RAG matched: Nov 2024 incident — root cause ISP BGP withdrawal. "
           "<strong>Action:</strong> Monitor 10 min, escalate to ISP if persists. 142 prefixes at risk.")

    metric_row([
        ("Devices Online",  "831",  "of 847 · 16 degraded",    "metric-card mc-green", "mcv-green"),
        ("Active Alerts",   "7",    "3 critical · 4 warning",   "metric-card mc-red",   "mcv-red"),
        ("BGP Sessions",    "248",  "247 established · 1 active","metric-card mc-blue",  "mcv-blue"),
        ("Avg Latency",     "14ms", "↑ +2ms from baseline",     "metric-card mc-amber", "mcv-amber"),
    ])

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**🗺 Topology Snapshot**")
        # SVG topology rendered via HTML
        st.markdown("""
        <div style="background:#f7f8fa;border:1px solid #d9dde6;border-radius:10px;overflow:hidden">
        <svg viewBox="0 0 480 200" width="100%" xmlns="http://www.w3.org/2000/svg">
          <rect width="480" height="200" fill="#f7f8fa"/>
          <line x1="240" y1="45" x2="110" y2="105" stroke="#b8bfcc" stroke-width="1.5"/>
          <line x1="240" y1="45" x2="240" y2="108" stroke="#f59e0b" stroke-width="2" stroke-dasharray="4 3"/>
          <line x1="240" y1="45" x2="370" y2="105" stroke="#b8bfcc" stroke-width="1.5"/>
          <line x1="110" y1="118" x2="65" y2="168" stroke="#d9dde6" stroke-width="1"/>
          <line x1="110" y1="118" x2="155" y2="168" stroke="#d9dde6" stroke-width="1"/>
          <line x1="240" y1="121" x2="240" y2="168" stroke="#d9dde6" stroke-width="1"/>
          <line x1="370" y1="118" x2="325" y2="168" stroke="#d9dde6" stroke-width="1"/>
          <line x1="370" y1="118" x2="415" y2="168" stroke="#d9dde6" stroke-width="1"/>
          <circle cx="240" cy="33" r="18" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
          <text x="240" y="30" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">CORE</text>
          <text x="240" y="41" text-anchor="middle" fill="#2356a8" font-size="7" font-family="DM Mono">RTR-01</text>
          <rect x="84" y="105" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
          <text x="110" y="119" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-W</text>
          <rect x="214" y="108" width="52" height="22" rx="5" fill="#fff8ea" stroke="#b06a00" stroke-width="1.5"/>
          <text x="240" y="122" text-anchor="middle" fill="#7a4a00" font-size="9" font-family="DM Mono">DIST-C⚠</text>
          <rect x="344" y="105" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
          <text x="370" y="119" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-E</text>
          <circle cx="65" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
          <circle cx="155" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
          <circle cx="240" cy="175" r="9" fill="#fef5f5" stroke="#c0392b" stroke-width="1.5"/>
          <circle cx="325" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
          <circle cx="415" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
          <text x="240" y="193" text-anchor="middle" fill="#c0392b" font-size="7" font-family="DM Mono">DOWN</text>
          <circle cx="24" cy="12" r="5" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
          <text x="33" y="16" fill="#4a5568" font-size="7">Up</text>
          <circle cx="54" cy="12" r="5" fill="#fff8ea" stroke="#b06a00" stroke-width="1"/>
          <text x="63" y="16" fill="#4a5568" font-size="7">Warn</text>
          <circle cx="92" cy="12" r="5" fill="#fef5f5" stroke="#c0392b" stroke-width="1"/>
          <text x="101" y="16" fill="#4a5568" font-size="7">Down</text>
        </svg>
        </div>""", unsafe_allow_html=True)

        if st.button("🗺 Full Topology →", use_container_width=True):
            st.session_state.active_page = "Topology"
            st.rerun()

    with col2:
        st.markdown("**🚨 Active Alerts**")
        alerts = [
            ("🔴", "BGP flapping — PE-MUM-01 → AS65002", "Routing · 142 prefixes · ISP root cause", "2m"),
            ("🔴", "Interface Down — Gi0/0/3 on SW-ACC-14", "Access · VLAN 120 · 47 users", "8m"),
            ("🟡", "High CPU — CORE-RTR-01 (88%)", "OSPF SPF recalculation suspected", "14m"),
            ("🟡", "VPN Tunnel Down — Branch-HYD", "IPSec · DPD timeout", "45m"),
        ]
        for sev, title, meta, t in alerts:
            with st.container():
                c1, c2, c3 = st.columns([0.08, 0.75, 0.17])
                c1.markdown(sev)
                c2.markdown(f"**{title}**\n\n*{meta}*")
                c3.markdown(f"`{t} ago`")
                st.divider()

    # Device table
    st.markdown("**📋 Critical Devices**")
    devs = get_devices()
    if devs:
        df = pd.DataFrame(devs)[["hostname","ip","vendor","role","site"]]
        st.dataframe(df, use_container_width=True, hide_index=True)

    # Quick actions
    st.markdown("**⚡ Quick AI Actions**")
    qc1, qc2, qc3, qc4 = st.columns(4)
    with qc1: quick_prompt("🔧 Diagnose BGP flap", "BGP session flapping on PE-MUM-01 AS65002. Analyze root cause and fix.")
    with qc2: quick_prompt("⚡ Query all devices", "Show BGP summary across all network devices")
    with qc3: quick_prompt("📋 Compliance check", "Run compliance analysis and give top 5 gaps to fix")
    with qc4: quick_prompt("🏗 Design SD-WAN", "Design SD-WAN for 50 branches with dual ISP and Azure integration")


# ─────────────────────────────────── AI ASSISTANT ─────────
elif page == "AI Assistant":
    st.markdown('<div class="sec-hdr">🤖 AI Network Assistant</div>', unsafe_allow_html=True)
    p_labels = {"ccna":"CCNA Mode","noc":"NOC Engineer","arch":"Expert Architect"}
    st.markdown(f'<div class="sec-sub">NLP · RAG · Incident Memory · Claude · Persona: <strong>{p_labels[st.session_state.persona]}</strong></div>', unsafe_allow_html=True)

    # Quick chips
    st.markdown("**Quick queries:**")
    qr1, qr2, qr3, qr4, qr5 = st.columns(5)
    with qr1: quick_prompt("BGP not forming", "Why is BGP not establishing between my edge router and ISP?")
    with qr2: quick_prompt("BGP all devices", "Show BGP summary across all network devices simultaneously")
    with qr3: quick_prompt("OSPF DR election", "Explain OSPF DR election — adapt to my level")
    with qr4: quick_prompt("Generate OSPF config", "Generate Cisco IOS-XR config for OSPF area 0 on Gi0/0/0 with MD5 auth")
    with qr5: quick_prompt("SD-WAN design", "Design SD-WAN for 50 branches, dual ISP, SASE, Azure breakout")

    st.divider()

    # Chat history
    chat_container = st.container()
    with chat_container:
        if not st.session_state.chat_messages:
            st.info("👋 Hello! I'm **NetBrain AI** — your autonomous network intelligence platform.\n\n"
                    "I run 4 AI systems: 🧬 **NLP** entity extraction · 📚 **RAG** knowledge retrieval · "
                    "⚡ **Multi-Device** parallel SSH · 🧠 **Claude** reasoning.\n\n"
                    "Ask me anything about networking — troubleshooting, design, CLI generation, or config analysis.")
        for msg in st.session_state.chat_messages:
            render_chat_message(msg["role"], msg["content"], msg.get("meta"))

    st.divider()

    # Input area
    col_inp, col_btn = st.columns([0.87, 0.13])
    with col_inp:
        user_input = st.text_area("Your message", placeholder="Ask anything — 'BGP not forming with ISP' · paste a config · describe an issue…", height=80, label_visibility="collapsed", key="chat_input_box")
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        send = st.button("Send ➤", use_container_width=True, type="primary")

    if send and user_input.strip():
        msg = user_input.strip()
        st.session_state.chat_messages.append({"role":"user","content":msg,"meta":None})
        with st.spinner("🧠 NLP extracting · RAG retrieving · Claude reasoning…"):
            result = full_pipeline(msg, st.session_state.persona, st.session_state.chat_history)
        st.session_state.chat_messages.append({"role":"assistant","content":result["response"],"meta":result})
        st.session_state.chat_history.append({"role":"user","content":msg})
        st.session_state.chat_history.append({"role":"assistant","content":result["response"]})
        st.rerun()

    if st.button("🗑 Clear conversation", key="clear_chat"):
        st.session_state.chat_messages = []
        st.session_state.chat_history  = []
        st.rerun()


# ─────────────────────────────────── MULTI-DEVICE QUERY ───
elif page == "Multi-Device Query ⚡":
    st.markdown('<div class="sec-hdr">⚡ Multi-Device Query Engine</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">System B — One NL query → all devices in parallel → AI synthesises unified answer</div>', unsafe_allow_html=True)

    ai_bar("Netmiko SSH Engine — System B",
           "Type plain English: <strong>'Show OSPF neighbors on all routers'</strong> · "
           "<strong>'Which devices have BGP in Active state?'</strong> · <strong>'CPU above 80%'</strong> — "
           "I SSH all devices simultaneously and synthesise one answer.")

    # Quick query buttons
    st.markdown("**Quick Queries:**")
    qr = st.columns(6)
    quick_queries = ["BGP summary","OSPF neighbors","CPU usage","Interface status","VLAN status","Routing table"]
    nl_map = {
        "BGP summary":"Show BGP summary across all routers",
        "OSPF neighbors":"Show OSPF neighbor status on all devices",
        "CPU usage":"Show CPU usage on all devices",
        "Interface status":"Show interface status",
        "VLAN status":"Show VLAN brief on all switches",
        "Routing table":"Show routing table summary",
    }
    for i, (col, q) in enumerate(zip(qr, quick_queries)):
        with col:
            if st.button(q, key=f"mdq_quick_{i}", use_container_width=True):
                st.session_state.mdq_input = nl_map[q]

    mdq_input = st.text_input(
        "Natural language query",
        value=st.session_state.get("mdq_input",""),
        placeholder='e.g. "Which routers have BGP sessions in Active state?" · "Show OSPF neighbors on all devices"',
        key="mdq_main_input"
    )

    if st.button("⚡ Query All Devices", type="primary", key="run_mdq"):
        if mdq_input.strip():
            with st.spinner(f"⚡ Querying all devices in parallel for: '{mdq_input}'…"):
                results = run_multi_device_query(mdq_input.strip(), st.session_state.persona)
            st.session_state.mdq_results = results
        else:
            st.warning("Please enter a query.")

    if st.session_state.mdq_results:
        res = st.session_state.mdq_results
        st.success(f"✓ Queried **{res['device_count']} devices** · Query: *{res['query']}*")

        # Device result cards
        st.markdown("**Device Results:**")
        devs = res.get("device_results", [])
        cols = st.columns(min(len(devs), 3)) if devs else []
        for i, dev in enumerate(devs):
            with cols[i % 3] if cols else st.container():
                cls = "dev-ok" if dev["status"]=="ok" else "dev-err"
                sim_note = " · simulated" if dev.get("simulated") else ""
                st.markdown(f"""
                <div class="dev-card {cls}">
                  <div class="dev-hostname">{dev['hostname']} ({dev['ip']})</div>
                  <div style="font-size:11px;color:#7a8799;margin:3px 0;font-family:'DM Mono',monospace">{dev.get('vendor','')} · {dev.get('role','')} · {dev.get('site','')}{sim_note}</div>
                  <div style="font-size:11px;color:#4a5568;font-family:'DM Mono',monospace;margin-bottom:4px">CMD: {dev['command']}</div>
                  <div class="dev-output">{dev['output'][:280]}</div>
                </div>""", unsafe_allow_html=True)

        # AI synthesis
        st.markdown("---")
        st.markdown("**🧠 AI Synthesis — All Devices**")
        st.markdown(res.get("ai_synthesis",""))


# ─────────────────────────────────── NLP ENGINE ───────────
elif page == "NLP Engine 🧬":
    st.markdown('<div class="sec-hdr">🧬 NLP Entity Extractor</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">System C — Extracts IPs, VLANs, protocols, devices, intent from any networking text</div>', unsafe_allow_html=True)

    ai_bar("spaCy + Regex NLP Engine — System C",
           "Paste any network query, log, config, or description. I extract all structured entities "
           "automatically — these are injected into every Claude API call for more precise answers.")

    sample_texts = {
        "BGP log":     "BGP neighbor 10.0.1.1 AS65002 stuck in Active state on GigabitEthernet0/0/0 at PE-MUM-01 in OSPF area 0 VLAN 100",
        "OSPF issue":  "OSPF adjacency lost between CORE-RTR-01 and DIST-SW-W on 192.168.1.0/30 area 0 Cisco IOS-XR",
        "Design req":  "Design VXLAN EVPN leaf-spine datacenter for Arista EOS with BGP EVPN and RoCE for AI GPU cluster",
        "Security":    "Zero Trust ZTNA micro-segmentation with Palo Alto Prisma Access and Zscaler ZPA for 5000 remote users",
    }

    col_s, col_b = st.columns([0.7, 0.3])
    with col_s:
        nlp_text = st.text_area("Paste networking text to extract entities",
            placeholder="BGP neighbor 10.0.1.1 AS65002 not forming on Gi0/0/0 at PE-MUM-01…",
            height=100, key="nlp_input_text")
    with col_b:
        st.markdown("**Sample texts:**")
        for name, sample in sample_texts.items():
            if st.button(name, key=f"nlp_sample_{name}", use_container_width=True):
                st.session_state.nlp_sample = sample
                st.rerun()

    if st.session_state.get("nlp_sample"):
        nlp_text = st.session_state.nlp_sample

    if st.button("🧬 Extract Entities", type="primary", key="run_nlp") and nlp_text:
        ents = extract_entities(nlp_text)
        st.session_state.nlp_results = ents
        st.session_state.nlp_sample = None

    if st.session_state.nlp_results:
        ents = st.session_state.nlp_results

        # Intent and urgency
        intent_colors = {
            "troubleshoot":"red","generate_config":"green","explain":"blue",
            "design":"orange","compare":"purple","query_devices":"teal","analyze_log":"violet","general":"grey"
        }
        col_i1, col_i2, col_i3 = st.columns(3)
        col_i1.metric("Detected Intent", ents.get("intent","general").replace("_"," ").title())
        col_i2.metric("Urgency", ents.get("urgency","normal").title())
        col_i3.metric("Persona Hint", ents.get("persona_hint","auto-detect") or "Auto-detect")

        st.markdown("---")
        entity_map = [
            ("IP Addresses", ents.get("ip_addresses",[])),
            ("Protocols",    ents.get("protocols",[])),
            ("Interfaces",   ents.get("interfaces",[])),
            ("VLANs",        ents.get("vlans",[])),
            ("AS Numbers",   ents.get("as_numbers",[])),
            ("Vendors",      ents.get("vendors",[])),
            ("Hostnames",    ents.get("hostnames",[])),
            ("OSPF Areas",   ents.get("ospf_areas",[])),
        ]
        cols = st.columns(4)
        for i, (label, items) in enumerate(entity_map):
            with cols[i % 4]:
                st.markdown(f"**{label}**")
                if items:
                    tags = " ".join(f'<span class="ent-tag">{x}</span>' for x in items)
                    st.markdown(tags, unsafe_allow_html=True)
                else:
                    st.caption("none detected")


# ─────────────────────────────────── RAG KNOWLEDGE ────────
elif page == "RAG Knowledge 📚":
    st.markdown('<div class="sec-hdr">📚 RAG Knowledge Base</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">System D — ChromaDB + sentence-transformers · Vendor docs, runbooks, RFCs, CVEs</div>', unsafe_allow_html=True)

    ai_bar("RAG Engine — System D",
           "Search the knowledge base directly, or let the AI use it automatically in every chat. "
           "Ingest your own vendor PDFs, runbooks, and SOPs to personalise answers for your network.")

    tab1, tab2 = st.tabs(["🔍 Search Knowledge", "➕ Ingest Document"])

    with tab1:
        rag_query = st.text_input("Search knowledge base",
            placeholder="BGP troubleshooting · OSPF neighbor states · MPLS L3VPN · Zero Trust design…")
        col_rag_v, col_rag_b = st.columns([0.7, 0.3])
        with col_rag_v:
            vendor_f = st.selectbox("Filter by vendor", ["All","cisco","juniper","arista","general"], key="rag_vendor")
        with col_rag_b:
            st.markdown("<br>", unsafe_allow_html=True)
            run_rag = st.button("📚 Search", type="primary", key="run_rag_btn")

        if run_rag and rag_query:
            vf = None if vendor_f == "All" else vendor_f
            with st.spinner("Searching vector knowledge base…"):
                results = rag_search(rag_query, n=5, vendor_filter=vf)
            st.session_state.rag_results = results

        if st.session_state.rag_results:
            st.markdown(f"**Found {len(st.session_state.rag_results)} relevant chunks:**")
            for r in st.session_state.rag_results:
                m = r.get("meta",{})
                st.markdown(f"""
                <div class="rag-chunk">
                  <div class="rag-src">📚 {m.get('title','Knowledge Doc')} · {m.get('vendor','general')} · {m.get('doc_type','ref')} · chunk {m.get('chunk',0)}</div>
                  <div class="rag-body">{r.get('content','')[:400]}{'…' if len(r.get('content',''))>400 else ''}</div>
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown("**Pre-loaded knowledge documents:**")
            docs = [
                ("BGP Troubleshooting Guide","cisco","runbook","BGP states, commands, route filtering, AS_PATH"),
                ("OSPF Troubleshooting Guide","cisco","runbook","Neighbor states, DR/BDR, LSA types, areas"),
                ("VLAN & STP Troubleshooting","cisco","runbook","Trunk config, STP states, EtherChannel"),
                ("SD-WAN Architecture","cisco","design","vManage, OMP, app-aware routing, SASE"),
                ("MPLS & Service Provider","general","reference","LDP, L3VPN, L2VPN, SR, SRv6"),
                ("Zero Trust & Security","general","design","ZTNA, SASE, micro-segmentation, identity"),
                ("VXLAN EVPN Datacenter","general","reference","Leaf-spine, EVPN routes, symmetric IRB, RoCE"),
            ]
            dcols = st.columns(4)
            for i, (title, vendor, dtype, desc) in enumerate(docs):
                with dcols[i % 4]:
                    st.markdown(f"""
                    <div class="rag-chunk">
                      <div class="rag-src">📚 {vendor} · {dtype}</div>
                      <div style="font-size:13px;font-weight:600;margin-bottom:3px">{title}</div>
                      <div class="rag-body">{desc}</div>
                    </div>""", unsafe_allow_html=True)

    with tab2:
        st.markdown("**Ingest your own vendor docs, runbooks, or SOPs into the knowledge base:**")
        ing_title  = st.text_input("Document title", placeholder="e.g. Juniper BGP Configuration Guide")
        ing_vendor = st.selectbox("Vendor", ["cisco","juniper","arista","paloalto","fortinet","general"], key="ing_vendor")
        ing_type   = st.selectbox("Document type", ["manual","runbook","design","reference","sop"], key="ing_type")
        ing_content= st.text_area("Document content", placeholder="Paste full document text here…", height=200)
        if st.button("➕ Ingest Document", type="primary") and ing_content and ing_title:
            with st.spinner("Chunking, embedding, and indexing…"):
                n = ingest_document(ing_title, ing_content, ing_vendor, ing_type)
            st.success(f"✅ Ingested **{n}** chunks from '{ing_title}' into the knowledge base.")


# ─────────────────────────────────── CLI ASSISTANT ────────
elif page == "CLI Assistant":
    st.markdown('<div class="sec-hdr">💻 CLI Assistant</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">NL → CLI translation · Multi-vendor · AI-explained output</div>', unsafe_allow_html=True)

    ai_bar("NL → CLI Engine",
           "Type plain English: <strong>'Enable OSPF on Gi0/0 area 0 with MD5'</strong> → get exact "
           "Cisco/Juniper/Arista CLI. Or paste a config line and ask <strong>'What does this do?'</strong>")

    col_cv, col_ci = st.columns([0.5, 0.5])
    with col_cv:
        cli_vendor = st.selectbox("Target vendor", ["Cisco IOS","Cisco IOS-XR","Cisco NX-OS","Juniper JunOS","Arista EOS","Palo Alto PAN-OS","Fortinet FortiOS"])
    with col_ci:
        cli_task = st.selectbox("Task type", ["NL to CLI","Explain this command","Review this config","Generate complete config"])

    cli_input = st.text_area("Enter natural language request or paste config/command",
        placeholder="e.g. 'Configure BGP with neighbor 10.0.1.1 AS65002, MD5 password netbrain, send default route' OR paste a config block to explain",
        height=100)

    if st.button("🧠 Generate / Explain", type="primary") and cli_input:
        prompt = f"Vendor: {cli_vendor}. Task: {cli_task}.\n\n{cli_input}\n\nProvide the exact CLI commands with explanation of each line."
        with st.spinner("🧠 Generating CLI…"):
            resp = call_claude([{"role":"user","content":prompt}], persona=st.session_state.persona)
        st.markdown("**Result:**")
        st.markdown(resp)

    # Quick CLI examples
    st.divider()
    st.markdown("**Quick CLI generations:**")
    cq1, cq2, cq3, cq4 = st.columns(4)
    with cq1:
        if st.button("OSPF area 0 config", use_container_width=True):
            st.session_state.active_page = "AI Assistant"
            quick_prompt("x","Generate Cisco IOS-XR config for OSPF area 0 on GigabitEthernet0/0/0 with MD5 auth, hello 5s dead 20s")
    with cq2:
        if st.button("BGP eBGP config", use_container_width=True):
            quick_prompt("x","Generate Cisco IOS-XR eBGP config for neighbor 10.0.1.1 AS65002 with MD5 auth, route-map out, BFD enabled")
    with cq3:
        if st.button("VLAN + trunk config", use_container_width=True):
            quick_prompt("x","Generate Cisco IOS config for VLAN 100 FINANCE, SVI 192.168.100.1/24, trunk on Gi0/1 with VLAN 100 200 300")
    with cq4:
        if st.button("SD-WAN policy", use_container_width=True):
            quick_prompt("x","Generate Cisco Viptela SD-WAN data policy for Office365 with direct internet breakout and SLA class")


# ─────────────────────────────────── TROUBLESHOOTING ──────
elif page == "Troubleshooting":
    st.markdown('<div class="sec-hdr">🔧 AI Troubleshooting</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">NLP + RAG + Incident Memory + Claude · 4-engine diagnosis pipeline</div>', unsafe_allow_html=True)

    ai_bar("4-Engine Troubleshoot Pipeline",
           "<strong>NLP</strong> extracts entities → <strong>RAG</strong> retrieves runbooks → "
           "<strong>Incident Memory</strong> surfaces past RCAs → <strong>Claude</strong> reasons across all → root cause + fix commands.")

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.markdown("**Describe your problem:**")
        problem = st.text_area("Problem description", placeholder="e.g. 'BGP session keeps flapping to ISP since 2 hours ago. CPU spiked to 88%. No config changes made. OSPF also went down briefly.'", height=120)
        tv, ts = st.columns(2)
        with tv: vendor = st.selectbox("Vendor", ["Any","Cisco IOS/IOS-XR","Juniper JunOS","Arista EOS","Palo Alto","Fortinet"])
        with ts: severity = st.selectbox("Severity", ["Unknown","🔴 Critical — production down","🟡 Major — degraded","🟢 Minor"])
        if st.button("🧠 Analyze with 4-Engine Pipeline", type="primary") and problem:
            ctx = f"Problem: {problem}\nVendor: {vendor}\nSeverity: {severity}"
            with st.spinner("🧠 Running NLP → RAG → Incident Memory → Claude…"):
                result = full_pipeline(ctx, st.session_state.persona)
            st.session_state.chat_messages.append({"role":"user","content":ctx,"meta":None})
            st.session_state.chat_messages.append({"role":"assistant","content":result["response"],"meta":result})
            st.session_state.active_page = "AI Assistant"
            st.rerun()

    with col_t2:
        st.markdown("**Common issues (click to diagnose):**")
        issues = [
            ("BGP stuck in Active state","BGP neighbor stuck in Active state on Cisco IOS-XR, troubleshoot systematically"),
            ("OSPF EXSTART stuck","OSPF adjacency stuck in EXSTART, MTU mismatch suspected, how to diagnose and fix"),
            ("VLAN trunk not passing","VLAN traffic not passing between trunk links, STP or allowed VLAN issue"),
            ("SD-WAN failover broken","SD-WAN failover not switching to backup when primary ISP link fails"),
            ("MPLS packet loss","High packet loss on MPLS backbone, how to isolate with LSP ping and trace"),
            ("IPSec VPN flapping","IPSec VPN tunnel flapping, DPD timeout, how to stabilize"),
            ("STP loop detected","Spanning tree loop detected, find blocking port and fix immediately"),
            ("BGP route not advertised","BGP route in routing table but not being advertised to peer"),
        ]
        for label, prompt in issues:
            if st.button(label, key=f"issue_{label}", use_container_width=True):
                with st.spinner(f"🧠 Diagnosing: {label}…"):
                    result = full_pipeline(prompt, st.session_state.persona)
                st.session_state.chat_messages.append({"role":"user","content":prompt,"meta":None})
                st.session_state.chat_messages.append({"role":"assistant","content":result["response"],"meta":result})
                st.session_state.active_page = "AI Assistant"
                st.rerun()


# ─────────────────────────────────── NETWORK DESIGN ───────
elif page == "Network Design":
    st.markdown('<div class="sec-hdr">🏗 Network Design Assistant</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Requirements → Architecture → Hardware sizing → BOM → Implementation roadmap</div>', unsafe_allow_html=True)

    ai_bar("Design AI Engine",
           "Tell me requirements in plain English: <strong>'50 branches, dual ISP, 300 users/branch, Azure, SASE, under $2M'</strong> → "
           "I produce full architecture, vendor selection, hardware list, BOM, and 90-day implementation roadmap.")

    design_types = {
        "🏢 Enterprise Campus": "Design complete enterprise campus network for 3000 users with 3-tier hierarchy, SD-Access, wireless, Zero Trust security",
        "🛣️ SD-WAN":           "Design SD-WAN for 50 branch offices with dual ISP, Azure cloud breakout, SASE integration, application SLA",
        "🏭 Datacenter Fabric": "Design datacenter leaf-spine fabric with VXLAN EVPN for 10000 servers including AI GPU cluster with RoCE",
        "☁️ Hybrid Cloud":     "Design hybrid cloud network connecting on-premises to AWS and Azure with Direct Connect ExpressRoute and SD-WAN",
        "🔐 Zero Trust":       "Design Zero Trust network architecture with ZTNA micro-segmentation Palo Alto Prisma Zscaler ZPA",
        "📡 5G Transport / SP":"Design 5G transport network with SR-MPLS SRv6 network slicing mobile backhaul for telecom operator",
    }

    cols_d = st.columns(3)
    for i, (name, prompt) in enumerate(design_types.items()):
        with cols_d[i % 3]:
            if st.button(name, key=f"design_{name}", use_container_width=True, type="secondary"):
                with st.spinner(f"🏗 Designing {name}…"):
                    result = full_pipeline(prompt, st.session_state.persona)
                st.session_state.chat_messages.append({"role":"user","content":prompt,"meta":None})
                st.session_state.chat_messages.append({"role":"assistant","content":result["response"],"meta":result})
                st.session_state.active_page = "AI Assistant"
                st.rerun()

    st.divider()
    st.markdown("**Or describe your custom requirements:**")
    custom_req = st.text_area("Custom design requirements", placeholder="e.g. 'I need to connect 20 hospitals with EHR systems, HIPAA compliance required, redundant WAN, SD-WAN with ISP diversity, integrate with Azure Health services…'", height=120)
    if st.button("🏗 Generate Architecture", type="primary") and custom_req:
        with st.spinner("🏗 Generating full network architecture…"):
            result = full_pipeline(custom_req, st.session_state.persona)
        st.session_state.chat_messages.append({"role":"user","content":custom_req,"meta":None})
        st.session_state.chat_messages.append({"role":"assistant","content":result["response"],"meta":result})
        st.session_state.active_page = "AI Assistant"
        st.rerun()


# ─────────────────────────────────── LEARNING HUB ─────────
elif page == "Learning Hub":
    st.markdown('<div class="sec-hdr">📖 Learning Hub</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">AI-adaptive · NLP detects your level · CCNA → CCNP → CCIE → Expert architect</div>', unsafe_allow_html=True)

    ai_bar("Adaptive NLP Learning Engine",
           "I detect your level from how you phrase questions. Ask <strong>'what is a VLAN?'</strong> → I teach from scratch. "
           "Ask <strong>'explain 802.1Q Q-in-Q double-tagging edge cases'</strong> → I go expert-level. No configuration needed.")

    tracks = [
        ("🌐","Routing Fundamentals","OSPF · BGP · EIGRP · IS-IS · Policy routing",65,"t-b","Start a lesson on routing fundamentals — OSPF BGP EIGRP. Detect my level first."),
        ("🔀","Switching & VLANs","STP · EtherChannel · VTP · RSTP · MACsec",40,"t-g","Teach me switching — VLANs STP EtherChannel. Start from my current level."),
        ("🛣️","SD-WAN & SASE","Viptela · Versa · Cato · Zscaler · ZTNA",20,"t-a","Explain SD-WAN concepts architecture Cisco Viptela vs Versa Networks and SASE"),
        ("🔒","Network Security","Zero Trust · ZTNA · Firewall · ACL · SASE",55,"t-r","Teach network security — Zero Trust ZTNA firewall ACL micro-segmentation"),
        ("🏢","Datacenter Networking","VXLAN · EVPN · Leaf-Spine · AI fabric · RoCE",10,"t-p","Explain VXLAN EVPN leaf-spine datacenter networking. I am CCNA level."),
        ("☁️","Cloud Networking","AWS · Azure · GCP · Hybrid · Kubernetes",30,"t-d","Teach cloud networking AWS VPC Azure VNet hybrid cloud Kubernetes networking"),
    ]

    cols_tk = st.columns(3)
    for i, (ico, name, desc, pct, cls, prompt) in enumerate(tracks):
        with cols_tk[i % 3]:
            with st.container():
                st.markdown(f"**{ico} {name}**\n\n*{desc}*")
                st.progress(pct / 100)
                st.caption(f"{pct}% complete")
                if st.button(f"Start → {name}", key=f"track_{name}", use_container_width=True):
                    with st.spinner(f"📖 Starting lesson: {name}…"):
                        result = full_pipeline(prompt, st.session_state.persona)
                    st.session_state.chat_messages.append({"role":"user","content":prompt,"meta":None})
                    st.session_state.chat_messages.append({"role":"assistant","content":result["response"],"meta":result})
                    st.session_state.active_page = "AI Assistant"
                    st.rerun()

    st.divider()
    st.markdown("**🏆 Certification Tracks**")
    cert_cols = st.columns(4)
    certs = [
        ("📘","CCNA 200-301","Foundation · Routing · Switching · Security","✅ Ready","green"),
        ("📗","CCNP Enterprise","Advanced routing · SD-Access · SD-WAN · QoS","⏳ In Progress","orange"),
        ("📕","CCIE Enterprise","Expert design · Implementation · Troubleshoot lab","🔴 Advanced","red"),
        ("🌐","CCNP/CCIE SP","MPLS · SRv6 · 5G transport · BGP-LU","📋 Available","blue"),
    ]
    for col, (ico, name, desc, status, color) in zip(cert_cols, certs):
        with col:
            st.markdown(f"**{ico} {name}**\n\n{desc}\n\n**{status}**")
            if st.button(f"Prepare for {name.split(' ')[0]}", key=f"cert_{name}", use_container_width=True):
                quick_prompt("x", f"Help me prepare for {name}. Assess my current level and build a study plan.")


# ─────────────────────────────────── DEVICE MANAGER ───────
elif page == "Device Manager":
    st.markdown('<div class="sec-hdr">🖧 Device Manager</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Add SSH-accessible devices for the multi-device query engine</div>', unsafe_allow_html=True)

    tab_list, tab_add = st.tabs(["📋 All Devices", "➕ Add Device"])

    with tab_list:
        devs = get_devices()
        if devs:
            df = pd.DataFrame(devs)[["hostname","ip","vendor","role","site","port"]]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"**{len(devs)} devices** in database. Netmiko simulation mode is {'ON' if not NETMIKO_OK else 'OFF — real SSH active'}.")
        else:
            st.info("No devices added yet.")

    with tab_add:
        st.markdown("**Add a network device for SSH queries:**")
        c1, c2, c3 = st.columns(3)
        with c1:
            hn = st.text_input("Hostname", placeholder="CORE-RTR-01")
            ip = st.text_input("IP Address", placeholder="10.0.0.1")
        with c2:
            vendor = st.selectbox("Vendor/OS", ["cisco_ios","cisco_ios_xe","cisco_ios_xr","cisco_nxos","juniper_junos","arista_eos","paloalto_panos","fortinet"])
            role   = st.text_input("Role", placeholder="Core Router")
        with c3:
            user   = st.text_input("SSH Username", placeholder="admin")
            passwd = st.text_input("SSH Password", type="password")
            site   = st.text_input("Site", placeholder="HQ")
            port   = st.number_input("Port", value=22, min_value=1, max_value=65535)

        if st.button("➕ Add Device", type="primary"):
            if hn and ip:
                add_device(hn, ip, vendor, user, passwd, int(port), role, site)
                st.success(f"✅ Device **{hn}** ({ip}) added successfully.")
                st.rerun()
            else:
                st.error("Hostname and IP are required.")


# ─────────────────────────────────── COMPLIANCE ───────────
elif page == "Compliance":
    st.markdown('<div class="sec-hdr">🛡 Compliance & Security Posture</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Automated policy validation · AI gap analysis · All frameworks</div>', unsafe_allow_html=True)

    metric_row([
        ("CIS Benchmark",  "91%", "23 violations of 256", "metric-card mc-green", "mcv-green"),
        ("NIST CSF 2.0",   "78%", "Identity controls gap","metric-card mc-amber", "mcv-amber"),
        ("PCI DSS 4.0",    "96%", "Cardholder isolated",  "metric-card mc-green", "mcv-green"),
        ("Zero Trust",     "62%", "Micro-seg partial",    "metric-card mc-amber", "mcv-amber"),
    ])

    frameworks = [
        ("CIS Benchmark","91%","#1e8f55",23,"256 controls · 23 violations · Passwords, logging, encryption"),
        ("NIST CSF 2.0","78%","#b06a00",None,"Identity gap · Govern Identify Protect Detect Respond Recover"),
        ("PCI DSS 4.0","96%","#1e8f55",None,"Cardholder network isolated · SAQ-D compliance"),
        ("ISO 27001","88%","#1e8f55",None,"Audit trail complete · ISMS controls"),
        ("Firmware CVEs","14","#c0392b",14,"3 critical · FW-EDGE-01 FW-EDGE-02 · Patch urgently"),
        ("Zero Trust","62%","#b06a00",None,"Microsegmentation 40% · ZTNA 70% · Identity 80%"),
    ]

    cols_c = st.columns(3)
    for i, (name, score, color, count, desc) in enumerate(frameworks):
        with cols_c[i % 3]:
            with st.container():
                st.markdown(f"**{name}**")
                st.markdown(f"<span style='font-family:Fraunces,serif;font-size:28px;font-weight:700;color:{color}'>{score}</span>", unsafe_allow_html=True)
                st.caption(desc)
                st.divider()

    if st.button("🧠 Run AI Gap Analysis", type="primary"):
        with st.spinner("🧠 Analyzing compliance posture…"):
            result = full_pipeline("Run a complete network compliance gap analysis across CIS, NIST, PCI DSS, Zero Trust. Give me top 5 critical gaps and remediation steps.", st.session_state.persona)
        st.markdown("**AI Gap Analysis:**")
        st.markdown(result["response"])


# ─────────────────────────────────── ALERTS ───────────────
elif page == "Alerts & Outages":
    st.markdown('<div class="sec-hdr">🚨 Alerts & Outage Management</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">AI root-cause correlation · Auto-suppression · Incident memory</div>', unsafe_allow_html=True)

    ai_bar("AI Correlation Engine",
           "<strong>7 alerts correlated into 2 root causes.</strong> Primary: ISP instability AS65002 → BGP flap → OSPF recalc → high CPU (alerts 1,3,4 are symptoms). "
           "Secondary: Physical failure SW-ACC-14 Gi0/0/3. Fix root causes, not all 7 symptoms.")

    metric_row([
        ("Critical Alerts", "3",  "BGP · Interface · Security","metric-card mc-red",   "mcv-red"),
        ("Warning Alerts",  "4",  "CPU · OSPF · VPN · CVEs",   "metric-card mc-amber", "mcv-amber"),
        ("Correlated",      "2",  "Root causes identified",    "metric-card mc-blue",  "mcv-blue"),
        ("MTTR",            "18m","↓ 40% vs last month",       "metric-card mc-green", "mcv-green"),
    ])

    alerts_data = [
        ("🔴","Critical","BGP session flapping — PE-MUM-01 → AS65002","Routing · 3 flaps/hr · 142 prefixes at risk","2m ago","ISP BGP withdrawal — same as Nov 2024 incident"),
        ("🔴","Critical","Interface Down — Gi0/0/3 on SW-ACC-14","Access · VLAN 120 · 47 users impacted","8m ago",None),
        ("🔴","Critical","Lateral Movement — 10.2.14.0/24","Security · Port scan · Possible compromise","22m ago","Correlates with SW-ACC-14 failure"),
        ("🟡","Warning","High CPU — CORE-RTR-01 (88%)","OSPF SPF recalculation · Symptom of BGP flap","14m ago","Related to BGP flap alert #1"),
        ("🟡","Warning","OSPF Neighbor Timeout — Area 0","DR/BDR election · Segment 10.10.40.0/24","31m ago",None),
        ("🟡","Warning","VPN Tunnel Down — Branch-HYD","IPSec · DPD timeout · 1 branch offline","45m ago",None),
        ("🟡","Warning","14 Unpatched CVEs — Edge Devices","Security · 3 critical severity CVEs","2h ago",None),
    ]

    for sev, sev_label, title, meta, t, rca in alerts_data:
        with st.expander(f"{sev} {title}", expanded=sev_label=="Critical"):
            c1, c2 = st.columns([0.75, 0.25])
            with c1:
                st.markdown(f"**{meta}**")
                st.caption(f"⏱ {t}")
                if rca:
                    st.markdown(f"🧠 **AI RCA:** {rca}")
            with c2:
                if st.button("🧠 AI Diagnose", key=f"al_diag_{title[:20]}", use_container_width=True):
                    quick_prompt("x", f"Diagnose this alert: {title}. {meta}. Give root cause and remediation steps.")


# ─────────────────────────────────── SECURITY OPS ─────────
elif page == "Security Ops":
    st.markdown('<div class="sec-hdr">🔒 Security Operations</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Threat correlation · Zero Trust validation · Firewall intelligence</div>', unsafe_allow_html=True)

    metric_row([
        ("Threats Active", "2",   "Lateral movement",       "metric-card mc-red",   "mcv-red"),
        ("CVEs Unpatched", "14",  "3 critical severity",    "metric-card mc-amber", "mcv-amber"),
        ("FW Rule Health", "98%", "Shadow rules cleaned",   "metric-card mc-green", "mcv-green"),
        ("Zero Trust",     "62%", "Improving steadily",     "metric-card mc-blue",  "mcv-blue"),
    ])

    if st.button("🧠 Run Full Security Audit", type="primary"):
        with st.spinner("🧠 Running security posture analysis…"):
            result = full_pipeline("Full security posture analysis: lateral movement threats, unpatched CVEs, firewall rule gaps, Zero Trust readiness, segmentation validation. Prioritize findings.", st.session_state.persona)
        st.markdown(result["response"])


# ─────────────────────────────────── AUTOMATION ───────────
elif page == "Automation":
    st.markdown('<div class="sec-hdr">⚙ Network Automation</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Ansible · Terraform · Self-healing · Config push · Workflow orchestration</div>', unsafe_allow_html=True)

    metric_row([
        ("Jobs This Week",  "342","99.7% success rate",   "metric-card mc-green", "mcv-green"),
        ("Running Now",     "3",  "Config push jobs",     "metric-card mc-blue",  "mcv-blue"),
        ("Self-Healed",     "12", "Auto-remediated",      "metric-card mc-amber", "mcv-amber"),
        ("Failed",          "1",  "Review required",      "metric-card mc-red",   "mcv-red"),
    ])

    auto_gens = [
        ("Ansible — OSPF","Generate Ansible playbook to configure OSPF area 0 on 10 Cisco IOS-XR routers with MD5 authentication and BFD"),
        ("Ansible — BGP","Generate Ansible playbook for BGP eBGP configuration with route-maps and prefix-lists on Cisco routers"),
        ("Terraform — AWS VPC","Generate Terraform code for AWS VPC with Transit Gateway, BGP routing, and SD-WAN integration"),
        ("Python — Config backup","Generate Python script using netmiko to backup running configs from all network devices to files"),
    ]
    gcols = st.columns(2)
    for i, (label, prompt) in enumerate(auto_gens):
        with gcols[i % 2]:
            if st.button(f"🧠 Generate {label}", key=f"auto_{label}", use_container_width=True):
                with st.spinner(f"🧠 Generating {label}…"):
                    result = full_pipeline(prompt, st.session_state.persona)
                st.markdown(f"**{label}:**")
                st.markdown(result["response"])


# ─────────────────────────────────── DIGITAL TWIN ─────────
elif page == "Digital Twin":
    st.markdown('<div class="sec-hdr">👾 Digital Twin</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Live topology clone · Outage simulation · Safe what-if testing</div>', unsafe_allow_html=True)

    ai_bar("Digital Twin Engine",
           "Ask: <strong>'What happens if PE-MUM-01 fails?'</strong> → I simulate the failure, show affected services, "
           "calculate failover time, and recommend mitigation — all before it happens in production.")

    metric_row([
        ("Devices Cloned",  "847",   "From live topology",  "metric-card mc-blue",  "mcv-blue"),
        ("Config Accuracy", "99.2%", "Last sync 14s ago",   "metric-card mc-green", "mcv-green"),
        ("Simulations",     "3",     "Active scenarios",    "metric-card mc-amber", "mcv-amber"),
        ("Changes Tested",  "47",    "This month",          "metric-card mc-green", "mcv-green"),
    ])

    scenarios = [
        ("CORE-RTR-01 failure","Simulate complete failure of CORE-RTR-01 and show affected services, failover time, and recommendations"),
        ("ISP link failure PE-MUM-01","What is the blast radius if ISP link on PE-MUM-01 goes completely down?"),
        ("Add OSPF area 10","Validate impact of adding new OSPF area 10 with 5 new subnets before applying to production"),
        ("Firmware upgrade","Simulate firmware upgrade on PE-MUM-01 IOS-XR 7.5.2 to 7.7.1 — predict risk and downtime"),
    ]

    st.markdown("**⚡ What-If Scenarios:**")
    sc_cols = st.columns(2)
    for i, (label, prompt) in enumerate(scenarios):
        with sc_cols[i % 2]:
            if st.button(f"▶ {label}", key=f"twin_{label}", use_container_width=True):
                with st.spinner(f"👾 Simulating: {label}…"):
                    result = full_pipeline(prompt, st.session_state.persona)
                st.markdown(f"**Simulation: {label}**")
                st.markdown(result["response"])


# ─────────────────────────────────── TOPOLOGY ─────────────
elif page == "Topology":
    st.markdown('<div class="sec-hdr">🗺 Network Topology</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Live topology · Click any device for AI analysis · NLP queries</div>', unsafe_allow_html=True)

    st.markdown("""
    <div style="background:#f7f8fa;border:1px solid #d9dde6;border-radius:12px;overflow:hidden;padding:10px">
    <svg viewBox="0 0 700 380" width="100%" xmlns="http://www.w3.org/2000/svg">
      <rect width="700" height="380" fill="#f7f8fa"/>
      <ellipse cx="350" cy="30" rx="70" ry="20" fill="#f5f0fd" stroke="#6b35b5" stroke-width="1" stroke-dasharray="4 3"/>
      <text x="350" y="34" text-anchor="middle" fill="#6b35b5" font-size="11" font-family="DM Mono">INTERNET / ISP</text>
      <line x1="350" y1="50" x2="350" y2="85" stroke="#6b35b5" stroke-width="1.5"/>
      <rect x="315" y="85" width="70" height="26" rx="6" fill="#f5f0fd" stroke="#6b35b5" stroke-width="1"/>
      <text x="350" y="101" text-anchor="middle" fill="#4a2080" font-size="10" font-family="DM Mono">FW-EDGE-01</text>
      <line x1="350" y1="111" x2="180" y2="160" stroke="#b8bfcc" stroke-width="1.5"/>
      <line x1="350" y1="111" x2="350" y2="160" stroke="#b8bfcc" stroke-width="2"/>
      <line x1="350" y1="111" x2="520" y2="160" stroke="#b8bfcc" stroke-width="1.5"/>
      <circle cx="180" cy="178" r="22" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
      <text x="180" y="175" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">CORE-RTR</text>
      <text x="180" y="187" text-anchor="middle" fill="#2356a8" font-size="8" font-family="DM Mono">10.0.0.1</text>
      <circle cx="350" cy="178" r="22" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
      <text x="350" y="175" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">PE-MUM-01</text>
      <text x="350" y="187" text-anchor="middle" fill="#2356a8" font-size="8" font-family="DM Mono">10.0.1.1</text>
      <circle cx="520" cy="178" r="22" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
      <text x="520" y="175" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">PE-DEL-01</text>
      <text x="520" y="187" text-anchor="middle" fill="#2356a8" font-size="8" font-family="DM Mono">10.0.2.1</text>
      <line x1="180" y1="200" x2="120" y2="250" stroke="#d9dde6" stroke-width="1"/>
      <line x1="180" y1="200" x2="240" y2="250" stroke="#d9dde6" stroke-width="1"/>
      <line x1="350" y1="200" x2="350" y2="250" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4 3"/>
      <line x1="520" y1="200" x2="460" y2="250" stroke="#d9dde6" stroke-width="1"/>
      <line x1="520" y1="200" x2="580" y2="250" stroke="#d9dde6" stroke-width="1"/>
      <rect x="94" y="250" width="52" height="22" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
      <text x="120" y="264" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-W</text>
      <rect x="214" y="250" width="52" height="22" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
      <text x="240" y="264" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-E</text>
      <rect x="324" y="250" width="52" height="22" rx="4" fill="#fff8ea" stroke="#b06a00" stroke-width="1.5"/>
      <text x="350" y="260" text-anchor="middle" fill="#7a4a00" font-size="9" font-family="DM Mono">DIST-C</text>
      <text x="350" y="270" text-anchor="middle" fill="#b06a00" font-size="7" font-family="DM Mono">⚠ warn</text>
      <rect x="434" y="250" width="52" height="22" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
      <text x="460" y="264" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-N</text>
      <rect x="554" y="250" width="52" height="22" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
      <text x="580" y="264" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-S</text>
      <line x1="120" y1="272" x2="80" y2="318" stroke="#eef0f4" stroke-width="1"/>
      <line x1="120" y1="272" x2="160" y2="318" stroke="#eef0f4" stroke-width="1"/>
      <line x1="240" y1="272" x2="200" y2="318" stroke="#eef0f4" stroke-width="1"/>
      <line x1="240" y1="272" x2="280" y2="318" stroke="#eef0f4" stroke-width="1"/>
      <line x1="460" y1="272" x2="440" y2="318" stroke="#eef0f4" stroke-width="1"/>
      <line x1="580" y1="272" x2="560" y2="318" stroke="#eef0f4" stroke-width="1"/>
      <line x1="580" y1="272" x2="620" y2="318" stroke="#eef0f4" stroke-width="1"/>
      <rect x="64" y="318" width="32" height="16" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="80" y="329" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-1</text>
      <rect x="144" y="318" width="32" height="16" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="160" y="329" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-2</text>
      <rect x="184" y="318" width="32" height="16" rx="3" fill="#fef5f5" stroke="#c0392b" stroke-width="1.2"/><text x="200" y="326" text-anchor="middle" fill="#8b1a1a" font-size="7" font-family="DM Mono">ACC-14</text><text x="200" y="336" text-anchor="middle" fill="#c0392b" font-size="6" font-family="DM Mono">↓DOWN</text>
      <rect x="264" y="318" width="32" height="16" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="280" y="329" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-4</text>
      <rect x="424" y="318" width="32" height="16" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="440" y="329" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-5</text>
      <rect x="544" y="318" width="32" height="16" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="560" y="329" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-6</text>
      <rect x="604" y="318" width="32" height="16" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="620" y="329" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-7</text>
    </svg>
    </div>""", unsafe_allow_html=True)

    topo_q = st.text_input("Ask about topology", placeholder="'Which devices are single points of failure?' · 'Show path from Branch-HYD to HQ Core' · 'OSPF area 0 devices'")
    if st.button("🧠 Analyze Topology", key="topo_analyze") and topo_q:
        with st.spinner("🧠 Analyzing topology…"):
            result = full_pipeline(topo_q, st.session_state.persona)
        st.markdown(result["response"])


# ─────────────────────────────────── EXECUTIVE VIEW ───────
elif page == "Executive View":
    st.markdown('<div class="sec-hdr">📈 Executive Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Business impact · SLA performance · Risk scores · Board-ready metrics</div>', unsafe_allow_html=True)

    metric_row([
        ("Network Uptime",    "99.94%","SLA target 99.9% ✅",  "metric-card mc-green", "mcv-green"),
        ("MTTR",             "18m",   "↓ 40% vs last quarter", "metric-card mc-blue",  "mcv-blue"),
        ("Risk Score",       "Medium","14 CVEs · 2 threats",   "metric-card mc-amber", "mcv-amber"),
        ("Automation Rate",  "78%",   "↑ 12% this quarter",    "metric-card mc-green", "mcv-green"),
    ])

    if st.button("🧠 Generate Board Report", type="primary"):
        with st.spinner("🧠 Generating executive network report…"):
            result = full_pipeline("Generate a concise executive board report on network health: uptime, MTTR, top risks, automation ROI, recommended investments, and 90-day outlook.", "arch")
        st.markdown(result["response"])


# ─────────────────────────────────── FINOPS ───────────────
elif page == "FinOps & Cost":
    st.markdown('<div class="sec-hdr">💰 FinOps & Cost Intelligence</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">License optimization · Cloud cost · Hardware lifecycle · Savings opportunities</div>', unsafe_allow_html=True)

    metric_row([
        ("Annual Spend",       "$4.2M", "Within budget",          "metric-card mc-blue",  "mcv-blue"),
        ("Identified Savings", "$380K", "License + cloud rightsizing","metric-card mc-green","mcv-green"),
        ("EoL Hardware",       "34",    "Devices need replacement","metric-card mc-amber", "mcv-amber"),
        ("Wasted Licenses",    "18%",   "Unused entitlements",    "metric-card mc-red",   "mcv-red"),
    ])

    if st.button("🧠 AI Cost Analysis", type="primary"):
        with st.spinner("🧠 Analyzing network spend…"):
            result = full_pipeline("Analyze network cost and identify top 5 optimization opportunities: license consolidation, hardware rightsizing, cloud cost reduction, automation ROI, vendor negotiation leverage.", st.session_state.persona)
        st.markdown(result["response"])


# ─────────────────────────────────── VOICE OPS ────────────
elif page == "Voice Ops":
    st.markdown('<div class="sec-hdr">🎙 Voice Operations</div>', unsafe_allow_html=True)
    st.markdown('<div class="sec-sub">Hands-free NOC · Web Speech API (browser) · NLP voice commands</div>', unsafe_allow_html=True)

    ai_bar("Voice NLP Engine",
           "Click the microphone button in your browser to use voice input. Speak your network query — "
           "the browser transcribes it and NetBrain AI processes it through the full 4-engine pipeline.")

    st.info("🎙 **Voice input** works directly in the AI Assistant panel — use your browser's built-in voice input (microphone icon in the text area) to speak your query. It will be transcribed and processed automatically.")

    st.markdown("**Voice runbooks:**")
    vr_cols = st.columns(2)
    voice_runbooks = [
        ("🔴 Outage Response","Voice-guided 8-step outage response process with AI assistance at each step"),
        ("🔧 BGP Troubleshoot","Voice-assisted BGP diagnostic with yes/no decision tree"),
        ("🔄 Shift Handover","Dictate shift notes, AI summarises for next NOC team"),
        ("📊 Morning Health Check","90-second daily network health briefing"),
    ]
    for i, (name, desc) in enumerate(voice_runbooks):
        with vr_cols[i % 2]:
            with st.expander(name):
                st.caption(desc)
                if st.button(f"▶ Start {name.split(' ',1)[1]}", key=f"vr_{name}"):
                    quick_prompt("x", f"Start the {name.split(' ',1)[1]} runbook. Guide me step by step.")
