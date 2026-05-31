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
        ("Workflows",    "🤖",  "AI Action"),
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

# ── AI CONFIG (must be defined before _get_monitor references call_ai) ────────
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
MODEL_NAME      = "anthropic/claude-3.5-sonnet"

# Build version — bump this whenever code changes so we can confirm at a glance
# in the running app that the latest deploy is actually live.
BUILD_VERSION = "2026.05.31-rag-nlp-10"


def _load_secrets_into_env() -> None:
    """
    Streamlit Secrets are NOT automatically environment variables. The network
    fixer and log engine read os.environ, so we must copy the relevant secrets
    into os.environ at startup. Without this, settings like GNS3_DEVICE_TYPE are
    silently ignored and the fixer falls back to SSH (cisco_ios), producing the
    'SSH-2.0-paramiko' error against a Telnet console.
    Existing os.environ values (e.g. set via the Admin UI) take precedence.
    """
    keys = [
        "GNS3_TUNNEL_URL", "GNS3_ROUTER_HOST", "GNS3_ROUTER_PORT",
        "GNS3_DEVICE_TYPE", "GNS3_SSH_USER", "GNS3_SSH_PASS", "GNS3_SSH_SECRET",
        "GNS3_TELNET_USER", "GNS3_ROUTER_USER", "GNS3_ROUTER_PASS",
        "GNS3_LOG_GITHUB_URL", "GNS3_LOG_DEFAULT_DEVICE", "GNS3_LOG_GITHUB_TOKEN",
        "NETBRAIN_LIVE_ONLY", "OPENROUTER_API_KEY",
    ]
    for k in keys:
        try:
            val = st.secrets.get(k, None)
        except Exception:
            val = None
        # Only fill from secrets if not already set in the environment.
        if val is not None and str(val).strip() and not os.environ.get(k):
            os.environ[k] = str(val).strip()


# Copy secrets → env BEFORE any engine/monitor is constructed.
_load_secrets_into_env()


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

def _resolve_gns3_endpoint() -> tuple:
    """
    Returns (host, port) for GNS3.
    Priority: GNS3_TUNNEL_URL secret/env → localhost:3080.
    GNS3_TUNNEL_URL examples: abc123.pinggy.io:12345  or  https://abc123.pinggy.io
    """
    try:
        raw = st.secrets.get("GNS3_TUNNEL_URL", "")
    except Exception:
        raw = ""
    if not raw:
        raw = os.environ.get("GNS3_TUNNEL_URL", "")

    if raw:
        raw = raw.strip().rstrip("/")
        for scheme in ("https://", "http://"):
            if raw.startswith(scheme):
                raw = raw[len(scheme):]
                break
        if ":" in raw:
            host, port_str = raw.rsplit(":", 1)
            try:
                return host, int(port_str)
            except ValueError:
                return raw, 443
        return raw, 443

    return "localhost", 3080


def _check_tunnel_and_reconnect() -> bool:
    """Returns True if GNS3 became newly reachable this call."""
    host, port = _resolve_gns3_endpoint()
    gns3 = getattr(orchestrator, "gns3", None)
    if gns3 is None:
        return False

    current_url = f"http://{host}:{port}/v2"
    if gns3.base_url != current_url:
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

# ── WORKSPACES list (updated to include Admin) ───────────────────────────────
WORKSPACES = [
    ("dashboard", "🖥",  "Dashboard"),
    ("Workflows", "🤖",  "AI Action"),
    ("incident",  "🚨",  "Incidents"),
    ("topology",  "🗺",  "Topology"),
    ("Observability", "📡", "Observability"),
    ("security",  "🔒",  "Security"),
    ("executive", "📈",  "Executive"),
    ("admin",     "⚙️",  "Admin"),
]

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

/* Device health card */
.dev-card { border-radius:10px; padding:14px; margin:4px 0; }

/* Approval card */
.approval-card {
    background: linear-gradient(135deg, #1a1200, #0d0d00);
    border: 2px solid #cc8800;
    border-radius: 10px;
    padding: 16px 20px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)

# ── helper: render a single device health card ────────────────────────────────
def _device_card(hostname: str, m, health: dict) -> None:
    score  = health.get("score", 100)
    status = health.get("status", "healthy")
    reachable = getattr(m, "reachable", True)
    color  = {"critical": "#cc0000", "warning": "#cc8800", "healthy": "#00aa44"}.get(status, "#555")
    icon   = {"critical": "🔴", "warning": "🟡", "healthy": "🟢"}.get(status, "⚫")

    cpu_bar  = int(m.cpu)
    mem_bar  = int(m.memory)
    cpu_col  = "#cc0000" if m.cpu >= 90 else "#cc8800" if m.cpu >= 70 else "#00aa44"
    mem_col  = "#cc0000" if m.memory >= 90 else "#cc8800" if m.memory >= 70 else "#00aa44"

    st.markdown(f"""
    <div style="background:#161b22; border:1px solid {color}; border-left:4px solid {color};
                border-radius:10px; padding:14px; margin:4px 0;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
            <span style="font-weight:700; color:#cdd9e5; font-size:14px;">{icon} {hostname}</span>
            <span style="font-size:11px; color:{color}; font-weight:600;">{status.upper()}</span>
        </div>
        <div style="font-size:11px; color:#8b949e; margin-bottom:6px;">
            {'✅ Reachable' if reachable else '❌ Unreachable'} &nbsp;|&nbsp; Health: {score:.0f}%
        </div>
        <div style="font-size:11px; color:#8b949e; margin:2px 0;">CPU</div>
        <div style="background:#30363d; border-radius:3px; height:6px; margin-bottom:4px;">
            <div style="background:{cpu_col}; width:{min(cpu_bar,100)}%; height:6px; border-radius:3px;"></div>
        </div>
        <div style="font-size:11px; color:#8b949e; margin:2px 0;">Memory</div>
        <div style="background:#30363d; border-radius:3px; height:6px; margin-bottom:6px;">
            <div style="background:{mem_col}; width:{min(mem_bar,100)}%; height:6px; border-radius:3px;"></div>
        </div>
        <div style="font-size:11px; color:#8b949e;">
            CPU {m.cpu:.1f}% &nbsp;|&nbsp; Mem {m.memory:.1f}%
            &nbsp;|&nbsp; Lat {m.latency_ms:.0f}ms &nbsp;|&nbsp; Loss {m.packet_loss_pct:.2f}%
        </div>
    </div>""", unsafe_allow_html=True)


# ── helper: render one pending-approval card ──────────────────────────────────
def _render_approval_card(run_id: str, data: dict) -> None:
    run     = data["run"]
    anomaly = data["anomaly"]
    plan    = data.get("plan", [])
    rca     = data.get("rca", "Root cause analysis pending.")
    sev_icon = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(run.severity, "⚪")

    # Build a clear, specific headline from the actual anomaly.
    iface = anomaly.get("interface")
    a_desc = anomaly.get("description") or f"{run.anomaly_type.replace('_',' ')} on {run.device}"
    a_state = anomaly.get("state", "")
    headline_target = f"{run.device} · {iface}" if iface else run.device

    st.markdown(f"""
    <div class="approval-card">
        <div style="font-size:16px; font-weight:700; color:#cc8800;">
            {sev_icon} APPROVAL REQUIRED — {run.anomaly_type.replace('_',' ').upper()}
        </div>
        <div style="font-size:13px; color:#cdd9e5; margin-top:6px;">
            {a_desc}
        </div>
        <div style="font-size:12px; color:#8b949e; margin-top:4px;">
            Target: <b style="color:#cdd9e5;">{headline_target}</b> &nbsp;|&nbsp;
            State: <b style="color:#cc8800;">{a_state or 'n/a'}</b> &nbsp;|&nbsp;
            Incident: <b style="color:#cdd9e5;">{run.incident_id}</b>
        </div>
    </div>""", unsafe_allow_html=True)

    # What the AI will actually do, in plain CLI terms.
    ai_status = data.get("ai_status", "unavailable")
    ai_cmds = data.get("ai_commands")
    needs_manual = data.get("needs_manual", False)

    if needs_manual:
        reasons = "; ".join(data.get("ai_block_reasons", [])) or "AI could not produce safe commands"
        st.error(
            f"⚠️ **Manual handling required.** The AI was unavailable or proposed "
            f"unsafe commands, so no automated fix will run. Reason: {reasons}. "
            f"Approving will mark this for manual review (no commands sent to the router)."
        )
    elif ai_cmds and ai_cmds.get("fix"):
        st.markdown("**🤖 AI-generated commands (passed safety filter):**")
        st.code("configure terminal\n " + "\n ".join(ai_cmds.get("fix", [])), language="text")
    elif run.anomaly_type == "interface_down" and iface:
        st.markdown("**Action the AI will take (after approval):**")
        st.code(f"configure terminal\n interface {iface}\n no shutdown\nend", language="text")

    col_rca, col_plan = st.columns([3, 2])
    with col_rca:
        st.markdown("**AI Root Cause Analysis**")
        st.info(rca[:400])
    with col_plan:
        st.markdown("**Remediation Plan**")
        for i, step in enumerate(plan, 1):
            st.markdown(f"  {i}. {step}")

    col_approve, col_reject, col_skip = st.columns([1, 1, 3])
    with col_approve:
        if st.button(f"✅ APPROVE FIX", key=f"approve_{run_id}", type="primary", use_container_width=True):
            monitor.approved_run_ids.add(run_id)
            # Run a cycle immediately so the fix executes now, not on next refresh.
            try:
                cyc = run_monitor_cycle()
            except Exception as _e:
                cyc = {}
            # Report what actually happened (live vs simulated, success/fail).
            last_fix = getattr(monitor, "last_fix_result", None)
            if last_fix is None:
                st.success("Fix approved — executing on the next monitoring cycle...")
            elif last_fix.get("success") and last_fix.get("simulated"):
                st.warning(
                    "⚠️ Fix ran in SIMULATION mode (no live router connection). "
                    "The real router was NOT changed. Set GNS3_ROUTER_HOST / "
                    "GNS3_ROUTER_PORT / GNS3_DEVICE_TYPE in Secrets to apply live."
                )
            elif last_fix.get("success"):
                st.success(
                    f"✅ Fix applied LIVE on {last_fix.get('device','router')}: "
                    f"{', '.join(last_fix.get('commands', [])) or 'no shutdown'}"
                )
            else:
                st.error(f"❌ Fix attempt failed: {last_fix.get('error','unknown error')}")
            st.rerun()
    with col_reject:
        if st.button(f"❌ REJECT", key=f"reject_{run_id}", use_container_width=True):
            monitor.rejected_run_ids.add(run_id)
            st.warning("Fix rejected.")
            st.rerun()
    with col_skip:
        st.caption(f"Run: `{run_id}` · Elapsed: {run.elapsed_seconds:.0f}s")


# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🧠 NetBrain AI")
    st.caption("Autonomous NOC Platform")
    st.divider()

    # Health score ring
    op_summary = orchestrator.state.get_operational_summary()
    score = op_summary.get("operational_score", 100)
    score_color = "#cc0000" if score < 60 else "#cc8800" if score < 80 else "#00aa44"
    st.markdown(
        f"""<div style="text-align:center; padding:12px; background:#161b22;
                        border-radius:8px; border:2px solid {score_color}33; margin-bottom:8px;">
                <div style="font-size:38px; font-weight:700; color:{score_color};">{score:.0f}</div>
                <div style="font-size:11px; color:#8b949e; letter-spacing:1px;">HEALTH SCORE</div>
            </div>""",
        unsafe_allow_html=True,
    )

    # Quick stats
    incidents_open   = sum(1 for i in orchestrator.state.get_all_incidents().values()
                           if i["status"] in {"new", "investigating"})
    anomaly_count    = len(orchestrator.telemetry.detect_anomalies())
    active_wf        = len(tracker.get_active_runs())
    pending_approvals_count = len(getattr(monitor, "pending_approvals", {}))

    c1, c2 = st.columns(2)
    c1.metric("Incidents",  incidents_open)
    c2.metric("Anomalies",  anomaly_count)
    c1.metric("Workflows",  active_wf)
    c2.metric("Approvals",  pending_approvals_count)

    if pending_approvals_count:
        st.warning(f"⚠️ {pending_approvals_count} fix(es) awaiting approval")

    st.divider()

    # Navigation
    st.markdown("**NAVIGATION**")
    current_ws = st.session_state["workspace"]
    for ws_id, icon, label in WORKSPACES:
        badge = f" ({pending_approvals_count})" if ws_id == "Workflows" and pending_approvals_count else ""
        btn_type = "primary" if ws_id == current_ws else "secondary"
        if st.button(f"{icon} {label}{badge}", key=f"ws_{ws_id}",
                     use_container_width=True, type=btn_type):
            st.session_state["workspace"] = ws_id
            st.rerun()

    st.divider()
    st.markdown("**SYSTEM**")
    mode      = "🟢 LIVE" if orchestrator.telemetry.live_mode else "🔵 SIM"
    ai_status = "🟢 AI" if _resolve_api_key() else "🟡 AI"
    st.caption(f"{mode} | {ai_status}")
    poll_age = time.time() - st.session_state.get("last_poll_time", 0)
    st.caption(f"Cycle #{st.session_state['cycle_count']} · {poll_age:.0f}s ago")

    # ── Build / deploy diagnostic (confirms the running app has latest code) ──
    _dtype_now = os.environ.get("GNS3_DEVICE_TYPE", "(not set → SSH)")
    try:
        from core.autonomous_monitor import LIVE_ONLY as _LO
    except Exception:
        _LO = None
    _conn_method = "TELNET ✅" if str(_dtype_now).endswith("_telnet") else "SSH ⚠️"
    st.caption(f"🏷 Build: `{BUILD_VERSION}`")
    st.caption(f"🔧 Fix uses: **{_conn_method}** ({_dtype_now})")
    st.caption(f"📡 Live-only: {'ON ✅' if _LO else 'OFF ⚠️'}")

    # GNS3 / tunnel
    gns3_engine = getattr(orchestrator, "gns3", None)
    gns3_host, gns3_port = _resolve_gns3_endpoint()
    if gns3_engine and gns3_engine.available:
        st.success(f"🟢 GNS3 v{gns3_engine.version}\n{len(gns3_engine.nodes)} nodes")
    elif gns3_host != "localhost":
        st.warning("🟡 Tunnel — waiting GNS3")
    else:
        st.info("🔵 Simulation mode")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE CONTENT
# ══════════════════════════════════════════════════════════════════════════════

workspace     = st.session_state["workspace"]
POLL_INTERVAL = 5  # seconds

# ── Check tunnel + poll monitor ───────────────────────────────────────────────
tunnel_just_connected = _check_tunnel_and_reconnect()
if tunnel_just_connected:
    try:
        orchestrator.telemetry.live_mode = True
        gns3_nodes = list(orchestrator.gns3.nodes.keys()) if getattr(orchestrator, "gns3", None) else []
        add_live_alert("recovery",
            f"GNS3 tunnel connected — {len(gns3_nodes)} device(s) now live",
            {"type": "tunnel_connected", "device": "gns3"},
        )
    except Exception:
        pass

now = time.time()
if now - st.session_state["last_poll_time"] >= POLL_INTERVAL:
    cycle_result = run_monitor_cycle()
    st.session_state["last_poll_time"] = now
else:
    cycle_result = {}

# ── Workflow fallback renderer (no ui module needed) ──────────────────────────
def _render_workflow_fallback(run) -> None:
    sev_icon     = {"critical": "🔴", "high": "🟠", "medium": "🟡"}.get(run.severity, "⚪")
    status_badge = {"running": "🔄 RUNNING", "awaiting_approval": "⏳ AWAITING APPROVAL",
                    "completed": "✅ DONE", "failed": "❌ FAILED"}.get(run.status, run.status)
    st.markdown(f"### {sev_icon} {run.anomaly_type.replace('_',' ').upper()} — {status_badge}")
    st.caption(f"Device: **{run.device}** | Incident: `{run.incident_id}` | Run: `{run.run_id}`")
    if run.progress_pct:
        st.progress(run.progress_pct / 100)
    cols = st.columns(len(run.steps))
    for step, col in zip(run.steps, cols):
        with col:
            st.markdown(f"**{step.icon}**\n\n<small>{step.name}</small>", unsafe_allow_html=True)
    completed = [s for s in run.steps if s.status.value == "completed"]
    running   = [s for s in run.steps if s.status.value == "running"]
    detail    = running[0] if running else (completed[-1] if completed else None)
    if detail and detail.output:
        with st.expander(f"▶ Step {detail.step_id}: {detail.name}", expanded=True):
            st.code("\n".join(detail.output[-20:]), language="bash")


# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: DASHBOARD (main NOC view)
# ══════════════════════════════════════════════════════════════════════════════
if workspace == "dashboard":
    op_summary  = orchestrator.state.get_operational_summary()
    inc_summary = op_summary.get("incidents", {})
    svc_summary = op_summary.get("services", {})
    score       = op_summary.get("operational_score", 100)
    open_inc    = inc_summary.get("new", 0) + inc_summary.get("investigating", 0)
    svc_down    = svc_summary.get("down", 0)
    anomalies   = orchestrator.telemetry.detect_anomalies()

    # ── Top status ribbon ─────────────────────────────────────────────────────
    score_color = "#cc0000" if score < 60 else "#cc8800" if score < 80 else "#00aa44"
    pending_cnt = len(getattr(monitor, "pending_approvals", {}))
    st.markdown(f"""
    <div style="display:flex; gap:10px; margin-bottom:16px; flex-wrap:wrap;">
        <div style="flex:1; min-width:120px; background:#161b22; border:1px solid {score_color};
                    border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:28px; font-weight:700; color:{score_color};">{score:.0f}%</div>
            <div style="font-size:11px; color:#8b949e;">HEALTH SCORE</div>
        </div>
        <div style="flex:1; min-width:120px; background:#161b22; border:1px solid {'#cc0000' if open_inc else '#30363d'};
                    border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:28px; font-weight:700; color:{'#cc0000' if open_inc else '#cdd9e5'};">{open_inc}</div>
            <div style="font-size:11px; color:#8b949e;">OPEN INCIDENTS</div>
        </div>
        <div style="flex:1; min-width:120px; background:#161b22; border:1px solid {'#cc8800' if anomalies else '#30363d'};
                    border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:28px; font-weight:700; color:{'#cc8800' if anomalies else '#cdd9e5'};">{len(anomalies)}</div>
            <div style="font-size:11px; color:#8b949e;">ANOMALIES</div>
        </div>
        <div style="flex:1; min-width:120px; background:#161b22; border:1px solid {'#cc8800' if pending_cnt else '#30363d'};
                    border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:28px; font-weight:700; color:{'#cc8800' if pending_cnt else '#cdd9e5'};">{pending_cnt}</div>
            <div style="font-size:11px; color:#8b949e;">AWAITING APPROVAL</div>
        </div>
        <div style="flex:1; min-width:120px; background:#161b22; border:1px solid #30363d;
                    border-radius:8px; padding:12px; text-align:center;">
            <div style="font-size:28px; font-weight:700; color:#cdd9e5;">{st.session_state['total_fixes_executed']}</div>
            <div style="font-size:11px; color:#8b949e;">FIXES APPLIED</div>
        </div>
    </div>""", unsafe_allow_html=True)

    # ── Alert ticker ──────────────────────────────────────────────────────────
    live_alerts = st.session_state["live_alerts"]
    critical_alerts = [a for a in live_alerts if a["severity"] in ("critical", "high")]
    if critical_alerts:
        msgs = "  &nbsp;|&nbsp;  ".join(
            f"🔴 {a['message']} ({a['timestamp'][-8:]})" for a in critical_alerts[:4]
        )
        st.markdown(f"""<div style="background:#1a0000; border:1px solid #cc000066; border-radius:6px;
            padding:8px 14px; font-size:12px; color:#ff6666; margin-bottom:12px;
            white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">
            🚨 LIVE ALERTS &nbsp;|&nbsp; {msgs}</div>""", unsafe_allow_html=True)

    # ── Pending approvals banner ───────────────────────────────────────────────
    if pending_cnt:
        st.warning(f"⚠️ **{pending_cnt} fix(es) awaiting your approval.** Go to **Workflows** to approve or reject.")

    # ── Device health cards ───────────────────────────────────────────────────
    st.markdown("### Device Health")
    all_metrics = orchestrator.state.get_all_device_metrics()
    if all_metrics:
        items   = list(all_metrics.items())
        n_cols  = min(4, len(items))
        cols    = st.columns(n_cols)
        for idx, (hostname, m) in enumerate(items):
            h = orchestrator.telemetry.get_device_health_score(hostname)
            with cols[idx % n_cols]:
                _device_card(hostname, m, h)
    else:
        st.info("⏳ No telemetry yet — first poll in progress...")

    # ── Two-column: events + active incidents ─────────────────────────────────
    st.markdown("### Live Event Feed & Active Incidents")
    col_ev, col_inc = st.columns([3, 2])

    with col_ev:
        event_feed = st.session_state.get("live_event_feed", [])
        if event_feed:
            feed_rows = [
                {"Time": ev.get("timestamp","")[-8:],
                 "Event": ev.get("type","?").replace("_"," ").title(),
                 "Sev": ev.get("severity","info").upper(),
                 "Detail": ev.get("description","")[:70]}
                for ev in event_feed[-15:]
            ]
            st.dataframe(pd.DataFrame(feed_rows), use_container_width=True, height=280)
        else:
            st.info("Events will appear here once monitoring starts.")

    with col_inc:
        active_inc = [i for i in orchestrator.state.get_all_incidents().values()
                      if i["status"] in {"new", "investigating"}]
        if active_inc:
            for inc in active_inc[:5]:
                sev_icon = {"critical":"🔴","high":"🟠","medium":"🟡"}.get(inc["severity"],"⚪")
                with st.expander(f"{sev_icon} {inc['id']} — {inc['title'][:40]}",
                                 expanded=inc["severity"] == "critical"):
                    st.caption(f"Status: {inc['status']} | {inc.get('created_at','')[-8:]}")
                    st.caption(f"Devices: {', '.join(inc.get('affected_devices',[]) or ['—'])}")
                    if inc.get("timeline"):
                        st.markdown(f"  `{inc['timeline'][-1]['timestamp'][-8:]}` {inc['timeline'][-1]['note'][:60]}")
        else:
            st.success("✅ No active incidents")

    # ── Auto-refresh ──────────────────────────────────────────────────────────
    remaining = max(0.0, POLL_INTERVAL - (time.time() - st.session_state["last_poll_time"]))
    st.caption(f"🔄 Next refresh in {remaining:.0f}s | Cycle #{st.session_state['cycle_count']}")
    time.sleep(remaining)
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: WORKFLOWS + APPROVALS
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "Workflows":
    st.markdown("## 🤖 AI Action — Autonomous Remediation")
    st.caption("Detect → Analyze → Plan → **APPROVE** → Fix → Verify → Close")

    # ── Natural-language query box (ask about incidents/logs in plain English) ─
    with st.expander("💬 Ask about your network (natural language)", expanded=False):
        st.caption("e.g. \"why did R2's interface go down?\", \"how many interface_down "
                   "incidents this session?\", \"what was the last fix on R2?\"")
        nlq = st.text_input("Your question", key="nl_query",
                            placeholder="Ask about incidents, logs, or fixes...")
        if st.button("Ask", key="nl_ask") and nlq.strip():
            with st.spinner("Analyzing your network data..."):
                # Build a compact context from real incidents + recent log events.
                incidents = orchestrator.state.get_all_incidents()
                inc_lines = []
                for inc in list(incidents.values())[-15:]:
                    last_note = inc["timeline"][-1]["note"] if inc.get("timeline") else ""
                    inc_lines.append(
                        f"- [{inc.get('status')}] {inc.get('title','')} on "
                        f"{','.join(inc.get('affected_devices') or [])}: {last_note}"
                    )
                log_lines = []
                gh = getattr(monitor, "github_log", None)
                if gh:
                    for e in gh.recent_events[:20]:
                        log_lines.append(
                            f"- {e['ts']} {e['device']} {e['mnemonic']} "
                            f"{e.get('interface') or ''} {e.get('state') or ''}")
                context = ("Incidents:\n" + ("\n".join(inc_lines) or "none") +
                           "\n\nRecent log events:\n" + ("\n".join(log_lines) or "none"))
                prompt = (
                    "You are a network operations assistant. Answer the user's "
                    "question using ONLY the data below. Be concise and factual. "
                    "If the data doesn't contain the answer, say so.\n\n"
                    f"{context}\n\nQuestion: {nlq.strip()}\nAnswer:"
                )
                try:
                    answer = call_ai(prompt)
                except Exception as e:
                    answer = ""
                if answer:
                    st.markdown(answer)
                else:
                    st.warning("AI is unavailable (check OPENROUTER_API_KEY). "
                               "Showing raw data instead:")
                    st.code(context, language="text")

    # ── SECTION 1: Pending approvals (most important) ─────────────────────────
    pending = getattr(monitor, "pending_approvals", {})
    if pending:
        st.markdown(f"### ⏳ Awaiting Approval ({len(pending)})")
        st.markdown("Review the AI analysis and remediation plan, then approve or reject each fix.")
        for run_id, data in list(pending.items()):
            _render_approval_card(run_id, data)
            st.divider()
    else:
        st.success("✅ No fixes awaiting approval")

    # ── SECTION 2: Active (approved, running) workflows ───────────────────────
    try:
        from ui.workflow_viz import render_workflow_run, render_no_active_workflow
        UI_VIZ = True
    except ImportError:
        UI_VIZ = False

    active_runs = tracker.get_active_runs()
    if active_runs:
        st.markdown("### 🔴 LIVE — Executing Fix")
        for run in active_runs:
            render_workflow_run(run) if UI_VIZ else _render_workflow_fallback(run)
            st.divider()
    elif not pending:
        if UI_VIZ:
            render_no_active_workflow()
        else:
            st.info("No workflows running. Anomalies will be processed automatically every 5 seconds.")

    # ── SECTION 3: Workflow history ───────────────────────────────────────────
    recent_runs = tracker.get_recent_runs(15)
    if recent_runs:
        st.divider()
        st.markdown("### 📋 Workflow History")
        wf_rows = []
        for run in recent_runs:
            s_icon = {"running":"🔄","awaiting_approval":"⏳","completed":"✅","failed":"❌"}.get(run.status,"⬜")
            v_icon = {"critical":"🔴","high":"🟠","medium":"🟡"}.get(run.severity,"⚪")
            wf_rows.append({
                "Run ID":   run.run_id,
                "Device":   run.device,
                "Issue":    run.anomaly_type.replace("_"," ").title(),
                "Sev":      f"{v_icon} {run.severity.upper()}",
                "Status":   f"{s_icon} {run.status}",
                "Progress": f"{run.progress_pct}%",
                "Duration": f"{run.elapsed_seconds:.1f}s",
                "Summary":  (run.summary or "—")[:55],
            })
        st.dataframe(pd.DataFrame(wf_rows), use_container_width=True)

    st.divider()
    wf_s = tracker.export_summary()
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Total",     wf_s["total_runs"])
    s2.metric("Active",    wf_s["active_runs"])
    s3.metric("Pending",   len(pending))
    s4.metric("Completed", wf_s["completed_runs"])
    s5.metric("Failed",    wf_s["failed_runs"])

    remaining = max(0.0, POLL_INTERVAL - (time.time() - st.session_state["last_poll_time"]))
    st.caption(f"🔄 Refreshing in {remaining:.0f}s")
    time.sleep(max(0.5, remaining))
    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: INCIDENT ROOM
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "incident":
    st.markdown("## 🚨 Incident War Room")
    all_incidents = orchestrator.state.get_all_incidents()
    open_inc  = sum(1 for i in all_incidents.values() if i["status"] in {"new","investigating"})
    resolved  = sum(1 for i in all_incidents.values() if i["status"] == "resolved")
    critical  = sum(1 for i in all_incidents.values() if i.get("severity") == "critical")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Open",     open_inc,        delta_color="inverse" if open_inc else "off")
    c2.metric("Critical", critical,        delta_color="inverse" if critical else "off")
    c3.metric("Resolved", resolved)
    c4.metric("Total",    len(all_incidents))

    tab_live, tab_all = st.tabs(["Live Alerts", "All Incidents"])

    with tab_live:
        live_alerts = st.session_state.get("live_alerts", [])
        if live_alerts:
            for a in live_alerts[:10]:
                s_icon = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢","recovery":"✅"}.get(a["severity"],"⚪")
                with st.expander(f"{s_icon} {a['message']} — {a['timestamp'][-8:]}",
                                 expanded=a["severity"] == "critical"):
                    st.json(a.get("anomaly", {}))
        else:
            st.info("No alerts yet")

    with tab_all:
        filter_status = st.selectbox("Filter", ["All", "Open", "Resolved"], key="inc_filter")
        for inc_id, inc in sorted(all_incidents.items(), key=lambda x: x[1]["created_at"], reverse=True):
            if filter_status == "Open" and inc["status"] not in {"new","investigating"}:
                continue
            if filter_status == "Resolved" and inc["status"] != "resolved":
                continue
            s_icon = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}.get(inc["severity"],"⚪")
            st_icon = {"new":"🔴","investigating":"🟠","resolved":"🟢","closed":"⚫"}.get(inc["status"],"⚪")
            with st.expander(f"{s_icon} {inc_id} — {inc['title']} — {st_icon} {inc['status'].upper()}",
                             expanded=False):
                c1, c2 = st.columns(2)
                c1.markdown(f"**Severity:** {inc['severity'].upper()}")
                c1.markdown(f"**Devices:** {', '.join(inc.get('affected_devices',[]) or ['—'])}")
                c2.markdown(f"**Status:** {inc['status']}")
                c2.markdown(f"**Created:** {inc.get('created_at','N/A')[-19:]}")
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
        tab1, tab2, tab3, tab4 = st.tabs(["Device Health", "Sites", "Links", "GNS3 Live"])
        with tab1:
            render_device_health_table(orchestrator.state, orchestrator.telemetry)
        with tab2:
            render_site_summary(orchestrator.simulator)
        with tab3:
            render_link_status(orchestrator.simulator)
        with tab4:
            render_gns3_topology(getattr(orchestrator, "gns3", None))
    except ImportError:
        op_s = orchestrator.state.get_operational_summary()
        d_s  = op_s.get("devices", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Devices", d_s.get("total", 0))
        c2.metric("Healthy",       d_s.get("healthy", 0))
        c3.metric("Critical",      d_s.get("critical", 0))
        rows = []
        for hn, m in orchestrator.state.get_all_device_metrics().items():
            h = orchestrator.telemetry.get_device_health_score(hn)
            rows.append({"Device":hn,"Health":f"{h['score']:.0f}%","CPU":f"{m.cpu:.1f}%",
                         "Memory":f"{m.memory:.1f}%","Latency":f"{m.latency_ms:.1f}ms"})
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
        render_anomaly_summary(orchestrator.telemetry.detect_anomalies())
        st.divider()
        render_device_sparklines(orchestrator.state)
        st.divider()
        devices = list(orchestrator.state.get_all_device_metrics().keys())
        if devices:
            sel = st.selectbox("History chart for device", devices)
            if sel:
                render_telemetry_history_chart(orchestrator.state, sel)
    except ImportError:
        health = orchestrator.telemetry.get_health_metrics()
        if health.get("status") != "no_data":
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Avg CPU",     f"{health['cpu']['average']:.1f}%")
            c2.metric("Avg Memory",  f"{health['memory']['average']:.1f}%")
            c3.metric("Avg Latency", f"{health['latency_ms']['average']:.1f}ms")
            c4.metric("Anomalies",   len(orchestrator.telemetry.detect_anomalies()))

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: SECURITY
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "security":
    st.markdown("## 🔒 Security Operations")
    op_s    = orchestrator.state.get_operational_summary()
    score   = op_s.get("operational_score", 100)
    threats = sum(1 for i in orchestrator.state.get_all_incidents().values()
                  if i.get("severity") in {"critical","high"})
    c1, c2, c3 = st.columns(3)
    c1.metric("Active Threats",    threats)
    c2.metric("Compliance Score",  f"{min(100,max(60,int(score+5)))}%")
    c3.metric("Config Drift",      len(orchestrator.state.compliance_status))
    critical_inc = [i for i in orchestrator.state.get_all_incidents().values()
                    if i.get("severity") in {"critical","high"} and i["status"] in {"new","investigating"}]
    if critical_inc:
        for inc in critical_inc:
            st.error(f"🚨 **{inc['title']}** — {inc['description'][:120]}")
    else:
        st.success("✅ No active security threats")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: EXECUTIVE
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "executive":
    st.markdown("## 📈 Executive Dashboard")
    try:
        op_status  = orchestrator.get_operational_status()
        op_summary = op_status["operational_summary"]
    except Exception:
        op_summary = orchestrator.state.get_operational_summary()
    score      = op_summary.get("operational_score", 100)
    open_inc   = sum(1 for i in orchestrator.state.get_all_incidents().values()
                     if i["status"] in {"new","investigating"})
    wf_s = tracker.export_summary()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Network Health",   f"{score:.0f}%")
    c2.metric("Open Incidents",   open_inc)
    c3.metric("Auto-Remediated",  wf_s["completed_runs"])
    c4.metric("Risk Exposure",    f"{min(100,100-int(score))}%")
    st.progress(int(max(0, min(100, score))))

    for insight in [
        f"Health score is **{score:.0f}%** with **{open_inc}** open incident(s).",
        f"Autonomous system executed **{wf_s['total_runs']} workflows** ({wf_s['completed_runs']} completed).",
        f"**{st.session_state['total_anomalies_seen']} anomalies** processed since session start.",
    ]:
        st.info(f"📌 {insight}")

    if score < 70:
        st.error("🔴 HIGH RISK — Immediate NOC escalation recommended.")
    elif score < 85:
        st.warning("🟠 MEDIUM RISK — Maintain elevated monitoring posture.")
    else:
        st.success("🟢 LOW RISK — Network operating normally.")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: ADMIN
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "admin":
    st.markdown("## ⚙️ Administration")
    st.caption("Configure connection settings, credentials, thresholds, and system actions.")

    tab_conn, tab_creds, tab_thresh, tab_actions = st.tabs(
        ["Connection", "Credentials", "Thresholds", "System Actions"]
    )

    # ── Connection tab ────────────────────────────────────────────────────────
    with tab_conn:
        st.markdown("### GNS3 Tunnel / Pingpy Configuration")
        st.info(
            "Set these in **Streamlit Secrets** (Settings → Secrets) for persistence. "
            "Changes here apply for this session only."
        )
        current_gns3_url  = os.environ.get("GNS3_TUNNEL_URL", "")
        current_router_h  = os.environ.get("GNS3_ROUTER_HOST", "")
        current_router_p  = os.environ.get("GNS3_ROUTER_PORT", "22")

        with st.form("conn_form"):
            new_gns3_url = st.text_input(
                "GNS3 API Tunnel URL (for topology fetch)",
                value=current_gns3_url,
                placeholder="e.g. abc123.pinggy.io:3080",
                help="Used by GNS3Engine to fetch node/link topology via REST API",
            )
            new_router_h = st.text_input(
                "Router SSH Host (pingpy tunnel for CLI access)",
                value=current_router_h,
                placeholder="e.g. ugtft-203-145-57-1.run.pinggy-free.link",
            )
            new_router_p = st.text_input(
                "Router SSH Port",
                value=current_router_p,
                placeholder="37459",
            )
            if st.form_submit_button("Apply Connection Settings", type="primary"):
                os.environ["GNS3_TUNNEL_URL"]   = new_gns3_url.strip()
                os.environ["GNS3_ROUTER_HOST"]  = new_router_h.strip()
                os.environ["GNS3_ROUTER_PORT"]  = new_router_p.strip()
                st.success("Connection settings applied for this session.")
                st.caption("Add to Streamlit secrets to persist across restarts.")

        st.divider()
        st.markdown("**Current GNS3 Status**")
        g = getattr(orchestrator, "gns3", None)
        if g and g.available:
            st.success(f"🟢 Connected to GNS3 v{g.version} — {len(g.nodes)} nodes, {len(g.links)} links")
            if st.button("🔄 Refresh Topology"):
                g.refresh()
                st.success("Topology refreshed.")
        else:
            st.warning("GNS3 not connected. Set tunnel URL above and click Apply.")
            if st.button("Test Connection"):
                _check_tunnel_and_reconnect()
                g2 = getattr(orchestrator, "gns3", None)
                if g2 and g2.available:
                    st.success(f"Connected! v{g2.version}")
                else:
                    st.error("Connection failed. Check tunnel URL and GNS3 server.")

        st.markdown("**Secrets file template** (paste into Streamlit → Settings → Secrets):")
        st.code(f"""GNS3_TUNNEL_URL = "{new_gns3_url if 'new_gns3_url' in dir() else ''}"
GNS3_ROUTER_HOST = "{new_router_h if 'new_router_h' in dir() else ''}"
GNS3_ROUTER_PORT = "{new_router_p if 'new_router_p' in dir() else '22'}"
GNS3_SSH_USER = "admin"
GNS3_SSH_PASS = "admin"
OPENROUTER_API_KEY = "your-key-here"
""", language="toml")

        # ── Router Login Test (Pinggy tunnel) ─────────────────────────────────
        st.divider()
        st.markdown("### 🔐 Router Login Test")
        st.caption(
            "Checks that the platform can reach your router through the Pinggy tunnel "
            "and log in with admin credentials. **Read-only — nothing on the router is changed.**"
        )
        st.markdown(
            "**How to get these values:** on the GNS3 host run "
            "`ssh -p 443 -R0:<ROUTER_IP>:22 tcp@a.pinggy.io`. "
            "Pinggy prints a line like `tcp://abcd-1-2-3-4.run.pinggy-free.link:33893` — "
            "the part before the last colon is the **Host**, the number after is the **Port**."
        )
        with st.form("router_login_test_form"):
            c1, c2 = st.columns([3, 1])
            with c1:
                test_host = st.text_input(
                    "Tunnel Host",
                    value=os.environ.get("GNS3_ROUTER_HOST", ""),
                    placeholder="abcd-1-2-3-4.run.pinggy-free.link",
                )
            with c2:
                test_port = st.text_input(
                    "Tunnel Port",
                    value=os.environ.get("GNS3_ROUTER_PORT", ""),
                    placeholder="33893",
                )
            c3, c4, c5 = st.columns(3)
            with c3:
                test_user = st.text_input("Username", value=os.environ.get("GNS3_SSH_USER", "admin"))
            with c4:
                test_pass = st.text_input("Password", value=os.environ.get("GNS3_SSH_PASS", "admin"), type="password")
            with c5:
                test_dtype = st.selectbox(
                    "Login type",
                    options=["cisco_ios", "cisco_ios_telnet"],
                    index=0,
                    help="Use cisco_ios for SSH (default). Use cisco_ios_telnet only if the router has no SSH.",
                )
            run_test = st.form_submit_button("🔌 Test Router Login", type="primary")

        if run_test:
            with st.spinner("Connecting through the tunnel and attempting login..."):
                try:
                    from core.router_login_check import validate_router_login
                    res = validate_router_login(
                        host=test_host, port=test_port,
                        username=test_user, password=test_pass,
                        device_type=test_dtype,
                    )
                except Exception as e:
                    res = {"success": False, "steps": [], "summary": f"Internal error: {e}",
                           "interfaces": "", "prompt": "", "can_login": False, "can_config": False}

            # Headline verdict
            if res["success"]:
                st.success("🎉 " + res["summary"])
                st.balloons()
            elif res.get("can_login"):
                st.warning("⚠️ " + res["summary"])
            else:
                st.error("❌ " + res["summary"])

            # Step-by-step breakdown
            st.markdown("**Step-by-step:**")
            for s in res["steps"]:
                icon = "✅" if s["ok"] else "❌"
                st.markdown(f"{icon} **{s['name']}** — {s['detail']}")

            # Read-only interface output, if we got it
            if res.get("interfaces"):
                with st.expander("Router interface summary (read-only)"):
                    st.code(res["interfaces"], language="text")

            # Offer to save working settings
            if res["success"]:
                # Remember the working host/port/type so the real fixer uses them.
                os.environ["GNS3_ROUTER_HOST"] = test_host.strip()
                os.environ["GNS3_ROUTER_PORT"] = test_port.strip()
                os.environ["GNS3_DEVICE_TYPE"] = test_dtype
                st.info(
                    "These settings work and have been applied for this session. "
                    "To persist across restarts, add them to Streamlit Secrets "
                    f"(including `GNS3_DEVICE_TYPE = \"{test_dtype}\"`)."
                )

        # ── GitHub log source ─────────────────────────────────────────────────
        st.divider()
        st.markdown("### 📥 GitHub Log Source")
        st.caption(
            "Pipeline: GNS3 Router → local syslog server → GitHub repo → this platform. "
            "The autonomous monitor reads router syslog from the raw GitHub URL each cycle."
        )
        gh_engine = getattr(monitor, "github_log", None)
        default_gh_url = (
            gh_engine.raw_url if gh_engine else
            os.environ.get("GNS3_LOG_GITHUB_URL", "")
        )
        with st.form("gh_log_form"):
            new_gh_url = st.text_input(
                "Raw log URL (network_audit.log)",
                value=default_gh_url,
                help="raw.githubusercontent.com URL of the log file in your gns3-router-logs repo",
            )
            new_gh_dev = st.text_input(
                "Default device name (for log lines with no hostname)",
                value=os.environ.get("GNS3_LOG_DEFAULT_DEVICE", "R1"),
            )
            if st.form_submit_button("Apply Log Source", type="primary"):
                os.environ["GNS3_LOG_GITHUB_URL"] = new_gh_url.strip()
                os.environ["GNS3_LOG_DEFAULT_DEVICE"] = new_gh_dev.strip()
                if gh_engine:
                    gh_engine.raw_url = new_gh_url.strip()
                    gh_engine.default_device = new_gh_dev.strip() or "R1"
                st.success("Log source applied for this session.")

        if gh_engine:
            colp, colr = st.columns([1, 4])
            with colp:
                if st.button("🔄 Poll Now"):
                    # Run a FULL monitoring cycle (not just a feed refresh) so any
                    # down interface is analyzed and turned into an approval card.
                    gh_engine.poll()
                    try:
                        run_monitor_cycle()
                    except Exception as _e:
                        st.warning(f"Cycle ran with a note: {_e}")
                    _pend = len(getattr(monitor, "pending_approvals", {}))
                    if _pend:
                        st.success(f"Cycle complete — {_pend} fix(es) now awaiting approval. "
                                   "Open **Workflows** to approve.")
                    else:
                        st.info("Cycle complete — no fixable interfaces are currently down.")
                    st.rerun()
            status = gh_engine.status()
            if status["last_error"]:
                st.error(f"Last fetch error: {status['last_error']}")
            else:
                st.success(
                    f"🟢 {status['lines_parsed']} log lines parsed · "
                    f"{len(status['open_interfaces'])} interface(s) currently down"
                )
            if status["open_interfaces"]:
                st.warning("Down now: " + ", ".join(status["open_interfaces"]))

            st.markdown("**Recent log events** (newest first)")
            events = gh_engine.recent_events[:15]
            if events:
                import pandas as _pd
                df = _pd.DataFrame([
                    {
                        "Time": e["ts"],
                        "Device": e["device"],
                        "Event": e["mnemonic"],
                        "Interface": e["interface"] or "—",
                        "State": e["state"] or "—",
                        "Action?": "⚠️ fixable" if e["actionable"] else "",
                    }
                    for e in events
                ])
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.caption("No events parsed yet — click Poll Now.")

        st.markdown("**Add to Streamlit secrets:**")
        st.code(f'GNS3_LOG_GITHUB_URL = "{default_gh_url}"\n'
                f'GNS3_LOG_DEFAULT_DEVICE = "R1"\n'
                '# GNS3_LOG_GITHUB_TOKEN = "ghp_..."  # only for a PRIVATE log repo',
                language="toml")

    # ── Credentials tab ───────────────────────────────────────────────────────
    with tab_creds:
        st.markdown("### Device SSH Credentials")
        st.warning("⚠️ Credentials entered here are stored in session memory only. Use Streamlit Secrets for production.")

        with st.form("cred_form"):
            new_user = st.text_input("SSH Username", value=os.environ.get("GNS3_SSH_USER","admin"))
            new_pass = st.text_input("SSH Password", value=os.environ.get("GNS3_SSH_PASS","admin"), type="password")
            new_secret = st.text_input("Enable Secret (optional)", value="", type="password")
            if st.form_submit_button("Save Credentials", type="primary"):
                os.environ["GNS3_SSH_USER"] = new_user
                os.environ["GNS3_SSH_PASS"] = new_pass
                if new_secret:
                    os.environ["GNS3_SSH_SECRET"] = new_secret
                # Update the fixer
                fixer.default_username = new_user
                fixer.default_password = new_pass
                st.success("Credentials updated.")

        st.divider()
        st.markdown("### OpenRouter AI Key")
        with st.form("ai_form"):
            new_ai_key = st.text_input("OPENROUTER_API_KEY", value=os.environ.get("OPENROUTER_API_KEY",""),
                                       type="password")
            if st.form_submit_button("Save AI Key"):
                os.environ["OPENROUTER_API_KEY"] = new_ai_key
                st.success("AI key updated. Restart the app if the AI client was already cached.")

    # ── Thresholds tab ────────────────────────────────────────────────────────
    with tab_thresh:
        st.markdown("### Anomaly Detection Thresholds")
        st.info("These thresholds determine when the autonomous monitor triggers a workflow.")
        col1, col2 = st.columns(2)
        with col1:
            cpu_warn  = st.slider("CPU Warning %",    50, 95, 80)
            cpu_crit  = st.slider("CPU Critical %",   60, 99, 90)
            mem_warn  = st.slider("Memory Warning %", 50, 95, 80)
            mem_crit  = st.slider("Memory Critical %",60, 99, 90)
        with col2:
            lat_warn  = st.slider("Latency Warning ms",  20, 200, 80)
            lat_crit  = st.slider("Latency Critical ms", 50, 500, 100)
            loss_warn = st.slider("Packet Loss Warning %", 1, 10, 3)
            loss_crit = st.slider("Packet Loss Critical %",2, 20, 5)

        if st.button("Apply Thresholds", type="primary"):
            try:
                te = orchestrator.telemetry
                te.thresholds = {
                    "cpu_warning": cpu_warn, "cpu_critical": cpu_crit,
                    "memory_warning": mem_warn, "memory_critical": mem_crit,
                    "latency_warning": lat_warn, "latency_critical": lat_crit,
                    "packet_loss_warning": loss_warn, "packet_loss_critical": loss_crit,
                }
                st.success("Thresholds updated.")
            except Exception as e:
                st.warning(f"Could not update thresholds: {e}")

        st.divider()
        st.markdown("### Autonomous Mode")
        col_a, col_b = st.columns(2)
        with col_a:
            auto_fix = st.toggle("Auto-fix without approval", value=False,
                                 help="If ON: fixes execute immediately without waiting for approval")
        with col_b:
            poll_int = st.number_input("Poll interval (seconds)", 3, 60, POLL_INTERVAL)

        if st.button("Save Mode Settings"):
            if auto_fix:
                st.session_state["auto_fix_mode"] = True
                st.warning("Auto-fix mode enabled. Fixes will execute without approval.")
            else:
                st.session_state["auto_fix_mode"] = False
                st.success("Approval-required mode enabled.")

    # ── System Actions tab ────────────────────────────────────────────────────
    with tab_actions:
        st.markdown("### System Actions")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Clear All Incidents", use_container_width=True):
                orchestrator.state.incidents.clear()
                st.success("All incidents cleared.")
            if st.button("🔄 Reset Monitor", use_container_width=True):
                monitor._active_signatures.clear()
                monitor.pending_approvals.clear()
                monitor.approved_run_ids.clear()
                monitor.rejected_run_ids.clear()
                monitor.cycle_count = 0
                st.success("Monitor reset.")
            if st.button("📋 Clear Workflow History", use_container_width=True):
                tracker.runs.clear()
                st.success("Workflow history cleared.")

        with col2:
            if st.button("🔌 Test Router SSH Connection", use_container_width=True):
                host = os.environ.get("GNS3_ROUTER_HOST","")
                port = os.environ.get("GNS3_ROUTER_PORT","22")
                if not host:
                    st.error("Set GNS3_ROUTER_HOST in Connection tab first.")
                else:
                    with st.spinner(f"Connecting to {host}:{port}..."):
                        try:
                            import paramiko
                            paramiko.Transport._preferred_kex = (
                                "diffie-hellman-group14-sha1",
                                "diffie-hellman-group-exchange-sha1",
                                "diffie-hellman-group1-sha1",
                            )
                            paramiko.Transport._preferred_ciphers = (
                                "aes128-cbc","aes192-cbc","aes256-cbc",
                            )
                            from netmiko import ConnectHandler
                            _dtype = os.environ.get("GNS3_DEVICE_TYPE", "cisco_ios").strip() or "cisco_ios"
                            _cfg = dict(
                                device_type=_dtype,
                                host=host, port=int(port),
                                password=fixer.default_password,
                                timeout=20, auth_timeout=20, fast_cli=False,
                            )
                            if not _dtype.endswith("_telnet"):
                                _cfg["username"] = fixer.default_username
                            conn = ConnectHandler(**_cfg)
                            out = conn.send_command("show ip interface brief")
                            conn.disconnect()
                            st.success("Connection successful!")
                            st.code(out, language="text")
                        except Exception as e:
                            st.error(f"Connection failed: {e}")

            if st.button("📊 Show Current Anomalies", use_container_width=True):
                anomalies = orchestrator.telemetry.detect_anomalies()
                if anomalies:
                    for a in anomalies:
                        sev_icon = {"critical":"🔴","high":"🟠","medium":"🟡"}.get(a.get("severity",""),"⚪")
                        st.markdown(f"{sev_icon} **{a.get('type','?')}** on `{a.get('device','?')}` — {a.get('severity','?').upper()}")
                else:
                    st.success("No anomalies currently detected.")

        st.divider()
        st.markdown("### About")
        g = getattr(orchestrator, "gns3", None)
        info = {
            "Platform": "NetBrain AI — Autonomous NOC",
            "GNS3 Connected": str(g.available if g else False),
            "GNS3 Version": g.version if (g and g.available) else "N/A",
            "GNS3 Nodes": str(len(g.nodes)) if (g and g.available) else "0",
            "Telemetry Mode": "LIVE" if orchestrator.telemetry.live_mode else "SIMULATION",
            "Monitor Cycles": str(monitor.cycle_count),
            "Active Signatures": str(len(monitor._active_signatures)),
        }
        for k, v in info.items():
            st.markdown(f"**{k}:** {v}")

else:
    st.header("🧠 NetBrain AI — Autonomous Network Operations")
    st.info("Select a workspace from the sidebar.")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**🖥 Dashboard**\nLive NOC with device health cards and event feed")
    c2.markdown("**🔄 Workflows**\nApprove/reject fixes, watch 7-step pipeline")
    c3.markdown("**⚙️ Admin**\nConfigure tunnel, credentials, thresholds")
