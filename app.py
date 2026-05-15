"""
NetBrain AI — Enterprise Autonomous Network Operations Platform
===============================================================
Every network issue is detected, analyzed, fixed, and verified automatically.
The full remediation pipeline is visible step-by-step in real time.
"""

# ── MUST BE FIRST ────────────────────────────────────────────────────────────
import streamlit as st

st.set_page_config(
    page_title="NetBrain AI — Autonomous NOC",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── IMPORTS ───────────────────────────────────────────────────────────────────
import os
import time
import logging
import random
from datetime import datetime
from typing import List, Dict, Any, Optional

import pandas as pd

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── OPTIONAL IMPORTS ──────────────────────────────────────────────────────────
OPENAI_AVAILABLE = False
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    pass

DATABASE_AVAILABLE = False
try:
    from database.database import seed_database, get_devices, get_incidents
    DATABASE_AVAILABLE = True
except Exception as e:
    logger.warning(f"Database import failed: {e}")

# ── WORKSPACES ────────────────────────────────────────────────────────────────
try:
    from config.workspaces import WORKSPACES
except Exception:
    WORKSPACES = [
        ("Net Ops",      "⚡",  "NOC Operations"),
        ("Workflows",    "🔄",  "Autonomous Workflows"),
        ("incident",     "🚨",  "Incident Room"),
        ("topology",     "🗺",  "Network Topology"),
        ("Observability","📡",  "Observability"),
        ("security",     "🔒",  "Security"),
        ("executive",    "📈",  "Executive"),
    ]

# ── SESSION STATE DEFAULTS ────────────────────────────────────────────────────
_DEFAULTS = {
    "workspace":               "Net Ops",
    "live_alerts":             [],
    "last_telemetry_hash":     None,
    "incident_timeline":       [],
    "ai_rca_steps":            [],
    "ai_rca_active":           False,
    "live_event_feed":         [],
    "last_anomaly_signatures": [],
    "recovery_timeline":       [],
    "remediation_workflow":    {},
    "remediation_actions":     [],
    "validation_commands":     [],
    "recovery_confidence":     0,
    "stabilization_status":    "idle",
    "last_poll_time":          0.0,
    "cycle_count":             0,
    "total_anomalies_seen":    0,
    "total_incidents_created": 0,
    "total_fixes_executed":    0,
    "selected_device":         None,
}
for k, v in _DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── DATABASE INIT ─────────────────────────────────────────────────────────────
if DATABASE_AVAILABLE:
    try:
        seed_database()
    except Exception as e:
        logger.warning(f"DB seed failed: {e}")

# ── AI CONFIG (must come before _get_monitor) ─────────────────────────────────
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME      = "anthropic/claude-3.5-sonnet"


def _resolve_api_key() -> str:
    try:
        return st.secrets.get("OPENROUTER_API_KEY", "")
    except Exception:
        return os.environ.get("OPENROUTER_API_KEY", "")


@st.cache_resource
def _get_ai_client():
    if not OPENAI_AVAILABLE:
        return None
    key = _resolve_api_key()
    if not key:
        return None
    try:
        return OpenAI(api_key=key, base_url=OPENROUTER_BASE)
    except Exception:
        return None


def call_ai(prompt: str) -> str:
    client = _get_ai_client()
    if not client:
        return ""
    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": (
                    "You are NetBrain AI — an expert autonomous network operations system. "
                    "Be concise, technical, and action-oriented. Focus on root cause and fix steps."
                )},
                {"role": "user", "content": prompt},
            ],
            max_tokens=600,
            temperature=0.1,
        )
        return resp.choices[0].message.content
    except Exception as e:
        logger.warning(f"AI call failed: {e}")
        return ""

# ── PINGPY / TUNNEL CONFIG ────────────────────────────────────────────────────

def _resolve_gns3_endpoint() -> tuple[str, int]:
    """
    Returns (host, port) for GNS3.
    Priority: GNS3_TUNNEL_URL env/secret → localhost:3080.
    GNS3_TUNNEL_URL can be a full URL like https://abc123.pinggy.io or host:port.
    """
    try:
        raw = st.secrets.get("GNS3_TUNNEL_URL", "")
    except Exception:
        raw = ""
    if not raw:
        raw = os.environ.get("GNS3_TUNNEL_URL", "")

    if raw:
        raw = raw.strip().rstrip("/")
        # Strip protocol
        for scheme in ("https://", "http://"):
            if raw.startswith(scheme):
                raw = raw[len(scheme):]
                break
        # host:port or just host
        if ":" in raw:
            host, port_str = raw.rsplit(":", 1)
            try:
                return host, int(port_str)
            except ValueError:
                return raw, 443
        return raw, 443  # pingpy tunnel uses 443 by default

    return "localhost", 3080


def _check_tunnel_and_reconnect() -> bool:
    """
    Returns True if GNS3 became newly reachable this call (tunnel just connected).
    Side-effect: updates gns3_engine when tunnel URL changes.
    """
    host, port = _resolve_gns3_endpoint()
    gns3 = getattr(orchestrator, "gns3", None)
    if gns3 is None:
        return False

    current_url = f"http://{host}:{port}/v2"
    if gns3.base_url != current_url:
        # Tunnel URL changed — reconfigure
        gns3.base_url = current_url
        gns3.available = False

    was_available = gns3.available
    if not gns3.available:
        gns3._check_connectivity()

    newly_connected = (not was_available) and gns3.available
    if newly_connected:
        gns3.refresh()
        logger.info(f"GNS3 tunnel connected: {current_url}")

    return newly_connected

# ── ORCHESTRATOR (singleton — survives reruns) ─────────────────────────────────
@st.cache_resource
def _get_orchestrator():
    from core.orchestration_engine import OperationsOrchestrator
    orc = OperationsOrchestrator()
    # Inject GNS3 engine with tunnel-aware endpoint
    try:
        from core.gns3_engine import GNS3Engine
        host, port = _resolve_gns3_endpoint()
        orc.gns3 = GNS3Engine(host=host, port=port)
    except Exception as e:
        logger.warning(f"GNS3 engine init failed: {e}")
        orc.gns3 = None
    return orc

@st.cache_resource
def _get_workflow_tracker():
    from core.workflow_tracker import WorkflowTracker
    return WorkflowTracker(max_history=100)

@st.cache_resource
def _get_network_fixer(_orchestrator):
    from core.network_fixer import NetworkFixer
    try:
        gns3 = getattr(_orchestrator, "gns3", None)
    except Exception:
        gns3 = None
    return NetworkFixer(gns3_engine=gns3)

@st.cache_resource
def _get_monitor(_orchestrator, _tracker, _fixer):
    from core.autonomous_monitor import AutonomousMonitor
    # call_ai is defined above — safe to reference here
    return AutonomousMonitor(
        orchestrator=_orchestrator,
        workflow_tracker=_tracker,
        network_fixer=_fixer,
        ai_call_fn=call_ai,
    )

orchestrator = _get_orchestrator()
tracker      = _get_workflow_tracker()
fixer        = _get_network_fixer(orchestrator)
monitor      = _get_monitor(orchestrator, tracker, fixer)

# ── ALERT HELPERS ─────────────────────────────────────────────────────────────

def add_live_alert(severity: str, message: str, anomaly: dict) -> None:
    alert = {
        "timestamp": datetime.utcnow().isoformat(),
        "severity":  severity,
        "message":   message,
        "anomaly":   anomaly,
        "id":        f"ALT-{datetime.utcnow().strftime('%H%M%S%f')}",
    }
    st.session_state["live_alerts"].insert(0, alert)
    st.session_state["live_alerts"] = st.session_state["live_alerts"][:15]


def _process_recovery(current_anomalies: list) -> None:
    current_sigs  = {f"{a.get('device')}:{a.get('type')}" for a in current_anomalies}
    previous_sigs = set(st.session_state.get("last_anomaly_signatures", []))
    cleared       = previous_sigs - current_sigs
    for sig in cleared:
        device, atype = sig.split(":", 1) if ":" in sig else (sig, "unknown")
        msg = f"Recovery confirmed: {atype.replace('_', ' ').title()} cleared on {device}"
        add_live_alert("recovery", msg, {"device": device, "type": atype})
        # Auto-resolve matching incidents
        for inc_id, inc in orchestrator.state.get_all_incidents().items():
            if device in inc.get("affected_devices", []) and inc["status"] in {"new", "investigating"}:
                orchestrator.state.update_incident(
                    inc_id, status="resolved",
                    note="Recovery confirmed by autonomous telemetry monitoring."
                )
    st.session_state["last_anomaly_signatures"] = list(current_sigs)

# ── MAIN POLL FUNCTION ─────────────────────────────────────────────────────────

def run_monitor_cycle() -> Dict[str, Any]:
    """
    Execute one autonomous monitoring cycle.
    This drives the entire detect → analyze → fix → verify pipeline.
    """
    try:
        result = monitor.run_cycle()
        anomalies = result.get("anomalies", [])

        st.session_state["cycle_count"]          = result.get("cycle", 0)
        st.session_state["total_anomalies_seen"] += result.get("anomalies_found", 0)

        # Generate live alerts for new high-severity anomalies
        for a in anomalies:
            if a.get("severity") in ("critical", "high"):
                add_live_alert(
                    a["severity"],
                    f"{a['type'].replace('_', ' ').title()} on {a.get('device', 'unknown')}",
                    a,
                )

        # Detect cleared anomalies → auto-resolve incidents
        _process_recovery(anomalies)

        # Update event feed
        st.session_state["live_event_feed"] = orchestrator.events.get_event_history(limit=25)

        # Update incident timeline
        event_history = orchestrator.events.get_event_history(limit=15)
        st.session_state["incident_timeline"] = [
            {
                "timestamp": ev.get("timestamp", ""),
                "event":     ev.get("type", "unknown").replace("_", " ").title(),
                "details":   ev.get("description", "")[:80],
                "severity":  ev.get("severity", "info"),
            }
            for ev in reversed(event_history)
        ]

        st.session_state["total_fixes_executed"] += result.get("workflows_started", 0)
        return result

    except Exception as e:
        logger.error(f"Monitor cycle failed: {e}", exc_info=True)
        return {"error": str(e), "anomalies_found": 0}

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Dark NOC theme */
.main { background: #0d1117; }
[data-testid="stSidebar"] { background: #161b22 !important; }

/* Metric cards */
[data-testid="metric-container"] {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px;
}

/* Alert banner */
.alert-critical {
    background: linear-gradient(135deg, #cc000022, #cc000011);
    border-left: 4px solid #cc0000;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 4px 0;
}

/* Step pipeline */
.step-box {
    border-radius: 8px;
    padding: 10px;
    text-align: center;
    transition: all 0.3s ease;
}

/* Scrollable terminal */
.terminal {
    background: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 12px;
    font-family: monospace;
    font-size: 12px;
    max-height: 300px;
    overflow-y: auto;
    color: #58a6ff;
}

/* Fix dataframe headers */
.dataframe th { background: #1c2128 !important; color: #cdd9e5 !important; }
</style>
""", unsafe_allow_html=True)

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🧠 NetBrain AI")
    st.caption("Autonomous Network Operations")
    st.divider()

    # Live health score
    op_summary = orchestrator.state.get_operational_summary()
    score = op_summary.get("operational_score", 100)
    score_color = "#cc0000" if score < 60 else "#cc8800" if score < 80 else "#00aa44"
    st.markdown(
        f"""<div style="text-align:center; padding:12px; background:#161b22;
                        border-radius:8px; border:1px solid #30363d; margin-bottom:8px;">
                <div style="font-size:36px; font-weight:700; color:{score_color};">{score:.0f}</div>
                <div style="font-size:12px; color:#8b949e;">HEALTH SCORE</div>
            </div>""",
        unsafe_allow_html=True,
    )

    # Quick stats
    incidents_open = len([i for i in orchestrator.state.get_all_incidents().values()
                          if i["status"] in {"new", "investigating"}])
    anomaly_count  = len(orchestrator.telemetry.detect_anomalies())
    active_wf      = len(tracker.get_active_runs())

    c1, c2 = st.columns(2)
    c1.metric("Incidents", incidents_open)
    c2.metric("Anomalies", anomaly_count)
    c1.metric("Workflows",  active_wf)
    c2.metric("Cycles",     st.session_state["cycle_count"])

    st.divider()

    # Navigation
    st.markdown("**WORKSPACES**")
    current_ws = st.session_state["workspace"]
    for ws_id, icon, label in WORKSPACES:
        btn_type = "primary" if ws_id == current_ws else "secondary"
        if st.button(f"{icon} {label}", key=f"ws_{ws_id}",
                     use_container_width=True, type=btn_type):
            st.session_state["workspace"] = ws_id
            st.rerun()

    st.divider()
    st.markdown("**SYSTEM STATUS**")
    mode = "🟢 LIVE" if orchestrator.telemetry.live_mode else "🔵 SIMULATION"
    ai_status = "🟢 AI ON" if _resolve_api_key() else "🟡 AI OFF"
    db_status = "🟢 DB ON" if DATABASE_AVAILABLE else "🟡 DB OFF"
    st.caption(f"{mode} | {ai_status} | {db_status}")
    poll_age = time.time() - st.session_state.get("last_poll_time", 0)
    st.caption(f"Last poll: {poll_age:.0f}s ago | Fixes: {st.session_state['total_fixes_executed']}")

    # ── Tunnel / GNS3 connection status ──────────────────────────────────────
    st.divider()
    st.markdown("**GNS3 / TUNNEL**")
    gns3_engine = getattr(orchestrator, "gns3", None)
    gns3_host, gns3_port = _resolve_gns3_endpoint()
    tunnel_url = os.environ.get("GNS3_TUNNEL_URL", "") or ""
    try:
        tunnel_url = st.secrets.get("GNS3_TUNNEL_URL", tunnel_url)
    except Exception:
        pass
    if gns3_engine and gns3_engine.available:
        st.success(f"🟢 Connected  v{gns3_engine.version}")
        st.caption(f"{gns3_host}:{gns3_port} · {len(gns3_engine.nodes)} nodes · {len(gns3_engine.links)} links")
    elif tunnel_url:
        st.warning("🟡 Tunnel configured — waiting for GNS3")
        st.caption(f"URL: {tunnel_url}")
    else:
        st.info("🔵 Simulation mode\nSet GNS3_TUNNEL_URL to connect live")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE CONTENT
# ══════════════════════════════════════════════════════════════════════════════

workspace = st.session_state["workspace"]
POLL_INTERVAL = 5  # seconds

# ── Check tunnel on every render — reconnect if GNS3 just became reachable ───
tunnel_just_connected = _check_tunnel_and_reconnect()
if tunnel_just_connected:
    # GNS3 tunnel just came up — switch telemetry to live mode and alert
    try:
        orchestrator.telemetry.live_mode = True
        gns3_nodes = list(getattr(orchestrator, "gns3", {}).nodes.keys()) if getattr(orchestrator, "gns3", None) else []
        add_live_alert(
            "recovery",
            f"GNS3 tunnel connected — pulling live data from {len(gns3_nodes)} device(s)",
            {"type": "tunnel_connected", "device": "gns3", "nodes": gns3_nodes},
        )
    except Exception:
        pass

# ── Poll if due ───────────────────────────────────────────────────────────────
now = time.time()
if now - st.session_state["last_poll_time"] >= POLL_INTERVAL:
    cycle_result = run_monitor_cycle()
    st.session_state["last_poll_time"] = now
else:
    cycle_result = {}

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: NOC OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════
if workspace == "Net Ops":
    st.markdown("## ⚡ Autonomous NOC Operations Center")
    st.caption("Real-time network monitoring with AI-powered autonomous remediation")

    # ── Live alert banner ────────────────────────────────────────────────────
    live_alerts = st.session_state["live_alerts"]
    critical_alerts = [a for a in live_alerts if a["severity"] in ("critical", "high")]
    if critical_alerts:
        st.markdown(
            f"""<div style="background:#1a0000; border:1px solid #cc0000; border-radius:8px;
                            padding:12px 16px; margin-bottom:12px;">
                    <b style="color:#ff4444;">🚨 CRITICAL ALERT — {len(critical_alerts)} active issue(s)</b>
                </div>""",
            unsafe_allow_html=True,
        )
        for a in critical_alerts[:3]:
            sev_icon = {"critical": "🔴", "high": "🟠"}.get(a["severity"], "⚪")
            st.markdown(
                f"&nbsp;&nbsp;{sev_icon} **{a['severity'].upper()}** — "
                f"{a['message']} — `{a['timestamp'][-8:]}`"
            )

    # ── KPI row ───────────────────────────────────────────────────────────────
    op_summary = orchestrator.state.get_operational_summary()
    inc_summary = op_summary.get("incidents", {})
    svc_summary = op_summary.get("services", {})
    score       = op_summary.get("operational_score", 100)
    open_inc    = inc_summary.get("new", 0) + inc_summary.get("investigating", 0)
    svc_down    = svc_summary.get("down", 0)
    mttr        = max(5, open_inc * 4)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Health Score",      f"{score:.0f}%",
              delta_color="inverse" if score < 80 else "off")
    k2.metric("Open Incidents",    open_inc,
              delta_color="inverse" if open_inc > 0 else "off")
    k3.metric("Active Anomalies",  len(st.session_state["live_event_feed"] and
              orchestrator.telemetry.detect_anomalies() or []))
    k4.metric("Services Impacted", svc_down,
              delta_color="inverse" if svc_down > 0 else "off")
    k5.metric("Est. MTTR",         f"{mttr}m")

    st.progress(int(max(0, min(100, score))))
    st.divider()

    # ── Live event feed ───────────────────────────────────────────────────────
    st.markdown("### 📡 Live Event Feed")
    event_feed = st.session_state.get("live_event_feed", [])
    if event_feed:
        feed_rows = [
            {
                "Time":     ev.get("timestamp", "")[-8:],
                "Event":    ev.get("type", "?").replace("_", " ").title(),
                "Severity": ev.get("severity", "info").upper(),
                "Detail":   ev.get("description", "")[:80],
            }
            for ev in event_feed[-20:]
        ]
        st.dataframe(pd.DataFrame(feed_rows), use_container_width=True, height=220)
    else:
        st.info("⏳ Monitoring active — events will appear here...")

    st.divider()

    # ── Device health matrix ──────────────────────────────────────────────────
    st.markdown("### 🖥 Device Health Matrix")
    all_metrics = orchestrator.state.get_all_device_metrics()
    if all_metrics:
        health_rows = []
        for hostname, m in all_metrics.items():
            h = orchestrator.telemetry.get_device_health_score(hostname)
            reachable = getattr(m, "reachable", True)
            link_st = "🟢 UP" if reachable and m.packet_loss_pct < 3 else \
                      "🟡 DEGRADED" if m.packet_loss_pct < 8 else "🔴 DOWN"
            health_rows.append({
                "Device":       hostname,
                "Health":       f"{h['score']:.0f}%",
                "Status":       h["status"].upper(),
                "CPU":          f"{m.cpu:.1f}%",
                "Memory":       f"{m.memory:.1f}%",
                "Latency":      f"{m.latency_ms:.1f}ms",
                "Pkt Loss":     f"{m.packet_loss_pct:.2f}%",
                "BGP↓":         str(m.bgp_sessions_down) if m.bgp_sessions_down else "—",
                "Link":         link_st,
            })
        st.dataframe(pd.DataFrame(health_rows), use_container_width=True, height=350)
    else:
        st.info("No telemetry yet — polling in progress...")

    # ── Active incidents summary ───────────────────────────────────────────────
    active_incidents = [i for i in orchestrator.state.get_all_incidents().values()
                        if i["status"] in {"new", "investigating"}]
    if active_incidents:
        st.divider()
        st.markdown("### 🚨 Active Incidents")
        for inc in active_incidents[:5]:
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(inc["severity"], "⚪")
            with st.expander(
                f"{sev_icon} **{inc['id']}** — {inc['title']} — {inc['status'].upper()}",
                expanded=inc["severity"] == "critical",
            ):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Severity:** {inc['severity'].upper()}")
                c1.markdown(f"**Devices:** {', '.join(inc.get('affected_devices', []))}")
                c2.markdown(f"**Services:** {', '.join(inc.get('affected_services', []) or ['None'])}")
                c2.markdown(f"**Created:** {inc.get('created_at', '')[-8:]}")
                if inc.get("timeline"):
                    st.markdown("**Timeline:**")
                    for note in inc["timeline"][-3:]:
                        st.markdown(f"  `{note['timestamp'][-8:]}` {note['note']}")

    # ── Auto-refresh ──────────────────────────────────────────────────────────
    remaining = max(0.0, POLL_INTERVAL - (time.time() - st.session_state["last_poll_time"]))
    st.caption(f"🔄 Next autonomous cycle in **{remaining:.0f}s** | Cycle #{st.session_state['cycle_count']}")
    if remaining > 0:
        time.sleep(remaining)
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: AUTONOMOUS WORKFLOWS
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "Workflows":
    st.markdown("## 🔄 Autonomous Remediation Workflows")
    st.caption(
        "Watch every step of the autonomous pipeline: "
        "Detection → Root Cause Analysis → Fix Execution → Verification → Closure"
    )

    try:
        from ui.workflow_viz import (
            render_workflow_run,
            render_workflow_history,
            render_no_active_workflow,
        )
        UI_VIZ_AVAILABLE = True
    except ImportError:
        UI_VIZ_AVAILABLE = False

    # ── Active workflow display ───────────────────────────────────────────────
    active_runs = tracker.get_active_runs()
    recent_runs = tracker.get_recent_runs(10)

    if active_runs:
        st.markdown("### 🔴 LIVE — Active Remediation")
        for run in active_runs:
            if UI_VIZ_AVAILABLE:
                render_workflow_run(run)
            else:
                _render_workflow_fallback(run)
            st.divider()
    else:
        latest = tracker.get_latest_run()
        if latest:
            st.markdown("### Last Completed Workflow")
            if UI_VIZ_AVAILABLE:
                render_workflow_run(latest)
            else:
                _render_workflow_fallback(latest)
        else:
            if UI_VIZ_AVAILABLE:
                render_no_active_workflow()
            else:
                st.success("🟢 Network operating normally. No active workflows.")
                st.info(
                    "When the autonomous monitor detects a high-severity anomaly, "
                    "it will start a remediation workflow visible here step by step."
                )

    # ── Workflow history ──────────────────────────────────────────────────────
    if recent_runs:
        st.divider()
        st.markdown("### 📋 Recent Workflow History")
        wf_rows = []
        for run in recent_runs:
            status_icon = {"running": "🔄", "completed": "✅", "failed": "❌"}.get(run.status, "⬜")
            sev_icon    = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(run.severity, "⚪")
            wf_rows.append({
                "Run ID":   run.run_id,
                "Device":   run.device,
                "Issue":    run.anomaly_type.replace("_", " ").title(),
                "Severity": f"{sev_icon} {run.severity.upper()}",
                "Status":   f"{status_icon} {run.status}",
                "Progress": f"{run.progress_pct}%",
                "Duration": f"{run.elapsed_seconds:.1f}s",
                "Summary":  run.summary[:60] if run.summary else "—",
            })
        st.dataframe(pd.DataFrame(wf_rows), use_container_width=True)

    # ── Stats ─────────────────────────────────────────────────────────────────
    st.divider()
    wf_summary = tracker.export_summary()
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total Runs",     wf_summary["total_runs"])
    s2.metric("Active",         wf_summary["active_runs"])
    s3.metric("Completed",      wf_summary["completed_runs"])
    s4.metric("Failed",         wf_summary["failed_runs"])

    # ── Auto refresh ──────────────────────────────────────────────────────────
    remaining = max(0.0, POLL_INTERVAL - (time.time() - st.session_state["last_poll_time"]))
    st.caption(f"🔄 Refreshing in {remaining:.0f}s")
    time.sleep(max(0.5, remaining))
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: INCIDENT ROOM
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "incident":
    st.markdown("## 🚨 Incident War Room")

    op_status    = orchestrator.get_operational_status()
    all_incidents = orchestrator.state.get_all_incidents()
    open_inc  = sum(1 for i in all_incidents.values() if i["status"] in {"new", "investigating"})
    resolved  = sum(1 for i in all_incidents.values() if i["status"] == "resolved")
    critical  = sum(1 for i in all_incidents.values() if i.get("severity") == "critical")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open Incidents",  open_inc)
    c2.metric("Critical",        critical)
    c3.metric("Resolved",        resolved)
    c4.metric("Total",           len(all_incidents))

    live_alerts = st.session_state.get("live_alerts", [])
    if live_alerts:
        st.subheader("🔴 Live Alerts")
        for a in live_alerts[:8]:
            sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡",
                        "low": "🟢", "recovery": "✅"}.get(a["severity"], "⚪")
            with st.expander(f"{sev_icon} {a['message']} — {a['timestamp'][-8:]}",
                             expanded=a["severity"] == "critical"):
                st.json(a.get("anomaly", {}))

    st.subheader("All Incidents")
    for inc_id, inc in sorted(all_incidents.items(), key=lambda x: x[1]["created_at"], reverse=True):
        sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(inc["severity"], "⚪")
        status_color = {"new": "🔴", "investigating": "🟠", "resolved": "🟢", "closed": "⚫"}.get(inc["status"], "⚪")
        with st.expander(
            f"{sev_icon} **{inc_id}** — {inc['title']} — {status_color} {inc['status'].upper()}",
            expanded=inc["severity"] == "critical" and inc["status"] in {"new", "investigating"},
        ):
            c1, c2 = st.columns(2)
            c1.markdown(f"**Severity:** {inc['severity'].upper()}")
            c1.markdown(f"**Status:** {inc['status']}")
            c1.markdown(f"**Created:** {inc.get('created_at', 'N/A')}")
            c2.markdown(f"**Devices:** {', '.join(inc.get('affected_devices', []) or ['—'])}")
            c2.markdown(f"**Services:** {', '.join(inc.get('affected_services', []) or ['—'])}")
            if inc.get("timeline"):
                st.markdown("**Timeline:**")
                for note in inc["timeline"][-5:]:
                    st.markdown(f"  `{note['timestamp'][-8:]}` {note['note']}")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: TOPOLOGY
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "topology":
    st.markdown("## 🗺 Network Topology")

    try:
        from ui.topology_view import (
            render_topology_kpis, render_device_health_table,
            render_site_summary, render_link_status, render_gns3_topology,
        )
        render_topology_kpis(orchestrator.state, orchestrator.simulator)
        st.divider()

        tab1, tab2, tab3, tab4 = st.tabs(["Device Health", "Sites", "Links", "GNS3"])
        with tab1:
            render_device_health_table(orchestrator.state, orchestrator.telemetry)
        with tab2:
            render_site_summary(orchestrator.simulator)
        with tab3:
            render_link_status(orchestrator.simulator)
        with tab4:
            gns3 = getattr(orchestrator, "gns3", None)
            render_gns3_topology(gns3)

    except ImportError:
        # Fallback if UI module not yet available
        op_summary = orchestrator.state.get_operational_summary()
        dev_summary  = op_summary.get("devices", {})
        link_summary = op_summary.get("links", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Devices",  dev_summary.get("total", 0))
        c2.metric("Healthy",        dev_summary.get("healthy", 0))
        c3.metric("Critical",       dev_summary.get("critical", 0))
        c4.metric("Links Active",   link_summary.get("active", 0))

        st.subheader("Device Status")
        rows = []
        for hostname, m in orchestrator.state.get_all_device_metrics().items():
            h = orchestrator.telemetry.get_device_health_score(hostname)
            rows.append({
                "Device":   hostname,
                "Health":   f"{h['score']:.0f}%",
                "Status":   h["status"].upper(),
                "CPU":      f"{m.cpu:.1f}%",
                "Memory":   f"{m.memory:.1f}%",
                "Latency":  f"{m.latency_ms:.1f}ms",
                "Reachable": "✅" if getattr(m, "reachable", True) else "❌",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True)

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: OBSERVABILITY
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "Observability":
    st.markdown("## 📡 Observability & Metrics")

    try:
        from ui.metrics_panel import (
            render_fleet_health_kpis, render_device_sparklines,
            render_telemetry_history_chart, render_anomaly_summary,
        )
        render_fleet_health_kpis(orchestrator.state, orchestrator.telemetry)
        st.divider()
        anomalies = orchestrator.telemetry.detect_anomalies()
        render_anomaly_summary(anomalies)
        st.divider()
        st.subheader("Device Metrics")
        render_device_sparklines(orchestrator.state)
        st.divider()

        # Per-device history chart
        devices = list(orchestrator.state.get_all_device_metrics().keys())
        if devices:
            selected = st.selectbox("Select device for history chart", devices)
            if selected:
                render_telemetry_history_chart(orchestrator.state, selected)

    except ImportError:
        # Fallback
        anomalies = orchestrator.telemetry.detect_anomalies()
        health    = orchestrator.telemetry.get_health_metrics()
        if health.get("status") != "no_data":
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Avg CPU",     f"{health['cpu']['average']:.1f}%")
            c2.metric("Avg Memory",  f"{health['memory']['average']:.1f}%")
            c3.metric("Avg Latency", f"{health['latency_ms']['average']:.1f}ms")
            c4.metric("Anomalies",   len(anomalies))
        st.subheader("Current Anomalies")
        if anomalies:
            for a in anomalies:
                st.warning(f"⚠️ **{a['type']}** on `{a.get('device','?')}` — {a.get('severity','?').upper()}")
        else:
            st.success("✅ No anomalies detected")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: SECURITY
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "security":
    st.markdown("## 🔒 Security Operations")

    op_summary = orchestrator.state.get_operational_summary()
    score  = op_summary.get("operational_score", 100)
    comp_s = min(100, max(60, int(score + 5)))
    threats = sum(1 for i in orchestrator.state.get_all_incidents().values()
                  if i.get("severity") in {"critical", "high"})
    drift   = len(orchestrator.state.compliance_status)

    c1, c2, c3 = st.columns(3)
    c1.metric("Active Threats",     threats)
    c2.metric("Compliance Score",   f"{comp_s}%")
    c3.metric("Config Drift Events",drift)

    st.subheader("Threat Intelligence")
    critical_inc = [i for i in orchestrator.state.get_all_incidents().values()
                    if i.get("severity") in {"critical", "high"} and
                    i["status"] in {"new", "investigating"}]
    if critical_inc:
        for inc in critical_inc:
            st.error(f"🚨 **{inc['title']}** — {inc['description'][:120]}")
    else:
        st.success("✅ No active security threats detected")

    st.subheader("Compliance Status")
    if orchestrator.state.compliance_status:
        for cid, comp in orchestrator.state.compliance_status.items():
            status = comp.get("status", "unknown")
            if status == "healthy":
                st.success(f"✅ {cid}: {comp.get('description', '')}")
            elif status == "degraded":
                st.warning(f"⚠️ {cid}: {comp.get('description', '')}")
            else:
                st.error(f"❌ {cid}: {comp.get('description', '')}")
    else:
        st.info("No compliance events recorded yet")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: EXECUTIVE
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "executive":
    st.markdown("## 📈 Executive Dashboard")

    op_status  = orchestrator.get_operational_status()
    op_summary = op_status["operational_summary"]
    score      = op_summary.get("operational_score", 100)
    inc_summary = op_summary.get("incidents", {})
    svc_summary = op_summary.get("services", {})
    open_inc    = inc_summary.get("new", 0) + inc_summary.get("investigating", 0)
    critical_in = sum(1 for i in orchestrator.state.get_all_incidents().values()
                      if i.get("severity") in {"critical", "high"})
    svc_down    = svc_summary.get("down", 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Network Health",   f"{score:.0f}%",    f"{svc_down} services impacted")
    c2.metric("Open Incidents",   open_inc,             f"{critical_in} critical")
    c3.metric("Auto-Remediated",  st.session_state["total_fixes_executed"])
    c4.metric("Risk Exposure",    f"{min(100, 100 - int(score))}%")

    st.progress(int(max(0, min(100, score))))

    st.subheader("Executive Insights")
    wf_total = tracker.export_summary()["total_runs"]
    wf_done  = tracker.export_summary()["completed_runs"]
    insights = [
        f"Network health score is **{score:.0f}%** with {open_inc} open incident(s).",
        f"The autonomous system has executed **{wf_total} remediation workflows** ({wf_done} completed).",
        f"**{st.session_state['total_anomalies_seen']} anomalies** detected and processed since session start.",
        f"**{svc_summary.get('total', 0)} services** tracked | {svc_down} currently impacted.",
    ]
    for insight in insights:
        st.info(f"📌 {insight}")

    if score < 70:
        st.error("🔴 **HIGH RISK** — Network health below 70%. Immediate NOC escalation recommended.")
    elif score < 85:
        st.warning("🟠 **MEDIUM RISK** — Maintain elevated monitoring posture.")
    else:
        st.success("🟢 **LOW RISK** — Network operating within normal parameters.")

    # AI operational summary
    try:
        ai_summary = orchestrator.generate_operational_ai_summary()
        st.subheader("AI Operational Brief")
        st.markdown(f"**Root Cause:** {ai_summary.get('root_cause', '—')}")
        st.markdown(f"**Executive Summary:** {ai_summary.get('executive_summary', '—')}")
        st.markdown(f"**Recommendation:** {ai_summary.get('recommendation', '—')}")
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# DEFAULT FALLBACK
# ══════════════════════════════════════════════════════════════════════════════
else:
    st.header("🚀 NetBrain AI — Autonomous Network Operations")
    st.info("Select a workspace from the sidebar to begin.")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**⚡ Net Ops**\nLive autonomous NOC with real-time monitoring")
    c2.markdown("**🔄 Workflows**\nStep-by-step autonomous remediation visualization")
    c3.markdown("**🗺 Topology**\nNetwork device health and link status")


# ── Workflow fallback renderer (when ui module not loaded) ────────────────────
def _render_workflow_fallback(run) -> None:
    """Simple fallback workflow display without the ui module."""
    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(run.severity, "⚪")
    status_badge = {"running": "🔄 RUNNING", "completed": "✅ DONE", "failed": "❌ FAILED"}.get(run.status, run.status)
    st.markdown(f"### {sev_icon} {run.anomaly_type.replace('_', ' ').upper()} — {status_badge}")
    st.caption(f"Device: **{run.device}** | Incident: `{run.incident_id}` | Run: `{run.run_id}`")
    st.progress(run.progress_pct / 100)

    cols = st.columns(len(run.steps))
    for step, col in zip(run.steps, cols):
        with col:
            st.markdown(
                f"**{step.icon}**\n\n"
                f"<small>{step.name}</small>",
                unsafe_allow_html=True,
            )

    running_steps = [s for s in run.steps if s.status.value == "running"]
    completed_steps = [s for s in run.steps if s.status.value == "completed"]
    detail = running_steps[0] if running_steps else (completed_steps[-1] if completed_steps else None)
    if detail and detail.output:
        with st.expander(f"▶ Step {detail.step_id}: {detail.name}", expanded=True):
            st.code("\n".join(detail.output[-20:]), language="bash")
