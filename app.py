"""
NetBrain AI — Autonomous Network Operating System
app.py — Main entry point (Streamlit)

Architecture:
  app.py                    ← This file (entry, routing, state)
  core/ai_engine.py         ← OpenRouter AI + personas
  core/nlp_engine.py        ← NLP entity extraction + intent
  core/rag_engine.py        ← RAG knowledge base (ChromaDB/keyword)
  core/mdq_engine.py        ← Multi-device parallel query
  database/models.py        ← SQLAlchemy ORM models
  database/database.py      ← DB manager, encryption, seeding
  security/rbac.py          ← Role-based access control
  ui/components.py          ← Design system + component library
"""

# ── MUST be first Streamlit call ──────────────────────────
import streamlit as st
st.set_page_config(
    page_title="NetBrain AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "NetBrain AI — Autonomous Network Operating System v2.0"},
)

# ── Standard library ──────────────────────────────────────
import sys, os, logging
from pathlib import Path

# ── Add project root to path ──────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# ── Logging setup ─────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger("netbrain.app")

# ── Module imports ─────────────────────────────────────────
import pandas as pd

from database.database import (
    seed_database, get_devices, get_incidents, get_changes,
    get_auto_actions, update_record, add_device, add_incident,
    write_audit, get_audit_logs,
)
from database.models import Change, AutonomousAction, Incident
from core.ai_engine import call_ai, analyze_incident, generate_config, score_change_risk, design_network, get_api_key
from core.nlp_engine import extract as nlp_extract, enrich_query
from core.rag_engine import search as rag_search, format_rag_context, ingest_document, rag_status
from core.mdq_engine import run_query as mdq_run, build_synthesis_prompt, NETMIKO_OK
from core.observability_engine import (
    get_live_telemetry, get_historical_telemetry, detect_anomalies,
    get_saas_health, get_netflow_summary, get_recent_syslogs,
)
from core.digital_twin_engine import simulate_failure, simulate_change, get_twin_status
from core.digital_twin_engine import simulate_failure, simulate_change, get_twin_status
from core.knowledge_graph import NODES, EDGES, get_node, get_neighbors, get_service_impact, get_spof_nodes
from core.incident_engine import calculate_blast_radius, correlate_incidents, get_similar_incidents_from_memory
from security.rbac import get_current_role, has_permission, require_permission, get_role_label, ALL_ROLES
from ui.components import (
    inject_css, ai_insight_card, metric_grid, render_chat_message,
    section_header, risk_bar, DESIGN_SYSTEM_CSS,
)

# ── Init ──────────────────────────────────────────────────
seed_database()

# ══════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════
_DEFAULTS = {
    "workspace":     "operations",
    "persona":       "noc",
    "chat_msgs":     [],
    "chat_hist":     [],
    "kg_selected":   None,
    "mdq_results":   None,
    "nlp_results":   None,
    "rag_results":   [],
    "design_output": None,
    "auto_mode":     "human",
    "user_role":     "admin",    # Set via login in production
    "user_name":     "engineer",
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════
# INJECT CSS
# ══════════════════════════════════════════════════════════
inject_css()

# ══════════════════════════════════════════════════════════
# STATUS CHECK
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=30)
def get_system_status():
    api_key = get_api_key()
    r_stat = rag_status()
    return {
        "ai":      bool(api_key),
        "ssh":     NETMIKO_OK,
        "rag":     r_stat,
        "db":      True,
    }

# ══════════════════════════════════════════════════════════
# CORE PIPELINE
# ══════════════════════════════════════════════════════════
def pipeline(query: str, persona: str = "noc", history: list = None,
             workspace_ctx: str = "") -> dict:
    """Full 4-engine pipeline: NLP → RAG → Incident Memory → Claude."""
    # 1 — NLP
    nlp_result = nlp_extract(query)
    effective_persona = nlp_result.persona_hint or persona

    # 2 — RAG
    rag_results = rag_search(query, n=3)
    rag_ctx = format_rag_context(rag_results)
    rag_topics = [m.get("topic", m.get("title", "")) for _, m in rag_results]

    # 3 — Incident Memory
    active_incs = get_incidents("active")
    similar = [i for i in active_incs
               if any(p.lower() in f"{i['title']} {i.get('protocols','')}".lower()
                      for p in nlp_result.protocols)][:2]
    inc_ctx = "\n".join(
        f"INCIDENT: {i['title']} | RCA: {i['root_cause']} | Fix: {i['resolution']}"
        for i in similar
    )

    # 4 — Enrich + Call Claude
    enriched = enrich_query(query, nlp_result)
    messages = (history or [])[-6:] + [{"role": "user", "content": enriched}]

    response = call_ai(
        messages,
        persona=effective_persona,
        rag_context=rag_ctx,
        incident_context=inc_ctx,
        workspace_context=workspace_ctx,
        max_tokens=2000,
    )

    write_audit(
        user=st.session_state.user_name,
        action="ai_query",
        resource=f"workspace:{st.session_state.workspace}",
        detail=query[:200],
    )

    return {
        "response":          response,
        "entities":          {"protocols": nlp_result.protocols, "ips": nlp_result.ipv4,
                               "devices": nlp_result.hostnames, "vlans": nlp_result.vlans},
        "persona_used":      effective_persona,
        "rag_topics":        rag_topics,
        "similar_incidents": [i["title"] for i in similar],
    }


def go(prompt: str, target_workspace: str = "troubleshoot", ctx: str = ""):
    """Send a prompt, store response, navigate to workspace."""
    st.session_state.chat_msgs.append({"role": "user", "content": prompt, "meta": None})
    with st.spinner("🧠 Reasoning…"):
        result = pipeline(prompt, st.session_state.persona,
                          st.session_state.chat_hist, ctx)
    st.session_state.chat_msgs.append({"role": "assistant", "content": result["response"], "meta": result})
    st.session_state.chat_hist += [
        {"role": "user", "content": prompt},
        {"role": "assistant", "content": result["response"]},
    ]
    st.session_state.workspace = target_workspace
    st.rerun()


# ══════════════════════════════════════════════════════════
# TOPBAR
# ══════════════════════════════════════════════════════════
def render_topbar():
    stat = get_system_status()

    def _chip(lbl, ok, sim=False):
        cls = "chip-ok" if ok else "chip-warn" if sim else "chip-err"
        return f'<span class="nb-chip {cls}"><span class="chip-dot"></span>{lbl}</span>'

    ai_lbl  = "AI ON"  if stat["ai"]  else "AI OFF"
    ssh_lbl = "SSH"    if stat["ssh"] else "SSH⚡sim"
    rag_lbl = stat["rag"]["backend"][:6]

    st.markdown(f"""
    <div class="nb-topbar">
      <div class="nb-logo">
        <div class="nb-logo-mark">🧠</div>
        <div>
          <div class="nb-logo-name">NetBrain AI</div>
          <div class="nb-logo-ver">Autonomous Network OS</div>
        </div>
      </div>
      <div class="nb-divider-v"></div>
      <div class="nb-status-row">
        {_chip(ai_lbl,  stat["ai"])}
        {_chip(ssh_lbl, stat["ssh"], sim=not stat["ssh"])}
        {_chip(rag_lbl, True, sim=stat["rag"]["backend"]=="Keyword")}
        {_chip("DB ✓", True)}
      </div>
      <div style="flex:1"></div>
      <div style="font-size:11px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">{get_role_label()}</div>
    </div>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# WORKSPACE NAV
# ══════════════════════════════════════════════════════════
WORKSPACES = [
    ("operations",  "⚡",  "Operations"),
    ("incident",    "🚨",  "Incidents"),
    ("topology",    "🗺",  "Topology"),
    ("observe",     "📡",  "Observability"),
    ("troubleshoot","🔧",  "Diagnose"),
    ("change",      "📋",  "Changes"),
    ("autonomous",  "🤖",  "Autonomous"),
    ("twin",        "👾",  "Digital Twin"),
    ("security",    "🔒",  "Security"),
    ("compliance",  "🛡",  "Compliance"),
    ("design",      "🏗",  "Design"),
    ("mdq",         "⚡",  "Multi-Device"),
    ("nlp",         "🧬",  "NLP"),
    ("rag",         "📚",  "Knowledge"),
    ("learn",       "📖",  "Learn"),
    ("devices",     "🖧",  "Devices"),
    ("executive",   "📈",  "Executive"),
    ("finops",      "💰",  "FinOps"),
    ("audit",       "🔐",  "Audit"),
]

def render_workspace_nav():
    active_incs = len(get_incidents("active"))
    pending_chg = len([c for c in get_changes() if c["status"] == "pending"])
    pending_auto= len([a for a in get_auto_actions() if a["status"] == "pending_approval"])

    badges = {"incident": active_incs, "change": pending_chg, "autonomous": pending_auto}

    cols = st.columns(len(WORKSPACES))
    for col, (ws_id, icon, label) in zip(cols, WORKSPACES):
        with col:
            badge = badges.get(ws_id, 0)
            btn_label = f"{icon} {label}" + (f" ·{badge}" if badge else "")
            is_active = st.session_state.workspace == ws_id
            if st.button(btn_label, key=f"ws_{ws_id}",
                         use_container_width=True,
                         type="primary" if is_active else "secondary"):
                st.session_state.workspace = ws_id
                st.rerun()


# ══════════════════════════════════════════════════════════
# PERSONA + GLOBAL SEARCH BAR
# ══════════════════════════════════════════════════════════
def render_persona_and_search():
    p_icons = {"fresher":"🌱","ccna":"🎓","noc":"🖥","architect":"🏗","manager":"📊","security":"🔒"}
    personas = list(p_icons.keys())

    st.markdown('<div class="ai-cmd-wrap"><div class="ai-cmd-label"><span class="ai-cmd-pulse"></span>AI Copilot — Natural Language Network Intelligence</div></div>',
                unsafe_allow_html=True)

    col_p, col_q, col_b, col_sel = st.columns([0.18, 0.52, 0.10, 0.20])
    with col_p:
        chosen = st.selectbox("Persona", [f"{p_icons[p]} {p.title()}" for p in personas],
                              index=personas.index(st.session_state.persona),
                              label_visibility="collapsed", key="persona_sel")
        st.session_state.persona = personas[[f"{p_icons[p]} {p.title()}" for p in personas].index(chosen)]
    with col_q:
        query = st.text_input("", placeholder="'Why is BGP flapping?' · 'Design SD-WAN 50 branches' · 'Show OSPF all devices' · 'Simulate CORE-RTR-01 failure'",
                              label_visibility="collapsed", key="global_q")
    with col_b:
        ask = st.button("⚡ Ask AI", use_container_width=True, type="primary", key="global_ask")
    with col_sel:
        sample = st.selectbox("", ["Examples…",
            "Why is BGP flapping on PE-MUM-01?","Show BGP summary all devices",
            "Design enterprise campus 3000 users","What if CORE-RTR-01 fails?",
            "Explain OSPF DR election","Generate Cisco IOS-XR BGP config",
            "Compliance gap analysis","Security posture analysis"],
            label_visibility="collapsed", key="sample_q")

    if ask and query.strip():
        ents = nlp_extract(query)
        target = {"incident_rca":"troubleshoot","design":"design","change_request":"change",
                  "query_devices":"mdq","security_analysis":"troubleshoot",
                  "digital_twin":"autonomous"}.get(ents.intent, "troubleshoot")
        go(query.strip(), target)
    if sample != "Examples…":
        go(sample, "troubleshoot")
        st.session_state["sample_q"] = "Examples…"


# ══════════════════════════════════════════════════════════
# RENDER
# ══════════════════════════════════════════════════════════
render_topbar()
render_workspace_nav()
st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
render_persona_and_search()
st.markdown("<div style='height:8px;background:var(--border-subtle);margin:8px 0'></div>", unsafe_allow_html=True)

ws = st.session_state.workspace

# ══════════════════════════════════════════════════════════
# WORKSPACE: OPERATIONS
# ══════════════════════════════════════════════════════════
if ws == "operations":
    section_header("⚡ Operations Command Center",
                   "Real-time network intelligence · AI-embedded in every workflow")

    ai_insight_card(
        "Operational Intelligence — Live",
        "<strong>2 active incidents</strong> — BGP flap PE-MUM-01 (<strong>87% confidence: ISP withdrawal</strong>) "
        "+ SW-ACC-14 interface down (<strong>94% confidence: physical failure</strong>). "
        "<strong>CORE-RTR-01 CPU 88%</strong> — correlates with BGP SPF recalculation. "
        "<strong>Autonomous action pending:</strong> BGP hold-timer increase awaiting your approval.",
        confidence=87, sources=["BGP","OSPF","Incident Memory"],
    )

    metric_grid([
        {"label":"Devices Online","value":"831","meta":"of 847 · 16 degraded","color":"green","icon":"✅"},
        {"label":"Active Incidents","value":"2","meta":"BGP + Interface","color":"red","icon":"🔴"},
        {"label":"BGP Sessions","value":"248","meta":"247 up · 1 active","color":"blue","icon":"🔄"},
        {"label":"Pending Actions","value":"1","meta":"Awaiting approval","color":"amber","icon":"🤖"},
    ])

    col_devs, col_timeline = st.columns([0.55, 0.45])

    with col_devs:
        st.markdown('<div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:10px">🖧 Live Device Status</div>', unsafe_allow_html=True)
        devices = get_devices()
        dev_cols = st.columns(2)
        for i, d in enumerate(devices):
            status = d.get("status", "up")
            cpu, mem = d.get("cpu", 0), d.get("memory", 0)
            cpu_cls = "mv-crit" if cpu >= 80 else "mv-warn" if cpu >= 60 else "mv-ok"
            mem_cls = "mv-crit" if mem >= 80 else "mv-warn" if mem >= 60 else "mv-ok"
            with dev_cols[i % 2]:
                st.markdown(f"""<div class="nb-dev dev-{status}">
                  <div class="nb-dev-hn">{d['hostname']}</div>
                  <div class="nb-dev-role">{d.get('role','')}</div>
                  <div class="nb-dev-site">📍 {d.get('site','')}</div>
                  <div class="nb-dev-metrics">
                    <div class="nb-dev-m"><div class="nb-dev-mv {cpu_cls}">{f"{cpu}%" if cpu else "—"}</div><div class="nb-dev-ml">CPU</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {mem_cls}">{f"{mem}%" if mem else "—"}</div><div class="nb-dev-ml">MEM</div></div>
                  </div>
                </div>""", unsafe_allow_html=True)
                if st.button(f"🧠", key=f"dev_ai_{d['hostname']}", help=f"AI analyze {d['hostname']}"):
                    go(f"Analyze health of {d['hostname']} ({d['ip']}). Status={status}, CPU={cpu}%, Memory={mem}%. Give assessment, risks, and recommendations.",
                       "troubleshoot", f"Device: {d['hostname']} | Role: {d['role']} | Status: {status}")

    with col_timeline:
        st.markdown('<div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:10px">⏱ Operational Timeline</div>', unsafe_allow_html=True)
        timeline = [
            ("crit","🔴","2m ago","BGP Flapping — PE-MUM-01","AS65002 · 142 prefixes · ISP root cause","AI: ISP BGP withdrawal — 87% confidence"),
            ("crit","🔴","8m ago","Interface Down — SW-ACC-14","VLAN 120 · 47 users","AI: Physical failure. Replace cable/SFP. 94% confidence."),
            ("warn","🟡","14m ago","High CPU — CORE-RTR-01 (88%)","OSPF SPF recalculation","AI: Symptom of BGP flap — will self-resolve"),
            ("ai","🤖","18m ago","BFD Auto-Enabled — PE-MUM-01","Confidence 91% · Executed","BGP detection reduced to 300ms"),
            ("warn","🟡","31m ago","OSPF Neighbor Timeout — Area 0","Segment 10.10.40.0/24","AI: Related to BGP instability cascade"),
            ("ok","✅","2h ago","Change #1 Approved — BGP timer","Risk score 15 · Low","Scheduled for maintenance window"),
        ]
        for sev, ico, ts, title, meta_txt, ai_txt in timeline:
            st.markdown(f"""<div class="nb-timeline-item">
              <div class="nb-tl-dot tl-{sev}">{ico}</div>
              <div class="nb-tl-body">
                <div class="nb-tl-title">{title}</div>
                <div class="nb-tl-meta">{ts} · {meta_txt}</div>
                <div class="nb-tl-ai">🧠 {ai_txt}</div>
              </div>
            </div>""", unsafe_allow_html=True)

    st.markdown("**⚡ Quick Actions:**")
    qc = st.columns(4)
    quick_actions = [
        ("🔧 Diagnose BGP", "BGP flapping on PE-MUM-01 AS65002 — root cause analysis and fix"),
        ("⚡ Query All Devices", "Show BGP summary across all network devices simultaneously", "mdq"),
        ("📊 Compliance Check", "Full compliance gap analysis — top 5 critical findings"),
        ("🏗 Design SD-WAN", "Design SD-WAN for 50 branches, dual ISP, Azure, SASE, app-SLA"),
    ]
    for col, action in zip(qc, quick_actions):
        with col:
            prompt, *rest = action[1:]
            target = rest[0] if rest else "troubleshoot"
            if st.button(action[0], use_container_width=True, key=f"qa_{action[0]}"):
                go(action[1], target)


# ══════════════════════════════════════════════════════════
# WORKSPACE: INCIDENTS
# ══════════════════════════════════════════════════════════
elif ws == "incident":
    section_header("🚨 Incident War Room", "AI-native incident operations · RCA · Blast radius · Autonomous remediation")

    incidents = get_incidents("active")
    resolved  = get_incidents("resolved")

    if not incidents:
        st.success("✅ All clear — no active incidents.")
    else:
        ai_insight_card(
            "AI Correlation",
            f"<strong>{len(incidents)} active incidents correlated.</strong> "
            "Primary root: ISP instability AS65002 → BGP flap → OSPF recalc → high CPU (alerts 1,3,4 are symptoms). "
            "Secondary: Physical failure SW-ACC-14 Gi0/0/3. <strong>Fix root causes, not all symptoms.</strong>",
        )

    for inc in incidents:
        conf = inc.get("ai_confidence", 0)
        conf_cls = "conf-high" if conf >= 80 else "conf-med" if conf >= 60 else "conf-low"
        sev = inc["severity"]

        st.markdown(f"""<div class="nb-warroom">
          <div class="nb-wr-hdr">
            <div class="nb-wr-pulse"></div>
            <div class="nb-wr-title">🚨 {inc['title']}</div>
            <span class="nb-chip {'chip-err' if sev=='critical' else 'chip-warn'}">{sev.upper()} · ACTIVE</span>
          </div>
          <div style="padding:14px 18px">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
              <div>
                <div style="font-size:9px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">AI Root Cause</div>
                <div style="font-size:13px;color:var(--text-primary);line-height:1.6">{inc.get('root_cause','Analyzing…')}</div>
                <div class="nb-conf {conf_cls}" style="margin-top:6px"><span class="nb-conf-pct">{conf}%</span><div class="nb-conf-track"><div class="nb-conf-fill" style="width:{conf}%"></div></div><span style="font-size:10px;color:var(--text-tertiary)">AI Confidence</span></div>
              </div>
              <div>
                <div style="font-size:9px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">Business Impact</div>
                <div style="font-size:13px;color:var(--text-primary);line-height:1.6">{inc.get('business_impact','Calculating…')}</div>
                <div style="margin-top:5px;font-size:13px;font-weight:700;color:var(--accent-red)">{inc.get('affected_users',0)} users impacted</div>
              </div>
              <div>
                <div style="font-size:9px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">Remediation</div>
                <div style="font-size:13px;color:var(--text-primary);line-height:1.6">{inc.get('resolution','Generating…')}</div>
              </div>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)

        ic1, ic2, ic3, ic4 = st.columns(4)
        with ic1:
            if st.button("🧠 Deep AI RCA", key=f"rca_{inc['id']}", use_container_width=True, type="primary"):
                result = analyze_incident(
                    inc["title"], inc["description"],
                    inc.get("protocols",""), inc.get("protocols",""),
                    st.session_state.persona,
                )
                st.session_state.chat_msgs.append({"role":"assistant","content":result["response"],"meta":None})
                st.markdown(result["response"])
        with ic2:
            if st.button("📊 Blast Radius", key=f"blast_{inc['id']}", use_container_width=True):
                go(f"Analyze blast radius for: {inc['title']}. What devices, services, users, applications are impacted? Show full dependency chain.", "incident")
        with ic3:
            if st.button("🔧 Auto-Remediate", key=f"rem_{inc['id']}", use_container_width=True):
                go(f"Generate autonomous remediation plan for: {inc['title']}. Include CLI commands, execution order, validation, rollback procedure.", "incident")
        with ic4:
            if has_permission("resolve_incidents"):
                if st.button("✅ Resolve", key=f"res_{inc['id']}", use_container_width=True):
                    update_record(Incident, inc["id"], status="resolved")
                    write_audit(st.session_state.user_name, "resolve_incident", f"incident:{inc['id']}", inc["title"])
                    st.rerun()
        st.markdown("---")

    if resolved:
        with st.expander(f"📋 Resolved ({len(resolved)}) — Operational Memory"):
            for r in resolved[:5]:
                st.markdown(f"""<div class="nb-timeline-item">
                  <div class="nb-tl-dot tl-ok">✅</div>
                  <div class="nb-tl-body">
                    <div class="nb-tl-title">{r['title']}</div>
                    <div class="nb-tl-meta">RCA: {r.get('root_cause','')} · Fix: {r.get('resolution','')[:80]}</div>
                  </div>
                </div>""", unsafe_allow_html=True)

    with st.expander("➕ Log New Incident"):
        f1, f2 = st.columns(2)
        with f1:
            nt = st.text_input("Title", key="ni_title")
            nd = st.text_input("Devices", placeholder="PE-MUM-01, CORE-RTR-01", key="ni_devs")
            ns = st.selectbox("Severity", ["critical","major","minor"], key="ni_sev")
        with f2:
            ndesc = st.text_area("Description", height=80, key="ni_desc")
            nimpact = st.text_input("Business impact", key="ni_impact")
        if st.button("🚨 Log + AI RCA", type="primary", key="ni_submit"):
            if nt:
                add_incident(nt, ndesc, ns, nd, nimpact, 0, 0)
                go(f"New incident: {nt}. Devices: {nd}. {ndesc}. Perform immediate RCA.", "incident")


# ══════════════════════════════════════════════════════════
# WORKSPACE: TOPOLOGY
# ══════════════════════════════════════════════════════════
elif ws == "topology":
    section_header("🗺 Network Knowledge Graph", "Everything connected · Click for AI analysis · Relationship-driven intelligence")

    ai_insight_card(
        "Topology Intelligence",
        "<strong>Dependency analysis:</strong> PE-MUM-01 is on the critical path for Mumbai SaaS access (340 users). "
        "SW-ACC-14 failure isolates Floor 2 from DIST-SW-C. "
        "<strong>SPOF detected:</strong> FW-EDGE-01 has no redundant path — single point of failure for all internet egress.",
        confidence=91, sources=["Topology","BGP","OSPF"],
    )

    st.markdown("""<div class="nb-topo-wrap">
      <div class="nb-topo-bar">
        <button class="nb-layer-btn active">🌐 All</button>
        <button class="nb-layer-btn">🔄 L3 Routing</button>
        <button class="nb-layer-btn">🔀 L2 Switching</button>
        <button class="nb-layer-btn">🔒 Security</button>
        <button class="nb-layer-btn">☁ Cloud</button>
        <button class="nb-layer-btn">📡 SD-WAN</button>
        <span style="margin-left:auto;font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">← Click nodes → select for AI analysis</span>
      </div>
      <div style="padding:16px;background:var(--bg-elevated);min-height:460px">
      <svg viewBox="0 0 760 440" width="100%" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <filter id="glow-b"><feGaussianBlur stdDeviation="3" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <filter id="glow-r"><feGaussianBlur stdDeviation="2" result="blur"/><feColorMatrix in="blur" type="matrix" values="1 0 0 0 0.97 0 0 0 0 0.32 0 0 0 0 0.29 0 0 0 0.8 0"/><feMerge><feMergeNode/><feMergeNode in="SourceGraphic"/></feMerge></filter>
        </defs>
        <!-- ISP Cloud -->
        <ellipse cx="380" cy="30" rx="80" ry="22" fill="rgba(188,140,255,.06)" stroke="rgba(188,140,255,.4)" stroke-width="1.5" stroke-dasharray="6 3"/>
        <text x="380" y="34" text-anchor="middle" fill="#bc8cff" font-size="11" font-family="JetBrains Mono">INTERNET / ISP</text>
        <!-- FW - SPOF warning -->
        <line x1="380" y1="52" x2="380" y2="88" stroke="rgba(188,140,255,.4)" stroke-width="1.5"/>
        <rect x="338" y="88" width="84" height="30" rx="7" fill="rgba(31,27,34,.9)" stroke="rgba(210,153,34,.6)" stroke-width="1.5"/>
        <text x="380" y="104" text-anchor="middle" fill="#d29922" font-size="10" font-family="JetBrains Mono" font-weight="600">FW-EDGE-01</text>
        <circle cx="416" cy="93" r="5" fill="#d29922" opacity=".9"/>
        <text x="424" y="97" fill="#d29922" font-size="8" font-family="JetBrains Mono">⚠ SPOF</text>
        <!-- Core router links -->
        <line x1="380" y1="118" x2="180" y2="172" stroke="rgba(48,54,61,.8)" stroke-width="2"/>
        <line x1="380" y1="118" x2="380" y2="172" stroke="rgba(48,54,61,.8)" stroke-width="2.5"/>
        <line x1="380" y1="118" x2="580" y2="172" stroke="rgba(48,54,61,.8)" stroke-width="2"/>
        <!-- CORE-RTR-01 — WARNING -->
        <circle cx="180" cy="192" r="28" fill="rgba(210,153,34,.1)" stroke="rgba(210,153,34,.7)" stroke-width="2.5"/>
        <text x="180" y="188" text-anchor="middle" fill="#d29922" font-size="10" font-family="JetBrains Mono" font-weight="600">CORE-RTR</text>
        <text x="180" y="200" text-anchor="middle" fill="#d29922" font-size="8" font-family="JetBrains Mono">01</text>
        <text x="180" y="212" text-anchor="middle" fill="#d29922" font-size="8" font-family="JetBrains Mono">CPU 88% ⚠</text>
        <!-- PE-MUM-01 — CRITICAL -->
        <circle cx="380" cy="192" r="30" fill="rgba(248,81,73,.1)" stroke="rgba(248,81,73,.8)" stroke-width="2.5" filter="url(#glow-r)"/>
        <text x="380" y="186" text-anchor="middle" fill="#f85149" font-size="10" font-family="JetBrains Mono" font-weight="600">PE-MUM-01</text>
        <text x="380" y="198" text-anchor="middle" fill="#f85149" font-size="8" font-family="JetBrains Mono">BGP FLAP 🔴</text>
        <text x="380" y="210" text-anchor="middle" fill="#f85149" font-size="8" font-family="JetBrains Mono">10.0.1.1</text>
        <!-- PE-DEL-01 — OK -->
        <circle cx="580" cy="192" r="26" fill="rgba(47,129,247,.08)" stroke="rgba(47,129,247,.5)" stroke-width="1.5"/>
        <text x="580" y="188" text-anchor="middle" fill="#2f81f7" font-size="10" font-family="JetBrains Mono" font-weight="600">PE-DEL-01</text>
        <text x="580" y="200" text-anchor="middle" fill="#2f81f7" font-size="8" font-family="JetBrains Mono">✓ stable</text>
        <!-- Distribution links -->
        <line x1="180" y1="220" x2="120" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <line x1="180" y1="220" x2="240" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <line x1="380" y1="222" x2="380" y2="270" stroke="rgba(210,153,34,.5)" stroke-width="2" stroke-dasharray="5 4"/>
        <line x1="580" y1="218" x2="500" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <line x1="580" y1="218" x2="660" y2="270" stroke="rgba(48,54,61,.7)" stroke-width="1.5"/>
        <!-- Dist switches -->
        <rect x="88"  y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="120" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-W</text>
        <rect x="208" y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="240" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-E</text>
        <rect x="348" y="270" width="64" height="24" rx="6" fill="rgba(210,153,34,.08)" stroke="rgba(210,153,34,.5)" stroke-width="1.5"/>
        <text x="380" y="279" text-anchor="middle" fill="#d29922" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-C</text>
        <text x="380" y="290" text-anchor="middle" fill="#d29922" font-size="8" font-family="JetBrains Mono">⚠ warn</text>
        <rect x="468" y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="500" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-N</text>
        <rect x="628" y="270" width="64" height="24" rx="6" fill="rgba(31,111,235,.08)" stroke="rgba(47,129,247,.4)" stroke-width="1.5"/>
        <text x="660" y="285" text-anchor="middle" fill="#2f81f7" font-size="9" font-family="JetBrains Mono" font-weight="600">DIST-SW-S</text>
        <!-- Access layer links -->
        <line x1="120" y1="294" x2="80"  y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="120" y1="294" x2="160" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="240" y1="294" x2="200" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="240" y1="294" x2="280" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="380" y1="294" x2="380" y2="348" stroke="rgba(248,81,73,.4)" stroke-width="1.5" stroke-dasharray="4 3"/>
        <line x1="500" y1="294" x2="480" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="660" y1="294" x2="640" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <line x1="660" y1="294" x2="700" y2="348" stroke="rgba(33,38,45,.9)" stroke-width="1"/>
        <!-- Access switches -->
        <rect x="60"  y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="80"  y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-1</text>
        <rect x="140" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="160" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-2</text>
        <rect x="180" y="348" width="40" height="17" rx="4" fill="rgba(248,81,73,.12)" stroke="rgba(248,81,73,.6)"  stroke-width="1.5"/>
        <text x="200" y="357" text-anchor="middle" fill="#f85149" font-size="8" font-family="JetBrains Mono">ACC-14</text>
        <text x="200" y="367" text-anchor="middle" fill="#f85149" font-size="7" font-family="JetBrains Mono">↓DOWN</text>
        <rect x="260" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="280" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-3</text>
        <rect x="460" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="480" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-5</text>
        <rect x="620" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="640" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-6</text>
        <rect x="680" y="348" width="40" height="17" rx="4" fill="rgba(63,185,80,.08)"  stroke="rgba(63,185,80,.4)"  stroke-width="1"/>
        <text x="700" y="360" text-anchor="middle" fill="#3fb950" font-size="8" font-family="JetBrains Mono">ACC-7</text>
        <!-- Legend -->
        <rect x="12" y="8" width="140" height="75" rx="6" fill="rgba(22,27,34,.95)" stroke="rgba(48,54,61,.8)" stroke-width="1"/>
        <circle cx="24" cy="22" r="5" fill="rgba(248,81,73,.2)" stroke="#f85149" stroke-width="1.5"/>
        <text x="34" y="26" fill="#8b949e" font-size="9" font-family="JetBrains Mono">Critical/Down</text>
        <circle cx="24" cy="38" r="5" fill="rgba(210,153,34,.2)" stroke="#d29922" stroke-width="1.5"/>
        <text x="34" y="42" fill="#8b949e" font-size="9" font-family="JetBrains Mono">Warning</text>
        <circle cx="24" cy="54" r="5" fill="rgba(47,129,247,.2)" stroke="#2f81f7" stroke-width="1.5"/>
        <text x="34" y="58" fill="#8b949e" font-size="9" font-family="JetBrains Mono">Healthy</text>
        <circle cx="24" cy="70" r="5" fill="rgba(210,153,34,.5)" stroke="#d29922" stroke-width="1"/>
        <text x="34" y="74" fill="#8b949e" font-size="9" font-family="JetBrains Mono">SPOF detected</text>
      </svg>
      </div>
    </div>""", unsafe_allow_html=True)

    tq = st.text_input("Ask about topology", placeholder="'Which devices are single points of failure?' · 'Path from Mumbai branch to Azure' · 'OSPF area 0 devices'", key="topo_q")
    if st.button("🧠 Analyze", type="primary", key="topo_ask") and tq:
        go(tq, "topology", "Topology workspace — user analyzing network graph")


# ══════════════════════════════════════════════════════════
# WORKSPACE: TROUBLESHOOT
# ══════════════════════════════════════════════════════════
elif ws == "troubleshoot":
    section_header("🔧 AI Diagnosis Engine", "NLP → RAG → Incident Memory → Claude · 4-engine pipeline")

    ai_insight_card(
        "Diagnosis Pipeline — Active",
        "<strong>NLP</strong> extracts entities → <strong>RAG</strong> retrieves runbooks → "
        "<strong>Incident Memory</strong> surfaces past RCAs → <strong>Claude</strong> reasons across all context. "
        "Every response shows evidence, confidence %, and rollback options.",
    )

    col_form, col_chat = st.columns([0.48, 0.52])
    with col_form:
        prob = st.text_area("Describe the problem in plain English",
                            placeholder="'BGP session keeps flapping to ISP since 2 hours ago. CPU spiked to 88%. OSPF also went down briefly. No config changes made.'",
                            height=110, key="ts_prob")
        v, sev = st.columns(2)
        vendor = v.selectbox("Vendor", ["Any","Cisco IOS/IOS-XR","Juniper JunOS","Arista EOS","Palo Alto","Fortinet"], key="ts_vendor")
        severity = sev.selectbox("Severity", ["Unknown","🔴 P1 — Production","🟡 P2 — Degraded","🟢 P3 — Minor"], key="ts_sev")
        affected = st.text_input("Affected devices (optional)", placeholder="PE-MUM-01, CORE-RTR-01", key="ts_devs")
        if st.button("🧠 Run 4-Engine Diagnosis", type="primary", use_container_width=True, key="ts_go") and prob:
            go(f"Diagnose: {prob}\nVendor:{vendor} | Severity:{severity} | Devices:{affected}\n\nProvide: 1)Root cause+evidence 2)AI confidence% 3)Business impact 4)Step-by-step CLI fix 5)Rollback plan 6)Prevention",
               "troubleshoot", f"Vendor:{vendor} Severity:{severity}")

        st.markdown("**One-click common issues:**")
        issues = [
            ("BGP stuck Active","BGP neighbor stuck in Active state Cisco IOS-XR — troubleshoot systematically"),
            ("OSPF EXSTART","OSPF adjacency stuck in EXSTART — MTU mismatch diagnosis and fix"),
            ("VLAN trunk issue","VLAN traffic not passing on trunk — STP or allowed VLAN diagnosis"),
            ("SD-WAN failover","SD-WAN not failing over to backup ISP — Cisco Viptela"),
            ("MPLS packet loss","High packet loss on MPLS backbone — LSP ping trace diagnosis"),
            ("IPSec flapping","IPSec VPN tunnel flapping DPD timeout — stabilize"),
            ("STP loop","Spanning tree loop causing broadcast storm — find and stop"),
            ("BGP route missing","BGP route in table but not advertised to peer — route-map issue"),
        ]
        ic = st.columns(2)
        for i, (lbl, prompt) in enumerate(issues):
            with ic[i % 2]:
                if st.button(lbl, key=f"issue_{lbl}", use_container_width=True):
                    go(prompt, "troubleshoot")

    with col_chat:
        st.markdown("**AI Diagnosis:**")
        if not st.session_state.chat_msgs:
            st.info("💡 Describe a problem → AI runs NLP + RAG + Incident Memory + Claude reasoning. Every answer shows evidence and confidence.")
        for msg in st.session_state.chat_msgs[-8:]:
            render_chat_message(msg["role"], msg["content"], msg.get("meta"))
        if st.session_state.chat_msgs:
            fu = st.text_input("Follow-up", placeholder="'What if that doesn't work?' · 'Show me the rollback CLI'", key="ts_fu")
            c1, c2 = st.columns([0.7, 0.3])
            with c1:
                if st.button("Ask follow-up", key="ts_fu_btn") and fu: go(fu, "troubleshoot")
            with c2:
                if st.button("🗑 Clear", key="ts_clr"):
                    st.session_state.chat_msgs = []; st.session_state.chat_hist = []; st.rerun()


# ══════════════════════════════════════════════════════════
# WORKSPACE: CHANGE SAFETY
# ══════════════════════════════════════════════════════════
elif ws == "change":
    section_header("📋 Change Safety Engine", "AI risk scoring · Digital twin pre-validation · Blast radius · Rollback planning")

    ai_insight_card(
        "Change Safety Intelligence",
        "<strong>3 changes in queue.</strong> IOS-XR firmware upgrade on CORE-RTR-01: <strong>score 72/100 — HIGH RISK</strong>. "
        "Digital twin test mandatory before production. "
        "<strong>BGP timer change: 15/100 — LOW RISK</strong>. Safe to proceed during business hours with monitoring.",
        confidence=88,
    )

    changes = get_changes()
    for chg in changes:
        score = chg.get("ai_risk_score", 0)
        risk_cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
        sev_ico = "🟢" if score < 30 else "🟡" if score < 65 else "🔴"
        tag_cls = {"approved":"tag-green","pending":"tag-amber","rejected":"tag-red"}.get(chg["status"],"tag-slate")

        with st.expander(f"{sev_ico} {chg['title']} — Risk {score}/100", expanded=chg["severity"] if "severity" in chg else score >= 65):
            cc1, cc2 = st.columns([0.65, 0.35])
            with cc1:
                st.markdown(f"**Device:** `{chg['device']}` | **Type:** `{chg['change_type']}` | **By:** {chg.get('created_by','')}")
                st.markdown(chg["description"])
                risk_bar(score)
                st.markdown(f"**AI Recommendation:** {chg.get('ai_recommendation','')}")
                if chg.get("rollback_plan"):
                    st.markdown(f"**Rollback:** {chg['rollback_plan']}")
            with cc2:
                st.markdown(f'<span class="nb-tag {tag_cls}">{chg["status"].upper()}</span>', unsafe_allow_html=True)
                if st.button("🧠 AI Risk Analysis", key=f"chg_ai_{chg['id']}", use_container_width=True):
                    result = score_change_risk(chg["title"], chg["description"], chg["device"], chg["change_type"])
                    st.markdown(result["response"])
                if st.button("👾 Digital Twin Test", key=f"chg_twin_{chg['id']}", use_container_width=True):
                    go(f"Simulate in digital twin: {chg['title']} on {chg['device']}. Show topology impact, traffic impact, predicted downtime, rollback triggers.", "autonomous")
                if chg["status"] == "pending" and has_permission("approve_changes"):
                    a1, a2 = st.columns(2)
                    with a1:
                        if st.button("✅ Approve", key=f"chg_app_{chg['id']}", use_container_width=True):
                            update_record(Change, chg["id"], status="approved")
                            write_audit(st.session_state.user_name, "approve_change", f"change:{chg['id']}", chg["title"])
                            st.rerun()
                    with a2:
                        if st.button("❌ Reject", key=f"chg_rej_{chg['id']}", use_container_width=True):
                            update_record(Change, chg["id"], status="rejected")
                            write_audit(st.session_state.user_name, "reject_change", f"change:{chg['id']}", chg["title"])
                            st.rerun()


# ══════════════════════════════════════════════════════════
# WORKSPACE: AUTONOMOUS OPERATIONS
# ══════════════════════════════════════════════════════════
elif ws == "autonomous":
    section_header("🤖 Autonomous Operations Center", "AI detection → recommendation → approval → execution → verification → learning")

    mode_cols = st.columns(3)
    modes = [
        ("human","👨‍💼 Human Approval","ALL AI actions require manual approval before execution."),
        ("semi", "🤝 Semi-Autonomous", "Low-risk (<30 score) auto-execute. High-risk needs approval."),
        ("full", "⚡ Fully Autonomous","AI executes all validated actions. Human notified only."),
    ]
    for col, (m_id, m_lbl, m_desc) in zip(mode_cols, modes):
        with col:
            selected = st.session_state.auto_mode == m_id
            sel_cls = f"selected-{m_id}" if selected else ""
            st.markdown(f"""<div class="nb-mode-btn {sel_cls}">
              <div class="nb-mode-title">{m_lbl}</div>
              <div class="nb-mode-desc">{m_desc}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Set {m_lbl.split()[1]}", key=f"mode_{m_id}", use_container_width=True,
                         type="primary" if selected else "secondary"):
                st.session_state.auto_mode = m_id
                st.rerun()

    st.markdown("---")
    ai_insight_card(
        "Autonomous Intelligence",
        f"Mode: <strong>{'Human Approval' if st.session_state.auto_mode=='human' else 'Semi-Autonomous' if st.session_state.auto_mode=='semi' else 'Fully Autonomous'}</strong>. "
        "<strong>3 actions logged</strong> — 2 executed, 1 pending approval. "
        "Auto-remediation success rate: <strong>94%</strong> this week. Time saved: <strong>4.2 hours</strong>.",
        confidence=94,
    )

    metric_grid([
        {"label":"Actions This Week","value":"47","meta":"94% success","color":"green","icon":"✅"},
        {"label":"Auto-Healed","value":"12","meta":"Issues resolved","color":"blue","icon":"🤖"},
        {"label":"Pending Approval","value":"1","meta":"BGP timer change","color":"amber","icon":"⏳"},
        {"label":"Time Saved","value":"4.2h","meta":"This week","color":"green","icon":"⚡"},
    ])

    auto_actions = get_auto_actions()
    for a in auto_actions:
        status = a.get("status", "")
        cls = "aa-exec" if status == "executed" else "aa-pend" if "pending" in status else "aa-fail"
        ico = "✅" if status == "executed" else "⏳" if "pending" in status else "❌"
        conf = a.get("ai_confidence", 0)
        conf_cls = "conf-high" if conf >= 80 else "conf-med" if conf >= 60 else "conf-low"

        st.markdown(f"""<div class="nb-auto-action">
          <div class="nb-aa-ico {cls}">{ico}</div>
          <div style="flex:1">
            <div class="nb-aa-title">{a['action']}</div>
            <div class="nb-aa-meta">Device: {a.get('device','')} · Trigger: {a.get('trigger','')}</div>
            <div class="nb-aa-ai">{a.get('result','')}</div>
            <div class="nb-conf {conf_cls}" style="margin-top:5px">
              <span class="nb-conf-pct">{conf}%</span>
              <div class="nb-conf-track"><div class="nb-conf-fill" style="width:{conf}%"></div></div>
              <span style="font-size:10px;color:var(--text-tertiary)">AI Confidence</span>
            </div>
          </div>
        </div>""", unsafe_allow_html=True)
        if "pending" in status and has_permission("run_automation"):
            pa1, pa2 = st.columns(2)
            with pa1:
                if st.button("✅ Approve", key=f"auto_app_{a['id']}", use_container_width=True, type="primary"):
                    update_record(AutonomousAction, a["id"], status="executed")
                    write_audit(st.session_state.user_name, "approve_auto_action", f"action:{a['id']}", a["action"])
                    st.rerun()
            with pa2:
                if st.button("❌ Reject", key=f"auto_rej_{a['id']}", use_container_width=True):
                    update_record(AutonomousAction, a["id"], status="rejected")
                    st.rerun()

    st.markdown("---")
    auto_q = st.text_input("Ask Autonomous AI", placeholder="'Generate self-healing policy for BGP flaps' · 'What actions were taken today?' · 'Simulate autonomous remediation for incident #1'", key="auto_q")
    if st.button("🤖 Ask", type="primary", key="auto_ask") and auto_q:
        go(auto_q, "autonomous", "Autonomous operations workspace")


# ══════════════════════════════════════════════════════════
# WORKSPACE: MULTI-DEVICE QUERY
# ══════════════════════════════════════════════════════════
elif ws == "mdq":
    section_header("⚡ Multi-Device Query Engine", "System B — Parallel SSH · ThreadPoolExecutor · Retry logic · AI synthesis")

    ai_insight_card(
        "Netmiko SSH Engine — System B",
        "Type plain English: <strong>'Show OSPF neighbors on all routers'</strong> · <strong>'BGP Active state anywhere?'</strong> — "
        "I SSH all devices in parallel (up to 20 concurrent) and synthesise one unified answer.",
    )

    qr = st.columns(6)
    quick_mdq = [("BGP summary","Show BGP summary all routers"),("OSPF neighbors","Show OSPF neighbor status all devices"),("CPU usage","Show CPU usage all devices"),("Interface status","Show interface status"),("VLAN status","Show VLAN brief all switches"),("Routing table","Show routing table summary all devices")]
    for col, (lbl, q) in zip(qr, quick_mdq):
        with col:
            if st.button(lbl, key=f"mdq_q_{lbl}", use_container_width=True):
                st.session_state["_mdqf"] = q

    mdq_inp = st.text_input("Natural language query", value=st.session_state.pop("_mdqf",""),
                             placeholder='"Which routers have BGP in Active state?" · "Show OSPF neighbors across all devices"', key="mdq_inp")

    if st.button("⚡ Query All Devices", type="primary", key="mdq_run") and mdq_inp.strip():
        devices = get_devices()
        with st.spinner(f"⚡ Querying {len(devices)} devices in parallel…"):
            results = mdq_run(mdq_inp.strip(), devices)
        synth_prompt = build_synthesis_prompt(mdq_inp.strip(), results)
        synthesis = call_ai([{"role":"user","content":synth_prompt}], st.session_state.persona)
        st.session_state.mdq_results = {"results": results, "synthesis": synthesis, "query": mdq_inp.strip()}

    if st.session_state.mdq_results:
        r = st.session_state.mdq_results
        ok = sum(1 for d in r["results"] if d.status == "ok")
        st.success(f"✓ {len(r['results'])} devices queried · {ok} successful · Simulated: {len(r['results'])-ok}")
        dev_cols = st.columns(min(len(r["results"]), 3))
        for i, d in enumerate(r["results"]):
            cls = "nb-dev dev-up" if d.status=="ok" else "nb-dev dev-critical"
            with dev_cols[i % 3]:
                st.markdown(f"""<div class="{cls}">
                  <div class="nb-dev-hn">{d.hostname} ({d.ip})</div>
                  <div class="nb-dev-role">{d.vendor} · {d.role} · {d.site}</div>
                  <div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">CMD: {d.command}</div>
                  <div class="nb-terminal">{d.output[:280]}</div>
                </div>""", unsafe_allow_html=True)
        st.markdown("---")
        st.markdown("**🧠 AI Synthesis — All Devices**")
        st.markdown(r["synthesis"])


# ══════════════════════════════════════════════════════════
# WORKSPACE: NLP ENGINE
# ══════════════════════════════════════════════════════════
elif ws == "nlp":
    section_header("🧬 NLP Entity Extractor", "System C — 14 intent classes · Entity extraction · Urgency detection · Auto persona")

    samples = {"BGP log": "BGP neighbor 10.0.1.1 AS65002 stuck Active on GigabitEthernet0/0/0 at PE-MUM-01 OSPF area 0 VLAN 100",
               "OSPF": "OSPF adjacency lost CORE-RTR-01 DIST-SW-W 192.168.1.0/30 area 0 Cisco IOS-XR",
               "Design": "Design VXLAN EVPN leaf-spine Arista EOS BGP EVPN RoCE GPU cluster AI fabric",
               "Security": "Lateral movement detected 10.2.14.0/24 Zero Trust micro-segmentation Palo Alto"}
    sc = st.columns(4)
    for col, (n, t) in zip(sc, samples.items()):
        with col:
            if st.button(n, key=f"nlp_s_{n}", use_container_width=True):
                st.session_state["_nlpf"] = t

    nlp_txt = st.text_area("Paste networking text", value=st.session_state.pop("_nlpf",""),
                            placeholder="Any networking query, log, config, alert…", height=90, key="nlp_inp")
    if st.button("🧬 Extract Entities", type="primary", key="nlp_run") and nlp_txt:
        st.session_state.nlp_results = nlp_extract(nlp_txt)

    if st.session_state.nlp_results:
        e = st.session_state.nlp_results
        m1, m2, m3 = st.columns(3)
        m1.metric("Intent", e.intent.replace("_"," ").title())
        m2.metric("Urgency", e.urgency.upper())
        m3.metric("Persona Hint", e.persona_hint or "Auto")
        st.divider()
        cats = [("IPs","ipv4"),("Protocols","protocols"),("Interfaces","interfaces"),("VLANs","vlans"),
                ("ASNs","asns"),("Vendors","vendors"),("Devices","hostnames"),("VRFs","vrfs"),
                ("Tickets","tickets"),("OSPF Areas","ospf_areas"),("IPv6","ipv6"),("Ports","ports")]
        cols = st.columns(4)
        for i, (lbl, key) in enumerate(cats):
            items = getattr(e, key, [])
            with cols[i % 4]:
                st.markdown(f"**{lbl}**")
                if items:
                    st.markdown(" ".join(f'<span style="font-size:11px;padding:2px 7px;border-radius:8px;border:1px solid var(--border-default);color:var(--text-secondary);font-family:JetBrains Mono,monospace;display:inline-block;margin:2px">{x}</span>' for x in items[:8]), unsafe_allow_html=True)
                else:
                    st.caption("none detected")


# ══════════════════════════════════════════════════════════
# WORKSPACE: RAG KNOWLEDGE
# ══════════════════════════════════════════════════════════
elif ws == "rag":
    r_stat = rag_status()
    section_header("📚 RAG Knowledge Base", f"System D — {r_stat['backend']} · {r_stat['doc_count']} indexed · Hybrid semantic search")

    tab1, tab2 = st.tabs(["🔍 Search", "➕ Ingest Document"])
    with tab1:
        rq = st.text_input("Search knowledge base", placeholder="BGP troubleshooting · OSPF states · SD-WAN design · MPLS L3VPN · Zero Trust…", key="rag_q")
        if st.button("📚 Search", type="primary", key="rag_srch") and rq:
            with st.spinner("Searching…"):
                results = rag_search(rq, 5)
            st.session_state.rag_results = results
        if st.session_state.rag_results:
            st.markdown(f"**{len(st.session_state.rag_results)} relevant chunks:**")
            for content, meta in st.session_state.rag_results:
                topic = meta.get("topic", meta.get("title","Doc"))
                st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:12px;margin-bottom:8px">
                  <div style="font-size:10px;font-weight:700;color:var(--accent-teal);font-family:JetBrains Mono,monospace;margin-bottom:5px">📚 {topic} · {meta.get('vendor','general')}</div>
                  <div style="font-size:12px;color:var(--text-secondary);line-height:1.7">{content[:450]}{'…' if len(content)>450 else ''}</div>
                </div>""", unsafe_allow_html=True)
        else:
            st.markdown("**Pre-loaded knowledge topics:**")
            tc = st.columns(4)
            for i, t in enumerate(r_stat["topics"]):
                with tc[i % 4]:
                    st.markdown(f'<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:8px;padding:10px;font-size:12px;font-weight:600;color:var(--text-primary)">{t}</div>', unsafe_allow_html=True)

    with tab2:
        it  = st.text_input("Title", placeholder="Juniper BGP Config Guide", key="ing_title")
        ic1, ic2 = st.columns(2)
        iv  = ic1.selectbox("Vendor", ["cisco","juniper","arista","paloalto","fortinet","general"], key="ing_vendor")
        idt = ic2.selectbox("Type",   ["manual","runbook","design","reference","sop","config","incident"], key="ing_type")
        ico = st.text_area("Content (paste full document)", placeholder="Paste vendor documentation, runbooks, config examples, SOPs…", height=200, key="ing_content")
        if st.button("➕ Ingest into Knowledge Base", type="primary", key="ing_btn") and ico and it:
            with st.spinner("Chunking and indexing…"):
                n = ingest_document(it, ico, iv, idt)
            st.success(f"✅ Ingested **{n} chunks** from '{it}' into {'ChromaDB' if r_stat['backend']=='ChromaDB' else 'knowledge base'}")


# ══════════════════════════════════════════════════════════
# WORKSPACE: NETWORK DESIGN
# ══════════════════════════════════════════════════════════
elif ws == "design":
    section_header("🏗 AI Design Studio", "ChatGPT for network architecture · Requirements → Full design → BOM → Roadmap")

    st.markdown("""<div class="nb-design-studio">
      <div class="nb-ds-title">🎯 AI Network Design Studio</div>
      <div class="nb-ds-sub">Describe requirements in plain English. I generate full architecture, vendor selection, hardware sizing, BOM, and implementation roadmap.</div>
    </div>""", unsafe_allow_html=True)

    templates = [
        ("🏢","Enterprise Campus","3000 users · 3-tier · SD-Access · Wireless · Zero Trust · HA",
         "Design enterprise campus network: 3000 users, 3-tier hierarchy, Cisco SD-Access, 802.11ax wireless, Zero Trust security, full HA redundancy. Include topology, hardware sizing, BOM top 15 items, 90-day roadmap."),
        ("🛣️","SD-WAN Deployment","50 branches · Dual ISP · Azure · SASE · App-SLA",
         "Design SD-WAN: 50 branches, 200 users each, dual ISP, Azure integration, Zscaler SASE, app-aware routing. Compare Cisco Viptela vs Versa. Full BOM and migration strategy."),
        ("🏭","AI Datacenter Fabric","GPU clusters · VXLAN EVPN · RoCE · Leaf-Spine · 400G",
         "Design AI datacenter: 500 GPU servers, leaf-spine VXLAN EVPN, RoCE lossless networking, 400G uplinks, Arista EOS. Include fabric design, BOM, performance calculations."),
        ("☁️","Hybrid Cloud","On-prem + AWS + Azure · Direct Connect · ExpressRoute · HA",
         "Design hybrid cloud: 2 DCs to AWS and Azure, Direct Connect + ExpressRoute, BGP routing, SD-WAN integration, HA. Compare connectivity options, include routing design and security."),
        ("🔐","Zero Trust Architecture","ZTNA · Micro-seg · Identity · Palo Alto · Zscaler",
         "Design Zero Trust: ZTNA replacing VPN, micro-segmentation east-west, Palo Alto Prisma + Zscaler ZPA, identity-based access, MFA. Phased implementation, maturity model, BOM."),
        ("📡","5G Transport / SP","SR-MPLS · SRv6 · Slicing · Backhaul · Nokia/Cisco",
         "Design 5G transport: 500 cell sites, SR-MPLS underlay, SRv6 services, network slicing eMBB/URLLC/mMTC, Nokia SR-OS or Cisco IOS-XR. Transport architecture, timing sync, BOM."),
    ]
    dc = st.columns(3)
    for i, (ico, name, desc, prompt) in enumerate(templates):
        with dc[i % 3]:
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:14px;margin-bottom:10px">
              <div style="font-size:20px;margin-bottom:7px">{ico}</div>
              <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:3px">{name}</div>
              <div style="font-size:11px;color:var(--text-secondary);margin-bottom:10px;line-height:1.5">{desc}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Design {name}", key=f"ds_{name}", use_container_width=True):
                with st.spinner(f"🏗 Generating {name} architecture…"):
                    output = design_network(prompt, st.session_state.persona)
                st.session_state.design_output = output
                st.session_state.workspace = "design"
                st.rerun()

    st.divider()
    st.markdown("**Custom Design:**")
    d1, d2 = st.columns(2)
    with d1:
        rs = st.text_input("Sites", placeholder="1 HQ + 20 branches + 2 DCs", key="d_sites")
        ru = st.text_input("Users per location", placeholder="500 HQ, 100 branch", key="d_users")
        rc = st.text_input("Cloud", placeholder="Azure primary, AWS DR, M365", key="d_cloud")
        rsec = st.text_input("Security", placeholder="Zero Trust, SASE, PCI DSS", key="d_sec")
    with d2:
        rb = st.text_input("Budget", placeholder="Under $500K CapEx", key="d_budget")
        rv = st.text_input("Vendor preference", placeholder="Cisco preferred, open to Juniper", key="d_vendor")
        rh = st.text_input("HA requirements", placeholder="99.99% uptime, dual ISP", key="d_ha")
        rsp = st.text_area("Special requirements", height=68, placeholder="HIPAA compliance, AI workloads, IoT, video surveillance…", key="d_special")

    if st.button("🏗 Generate Full Architecture", type="primary", use_container_width=True, key="ds_custom"):
        reqs = f"Sites:{rs} | Users:{ru} | Cloud:{rc} | Security:{rsec} | Budget:{rb} | Vendors:{rv} | HA:{rh} | Special:{rsp}"
        with st.spinner("🧠 Generating architecture…"):
            output = design_network(reqs, st.session_state.persona)
        st.session_state.design_output = output

    if st.session_state.design_output:
        st.markdown("---")
        st.markdown("**🏗 Generated Architecture:**")
        st.markdown(st.session_state.design_output)
        st.download_button("⬇ Download as Markdown", st.session_state.design_output, "network_design.md", "text/markdown")


# ══════════════════════════════════════════════════════════
# WORKSPACE: LEARNING
# ══════════════════════════════════════════════════════════
elif ws == "learn":
    section_header("📖 Adaptive Learning Hub", "AI detects your level automatically · CCNA → CCNP → CCIE → Expert Architect")

    ai_insight_card(
        "Adaptive NLP Learning",
        f"Persona: <strong>{st.session_state.persona.upper()}</strong>. "
        "Ask <strong>'what is a VLAN?'</strong> → basics with analogy. "
        "Ask <strong>'explain Q-in-Q double-tagging MTU implications'</strong> → expert level. "
        "<strong>No configuration needed — I auto-detect your level.</strong>",
    )

    tracks = [
        ("🌐","Routing Fundamentals","OSPF · BGP · EIGRP · IS-IS · Policy · Redistribution",65,"blue","Start routing lesson. Detect my level. Include OSPF, BGP, EIGRP with practical examples."),
        ("🔀","Switching & Fabric","VLANs · STP · EtherChannel · RSTP · MACsec · SD-Access",40,"green","Teach switching and VLANs from my level. STP, EtherChannel, campus fabric design."),
        ("🛣️","WAN & SD-WAN","MPLS · SD-WAN · DMVPN · SASE · QoS · Cloud WAN",20,"amber","Explain WAN technologies. Start basics then Cisco Viptela, SASE, cloud WAN architecture."),
        ("🔒","Network Security","Zero Trust · ZTNA · Firewall · ACL · IPSec · SASE · NAC",55,"red","Teach network security from my level. Zero Trust, ZTNA, firewall policies, segmentation."),
        ("🏢","Datacenter","VXLAN · EVPN · Leaf-Spine · ACI · AI Fabric · RoCE",10,"purple","Explain datacenter networking. Why leaf-spine, VXLAN EVPN, AI fabric, RoCE for GPU."),
        ("☁️","Cloud & Hybrid","AWS VPC · Azure VNet · GCP · Transit Gateway · Kubernetes",30,"blue","Teach cloud networking. AWS VPC, Azure VNet, hybrid connectivity, Kubernetes CNI."),
        ("📡","Service Provider","MPLS L3VPN · SR-MPLS · SRv6 · 5G Transport · BGP-LU",5,"purple","Explain SP networking. MPLS L3VPN, SR-MPLS, SRv6, 5G transport. Expert level."),
        ("🤖","Automation","Ansible · Terraform · Python · NETCONF · RESTCONF · gRPC",15,"green","Teach network automation. Ansible, Python netmiko, NETCONF/RESTCONF, practical examples."),
    ]
    tc = st.columns(4)
    for i, (ico, name, desc, pct, color, prompt) in enumerate(tracks):
        with tc[i % 4]:
            color_map = {"blue":"#2f81f7","green":"#3fb950","amber":"#d29922","red":"#f85149","purple":"#bc8cff"}
            cv = color_map.get(color, "#2f81f7")
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:13px;margin-bottom:4px">
              <div style="font-size:18px;margin-bottom:6px">{ico}</div>
              <div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:2px">{name}</div>
              <div style="font-size:11px;color:var(--text-secondary);margin-bottom:9px;line-height:1.5">{desc}</div>
              <div style="height:3px;background:var(--border-default);border-radius:4px;overflow:hidden;margin-bottom:4px"><div style="height:100%;width:{pct}%;background:{cv};border-radius:4px"></div></div>
              <div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace">{pct}% complete</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Start", key=f"tk_{name}", use_container_width=True):
                go(prompt, "learn")

    st.divider()
    lq = st.text_input("Ask anything to learn", placeholder="'What is BGP?' · 'Explain OSPF DR election' · 'How does VXLAN work?' · 'Compare SD-WAN vs MPLS'", key="lq")
    if st.button("📖 Learn", type="primary", key="learn_ask") and lq:
        go(lq, "learn")

    ai_learns = [m for m in st.session_state.chat_msgs if m["role"] == "assistant"]
    if ai_learns:
        with st.expander("📖 Latest Learning Response", expanded=True):
            render_chat_message("assistant", ai_learns[-1]["content"], ai_learns[-1].get("meta"))


# ══════════════════════════════════════════════════════════
# WORKSPACE: DEVICE MANAGER
# ══════════════════════════════════════════════════════════
elif ws == "devices":
    section_header("🖧 Device Manager", "Add SSH devices for multi-device query engine · Encrypted credential storage")

    t1, t2 = st.tabs(["📋 All Devices", "➕ Add Device"])
    with t1:
        devs = get_devices()
        if devs:
            df = pd.DataFrame(devs)[["hostname","ip","vendor","role","site","status","cpu","memory","port"]]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption(f"**{len(devs)} devices** · SSH {'live' if NETMIKO_OK else '⚡ simulation mode'} · Passwords stored encrypted (Fernet)")
        else:
            st.info("No devices. Add below.")
    with t2:
        if has_permission("manage_devices"):
            c1, c2, c3 = st.columns(3)
            hn   = c1.text_input("Hostname", placeholder="CORE-RTR-01")
            ip   = c1.text_input("IP Address", placeholder="10.0.0.1")
            ven  = c2.selectbox("Vendor", ["cisco_ios","cisco_ios_xe","cisco_ios_xr","cisco_nxos","juniper_junos","arista_eos","paloalto_panos","fortinet","huawei_vrp"])
            role = c2.text_input("Role", placeholder="Core Router")
            usr  = c3.text_input("SSH Username", placeholder="admin")
            pwd  = c3.text_input("SSH Password", type="password")
            site = c3.text_input("Site", placeholder="HQ")
            port = c3.number_input("Port", value=22, min_value=1, max_value=65535)
            if st.button("➕ Add Device (encrypted)", type="primary"):
                if hn and ip:
                    add_device(hn, ip, ven, usr, pwd, int(port), role, site)
                    write_audit(st.session_state.user_name, "add_device", f"device:{hn}", f"IP:{ip}")
                    st.success(f"✅ Added {hn} — password encrypted with Fernet")
                    st.rerun()
                else:
                    st.error("Hostname and IP required")
        else:
            st.warning("🔒 Insufficient permissions to add devices")


# ══════════════════════════════════════════════════════════
# WORKSPACE: EXECUTIVE
# ══════════════════════════════════════════════════════════
elif ws == "executive":
    section_header("📈 Executive Dashboard", "Business impact · SLA performance · Risk scores · Board-ready metrics")

    metric_grid([
        {"label":"Network Uptime","value":"99.94%","meta":"SLA target 99.9% ✅","color":"green","icon":"✅"},
        {"label":"MTTR","value":"18m","meta":"↓ 40% vs last quarter","color":"blue","icon":"⚡"},
        {"label":"Risk Score","value":"Medium","meta":"14 CVEs · 2 threats","color":"amber","icon":"⚠"},
        {"label":"Automation Rate","value":"78%","meta":"↑ 12% this quarter","color":"green","icon":"🤖"},
    ])

    col_l, col_r = st.columns(2)
    with col_l:
        st.markdown("**📊 Operational Health**")
        metrics_data = {"SLA Performance":"99.94%","MTTR Reduction":"↓ 40%","Change Success":"97.3%","Auto-Remediation":"94%","Incidents Resolved":"2/2"}
        for k, v in metrics_data.items():
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:13px">{k}</span><span style="color:var(--text-primary);font-weight:700;font-size:13px">{v}</span></div>', unsafe_allow_html=True)
    with col_r:
        st.markdown("**💰 Business Value**")
        biz_data = {"Time Saved This Week":"4.2 hours","Outages Prevented":"3","Auto-Actions Executed":"47","Approx. Cost Saving":"$8,400","Engineers Upskilled":"8"}
        for k, v in biz_data.items():
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:13px">{k}</span><span style="color:var(--accent-green);font-weight:700;font-size:13px">{v}</span></div>', unsafe_allow_html=True)

    if st.button("🧠 Generate Board Report", type="primary"):
        with st.spinner("Generating executive report…"):
            report = call_ai([{"role":"user","content":"Generate concise executive board report: network health uptime MTTR risks automation ROI investments needed 90-day outlook. Business language only."}], "manager", max_tokens=1500)
        st.markdown(report)
        st.download_button("⬇ Download Report", report, "exec_report.md", "text/markdown")


# ══════════════════════════════════════════════════════════
# WORKSPACE: AUDIT LOG
# ══════════════════════════════════════════════════════════
elif ws == "audit":
    if not require_permission("view_audit"):
        st.stop()
    section_header("🔐 Audit Log", "Complete audit trail · All user actions · Security events")

    logs = get_audit_logs(100)
    if logs:
        df = pd.DataFrame(logs)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.caption(f"{len(logs)} audit entries shown")
    else:
        st.info("No audit events recorded yet.")


# ══════════════════════════════════════════════════════════
# WORKSPACE: OBSERVABILITY
# ══════════════════════════════════════════════════════════
elif ws == "observe":
    section_header("📡 Observability", "Live telemetry · Anomaly detection · SaaS monitoring · NetFlow · Syslog")

    telemetry = get_live_telemetry()
    anomalies = detect_anomalies(telemetry)

    if anomalies:
        crit = [a for a in anomalies if a["severity"] == "critical"]
        warn = [a for a in anomalies if a["severity"] == "warning"]
        ai_insight_card(
            "Anomaly Detection — Live",
            f"<strong>{len(crit)} critical</strong> and <strong>{len(warn)} warning</strong> anomalies detected. "
            + (f"Top: {crit[0]['message']} — {crit[0]['ai_hint']}" if crit else "No critical anomalies."),
            confidence=91,
        )

    # Metrics
    metric_grid([
        {"label":"Devices Monitored","value":str(len(telemetry)),"meta":"Live telemetry","color":"blue","icon":"📡"},
        {"label":"Active Anomalies","value":str(len(anomalies)),"meta":f"{len([a for a in anomalies if a['severity']=='critical'])} critical","color":"red" if anomalies else "green","icon":"⚠"},
        {"label":"Avg CPU","value":f"{int(sum(t['cpu'] for t in telemetry)/max(1,len(telemetry)))}%","meta":"Across all devices","color":"amber","icon":"💻"},
        {"label":"Avg Latency","value":"14ms","meta":"Network baseline","color":"green","icon":"⚡"},
    ])

    tab_live, tab_saas, tab_flow, tab_syslog = st.tabs(["📊 Live Telemetry","🌐 SaaS Health","🔄 NetFlow","📋 Syslog"])

    with tab_live:
        st.markdown("**Device Telemetry — Refreshes every 15s**")
        dev_cols = st.columns(4)
        for i, t in enumerate(telemetry):
            cpu, mem = t.get("cpu",0), t.get("memory",0)
            status = t.get("status","up")
            cpu_cls = "mv-crit" if cpu >= 85 else "mv-warn" if cpu >= 70 else "mv-ok"
            mem_cls = "mv-crit" if mem >= 80 else "mv-warn" if mem >= 60 else "mv-ok"
            with dev_cols[i % 4]:
                st.markdown(f"""<div class="nb-dev dev-{status}">
                  <div class="nb-dev-hn">{t['hostname']}</div>
                  <div class="nb-dev-role">{t['role']}</div>
                  <div class="nb-dev-metrics">
                    <div class="nb-dev-m"><div class="nb-dev-mv {cpu_cls}">{f"{cpu}%" if cpu else "—"}</div><div class="nb-dev-ml">CPU</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {mem_cls}">{f"{mem}%" if mem else "—"}</div><div class="nb-dev-ml">MEM</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {'mv-crit' if t.get('packet_loss',0)>0.5 else 'mv-ok'}">{t.get('packet_loss',0)}%</div><div class="nb-dev-ml">LOSS</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv mv-ok">{t.get('latency_ms',0)}ms</div><div class="nb-dev-ml">RTT</div></div>
                  </div>
                </div>""", unsafe_allow_html=True)

        if anomalies:
            st.markdown("**🔍 Detected Anomalies:**")
            for a in anomalies:
                sev_ico = "🔴" if a["severity"] == "critical" else "🟡"
                st.markdown(f"""<div class="nb-timeline-item">
                  <div class="nb-tl-dot {'tl-crit' if a['severity']=='critical' else 'tl-warn'}">{sev_ico}</div>
                  <div class="nb-tl-body">
                    <div class="nb-tl-title">{a['message']}</div>
                    <div class="nb-tl-meta">{a['device']} · {a['type']} · value: {a['value']}</div>
                    <div class="nb-tl-ai">🧠 {a['ai_hint']}</div>
                  </div>
                </div>""", unsafe_allow_html=True)
            if st.button("🧠 AI Anomaly Analysis", type="primary"):
                anomaly_desc = "\n".join(f"- {a['message']} ({a['severity']})" for a in anomalies[:5])
                go(f"Analyze these network anomalies and correlate root causes:\n{anomaly_desc}", "troubleshoot")

    with tab_saas:
        saas = get_saas_health()
        st.markdown("**SaaS Application Health — Internet Experience Monitoring**")
        saas_cols = st.columns(4)
        for i, svc in enumerate(saas):
            score = svc["score"]
            color = "var(--accent-green)" if score >= 85 else "var(--accent-amber)" if score >= 60 else "var(--accent-red)"
            status_text = "Healthy" if score >= 85 else "Degraded" if score >= 60 else "Critical"
            with saas_cols[i % 4]:
                st.markdown(f"""<div class="nb-dev dev-{'up' if score>=85 else 'warn' if score>=60 else 'critical'}">
                  <div style="font-size:18px;margin-bottom:4px">{svc['icon']}</div>
                  <div class="nb-dev-hn" style="font-size:12px">{svc['name']}</div>
                  <div class="nb-dev-metrics">
                    <div class="nb-dev-m"><div class="nb-dev-mv" style="color:{color}">{score}</div><div class="nb-dev-ml">Score</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {'mv-warn' if svc['latency_ms']>150 else 'mv-ok'}">{svc['latency_ms']}ms</div><div class="nb-dev-ml">Latency</div></div>
                    <div class="nb-dev-m"><div class="nb-dev-mv {'mv-crit' if svc['loss_pct']>0.5 else 'mv-ok'}">{svc['loss_pct']}%</div><div class="nb-dev-ml">Loss</div></div>
                  </div>
                </div>""", unsafe_allow_html=True)
        degraded = [s for s in saas if s["score"] < 85]
        if degraded:
            if st.button("🧠 AI SaaS Analysis", type="primary"):
                desc = "\n".join(f"- {s['name']}: score {s['score']}, latency {s['latency_ms']}ms" for s in degraded)
                go(f"Analyze SaaS degradation:\n{desc}\nIs this caused by our BGP issues on PE-MUM-01?", "troubleshoot")

    with tab_flow:
        nf = get_netflow_summary()
        col_nf1, col_nf2 = st.columns(2)
        with col_nf1:
            st.markdown("**Top Talkers**")
            for t in nf["top_talkers"]:
                st.markdown(f"""<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--border-subtle)">
                  <div><span style="font-family:JetBrains Mono,monospace;font-size:12px;color:var(--text-primary)">{t['src']}</span>
                  <span style="font-size:11px;color:var(--text-tertiary);margin:0 6px">→</span>
                  <span style="font-size:11px;color:var(--accent-blue)">{t['app']}</span></div>
                  <span style="font-family:JetBrains Mono,monospace;font-size:12px;font-weight:700;color:var(--accent-amber)">{t['mbps']} Mbps</span>
                </div>""", unsafe_allow_html=True)
        with col_nf2:
            st.markdown("**Traffic Summary**")
            st.metric("Total Throughput", f"{nf['total_gbps']} Gbps")
            st.metric("Flow Rate", f"{nf['flows_per_sec']:,} flows/s")
            for proto, pct in list(nf["protocol_mix"].items())[:5]:
                st.markdown(f'<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:12px">{proto}</span><span style="font-family:JetBrains Mono,monospace;font-size:12px;color:var(--text-primary)">{pct}%</span></div>', unsafe_allow_html=True)

    with tab_syslog:
        logs = get_recent_syslogs(15)
        st.markdown("**Recent Syslog Events**")
        for log in logs:
            sev = log["severity"]
            ico = "🔴" if sev == "critical" else "🟡" if sev == "warning" else "ℹ️"
            dot_cls = "tl-crit" if sev == "critical" else "tl-warn" if sev == "warning" else "tl-info"
            st.markdown(f"""<div class="nb-timeline-item">
              <div class="nb-tl-dot {dot_cls}">{ico}</div>
              <div class="nb-tl-body">
                <div class="nb-tl-title" style="font-family:JetBrains Mono,monospace;font-size:12px">{log['message']}</div>
                <div class="nb-tl-meta">{log['ts']} · {log['device']}</div>
              </div>
            </div>""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# WORKSPACE: DIGITAL TWIN
# ══════════════════════════════════════════════════════════
elif ws == "twin":
    section_header("👾 Digital Twin", "Topology clone · Failure simulation · Change validation · What-if analysis")

    twin_stat = get_twin_status()
    ai_insight_card(
        "Digital Twin Engine",
        "Ask: <strong>'What happens if PE-MUM-01 fails?'</strong> → I simulate failure, show affected services, "
        "calculate failover time, and recommend mitigation — <strong>before it happens in production.</strong> "
        "Every change is tested here first.",
        confidence=99,
    )

    metric_grid([
        {"label":"Devices Cloned","value":str(twin_stat["cloned_devices"]),"meta":"From live topology","color":"blue","icon":"👾"},
        {"label":"Config Accuracy","value":f"{twin_stat['accuracy_pct']}%","meta":f"Last sync {twin_stat['last_sync_s']}s ago","color":"green","icon":"✅"},
        {"label":"Active Simulations","value":str(twin_stat["active_simulations"]),"meta":"Running now","color":"amber","icon":"⚡"},
        {"label":"Changes Tested","value":str(twin_stat["changes_tested"]),"meta":"This month","color":"green","icon":"🧪"},
    ])

    col_sim, col_result = st.columns([0.45, 0.55])

    with col_sim:
        st.markdown("**⚡ Failure Simulation**")
        devices = get_devices()
        dev_names = [d["hostname"] for d in devices]
        sim_device = st.selectbox("Select device to simulate failure", dev_names, key="twin_dev")
        if st.button("▶ Simulate Failure", type="primary", use_container_width=True, key="twin_sim"):
            with st.spinner(f"Simulating {sim_device} failure…"):
                result = simulate_failure(sim_device)
            st.session_state["twin_result"] = result
            st.session_state["twin_type"] = "failure"

        st.markdown("---")
        st.markdown("**🔧 Change Simulation**")
        chg_dev  = st.selectbox("Device", dev_names, key="twin_chg_dev")
        chg_type = st.selectbox("Change type", ["firmware","config","vlan","routing","hardware"], key="twin_chg_type")
        chg_desc = st.text_input("Change description", placeholder="e.g. Upgrade IOS-XR 7.5.2 → 7.7.1", key="twin_chg_desc")
        if st.button("▶ Simulate Change", use_container_width=True, key="twin_chg_sim"):
            with st.spinner("Simulating change impact…"):
                result = simulate_change(chg_dev, chg_type, chg_desc or f"{chg_type} on {chg_dev}")
            st.session_state["twin_result"] = result
            st.session_state["twin_type"] = "change"

        st.markdown("---")
        st.markdown("**🤖 AI What-If Scenarios**")
        for scenario, prompt in [
            ("PE-MUM-01 failure", "Simulate complete failure of PE-MUM-01. What services fail? Failover? Recommendations?"),
            ("ISP link drops", "What if the ISP link on PE-MUM-01 to AS65002 goes completely down?"),
            ("CORE-RTR-01 firmware", "Simulate firmware upgrade on CORE-RTR-01 from 7.5.2 to 7.7.1. Risk and downtime?"),
            ("Add OSPF area 10", "Validate adding OSPF area 10 with 5 new subnets before production. What are risks?"),
        ]:
            if st.button(f"▶ {scenario}", key=f"twin_{scenario}", use_container_width=True):
                go(prompt, "twin", "Digital Twin workspace — what-if simulation")

    with col_result:
        st.markdown("**📊 Simulation Result**")
        result = st.session_state.get("twin_result")
        twin_type = st.session_state.get("twin_type", "failure")

        if not result:
            st.info("Run a simulation on the left to see results here.")
        elif twin_type == "failure":
            sev_color = "var(--accent-red)" if result.get("severity") == "critical" else "var(--accent-amber)"
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:16px;margin-bottom:10px">
              <div style="font-size:14px;font-weight:700;color:{sev_color};margin-bottom:12px">⚡ Failure: {result.get('failed_device','')}</div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px">
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">Criticality</div><div style="font-size:16px;font-weight:700;color:{sev_color}">{result.get('criticality',0)}/10</div></div>
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">Users Impacted</div><div style="font-size:16px;font-weight:700;color:var(--accent-red)">{result.get('affected_users',0)}</div></div>
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">Failover</div><div style="font-size:13px;font-weight:600;color:var(--accent-green)">{'✅ ' + result['failover_device'] + f' ({result[\"estimated_rto_s\"]}s)' if result.get('failover_possible') else '❌ No failover — SPOF'}</div></div>
                <div><div style="font-size:10px;color:var(--text-tertiary);font-family:JetBrains Mono,monospace;text-transform:uppercase;margin-bottom:3px">SPOF</div><div style="font-size:13px;font-weight:600;color:{'var(--accent-red)' if result.get('is_spof') else 'var(--accent-green)'}">{'⚠️ YES' if result.get('is_spof') else '✅ No'}</div></div>
              </div>
              <div style="margin-bottom:8px"><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">Affected Services</div>{"".join(f'<span style="font-size:11px;padding:2px 7px;border-radius:8px;background:var(--accent-red-subtle);color:var(--accent-red);margin:2px;display:inline-block">{s}</span>' for s in result.get("affected_services",[]))}</div>
              <div><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">AI Recommendations</div>{"".join(f'<div style="font-size:12px;color:var(--text-primary);padding:4px 0;border-bottom:1px solid var(--border-subtle)">{r}</div>' for r in result.get("recommendations",[]))}</div>
            </div>""", unsafe_allow_html=True)
        else:
            score = result.get("risk_score", 0)
            risk_cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:16px">
              <div style="font-size:14px;font-weight:700;color:var(--text-primary);margin-bottom:12px">🔧 Change: {result.get('device','')} — {result.get('change_type','')}</div>
              <div style="margin-bottom:10px"><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:4px">Risk Score</div></div>
            </div>""", unsafe_allow_html=True)
            risk_bar(score)
            st.markdown(f"**Downtime:** {result.get('predicted_downtime',0)}s &nbsp;|&nbsp; **Users:** {result.get('affected_users',0)}")
            st.markdown(f"**Maintenance window required:** {'✅ Yes' if result.get('maintenance_window_required') else '❌ No'}")
            if result.get("risks"):
                st.markdown("**Risks:**")
                for r in result["risks"]:
                    st.markdown(f"- {r}")
            if result.get("rollback_steps"):
                with st.expander("📋 Rollback Plan"):
                    for step in result["rollback_steps"]:
                        st.markdown(f"`{step}`")


# ══════════════════════════════════════════════════════════
# WORKSPACE: SECURITY OPERATIONS
# ══════════════════════════════════════════════════════════
elif ws == "security":
    section_header("🔒 Security Operations", "Zero Trust · Threat correlation · Firewall intelligence · Posture analysis")

    ai_insight_card(
        "Security Intelligence",
        "<strong>Lateral movement detected</strong> from 10.2.14.0/24 (SW-ACC-14 segment) — "
        "port scan pattern, 23 hosts probed in 4 minutes. "
        "<strong>Zero Trust score: 62%</strong> — micro-segmentation gap in access layer. "
        "<strong>14 unpatched CVEs</strong> on edge devices — 3 critical severity.",
        confidence=89, sources=["Firewall","SIEM","Threat Intel"],
    )

    metric_grid([
        {"label":"Active Threats","value":"2","meta":"Lateral movement + CVEs","color":"red","icon":"🚨"},
        {"label":"CVEs Unpatched","value":"14","meta":"3 critical severity","color":"amber","icon":"⚠"},
        {"label":"FW Rule Health","value":"98%","meta":"Shadow rules cleaned","color":"green","icon":"🛡"},
        {"label":"Zero Trust Score","value":"62%","meta":"Improving +8% this month","color":"blue","icon":"🔐"},
    ])

    tab_threats, tab_fw, tab_zt, tab_vuln = st.tabs(["🚨 Threats","🛡 Firewall","🔐 Zero Trust","⚠ Vulnerabilities"])

    with tab_threats:
        threats = [
            {"sev":"critical","type":"Lateral Movement","src":"10.2.14.45","dst":"10.1.0.0/16","detail":"Port scan 23 hosts in 4 min on SW-ACC-14 segment. Possible credential theft following interface failure.","action":"Isolate 10.2.14.45. Check for compromised credentials. Enable 802.1X."},
            {"sev":"warning","type":"Unusual Egress","src":"10.1.100.87","dst":"45.141.87.0/24","detail":"DNS queries to known C2 domain (IOC match). Volume 2x baseline.","action":"Block at DNS layer (Umbrella). Investigate endpoint 10.1.100.87."},
        ]
        for t in threats:
            st.markdown(f"""<div class="nb-warroom">
              <div class="nb-wr-hdr" style="background:{'linear-gradient(135deg,#3d0f0a,#5c1a12)' if t['sev']=='critical' else 'linear-gradient(135deg,#3d2b00,#6b4a00)'}">
                <div class="nb-wr-pulse"></div>
                <div class="nb-wr-title">{'🔴' if t['sev']=='critical' else '🟡'} {t['type']}</div>
              </div>
              <div style="padding:14px 18px">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
                  <div><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:3px">Source → Destination</div><div style="font-size:13px;font-family:JetBrains Mono,monospace;color:var(--accent-red)">{t['src']} → {t['dst']}</div></div>
                  <div><div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:3px">Detail</div><div style="font-size:12px;color:var(--text-primary)">{t['detail']}</div></div>
                </div>
                <div style="margin-top:8px;padding:8px;background:rgba(47,129,247,.06);border-radius:6px;font-size:12px;color:var(--accent-blue)">🧠 Recommended: {t['action']}</div>
              </div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"🧠 AI Threat Analysis", key=f"threat_{t['type']}", use_container_width=True):
                go(f"Security threat: {t['type']} — {t['detail']}. Source: {t['src']}. Analyze attack path, lateral movement risk, and provide containment actions.", "security")

    with tab_fw:
        st.markdown("**Firewall Rule Health — FW-EDGE-01**")
        fw_stats = [
            ("Total rules","284","Rule base size"),("Shadow rules","0","Cleaned last week"),
            ("Unused rules","12","No traffic in 90 days"),("Any-Any rules","2","High risk — review needed"),
            ("Expired rules","4","Past end-date"),("Rules without logs","8","Compliance gap"),
        ]
        fc = st.columns(3)
        for i, (label, val, meta) in enumerate(fw_stats):
            with fc[i % 3]:
                color = "var(--accent-red)" if "risk" in meta.lower() or "gap" in meta.lower() else "var(--accent-green)" if val == "0" else "var(--text-primary)"
                st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:8px;padding:12px;text-align:center;margin-bottom:8px">
                  <div style="font-size:10px;color:var(--text-tertiary);text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:4px">{label}</div>
                  <div style="font-size:22px;font-weight:700;font-family:Fraunces,serif;color:{color}">{val}</div>
                  <div style="font-size:11px;color:var(--text-tertiary)">{meta}</div>
                </div>""", unsafe_allow_html=True)
        if st.button("🧠 AI Firewall Optimization", type="primary"):
            go("Analyze firewall rule base: shadow rules, unused rules, any-any rules, missing logs. Provide cleanup recommendations prioritized by risk.", "security")

    with tab_zt:
        st.markdown("**Zero Trust Maturity Assessment**")
        pillars = [
            ("Identity","80%","MFA enforced. Conditional access configured.","green"),
            ("Devices","65%","MDM enrolled. Some unmanaged devices remain.","amber"),
            ("Networks","50%","Micro-segmentation partial. VXLAN in DC only.","amber"),
            ("Applications","70%","ZTNA deployed for 60% of apps. VPN still used.","amber"),
            ("Data","45%","DLP partial. Shadow IT uncontrolled.","red"),
            ("Visibility","75%","SIEM active. NDR deployed. Some gaps in cloud.","green"),
        ]
        pc = st.columns(3)
        for i, (pillar, score, desc, color) in enumerate(pillars):
            pct = int(score.rstrip("%"))
            bar_color = {"green":"var(--accent-green)","amber":"var(--accent-amber)","red":"var(--accent-red)"}[color]
            with pc[i % 3]:
                st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:13px;margin-bottom:8px">
                  <div style="font-size:12px;font-weight:700;color:var(--text-primary);margin-bottom:3px">{pillar}</div>
                  <div style="font-size:18px;font-weight:700;font-family:Fraunces,serif;color:{bar_color};margin-bottom:6px">{score}</div>
                  <div style="height:3px;background:var(--border-default);border-radius:4px;overflow:hidden;margin-bottom:6px"><div style="height:100%;width:{pct}%;background:{bar_color}"></div></div>
                  <div style="font-size:11px;color:var(--text-tertiary)">{desc}</div>
                </div>""", unsafe_allow_html=True)
        if st.button("🧠 Zero Trust Gap Analysis", type="primary"):
            go("Full Zero Trust maturity assessment. Top 5 gaps to close, prioritized by risk reduction impact. Practical implementation steps for each.", "security")

    with tab_vuln:
        vulns = [
            ("CVE-2024-20399","Cisco IOS-XR","9.8 Critical","FW-EDGE-01, PE-MUM-01","Patch available — schedule immediately"),
            ("CVE-2024-3400", "Palo Alto PAN-OS","10.0 Critical","FW-EDGE-01","Emergency patch — exploited in wild"),
            ("CVE-2023-44487","HTTP/2","7.5 High","WLC-HQ-01","Apply workaround — vendor patch pending"),
            ("CVE-2024-21893","Fortinet","8.2 High","No Fortinet devices","N/A in your environment"),
        ]
        for v in vulns[:3]:
            sev_color = "var(--accent-red)" if "Critical" in v[2] else "var(--accent-amber)"
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-left:3px solid {sev_color};border-radius:0 10px 10px 0;padding:12px;margin-bottom:8px;display:flex;gap:12px;align-items:flex-start">
              <div style="flex:1">
                <div style="font-family:JetBrains Mono,monospace;font-size:12px;font-weight:600;color:{sev_color}">{v[0]} — {v[1]}</div>
                <div style="font-size:13px;color:var(--text-primary);margin:3px 0">CVSS: {v[2]} · Affected: {v[3]}</div>
                <div style="font-size:11px;color:var(--accent-blue)">🧠 {v[4]}</div>
              </div>
            </div>""", unsafe_allow_html=True)
        if st.button("🧠 AI Vulnerability Prioritization", type="primary"):
            go("Prioritize 14 unpatched CVEs on network devices. Which to patch first based on CVSS score, exposure, and our specific network topology? Provide patch schedule.", "security")


# ══════════════════════════════════════════════════════════
# WORKSPACE: COMPLIANCE
# ══════════════════════════════════════════════════════════
elif ws == "compliance":
    section_header("🛡 Compliance & Posture", "CIS · NIST · PCI DSS · ISO 27001 · Zero Trust · Automated validation")

    ai_insight_card(
        "Compliance Intelligence",
        "<strong>Overall posture: 84%</strong> across all frameworks. "
        "Top gap: <strong>NIST CSF Identity pillar (72%)</strong> — incomplete MFA rollout. "
        "<strong>PCI DSS cardholder environment</strong> correctly isolated. "
        "<strong>14 CVEs</strong> create compliance risk — remediate within 30 days per policy.",
        confidence=91,
    )

    # Framework scores
    frameworks = [
        ("CIS Benchmark","91%",91,"23 violations of 256 controls","green"),
        ("NIST CSF 2.0","78%",78,"Identity + Govern pillars gap","amber"),
        ("PCI DSS 4.0","96%",96,"Cardholder network isolated","green"),
        ("ISO 27001","88%",88,"Audit trail complete","green"),
        ("Zero Trust","62%",62,"Micro-segmentation partial","amber"),
        ("Firmware CVEs","14 open",14,"3 critical unpatched → compliance risk","red"),
    ]
    fc = st.columns(3)
    for i, (name, score, pct, desc, color) in enumerate(frameworks):
        bar_color = {"green":"var(--accent-green)","amber":"var(--accent-amber)","red":"var(--accent-red)"}[color]
        bar_w = min(100, pct)
        with fc[i % 3]:
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:14px;margin-bottom:10px">
              <div style="font-size:11px;font-weight:700;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.8px;font-family:JetBrains Mono,monospace;margin-bottom:5px">{name}</div>
              <div style="font-size:24px;font-weight:700;font-family:Fraunces,serif;color:{bar_color};margin-bottom:6px">{score}</div>
              <div style="height:4px;background:var(--border-default);border-radius:4px;overflow:hidden;margin-bottom:6px"><div style="height:100%;width:{bar_w}%;background:{bar_color}"></div></div>
              <div style="font-size:11px;color:var(--text-tertiary)">{desc}</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # Remediation priorities
    st.markdown("**🔧 Top Remediation Priorities**")
    priorities = [
        ("🔴","P1","Patch CVE-2024-3400 on FW-EDGE-01","PAN-OS critical — exploited in wild. Emergency maintenance window.","3 days"),
        ("🔴","P1","Complete MFA rollout for NIST CSF","18% of users lack MFA. NIST CSF Identity gap.","7 days"),
        ("🟡","P2","Remove unused firewall rules (12)","PCI DSS 1.2.1 requires rule review quarterly.","14 days"),
        ("🟡","P2","Enable logging on 8 firewall rules","Compliance requires all rules logged.","7 days"),
        ("🟢","P3","Micro-segmentation — access layer","Zero Trust maturity gap. Implement 802.1X.","60 days"),
    ]
    for sev, pri, title, detail, deadline in priorities:
        st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:12px;margin-bottom:8px;display:flex;align-items:flex-start;gap:12px">
          <div style="font-size:18px;flex-shrink:0">{sev}</div>
          <div style="flex:1">
            <div style="font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:2px">{title}</div>
            <div style="font-size:12px;color:var(--text-secondary)">{detail}</div>
          </div>
          <div style="font-size:11px;font-family:JetBrains Mono,monospace;color:var(--text-tertiary);flex-shrink:0">Due: {deadline}</div>
        </div>""", unsafe_allow_html=True)

    col_c1, col_c2 = st.columns(2)
    with col_c1:
        if st.button("🧠 AI Gap Analysis", type="primary", use_container_width=True):
            go("Full compliance gap analysis across CIS Benchmark, NIST CSF 2.0, PCI DSS 4.0, Zero Trust. Top 5 gaps with business risk, remediation steps, and implementation timeline.", "compliance")
    with col_c2:
        if st.button("📋 Generate Audit Report", use_container_width=True):
            go("Generate a formal compliance audit report suitable for CISO and board presentation. Include all frameworks, scores, gaps, risks, and remediation roadmap.", "compliance")


# ══════════════════════════════════════════════════════════
# WORKSPACE: FINOPS
# ══════════════════════════════════════════════════════════
elif ws == "finops":
    section_header("💰 FinOps & Cost Intelligence", "License optimization · Cloud cost · Hardware lifecycle · ROI tracking")

    ai_insight_card(
        "Cost Intelligence",
        "<strong>$380K savings identified</strong> this quarter. Top opportunities: "
        "<strong>18% unused Cisco licenses</strong> ($142K), "
        "<strong>34 EoL devices</strong> nearing support expiry ($220K refresh avoided with timing), "
        "<strong>SD-WAN replacing MPLS</strong> at 3 branches saves $45K/year.",
        confidence=84,
    )

    metric_grid([
        {"label":"Annual Network Spend","value":"$4.2M","meta":"Within approved budget","color":"blue","icon":"💰"},
        {"label":"Identified Savings","value":"$380K","meta":"License + cloud rightsizing","color":"green","icon":"📉"},
        {"label":"EoL Hardware","value":"34","meta":"Devices need replacement","color":"amber","icon":"⚠"},
        {"label":"Wasted Licenses","value":"18%","meta":"Unused entitlements","color":"red","icon":"🔓"},
    ])

    col_f1, col_f2 = st.columns(2)
    with col_f1:
        st.markdown("**💡 Savings Opportunities**")
        opps = [
            ("Cisco Smart Licensing","$142K/yr","18% of DNA licenses unused. Rightsizing recommended.","green"),
            ("MPLS → SD-WAN migration","$45K/yr","3 branches still on MPLS. SD-WAN at half the cost.","green"),
            ("Cloud egress optimization","$28K/yr","Suboptimal routing increases AWS egress charges.","amber"),
            ("Hardware EoL planning","$220K total","Early refresh of 12 critical devices saves premium support.","amber"),
            ("Redundant WAN links","$18K/yr","2 backup circuits unused >99% of time.","red"),
        ]
        for item, savings, detail, color in opps:
            bar_color = {"green":"var(--accent-green)","amber":"var(--accent-amber)","red":"var(--accent-red)"}[color]
            st.markdown(f"""<div style="background:var(--bg-surface);border:1px solid var(--border-default);border-radius:10px;padding:12px;margin-bottom:8px">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:4px">
                <div style="font-size:13px;font-weight:600;color:var(--text-primary)">{item}</div>
                <div style="font-size:14px;font-weight:700;color:{bar_color};font-family:Fraunces,serif">{savings}</div>
              </div>
              <div style="font-size:12px;color:var(--text-secondary)">{detail}</div>
            </div>""", unsafe_allow_html=True)

    with col_f2:
        st.markdown("**📊 Spend Breakdown**")
        breakdown = [
            ("Hardware CapEx","$1.8M","43%"),("Software Licenses","$920K","22%"),
            ("MPLS/WAN Circuits","$680K","16%"),("Cloud Connectivity","$420K","10%"),
            ("Maintenance & Support","$280K","7%"),("Professional Services","$100K","2%"),
        ]
        for item, amount, pct in breakdown:
            st.markdown(f"""<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--border-subtle)">
              <span style="font-size:13px;color:var(--text-secondary)">{item}</span>
              <div style="text-align:right">
                <span style="font-size:13px;font-weight:700;color:var(--text-primary);margin-right:10px">{amount}</span>
                <span style="font-size:11px;font-family:JetBrains Mono,monospace;color:var(--text-tertiary)">{pct}</span>
              </div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**📈 Automation ROI**")
        roi_data = [
            ("Hours saved (automation)","4.2 hrs/week"),("Incidents auto-resolved","12 this month"),
            ("MTTR reduction","↓ 40% vs last year"),("Estimated cost saving","$8,400/month"),
        ]
        for label, val in roi_data:
            st.markdown(f'<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border-subtle)"><span style="color:var(--text-secondary);font-size:12px">{label}</span><span style="color:var(--accent-green);font-weight:700;font-size:12px">{val}</span></div>', unsafe_allow_html=True)

    st.markdown("---")
    if st.button("🧠 AI Cost Optimization Analysis", type="primary"):
        go("Analyze network cost structure and identify top 5 optimization opportunities: license consolidation, hardware refresh timing, WAN modernization, cloud cost reduction, automation ROI. Include 3-year TCO comparison.", "finops")


# ══════════════════════════════════════════════════════════
# FLOATING AI COPILOT (non-primary workspaces)
# ══════════════════════════════════════════════════════════
if ws not in ["troubleshoot", "learn", "design"]:
    st.markdown("---")
    with st.expander("💬 AI Copilot — Always available", expanded=False):
        if st.session_state.chat_msgs:
            for msg in st.session_state.chat_msgs[-4:]:
                render_chat_message(msg["role"], msg["content"], msg.get("meta"))

        ci, cb, ccl = st.columns([0.80, 0.12, 0.08])
        with ci:
            fi = st.text_input("", placeholder="Ask anything about your network…",
                               label_visibility="collapsed", key="float_inp")
        with cb:
            if st.button("Send", use_container_width=True, type="primary", key="float_send") and fi:
                go(fi, ws)
        with ccl:
            if st.button("🗑", use_container_width=True, key="float_clr"):
                st.session_state.chat_msgs = []; st.session_state.chat_hist = []; st.rerun()
