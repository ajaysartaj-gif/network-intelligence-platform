"""
NetBrain AI — Enterprise Autonomous Network Operations Platform
===============================================================
Every network issue is detected, analyzed, fixed, and verified automatically.
The full remediation pipeline is visible step-by-step in real time.
"""

# ── MUST BE FIRST ────────────────────────────────────────────────────────────
import streamlit as st

# Load .env file BEFORE anything reads os.environ
# .env file lives in the repo root (same folder as app.py)
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)   # override=False: Streamlit Secrets take priority
except ImportError:
    pass  # python-dotenv not installed; rely on os.environ / Streamlit Secrets

st.set_page_config(
    page_title="NetBrain AI — Autonomous NOC",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── IMPORTS ───────────────────────────────────────────────────────────────────
import os
from core.ai_engine import ask_ai, get_api_key
from core.orchestration_engine import OperationsOrchestrator
from core.github_log_engine import GitHubLogEngine
from config.netmiko_devices import load_device_catalog
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

# ── LOCAL ROUTER ACCESS (primary access layer — Pinggy is fallback only) ──────
try:
    from Local_Router_Access import get_manager as _get_lra_manager, render_local_access_ui, LocalLinkGenerator
    LRA_AVAILABLE = True
except Exception as _lra_err:
    LRA_AVAILABLE = False
    logger.warning(f"Local_Router_Access not loaded: {_lra_err}")

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
        logger.warning(f"Database seed failed: {e}")

# GitHub logs engine and device catalog — cached to avoid re-init on every rerun
@st.cache_resource
def _get_gh_log_engine():
    return GitHubLogEngine()

@st.cache_resource
def _get_device_catalog():
    return load_device_catalog()

gh_log_engine  = _get_gh_log_engine()
device_catalog = _get_device_catalog()

# =========================================================
# AI CONFIG
# =========================================================

# ── AI CONFIG (must come before _get_monitor) ─────────────────────────────────
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
# Free model by default (no cost, no credit card). Override via the
# OPENROUTER_MODEL secret if you want a different one. ':free' models and the
# 'openrouter/free' auto-router are free on OpenRouter.
def _resolve_model() -> str:
    try:
        import streamlit as _st
        m = _st.secrets.get("OPENROUTER_MODEL", "")
    except Exception:
        m = ""
    if not m:
        m = os.environ.get("OPENROUTER_MODEL", "")
    # Default to claude-sonnet — reliable, matches config/ai.py
    return (m or "anthropic/claude-sonnet-4-5").strip()

MODEL_NAME = _resolve_model()

# Build version — bump this whenever code changes so we can confirm at a glance
# in the running app that the latest deploy is actually live.
BUILD_VERSION = "2026.05.31-tunnel-logs-20"


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
    # 1. Streamlit Secrets (works on Cloud + local .streamlit/secrets.toml)
    try:
        key = st.secrets.get("OPENROUTER_API_KEY", "")
        if key and key.strip():
            return key.strip()
    except Exception:
        pass
    # 2. os.environ (already set via _load_secrets_into_env or export)
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    # 3. Read .env file directly — covers local Mac / Codespace development
    try:
        from dotenv import load_dotenv
        _repo = os.path.dirname(os.path.abspath(__file__))
        _env  = os.path.join(_repo, ".env")
        if os.path.exists(_env):
            load_dotenv(_env, override=True)
            key = os.environ.get("OPENROUTER_API_KEY", "").strip()
            if key:
                return key
    except Exception:
        pass
    return ""


def _get_ai_client():
    # NOT cached — caching None when key is missing would permanently break
    # the chat even after the key is correctly set in secrets/.env
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
            max_tokens=1200,
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
# ── CSS (theme lives in ui/app_theme.py — presentation only) ──────────────────
from ui.app_theme import inject_theme
inject_theme()

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
        if st.button(f"✅ APPROVE FIX", key=f"approve_{run_id}", type="primary", width='stretch'):
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
        if st.button(f"❌ REJECT", key=f"reject_{run_id}", width='stretch'):
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

    # The tool talks to the router over a TELNET tunnel (not the GNS3 HTTP API),
    # so check the actual router host:port the fixer uses — that's the truth.
    def _router_tunnel_reachable() -> bool:
        host = os.environ.get("GNS3_ROUTER_HOST", "").strip()
        port = os.environ.get("GNS3_ROUTER_PORT", "").strip()
        if not host or not port:
            return False
        import socket
        try:
            with socket.create_connection((host, int(port)), timeout=4):
                return True
        except Exception:
            return False

    _rhost = os.environ.get("GNS3_ROUTER_HOST", "").strip()
    if _rhost:
        if _router_tunnel_reachable():
            st.success(f"🟢 Router tunnel UP\n{_rhost}:{os.environ.get('GNS3_ROUTER_PORT','')}")
        else:
            st.error("🔴 Router tunnel DOWN\nStart Pinggy & update Secrets")
    elif gns3_engine and gns3_engine.available:
        st.success(f"🟢 GNS3 v{gns3_engine.version}\n{len(gns3_engine.nodes)} nodes")
    else:
        st.info("🔵 No tunnel configured")

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

    # ── LOCAL ACCESS LINKS ────────────────────────────────────────────────────
    st.divider()
    st.markdown("**🔗 LOCAL ACCESS**")
    if LRA_AVAILABLE:
        try:
            _links = LocalLinkGenerator.generate_links()
            _lan   = _links.get("local_lan", "")
            _local = _links.get("localhost", "")
            if _lan:
                st.markdown(
                    f"<div style='background:#0c1a2e;border:1px solid #22d3ee;border-radius:6px;"
                    f"padding:.45rem .7rem;font-size:.78rem;color:#22d3ee;font-family:monospace;"
                    f"word-break:break-all;'>🌐 <a href='{_lan}' target='_blank' "
                    f"style='color:#22d3ee;text-decoration:none;'>{_lan}</a></div>",
                    unsafe_allow_html=True,
                )
            if _local:
                st.caption(f"🖥️ [localhost]({_local})  ·  [Open Local Router Access](?workspace=local_router)")
            pinggy_url = _links.get("pinggy_fallback", "")
            if pinggy_url:
                st.caption(f"☁️ Pinggy fallback: [link]({pinggy_url})")
            else:
                st.caption("☁️ Pinggy: _not configured_ (secondary)")
        except Exception:
            st.caption("Local links unavailable")
    else:
        st.caption("Local_Router_Access module not found")


# WORKSPACE CONTENT
# ══════════════════════════════════════════════════════════════════════════════

workspace     = st.session_state["workspace"]
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
    st.markdown("### GitHub Router Logs (gns3-router-logs)")
    col_sync, col_file = st.columns([1, 3])
    with col_sync:
        if st.button("Sync logs from GitHub", key="sync_github_logs"):
            sync_result = gh_log_engine.sync_repo()
            st.success(f"Sync result: {sync_result}")
            # refresh device catalog
            device_catalog = load_device_catalog()
            st.rerun()
    with col_file:
        logs = gh_log_engine.list_logs()
        if not logs:
            st.info("No logs found. Click 'Sync logs from GitHub' to fetch the repo.")
        else:
            selected = st.selectbox("Select log file", options=logs, index=0, key="selected_github_log")
            if selected:
                content = gh_log_engine.read_log(selected)
                st.code(content[:20000])
                if st.button("Analyze selected log", key="analyze_github_log"):
                    with st.spinner("Analyzing log with AI..."):
                        analysis = gh_log_engine.analyze_log(content)
                        st.text_area("AI Analysis", value=analysis, height=240)
                        suggested_cmds = gh_log_engine.propose_remediation_commands(analysis)
                        st.subheader("Suggested Diagnostic / Remediation Commands")
                        for cmd in suggested_cmds:
                            st.code(cmd)

                        # Remediation approval UI
                        if device_catalog:
                            device_names = [d.get('hostname') or d.get('host') for d in device_catalog]
                            chosen = st.selectbox("Target device for remediation", options=device_names, key="gh_log_target_device")
                            target_device = next((d for d in device_catalog if (d.get('hostname') or d.get('host')) == chosen), device_catalog[0])
                            dry = st.checkbox("Dry run (do not execute commands)", value=True, key="gh_log_dry_run")
                            if st.button("Approve & Execute Remediation", key="gh_log_execute"):
                                with st.spinner("Executing remediation..."):
                                    res = gh_log_engine.apply_remediation(target_device, suggested_cmds, dry_run=dry)
                                    if res.get('error'):
                                        st.error(f"Remediation failed: {res['error']}")
                                    else:
                                        st.success(f"Remediation executed: {res.get('executed')}")
                                        st.text_area("Execution Output", value='\n\n'.join(res.get('output', []))[:20000], height=300)
                        else:
                            st.info("No device catalog configured. Set NETBRAIN_DEVICE_* env vars or NETBRAIN_DEVICE_CATALOG.")

    st.divider()
    st.markdown("### Incident & Recovery Timeline")
    active_incidents = [
        i for i in orchestrator.state.get_all_incidents().values()
        if i["status"] in {"new", "investigating"}
    ]
    recovery_feed = st.session_state.get("incident_timeline", [])
    if active_incidents or recovery_feed:
        timeline_rows = []
        for event in st.session_state.get("incident_timeline", [])[:15]:
            timeline_rows.append({
                "time": event.get("timestamp", "")[-8:],
                "event": event.get("event", "unknown"),
                "severity": event.get("severity", "info").upper(),
                "details": event.get("details", "")[:80],
            })
        st.dataframe(pd.DataFrame(timeline_rows), use_container_width=True)

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

    tab_conn, tab_creds, tab_thresh, tab_actions, tab_aicfg, tab_devices = st.tabs(
        ["Connection", "Credentials", "Thresholds", "System Actions", "🧠 AI Config", "🖧 Devices"]
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
            getattr(gh_engine, "raw_url", "") if gh_engine else
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

        if gh_engine and callable(getattr(gh_engine, "status", None)):
            colp, colr = st.columns([1, 4])
            with colp:
                if st.button("🔄 Poll Now"):
                    # Run a FULL monitoring cycle (not just a feed refresh) so any
                    # down interface is analyzed and turned into an approval card.
                    if callable(getattr(gh_engine, "poll", None)):
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
            events = getattr(gh_engine, "recent_events", [])[:15]
            if events:
                import pandas as _pd
                df = _pd.DataFrame([
                    {
                        "Time": e.get("ts", ""),
                        "Device": e.get("device", ""),
                        "Event": e.get("mnemonic", ""),
                        "Interface": e.get("interface") or "—",
                        "State": e.get("state") or "—",
                        "Action?": "⚠️ fixable" if e.get("actionable") else "",
                    }
                    for e in events
                ])
                st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.caption("No events parsed yet — click Poll Now.")
        else:
            st.warning("GitHub log engine is unavailable or incomplete. Check app logs for init errors.")

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

        st.caption(f"Current model: `{MODEL_NAME}`  ·  set `OPENROUTER_MODEL` in Secrets to change it.")
        if st.button("🔌 Test AI Connection"):
            with st.spinner("Calling OpenRouter..."):
                diag = diagnose_ai()
            if diag["ok"]:
                st.success(f"✅ AI is working. {diag['detail']}")
                st.caption(f"Model: `{diag.get('model')}` · Key: `{diag.get('key')}`")
            else:
                st.error(f"❌ AI failed at stage: {diag['stage']}")
                st.code(diag["detail"], language="text")
                if diag["stage"] == "request":
                    st.caption("Common causes: invalid/expired key, rate-limited, or the model "
                               f"isn't available. Current model: `{MODEL_NAME}`. Free options: "
                               "`deepseek/deepseek-chat-v3-0324:free`, `openrouter/free`.")

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
            if st.button("🗑️ Clear All Incidents", width='stretch'):
                orchestrator.state.incidents.clear()
                st.success("All incidents cleared.")
            if st.button("🔄 Reset Monitor", width='stretch'):
                monitor._active_signatures.clear()
                monitor.pending_approvals.clear()
                monitor.approved_run_ids.clear()
                monitor.rejected_run_ids.clear()
                monitor.cycle_count = 0
                st.success("Monitor reset.")
            if st.button("📋 Clear Workflow History", width='stretch'):
                tracker.runs.clear()
                st.success("Workflow history cleared.")

        with col2:
            if st.button("🔌 Test Router SSH Connection", width='stretch'):
                host = os.environ.get("GNS3_ROUTER_HOST","")
                port = os.environ.get("GNS3_ROUTER_PORT","22")
                if not host:
                    st.error("Set GNS3_ROUTER_HOST in Connection tab first.")
                else:
                    with st.spinner(f"Connecting to {host}:{port}..."):
                        try:
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

            if st.button("📊 Show Current Anomalies", width='stretch'):
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

    # ── AI Config tab (natural-language → router config, preview + approve) ────
    with tab_aicfg:
        st.markdown("### 🧠 Natural-Language Configuration")
        st.caption(
            "Describe what you want in plain English. The AI proposes Cisco IOS "
            "commands, a safety filter blocks anything that could lock out or damage "
            "the device, you preview the exact commands, then approve to apply to the router."
        )
        st.warning(
            "Advanced feature. Commands run on the **live router** only after you click "
            "Apply. Lockout/destructive commands (VTY ACLs, removing IPs, reload, "
            "credential changes, etc.) are always blocked — no exceptions."
        )

        target_dev = st.text_input(
            "Target device", value="R2",
            help="Hostname as seen in logs. Connection uses the same tunnel settings as remediation.",
        )
        nl_request = st.text_area(
            "What do you want to configure?",
            placeholder="e.g. 'add description Uplink-to-core on GigabitEthernet1/0' or "
                        "'enable OSPF process 1 and advertise 10.0.0.0/24 in area 0'",
            height=80,
        )

        if st.button("🔍 Generate & Preview (no changes yet)", type="primary"):
            if not nl_request.strip():
                st.error("Please describe what you want to configure.")
            else:
                with st.spinner("Generating configuration and running safety checks..."):
                    try:
                        from core.ai_config import generate_config
                        facts = ""
                        try:
                            facts = monitor._device_facts(target_dev.strip())
                        except Exception:
                            pass
                        res = generate_config(nl_request.strip(), target_dev.strip(),
                                              call_ai, facts)
                    except Exception as e:
                        res = {"status": "unavailable", "reasons": [str(e)],
                               "commands": [], "summary": "", "blocked": []}
                st.session_state["aicfg_result"] = res
                st.session_state["aicfg_device"] = target_dev.strip()

        res = st.session_state.get("aicfg_result")
        if res:
            status = res.get("status")
            if status == "ok":
                mode = res.get("mode", "config")
                risk = res.get("risk", "unknown")
                risk_icon = {"low": "🟢", "medium": "🟡", "high": "🟠"}.get(risk, "⚪")

                # Plain prose answer (AI answered a question rather than returning commands)
                if res.get("plain_answer"):
                    st.info("💬 AI answered your question:")
                    st.markdown(res["plain_answer"])
                    st.caption(
                        "Tip: For router commands use requests like "
                        "'show ip interface brief' or 'add description Uplink to Gi1/0'"
                    )

                elif mode == "diagnostic":
                    st.info(f"🔍 Diagnostic query — read-only. {res.get('summary','')}")
                    st.markdown("**Commands:**")
                    st.code("\n".join(res.get("commands", [])), language="text")
                    if st.button("▶ Run diagnostic on router", type="primary", key="aicfg_diag"):
                        with st.spinner(f"Querying {st.session_state.get('aicfg_device')}..."):
                            try:
                                cmds = [c for c in res.get("commands", [])
                                        if c.lower() not in ("configure terminal", "conf t", "end", "exit")]
                                override = {"diagnostic": cmds, "fix": [], "verify": []}
                                anomaly = {"device": st.session_state.get("aicfg_device"),
                                           "type": "manual_diagnostic", "interface": ""}
                                device_cfg = monitor._get_device_config(st.session_state.get("aicfg_device"))
                                logs = []
                                fr = fixer.fix(anomaly, device_config=device_cfg,
                                               step_logger=lambda m: logs.append(m),
                                               command_override=override)
                            except Exception as e:
                                fr, logs = None, [f"Error: {e}"]
                            # Detect simulation FIRST — don't show fake output as real.
                            if fr and getattr(fr, "simulated", False):
                                st.warning(
                                    "⚠️ No live router connection — the tunnel is down "
                                    "(sidebar shows 'waiting GNS3'). The output below would "
                                    "be simulated/fake, so it's not shown. Start your Pinggy "
                                    "tunnel and make sure GNS3_ROUTER_HOST/PORT in Secrets "
                                    "match it, then try again."
                                )
                            elif fr and getattr(fr, "outputs", None):
                                # Collect the REAL router output.
                                pairs = list(zip(getattr(fr, "commands_executed", []), fr.outputs))
                                raw_block = "\n\n".join(
                                    f"$ {c}\n{o}" for c, o in pairs if o)

                                # AI interpretation — explain what the output means.
                                st.markdown("### 🤖 AI Analysis")
                                with st.spinner("Analyzing the router output..."):
                                    interp_prompt = (
                                        "You are a senior Cisco network engineer. The operator "
                                        f"asked: \"{nl_request.strip()}\".\n\n"
                                        "Here is the ACTUAL output from the router:\n\n"
                                        f"{raw_block}\n\n"
                                        "Answer the operator's question directly and concisely in "
                                        "plain English. State clearly whether things are OK or not, "
                                        "what the key findings are, and any concern or next step. "
                                        "Do not just repeat the raw output — interpret it."
                                    )
                                    try:
                                        answer = call_ai(interp_prompt)
                                    except Exception:
                                        answer = ""
                                if answer:
                                    st.markdown(answer)
                                else:
                                    st.info("AI interpretation unavailable — showing raw output below.")

                                with st.expander("📄 Raw router output"):
                                    for c, o in pairs:
                                        st.markdown(f"`{c}`")
                                        st.code(o or "(no output)", language="text")
                            else:
                                st.error("No output returned. Check tunnel/console.")
                                st.code("\n".join(logs), language="text")
                            st.session_state.pop("aicfg_result", None)
                else:
                    st.success(f"✅ Safe configuration generated. Risk: {risk_icon} {risk}")
                    st.markdown(f"**What this does:** {res.get('summary','(no summary)')}")
                    st.markdown("**Commands to be applied (preview):**")
                    st.code("\n".join(res.get("commands", [])), language="text")
                    st.info("Review carefully. Click Apply only if this is exactly what you intend.")
                    if st.button("⚡ Apply to Router", type="primary", key="aicfg_apply"):
                        with st.spinner(f"Applying configuration to {st.session_state.get('aicfg_device')}..."):
                            try:
                                cmds = res.get("commands", [])
                                inner = [c for c in cmds if c.lower() not in
                                         ("configure terminal", "conf t", "end", "exit")]
                                override = {"diagnostic": [], "fix": inner + ["end"], "verify": []}
                                anomaly = {"device": st.session_state.get("aicfg_device"),
                                           "type": "manual_config", "interface": ""}
                                device_cfg = monitor._get_device_config(st.session_state.get("aicfg_device"))
                                logs = []
                                fr = fixer.fix(anomaly, device_config=device_cfg,
                                               step_logger=lambda m: logs.append(m),
                                               command_override=override)
                            except Exception as e:
                                fr = None
                                logs = [f"Error: {e}"]
                            if fr and getattr(fr, "success", False) and not getattr(fr, "simulated", True):
                                st.success(f"✅ Applied LIVE to {st.session_state.get('aicfg_device')}.")
                                st.code("\n".join(logs), language="text")
                            elif fr and getattr(fr, "simulated", False):
                                st.warning("⚠️ Ran in SIMULATION (no live tunnel). Router not changed. "
                                           "Set GNS3_ROUTER_HOST/PORT/DEVICE_TYPE in Secrets.")
                            else:
                                st.error("❌ Apply failed.")
                                st.code("\n".join(logs), language="text")
                            st.session_state.pop("aicfg_result", None)
            elif status == "unsafe":
                st.error("❌ Blocked for safety — this request would run lockout/destructive commands.")
                st.markdown("**Blocked commands:**")
                st.code("\n".join(res.get("blocked", [])), language="text")
                st.caption("Per policy, these are never applied. Rephrase to avoid changing "
                           "management access, credentials, routing processes, or device state.")
            elif status == "empty":
                st.warning("The AI did not produce safe commands for this request.")
                for r in res.get("reasons", []):
                    st.caption(f"• {r}")
            else:
                st.error("AI unavailable. " + "; ".join(res.get("reasons", [])))
                st.caption("Check that OPENROUTER_API_KEY is set in Secrets.")

    # ══════════════════════════════════════════════════════════════════════════
    # TAB: DEVICES — Auto-discovery + AI Network Troubleshooting
    # ══════════════════════════════════════════════════════════════════════════
    with tab_devices:
        # ── CSS ───────────────────────────────────────────────────────────────
        st.markdown("""
        <style>
        .dd-card {
            background: linear-gradient(135deg, #0c1622 0%, #0f2132 100%);
            border: 1px solid #1e3a52;
            border-radius: 12px;
            padding: 1rem 1.2rem;
            margin-bottom: .75rem;
            position: relative;
        }
        .dd-card-pending  { border-left: 4px solid #f59e0b; }
        .dd-card-approved { border-left: 4px solid #10b981; }
        .dd-card-rejected { border-left: 4px solid #ef4444; }
        .dd-card-trouble  { border-left: 4px solid #6366f1; }
        .dd-badge {
            display: inline-block; border-radius: 20px;
            padding: 2px 10px; font-size: .72rem; font-weight: 600;
        }
        .dd-badge-pending  { background:#78350f; color:#fde68a; }
        .dd-badge-approved { background:#064e3b; color:#6ee7b7; }
        .dd-badge-rejected { background:#7f1d1d; color:#fca5a5; }
        .dd-badge-online   { background:#052e16; color:#4ade80; }
        .dd-ip { font-family: monospace; color: #67e8f9; font-size: .9rem; }
        .dd-hostname { color: #f1f5f9; font-weight: 600; font-size: 1rem; }
        .dd-meta { color: #94a3b8; font-size: .78rem; }
        .dd-pulse {
            display: inline-block; width: 10px; height: 10px;
            background: #22c55e; border-radius: 50%;
            box-shadow: 0 0 0 0 rgba(34,197,94,.4);
            animation: pulse-ring 1.5s infinite;
        }
        @keyframes pulse-ring {
            0%   { box-shadow: 0 0 0 0 rgba(34,197,94,.4); }
            70%  { box-shadow: 0 0 0 8px rgba(34,197,94,0); }
            100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
        }
        .dd-section-title {
            font-size: 1.05rem; font-weight: 700; color: #e2e8f0;
            border-bottom: 1px solid #1e3a52; padding-bottom: .4rem;
            margin-bottom: 1rem;
        }
        .ai-ts-step-ok   { color: #4ade80; }
        .ai-ts-step-fail { color: #f87171; }
        .ai-ts-step-info { color: #93c5fd; }
        .health-critical { color:#ef4444; font-weight:700; }
        .health-degraded { color:#f59e0b; font-weight:700; }
        .health-healthy  { color:#22c55e; font-weight:700; }
        </style>
        """, unsafe_allow_html=True)

        # ── Init discovery engine ─────────────────────────────────────────────
        try:
            from core.device_discovery import get_discovery_engine, get_log_store
            # Anchor engine in session_state so it survives Streamlit reruns
            # within the same browser session. Module-level singleton + JSON
            # file handle full-process restarts.
            if "disc_engine" not in st.session_state:
                st.session_state["disc_engine"] = get_discovery_engine()
            disc = st.session_state["disc_engine"]
            log_store = get_log_store()
            DISC_OK = True
        except Exception as _de:
            DISC_OK = False
            st.error(f"Device discovery engine failed to load: {_de}")

        if DISC_OK:
            st.markdown("## 🖧 Device Management")
            st.caption(
                "Devices that ping from your Mac/Linux terminal are automatically detected "
                "and queued below for approval. Once approved they join your network inventory "
                "and become available for AI troubleshooting."
            )

            # ── AI ASSISTANT — search-style input box ─────────────────────────
            st.markdown("""
            <style>
            .ai-assistant-container {
                position: relative;
                margin: 0.8rem 0 1.2rem 0;
            }
            .ai-assistant-label {
                display: flex; align-items: center; gap: .5rem;
                color: #475569; font-size: .78rem; font-weight: 500;
                margin-bottom: .3rem; letter-spacing: .04em;
                text-transform: uppercase;
            }
            /* Override Streamlit text_input to look like a search bar */
            div[data-testid="stTextInput"][id^="ai_assistant"] > div > div > input {
                background: #0a1628 !important;
                border: 1px solid #1e3a52 !important;
                border-radius: 30px !important;
                padding: .7rem 1.2rem .7rem 3rem !important;
                color: #94a3b8 !important;
                font-size: .95rem !important;
                box-shadow: 0 4px 24px rgba(0,0,0,.4), 0 0 0 1px rgba(34,211,238,.06) !important;
                transition: all .2s ease;
            }
            div[data-testid="stTextInput"][id^="ai_assistant"] > div > div > input:focus {
                border-color: #22d3ee !important;
                box-shadow: 0 4px 32px rgba(0,0,0,.5), 0 0 0 2px rgba(34,211,238,.2) !important;
                color: #e2e8f0 !important;
            }
            .ai-response-box {
                background: linear-gradient(135deg, #0a1628 0%, #0f2132 100%);
                border: 1px solid #1e3a52;
                border-left: 3px solid #22d3ee;
                border-radius: 10px;
                padding: 1rem 1.2rem;
                margin: .5rem 0 1rem 0;
                color: #cbd5e1;
                font-size: .92rem;
                line-height: 1.6;
                box-shadow: 0 4px 20px rgba(0,0,0,.3);
            }
            .ai-response-header {
                color: #22d3ee; font-size: .78rem; font-weight: 600;
                text-transform: uppercase; letter-spacing: .05em;
                margin-bottom: .5rem; display: flex; align-items: center; gap: .4rem;
            }
            </style>
            """, unsafe_allow_html=True)

            # Robot icon overlay using a label trick
            _aic1, _aic2 = st.columns([20, 1])
            with _aic1:
                st.markdown(
                    "<div class='ai-assistant-label'>🤖 &nbsp;AI Assistant</div>",
                    unsafe_allow_html=True
                )
                _ai_q = st.text_input(
                    label="ai_assistant_input",
                    label_visibility="collapsed",
                    placeholder="✦ AI Assistant  —  ask about your network, devices, or configs...",
                    key="devices_ai_input",
                )

            # Handle submission — Enter key submits automatically via Streamlit
            if _ai_q and _ai_q != st.session_state.get("devices_ai_last_q"):
                st.session_state["devices_ai_last_q"] = _ai_q
                # Build context from approved devices
                try:
                    _d_ctx = ""
                    if DISC_OK:
                        _devs = disc.get_approved()
                        if _devs:
                            _d_ctx = "Approved devices: " + ", ".join(
                                f"{d.hostname or d.ip} ({d.ip}, {d.device_type})"
                                for d in _devs
                            ) + "\n\n"
                except Exception:
                    _d_ctx = ""
                with st.spinner(""):
                    _ai_ans = call_ai(
                        "You are NetBrain AI — a senior network engineer. "
                        "Be concise, technical, and use bullet points for lists.\n\n"
                        + _d_ctx
                        + f"Question: {_ai_q}"
                    ) or "AI unavailable — check OPENROUTER_API_KEY."
                st.session_state["devices_ai_last_ans"] = _ai_ans

            # Show answer
            if st.session_state.get("devices_ai_last_ans") and st.session_state.get("devices_ai_last_q"):
                _q_display = st.session_state["devices_ai_last_q"]
                _a_display = st.session_state["devices_ai_last_ans"]
                st.markdown(
                    f"<div class='ai-response-box'>"
                    f"<div class='ai-response-header'>🤖 AI Assistant &nbsp;·&nbsp; "
                    f"<span style='color:#475569;font-weight:400;text-transform:none;font-size:.82rem'>"
                    f"{_q_display}</span></div>"
                    f"{_a_display}"
                    f"</div>",
                    unsafe_allow_html=True
                )

            st.divider()

            # ── Top action bar ────────────────────────────────────────────────
            col_scan, col_ping, col_refresh = st.columns([2, 2, 1])
            with col_scan:
                subnet_prefix = st.text_input(
                    "Scan subnet (first 3 octets)",
                    value="192.168.0", key="dd_subnet",
                    placeholder="192.168.1",
                )
                if st.button("🔍 Scan Subnet", width='stretch', key="dd_scan"):
                    disc.scan_subnet(subnet_prefix)
                    st.toast(f"Scanning {subnet_prefix}.1–254 in background… check back in ~30s")

            with col_ping:
                manual_ip = st.text_input(
                    "Or ping a specific IP",
                    key="dd_manual_ip", placeholder="10.0.0.1"
                )
                if st.button("📡 Ping & Discover", width='stretch', key="dd_ping"):
                    if manual_ip:
                        with st.spinner(f"Pinging {manual_ip}…"):
                            result = disc.ping_and_discover(manual_ip.strip())
                        if result:
                            st.success(f"✅ {manual_ip} is reachable — added to pending queue")
                        else:
                            st.error(f"❌ {manual_ip} did not respond")
                    else:
                        st.warning("Enter an IP address first.")

            with col_refresh:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🔄 Refresh", width='stretch', key="dd_refresh"):
                    st.rerun()

            st.divider()

            # ════════════════════════════════════════════════════════════════
            # SECTION 1 — PENDING DEVICES (auto-discovered, awaiting approval)
            # ════════════════════════════════════════════════════════════════
            pending = disc.get_pending()
            pending_count = len(pending)

            _pulse_html = "<span class='dd-pulse'></span>" if pending_count else ""
            st.markdown(
                f"<div class='dd-section-title'>"
                f"⚠️ Pending Approval {_pulse_html}"
                f"&nbsp;({pending_count})</div>",
                unsafe_allow_html=True
            )

            if not pending:
                st.info(
                    "No new devices detected yet.\n\n"
                    "**To trigger auto-discovery:** ping any GNS3 router from your Mac terminal:\n"
                    "```\nping 192.168.0.1\n```\n"
                    "It will appear here within ~10 seconds."
                )
            else:
                for dev in pending:
                    ports_str = ", ".join(str(p) for p in dev.open_ports) or "none detected"
                    _display_name = dev.hostname if dev.hostname else "Resolving name..."
                    _name_style = "color:#f1f5f9" if dev.hostname else "color:#94a3b8;font-style:italic"
                    with st.container():
                        st.markdown(f"""
                        <div class='dd-card dd-card-pending'>
                          <span class='dd-hostname' style='{_name_style}'>{_display_name}</span>
                          &nbsp;&nbsp;<span class='dd-ip'>{dev.ip}</span>
                          &nbsp;&nbsp;<span class='dd-badge dd-badge-pending'>⏳ PENDING</span>
                          <br><span class='dd-meta'>
                            Type: {dev.device_type} &nbsp;·&nbsp;
                            Source: {dev.source} &nbsp;·&nbsp;
                            Open ports: {ports_str} &nbsp;·&nbsp;
                            First seen: {dev.first_seen}
                          </span>
                        </div>
                        """, unsafe_allow_html=True)

                        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])
                        with btn_col1:
                            if st.button(f"✅ Approve", key=f"approve_{dev.ip}",
                                         use_container_width=True, type="primary"):
                                disc.approve_device(dev.ip, approved_by="admin")
                                st.success(f"✅ {dev.ip} approved and added to inventory")
                                st.rerun()
                        with btn_col2:
                            if st.button(f"❌ Reject", key=f"reject_{dev.ip}",
                                         use_container_width=True):
                                disc.reject_device(dev.ip)
                                st.rerun()
                        with btn_col3:
                            override_type = st.selectbox(
                                "Override device type",
                                ["cisco_ios", "cisco_iosxe", "cisco_nxos",
                                 "juniper_junos", "arista_eos", "linux", "cisco_ios_telnet"],
                                key=f"dtype_{dev.ip}",
                                index=["cisco_ios","cisco_iosxe","cisco_nxos",
                                       "juniper_junos","arista_eos","linux",
                                       "cisco_ios_telnet"].index(dev.device_type)
                                       if dev.device_type in ["cisco_ios","cisco_iosxe","cisco_nxos",
                                                               "juniper_junos","arista_eos","linux",
                                                               "cisco_ios_telnet"] else 0,
                            )
                            dev.device_type = override_type

            st.divider()

            # ════════════════════════════════════════════════════════════════
            # SECTION 2 — APPROVED INVENTORY
            # ════════════════════════════════════════════════════════════════
            approved = disc.get_approved()
            st.markdown(
                f"<div class='dd-section-title'>✅ Approved Inventory ({len(approved)})</div>",
                unsafe_allow_html=True
            )

            if not approved:
                st.caption("No devices approved yet. Approve devices from the Pending section above.")
            else:
                for dev in approved:
                    session = disc.get_session(dev.ip)
                    sess_status = session.status if session else None
                    _live_name = (session.device_hostname
                                  if session and session.device_hostname != dev.ip
                                  else dev.hostname) or dev.ip

                    # ── Health badge ──────────────────────────────────────────
                    _health = "—"
                    _health_cls = "health-healthy"
                    _health_icon = "⚪"
                    if session and session.ai_diagnosis:
                        for _ln in session.ai_diagnosis.splitlines():
                            if _ln.startswith("HEALTH:"):
                                _health = _ln.replace("HEALTH:", "").strip()
                        _health_icon = {"CRITICAL":"🔴","DEGRADED":"🟠","HEALTHY":"🟢"}.get(_health.upper(),"⚪")
                        _health_cls  = {"CRITICAL":"health-critical","DEGRADED":"health-degraded","HEALTHY":"health-healthy"}.get(_health.upper(),"health-healthy")

                    _card_cls = "dd-card-trouble" if sess_status == "running" else "dd-card-approved"

                    st.markdown(f"""
                    <div class='dd-card {_card_cls}'>
                      <span class='dd-hostname'>{_live_name}</span>
                      &nbsp;&nbsp;<span class='dd-ip'>{dev.ip}</span>
                      &nbsp;&nbsp;<span class='dd-badge dd-badge-approved'>✅ APPROVED</span>
                      &nbsp;&nbsp;<span class='dd-meta'>{_health_icon} Health: <span class='{_health_cls}'>{_health}</span>
                      &nbsp;·&nbsp; Status: {sess_status or "idle"}
                      &nbsp;·&nbsp; Steps: {len(session.steps) if session else 0}</span>
                      <br><span class='dd-meta'>
                        Type: {dev.device_type} &nbsp;·&nbsp;
                        Ports: {", ".join(str(p) for p in dev.open_ports) or "—"} &nbsp;·&nbsp;
                        Added: {dev.first_seen}
                      </span>
                    </div>
                    """, unsafe_allow_html=True)

                    # ── Action bar: 4 small buttons + AI Assistant NLP bar ────
                    st.markdown("""
                    <style>
                    /* Shrink all buttons inside .dev-action-row to be compact */
                    .dev-action-row div[data-testid="stButton"] > button {
                        padding: 4px 8px !important;
                        font-size: 10.5px !important;
                        min-height: 0 !important;
                        height: 34px !important;
                        white-space: nowrap !important;
                        border-radius: 6px !important;
                    }
                    /* AI Assistant bar styling */
                    .dev-action-row div[data-testid="stTextInput"] > div > div > input {
                        background: #1a2030 !important;
                        border: 1px solid #1D9E7566 !important;
                        border-radius: 8px !important;
                        color: #e0e6f0 !important;
                        font-size: 12.5px !important;
                        height: 34px !important;
                        padding: 4px 12px 4px 12px !important;
                    }
                    .dev-action-row div[data-testid="stTextInput"] > div > div > input:focus {
                        border-color: #1D9E75 !important;
                        box-shadow: 0 0 0 2px #1D9E7522 !important;
                    }
                    .dev-action-row div[data-testid="stTextInput"] > div > div > input::placeholder {
                        color: #4a5570 !important;
                    }
                    /* Remove default Streamlit label margin above input */
                    .dev-action-row div[data-testid="stTextInput"] > label {
                        display: none !important;
                    }
                    </style>
                    <div class="dev-action-row">
                    """, unsafe_allow_html=True)

                    _login_running = (
                        sess_status == "running"
                        and st.session_state.get(f"login_mode_{dev.ip}")
                    )
                    _ts_running = (
                        sess_status == "running"
                        and not st.session_state.get(f"login_mode_{dev.ip}")
                    )
                    _panel_open = st.session_state.get(f"ts_expanded_{dev.ip}", False)
                    _steps_n    = len(session.steps) if session else 0

                    # 4 small buttons + AI bar in a single row (ratio: 1:1:1:1:4)
                    _b1, _b2, _b3, _b4, _bai = st.columns([1, 1, 1, 1.4, 4], gap="small")

                    # Button 1 — Disapprove
                    with _b1:
                        if st.button("🔴 Disapprove", key=f"dis_{dev.ip}",
                                     use_container_width=True,
                                     help="Move back to Pending"):
                            disc.disapprove_device(dev.ip)
                            st.session_state.pop(f"ts_expanded_{dev.ip}", None)
                            st.session_state.pop(f"login_expanded_{dev.ip}", None)
                            st.rerun()

                    # Button 2 — Login
                    with _b2:
                        if st.button(
                            "⏳ Login…" if _login_running else "🔐 Login",
                            key=f"login_{dev.ip}",
                            disabled=_login_running,
                            use_container_width=True,
                            help="SSH into device",
                        ):
                            _creds = {
                                "username":      os.environ.get("GNS3_SSH_USER", "admin"),
                                "password":      os.environ.get("GNS3_SSH_PASS", "admin"),
                                "enable_secret": os.environ.get("GNS3_SSH_SECRET", ""),
                            }
                            st.session_state[f"login_mode_{dev.ip}"] = True
                            st.session_state[f"ts_expanded_{dev.ip}"] = True
                            st.session_state.pop(f"poll_count_{dev.ip}", None)
                            disc.start_login_session(dev.ip, _creds)
                            st.rerun()

                    # Button 3 — AI Diagnose
                    with _b3:
                        if st.button(
                            "⏳ Running…" if _ts_running else "🤖 AI Diagnose",
                            key=f"ai_ts_{dev.ip}",
                            disabled=_ts_running,
                            type="primary",
                            use_container_width=True,
                            help="Full diagnostics + AI fix plan",
                        ):
                            _creds = {
                                "username":      os.environ.get("GNS3_SSH_USER", "admin"),
                                "password":      os.environ.get("GNS3_SSH_PASS", "admin"),
                                "enable_secret": os.environ.get("GNS3_SSH_SECRET", ""),
                            }
                            st.session_state[f"login_mode_{dev.ip}"] = False
                            st.session_state[f"ts_expanded_{dev.ip}"] = True
                            st.session_state.pop(f"poll_count_{dev.ip}", None)
                            disc.start_ai_troubleshoot(dev.ip, call_ai, _creds, approved=False)
                            st.rerun()

                    # Button 4 — Show / Hide Progress
                    with _b4:
                        _panel_lbl = f"{'🔼 Hide' if _panel_open else '🔽 Show'} ({_steps_n})"
                        if st.button(_panel_lbl, key=f"toggle_{dev.ip}",
                                     use_container_width=True):
                            st.session_state[f"ts_expanded_{dev.ip}"] = not _panel_open
                            st.rerun()

                    # AI Assistant NLP bar — 5th option (wider)
                    with _bai:
                        _ai_nlp_q = st.text_input(
                            label=f"ai_nlp_{dev.ip}",
                            label_visibility="collapsed",
                            placeholder="🤖  AI Assistant — ask about config, logs, BGP, traps, debug...",
                            key=f"ai_nlp_input_{dev.ip}",
                        )

                    st.markdown("</div>", unsafe_allow_html=True)

                    # ── Handle AI Assistant NLP submission ────────────────────
                    _nlp_last_key = f"ai_nlp_last_{dev.ip}"
                    if _ai_nlp_q and _ai_nlp_q != st.session_state.get(_nlp_last_key):
                        st.session_state[_nlp_last_key] = _ai_nlp_q

                        # ── Check if operator is approving a pending config ───
                        _pending_key = f"ai_nlp_pending_cmds_{dev.ip}"
                        _approve_words = {"yes", "approve", "apply", "deploy",
                                          "confirm", "go", "do it", "execute",
                                          "proceed", "run it"}
                        _reject_words  = {"no", "cancel", "reject", "abort",
                                          "stop", "don't", "skip"}
                        _q_lower = _ai_nlp_q.strip().lower()

                        if st.session_state.get(_pending_key):
                            # Operator is responding to an approval request
                            _pending = st.session_state[_pending_key]
                            if any(w in _q_lower for w in _approve_words):
                                # ── EXECUTE the pending commands ──────────────
                                _exec_log = []
                                _creds_exec = {
                                    "username":      os.environ.get("GNS3_SSH_USER", "admin"),
                                    "password":      os.environ.get("GNS3_SSH_PASS", "admin"),
                                    "enable_secret": os.environ.get("GNS3_SSH_SECRET", ""),
                                }
                                try:
                                    from netmiko import ConnectHandler
                                    _cfg_exec = dict(
                                        device_type=dev.device_type or "cisco_ios",
                                        host=dev.ip,
                                        port=int(dev.ssh_port or 22),
                                        username=_creds_exec["username"],
                                        password=_creds_exec["password"],
                                        timeout=30,
                                        auth_timeout=30,
                                        fast_cli=False,
                                        global_delay_factor=2,
                                    )
                                    if _creds_exec["enable_secret"]:
                                        _cfg_exec["secret"] = _creds_exec["enable_secret"]

                                    with st.spinner(f"⚙️ Deploying configuration on {dev.ip}…"):
                                        _conn_exec = ConnectHandler(**_cfg_exec)
                                        _config_cmds = [c.replace("[CONFIG]","").strip()
                                                        for c in _pending if "[CONFIG]" in c]
                                        _exec_cmds   = [c.replace("[EXEC]","").strip()
                                                        for c in _pending if "[EXEC]" in c]
                                        if _exec_cmds:
                                            for _ec in _exec_cmds:
                                                _o = _conn_exec.send_command(_ec, read_timeout=20)
                                                _exec_log.append(f"$ {_ec}\n{_o}")
                                        if _config_cmds:
                                            _o = _conn_exec.send_config_set(_config_cmds)
                                            _exec_log.append(f"[CONFIG MODE]\n{_o}")
                                        _conn_exec.disconnect()

                                    _nlp_reply = (
                                        "✅ **Configuration deployed successfully on "
                                        f"{dev.hostname or dev.ip}**\n\n"
                                        "```\n" + "\n".join(_exec_log) + "\n```"
                                    )
                                except Exception as _exec_err:
                                    _nlp_reply = f"❌ Execution failed: {_exec_err}"

                                # Clear pending after execution
                                st.session_state.pop(_pending_key, None)

                            elif any(w in _q_lower for w in _reject_words):
                                _nlp_reply = "❌ Configuration cancelled. No changes were made to the router."
                                st.session_state.pop(_pending_key, None)
                            else:
                                _nlp_reply = (
                                    "⏳ There are pending commands waiting for your approval. "
                                    "Please say **yes** to deploy or **no** to cancel."
                                )

                        else:
                            # ── Normal AI chat — understand intent ────────────
                            _dev_ctx = (
                                f"Device: {dev.ip}  hostname={dev.hostname or dev.ip}  "
                                f"type={dev.device_type}  ports={dev.open_ports}\n"
                            )
                            if session and session.output:
                                _dev_ctx += f"\nLatest device output:\n{session.output[:2000]}"
                            if session and session.ai_diagnosis:
                                _dev_ctx += f"\nPrevious AI diagnosis:\n{session.ai_diagnosis[:1000]}"

                            # AI is told to return commands in a structured way
                            _nlp_sys = (
                                "You are an AI network engineer embedded in NetBrain AI, "
                                "with LIVE SSH access to the following device:\n"
                                f"{_dev_ctx}\n\n"
                                "When the operator asks you to CONFIGURE, DEPLOY, ADD, REMOVE, "
                                "ENABLE, DISABLE or CHANGE anything on the router, you MUST:\n"
                                "1. Explain what you will do in 1-2 sentences.\n"
                                "2. List ALL required IOS commands, one per line, prefixed with "
                                "[CONFIG] for config-mode commands or [EXEC] for exec-mode commands.\n"
                                "3. End with exactly this line: APPROVAL_REQUIRED\n\n"
                                "When the operator asks a READ-ONLY question (show, verify, explain, "
                                "check, what is, why), just answer directly — no commands needed.\n\n"
                                "Always be concise, use proper Cisco IOS format."
                            )

                            with st.spinner(f"🤖 AI Assistant thinking about {dev.ip}…"):
                                try:
                                    _raw_reply = call_ai(
                                        _nlp_sys + f"\n\nOperator: {_ai_nlp_q}\nAI Assistant:"
                                    )
                                except Exception as _nlp_err:
                                    _raw_reply = f"AI unavailable: {_nlp_err}"

                            if not _raw_reply:
                                _raw_reply = "AI is unavailable. Please check your OPENROUTER_API_KEY in Secrets."

                            # ── Parse AI response — extract commands if present ─
                            if "APPROVAL_REQUIRED" in _raw_reply:
                                _lines = _raw_reply.replace("APPROVAL_REQUIRED","").strip().splitlines()
                                _cmds   = [l.strip() for l in _lines
                                           if l.strip().startswith("[CONFIG]")
                                           or l.strip().startswith("[EXEC]")]
                                _explain = "\n".join(
                                    l for l in _lines
                                    if not l.strip().startswith("[CONFIG]")
                                    and not l.strip().startswith("[EXEC]")
                                ).strip()

                                if _cmds:
                                    # Store commands pending approval
                                    st.session_state[_pending_key] = _cmds
                                    _cmd_display = "\n".join(
                                        c.replace("[CONFIG]","  ").replace("[EXEC]","  ")
                                        for c in _cmds
                                    )
                                    _nlp_reply = (
                                        f"{_explain}\n\n"
                                        f"**Commands to be executed on {dev.hostname or dev.ip}:**\n"
                                        f"```\n{_cmd_display}\n```\n\n"
                                        "⚠️ **Type `yes` to deploy or `no` to cancel.**"
                                    )
                                else:
                                    _nlp_reply = _raw_reply.replace("APPROVAL_REQUIRED","").strip()
                            else:
                                # Read-only response — just show it
                                _nlp_reply = _raw_reply

                        # Store reply in session state to persist across reruns
                        if f"ai_nlp_history_{dev.ip}" not in st.session_state:
                            st.session_state[f"ai_nlp_history_{dev.ip}"] = []
                        st.session_state[f"ai_nlp_history_{dev.ip}"].append({
                            "q": _ai_nlp_q,
                            "a": _nlp_reply,
                        })

                    # ── Render NLP chat history for this device ───────────────
                    _nlp_history = st.session_state.get(f"ai_nlp_history_{dev.ip}", [])
                    if _nlp_history:
                        st.markdown("""
                        <style>
                        .nlp-chat-wrap {
                            background: #0d1320;
                            border: 1px solid #1e3a52;
                            border-radius: 10px;
                            padding: .75rem 1rem;
                            margin: .4rem 0 .6rem 0;
                        }
                        .nlp-msg-user {
                            background: #1e3a5f;
                            border-left: 3px solid #378ADD;
                            border-radius: 6px;
                            padding: .45rem .8rem;
                            margin: .35rem 0;
                            color: #cbd5e1;
                            font-size: .85rem;
                        }
                        .nlp-msg-ai {
                            background: #0f2132;
                            border-left: 3px solid #1D9E75;
                            border-radius: 6px;
                            padding: .45rem .8rem;
                            margin: .35rem 0;
                            color: #cbd5e1;
                            font-size: .85rem;
                            white-space: pre-wrap;
                        }
                        .nlp-label { font-size: .72rem; font-weight: 600;
                                     margin-bottom: .2rem; }
                        .nlp-label-user { color: #60a5fa; }
                        .nlp-label-ai   { color: #1D9E75; }
                        </style>
                        """, unsafe_allow_html=True)

                        import html as _html
                        with st.expander(
                            f"🤖 AI Assistant — {len(_nlp_history)} message(s) for {dev.ip}",
                            expanded=True
                        ):
                            st.markdown("<div class='nlp-chat-wrap'>", unsafe_allow_html=True)
                            for _entry in _nlp_history[-6:]:
                                _q_safe = _html.escape(_entry["q"])
                                _a_safe = _entry["a"]   # keep markdown for AI responses
                                st.markdown(
                                    f"<div class='nlp-msg-user'>"
                                    f"<div class='nlp-label nlp-label-user'>👤 You</div>{_q_safe}"
                                    f"</div>",
                                    unsafe_allow_html=True
                                )
                                st.markdown(
                                    f"<div class='nlp-label nlp-label-ai' style='color:#1D9E75;"
                                    f"font-size:.72rem;font-weight:600;margin:.35rem 0 .1rem 0'>"
                                    f"🤖 AI Assistant</div>",
                                    unsafe_allow_html=True
                                )
                                st.markdown(_a_safe)
                            st.markdown("</div>", unsafe_allow_html=True)

                            # ── Approval buttons — shown when commands are pending ──
                            _pend = st.session_state.get(f"ai_nlp_pending_cmds_{dev.ip}")
                            if _pend:
                                st.markdown("---")
                                st.warning(f"⚠️ **{len(_pend)} command(s) ready to deploy on {dev.hostname or dev.ip}. Approve?**")
                                _col_yes, _col_no = st.columns(2)
                                with _col_yes:
                                    if st.button("✅ Deploy Now", key=f"nlp_approve_{dev.ip}",
                                                 type="primary", use_container_width=True):
                                        _exec_log  = []
                                        _rollback_cmds = []
                                        _creds_exec = {
                                            "username":      os.environ.get("GNS3_SSH_USER", "admin"),
                                            "password":      os.environ.get("GNS3_SSH_PASS", "admin"),
                                            "enable_secret": os.environ.get("GNS3_SSH_SECRET", ""),
                                        }
                                        try:
                                            from netmiko import ConnectHandler
                                            import re as _re

                                            _dtype = dev.device_type or "cisco_ios"
                                            _cfg_exec = dict(
                                                device_type=_dtype,
                                                host=dev.ip,
                                                port=int(dev.ssh_port or 22),
                                                username=_creds_exec["username"],
                                                password=_creds_exec["password"],
                                                timeout=60,
                                                auth_timeout=60,
                                                conn_timeout=30,
                                                fast_cli=False,
                                                global_delay_factor=4,
                                                session_log=None,
                                            )
                                            if _creds_exec["enable_secret"]:
                                                _cfg_exec["secret"] = _creds_exec["enable_secret"]

                                            with st.spinner("⚙️ Connecting to " + dev.ip + "…"):
                                                _conn_exec = ConnectHandler(**_cfg_exec)
                                                # Enter enable mode if secret is set
                                                try:
                                                    _conn_exec.enable()
                                                except Exception:
                                                    pass

                                            # Strip "end", "exit", "write memory" — 
                                            # send_config_set handles these automatically
                                            _strip_cmds = {"end", "exit", "write memory", "wr", "wr mem"}
                                            _config_cmds = [
                                                c.replace("[CONFIG]","").strip()
                                                for c in _pend if "[CONFIG]" in c
                                                and c.replace("[CONFIG]","").strip()
                                                and c.replace("[CONFIG]","").strip().lower() not in _strip_cmds
                                            ]
                                            _exec_cmds   = [c.replace("[EXEC]","").strip()
                                                            for c in _pend if "[EXEC]" in c
                                                            and c.replace("[EXEC]","").strip()]

                                            # ── Capture PRE-change state for rollback ──
                                            with st.spinner("📸 Capturing pre-change snapshot…"):
                                                try:
                                                    _pre_run = _conn_exec.send_command(
                                                        "show running-config", read_timeout=30
                                                    )
                                                    # Build rollback commands from config cmds
                                                    for _cmd in _config_cmds:
                                                        _c = _cmd.strip().lower()
                                                        if _c.startswith("interface loopback"):
                                                            _iface = _cmd.strip().split()[-1]
                                                            _rollback_cmds += [
                                                                "[CONFIG] no interface loopback " + _iface
                                                            ]
                                                        elif _c.startswith("router ospf"):
                                                            _pid = _cmd.strip().split()[-1]
                                                            _rollback_cmds += [
                                                                "[CONFIG] no router ospf " + _pid
                                                            ]
                                                        elif _c.startswith("router bgp"):
                                                            _asn = _cmd.strip().split()[-1]
                                                            _rollback_cmds += [
                                                                "[CONFIG] no router bgp " + _asn
                                                            ]
                                                        elif _c.startswith("ip route"):
                                                            _rollback_cmds += [
                                                                "[CONFIG] no " + _cmd.strip()
                                                            ]
                                                        elif _c.startswith("no "):
                                                            # Reversing a "no" = add it back
                                                            _rollback_cmds += [
                                                                "[CONFIG] " + _cmd.strip()[3:]
                                                            ]
                                                except Exception:
                                                    _pre_run = ""

                                            # ── Execute EXEC-mode commands ────────────
                                            with st.spinner("⚙️ Executing commands on " + dev.ip + "…"):
                                                if _exec_cmds:
                                                    for _ec in _exec_cmds:
                                                        try:
                                                            _o = _conn_exec.send_command(
                                                                _ec,
                                                                read_timeout=30,
                                                                expect_string=r"#",
                                                            )
                                                            _exec_log.append("$ " + _ec + "\n" + _o)
                                                        except Exception as _ce:
                                                            _exec_log.append("$ " + _ec + "\nERROR: " + str(_ce))

                                                # ── Execute CONFIG-mode commands ──────
                                                if _config_cmds:
                                                    try:
                                                        _o = _conn_exec.send_config_set(
                                                            _config_cmds,
                                                            read_timeout=30,
                                                            enter_config_mode=True,
                                                            exit_config_mode=True,
                                                        )
                                                        _exec_log.append("[CONFIG MODE]\n" + _o)
                                                        # Save config
                                                        try:
                                                            _conn_exec.save_config()
                                                        except Exception:
                                                            pass
                                                    except Exception as _cfg_err:
                                                        _exec_log.append("[CONFIG MODE] ERROR: " + str(_cfg_err))

                                                _conn_exec.disconnect()

                                            _hostname_disp = dev.hostname or dev.ip
                                            _deploy_result = (
                                                "✅ **Deployed successfully on " + _hostname_disp + "**\n\n"
                                                + "```\n" + "\n".join(_exec_log) + "\n```"
                                            )
                                            # Store rollback plan in session state
                                            if _rollback_cmds:
                                                st.session_state[f"ai_nlp_rollback_{dev.ip}"] = _rollback_cmds
                                                _deploy_result += (
                                                    "\n\n🔄 **Rollback available** — "
                                                    "click **↩️ Undo** below to revert these changes."
                                                )

                                        except Exception as _ex_err:
                                            _deploy_result = "❌ Deployment failed: " + str(_ex_err)

                                        st.session_state.pop(f"ai_nlp_pending_cmds_{dev.ip}", None)
                                        st.session_state.setdefault(
                                            f"ai_nlp_history_{dev.ip}", []
                                        ).append({"q": "✅ Approved — Deploy Now", "a": _deploy_result})
                                        st.rerun()

                                with _col_no:
                                    if st.button("❌ Cancel", key=f"nlp_reject_{dev.ip}",
                                                 use_container_width=True):
                                        st.session_state.pop(f"ai_nlp_pending_cmds_{dev.ip}", None)
                                        st.session_state.setdefault(
                                            f"ai_nlp_history_{dev.ip}", []
                                        ).append({"q": "❌ Cancelled", "a": "Configuration cancelled. No changes made."})
                                        st.rerun()

                            # ── Rollback / Undo button ────────────────────────
                            _rollback_key = f"ai_nlp_rollback_{dev.ip}"
                            _pending_key  = f"ai_nlp_pending_cmds_{dev.ip}"
                            if st.session_state.get(_rollback_key) and not st.session_state.get(_pending_key):
                                st.markdown("---")
                                st.info("↩️ **Rollback available** — undo the last deployed configuration.")
                                _col_rb, _col_rb2 = st.columns(2)
                                with _col_rb:
                                    if st.button("↩️ Undo Last Change", key=f"nlp_rollback_{dev.ip}",
                                                 use_container_width=True):
                                        _rb_cmds = st.session_state[_rollback_key]
                                        _rb_log  = []
                                        _creds_rb = {
                                            "username":      os.environ.get("GNS3_SSH_USER", "admin"),
                                            "password":      os.environ.get("GNS3_SSH_PASS", "admin"),
                                            "enable_secret": os.environ.get("GNS3_SSH_SECRET", ""),
                                        }
                                        try:
                                            from netmiko import ConnectHandler
                                            _cfg_rb = dict(
                                                device_type=dev.device_type or "cisco_ios",
                                                host=dev.ip,
                                                port=int(dev.ssh_port or 22),
                                                username=_creds_rb["username"],
                                                password=_creds_rb["password"],
                                                timeout=60,
                                                auth_timeout=60,
                                                fast_cli=False,
                                                global_delay_factor=4,
                                            )
                                            if _creds_rb["enable_secret"]:
                                                _cfg_rb["secret"] = _creds_rb["enable_secret"]
                                            with st.spinner("↩️ Rolling back changes on " + dev.ip + "…"):
                                                _conn_rb = ConnectHandler(**_cfg_rb)
                                                try:
                                                    _conn_rb.enable()
                                                except Exception:
                                                    pass
                                                _rb_config = [c.replace("[CONFIG]","").strip()
                                                              for c in _rb_cmds if "[CONFIG]" in c]
                                                _rb_exec   = [c.replace("[EXEC]","").strip()
                                                              for c in _rb_cmds if "[EXEC]" in c]
                                                if _rb_exec:
                                                    for _rc in _rb_exec:
                                                        _o = _conn_rb.send_command(
                                                            _rc, read_timeout=30, expect_string=r"#"
                                                        )
                                                        _rb_log.append("$ " + _rc + "\n" + _o)
                                                if _rb_config:
                                                    _o = _conn_rb.send_config_set(
                                                        _rb_config,
                                                        read_timeout=30,
                                                        enter_config_mode=True,
                                                        exit_config_mode=True,
                                                    )
                                                    _rb_log.append("[ROLLBACK CONFIG]\n" + _o)
                                                    try:
                                                        _conn_rb.save_config()
                                                    except Exception:
                                                        pass
                                                _conn_rb.disconnect()
                                            _rb_result = (
                                                "↩️ **Rollback completed on " + (dev.hostname or dev.ip) + "**\n\n"
                                                + "```\n" + "\n".join(_rb_log) + "\n```"
                                            )
                                            st.session_state.pop(_rollback_key, None)
                                        except Exception as _rb_err:
                                            _rb_result = "❌ Rollback failed: " + str(_rb_err)
                                        st.session_state.setdefault(
                                            f"ai_nlp_history_{dev.ip}", []
                                        ).append({"q": "↩️ Undo Last Change", "a": _rb_result})
                                        st.rerun()
                                with _col_rb2:
                                    if st.button("🗑 Discard Rollback", key=f"nlp_discard_rb_{dev.ip}",
                                                 use_container_width=True):
                                        st.session_state.pop(_rollback_key, None)
                                        st.rerun()

                            if st.button("🗑 Clear chat", key=f"nlp_clear_{dev.ip}"):
                                st.session_state.pop(f"ai_nlp_history_{dev.ip}", None)
                                st.session_state.pop(f"ai_nlp_last_{dev.ip}", None)
                                st.session_state.pop(f"ai_nlp_pending_cmds_{dev.ip}", None)
                                st.rerun()

                    # ── Live Progress + Details Panel ─────────────────────────
                    if st.session_state.get(f"ts_expanded_{dev.ip}") and session:

                        # Live polling: use st.empty + rerun only when running,
                        # capped at max 30 polls to prevent infinite loop
                        _poll_key = f"poll_count_{dev.ip}"
                        if sess_status == "running":
                            _polls = st.session_state.get(_poll_key, 0)
                            if _polls < 30:
                                st.session_state[_poll_key] = _polls + 1
                                import time as _time
                                _time.sleep(1.2)
                                st.rerun()
                            else:
                                # Safety: stop polling after 30 cycles (~36 sec)
                                st.warning("⏳ Session taking longer than expected — click Refresh to check progress.")
                        else:
                            # Reset poll counter when session completes
                            st.session_state.pop(_poll_key, None)

                        with st.container():
                            st.markdown("""
                            <div style='background:#080f1a;border:1px solid #1e3a52;
                                        border-radius:10px;padding:1rem 1.2rem;margin:.5rem 0'>
                            """, unsafe_allow_html=True)

                            # ── Live progress steps ───────────────────────────
                            _mode_label = "🔐 Login" if st.session_state.get(f"login_mode_{dev.ip}") else "🤖 AI Troubleshooting"
                            _status_badge = {
                                "running":  "<span style='color:#f59e0b'>⏳ Running…</span>",
                                "complete": "<span style='color:#22c55e'>✅ Complete</span>",
                                "failed":   "<span style='color:#ef4444'>❌ Failed</span>",
                            }.get(session.status, "")
                            st.markdown(
                                f"**📋 Progress — {_mode_label}** &nbsp; {_status_badge}",
                                unsafe_allow_html=True
                            )

                            # Historical sessions count from log store
                            _prior = log_store.get_all_logs(dev.ip)
                            _hist_count = len(_prior.get("ai_history", []))
                            if _hist_count:
                                st.caption(f"📚 {_hist_count} historical session(s) stored — AI uses these for context")

                            # Steps — live streaming
                            for _s in session.steps:
                                _icon = "✅" if _s["ok"] else "❌"
                                _step_col, _detail_col = st.columns([2, 5])
                                with _step_col:
                                    st.markdown(
                                        f"{_icon} `{_s['ts']}` **{_s['name']}**"
                                    )
                                with _detail_col:
                                    st.markdown(f"<span style='color:#94a3b8'>{_s['detail']}</span>",
                                                unsafe_allow_html=True)
                                if _s.get("output"):
                                    with st.expander(f"📄 Output: {_s['name']}"):
                                        st.code(_s["output"][:3000], language="text")

                            # Spinner if still running
                            if sess_status == "running":
                                st.markdown(
                                    "<span style='color:#f59e0b'>⏳ Working — page refreshes automatically…</span>",
                                    unsafe_allow_html=True
                                )

                            st.markdown("</div>", unsafe_allow_html=True)

                        # ── AI Diagnosis (only for AI troubleshoot mode) ───────
                        if session.ai_diagnosis and not st.session_state.get(f"login_mode_{dev.ip}"):
                            with st.expander("🤖 AI Diagnosis", expanded=True):
                                if "HEALTH: CRITICAL" in session.ai_diagnosis:
                                    st.error("🔴 HEALTH: CRITICAL")
                                elif "HEALTH: DEGRADED" in session.ai_diagnosis:
                                    st.warning("🟠 HEALTH: DEGRADED")
                                elif "HEALTH: HEALTHY" in session.ai_diagnosis:
                                    st.success("🟢 HEALTH: HEALTHY")
                                st.markdown(session.ai_diagnosis)

                        # ── Raw output ────────────────────────────────────────
                        if session.output:
                            with st.expander("📄 Raw Device Output"):
                                st.code(session.output[:8000], language="text")

                        # ── Fix plan + approve/dismiss ────────────────────────
                        if session.ai_fix_plan and not session.fix_applied and session.status == "complete":
                            st.markdown("**🔧 Proposed Fix Commands**")
                            st.code(session.ai_fix_plan, language="text")
                            st.warning(
                                "⚠️ Review carefully — these will execute on the live device."
                            )
                            _fc1, _fc2 = st.columns(2)
                            with _fc1:
                                if st.button("✅ APPROVE & APPLY FIXES",
                                             key=f"apply_fix_{dev.ip}", type="primary"):
                                    _creds = {
                                        "username": os.environ.get("GNS3_SSH_USER", "admin"),
                                        "password": os.environ.get("GNS3_SSH_PASS", "admin"),
                                        "enable_secret": os.environ.get("GNS3_SSH_SECRET", ""),
                                    }
                                    disc.approve_and_apply_fixes(dev.ip, call_ai, _creds)
                                    st.session_state[f"ts_expanded_{dev.ip}"] = True
                                    st.rerun()
                            with _fc2:
                                if st.button("🚫 Dismiss", key=f"dismiss_fix_{dev.ip}"):
                                    st.session_state[f"ts_expanded_{dev.ip}"] = False
                                    st.rerun()

                        elif session.fix_applied:
                            st.success("✅ Fixes applied. Run AI Diagnose again to verify health.")

                    st.markdown("---")

            st.divider()

            # ════════════════════════════════════════════════════════════════
            # SECTION 3 — FULL DISCOVERY LOG
            # ════════════════════════════════════════════════════════════════
            all_devices = disc.get_all()
            with st.expander(f"📜 Full Discovery Log ({len(all_devices)} total)"):
                if all_devices:
                    import pandas as _pd
                    rows = [
                        {
                            "IP":          d.ip,
                            "Hostname":    d.hostname or "—",
                            "Type":        d.device_type,
                            "Status":      d.status,
                            "Source":      d.source,
                            "Open Ports":  ", ".join(str(p) for p in d.open_ports) or "—",
                            "First Seen":  d.first_seen,
                            "Last Seen":   d.last_seen,
                        }
                        for d in all_devices
                    ]
                    st.dataframe(_pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No devices discovered yet.")

            st.divider()

            # ════════════════════════════════════════════════════════════════
            # SECTION 4 — DEVICE LOG STORE (AI memory for each device)
            # ════════════════════════════════════════════════════════════════
            st.markdown(
                "<div class='dd-section-title'>🧠 Device Log Store — AI Memory</div>",
                unsafe_allow_html=True
            )
            st.caption(
                "All SSH outputs, AI diagnoses and applied fixes are stored here. "
                "The AI uses this history as context for smarter future suggestions."
            )

            all_log_devices = log_store.get_all_devices()
            if not all_log_devices:
                st.info("No logs stored yet. Approve a device and run AI Troubleshooting to populate.")
            else:
                for _lip, _ldata in all_log_devices.items():
                    _ldev = disc.get_device(_lip)
                    _lname = (_ldev.hostname if _ldev and _ldev.hostname else _lip)
                    _lhealth = _ldata.get("last_health", "unknown")
                    _health_icon = {"CRITICAL": "🔴", "DEGRADED": "🟠",
                                    "HEALTHY": "🟢"}.get(_lhealth.upper(), "⚪")
                    _logs = _ldata.get("logs", [])
                    _ai_hist = _ldata.get("ai_history", [])

                    with st.expander(
                        f"{_health_icon} {_lname} ({_lip})  "
                        f"· {len(_logs)} log entries · {len(_ai_hist)} AI sessions",
                        expanded=False
                    ):
                        # Tabs within expander
                        _lt1, _lt2, _lt3 = st.tabs(["📋 Logs", "🤖 AI History", "🔍 Full Context"])

                        with _lt1:
                            if _logs:
                                import pandas as _pd2
                                st.dataframe(
                                    _pd2.DataFrame([{
                                        "Time": l.get("ts","")[:19],
                                        "Type": l.get("type",""),
                                        "Summary": str(l.get("summary",""))[:120],
                                    } for l in reversed(_logs)]),
                                    use_container_width=True, hide_index=True
                                )
                            else:
                                st.caption("No logs yet.")

                        with _lt2:
                            if _ai_hist:
                                for _ah in reversed(_ai_hist):
                                    _applied = "✅ Applied" if _ah.get("applied") else "📋 Plan only"
                                    with st.expander(
                                        f"{_ah.get('ts','')[:19]}  · {_applied}"
                                    ):
                                        st.markdown("**AI Diagnosis:**")
                                        st.markdown(_ah.get("diagnosis",""))
                                        if _ah.get("fix_plan"):
                                            st.markdown("**Fix Plan:**")
                                            st.code(_ah.get("fix_plan",""), language="text")
                            else:
                                st.caption("No AI sessions yet. Run AI Troubleshooting on the device.")

                        with _lt3:
                            ctx = log_store.get_context_for_ai(_lip)
                            if ctx:
                                st.code(ctx, language="text")
                                st.caption("This is the exact context passed to AI on the next troubleshoot run.")
                            else:
                                st.caption("No context available yet.")

            st.divider()

            # ── How it works callout ──────────────────────────────────────────
            # ── SSH Credentials for Troubleshooting ──────────────────────────
            with st.expander("🔑 SSH Credentials for AI Troubleshooting", expanded=False):
                st.caption(
                    "These credentials are used when **AI Network Troubleshooting** SSHs "
                    "into your approved devices. They must match the login configured on "
                    "your GNS3 router (set via `username admin privilege 15 secret <pass>`)."
                )
                col_u, col_p, col_s = st.columns(3)
                _ts_user   = col_u.text_input("SSH Username",    value=os.environ.get("GNS3_SSH_USER", "admin"),    key="dd_ts_user")
                _ts_pass   = col_p.text_input("SSH Password",    value=os.environ.get("GNS3_SSH_PASS", "admin"),    key="dd_ts_pass", type="password")
                _ts_secret = col_s.text_input("Enable Secret",   value=os.environ.get("GNS3_SSH_SECRET", ""),       key="dd_ts_secret", type="password")
                if st.button("💾 Save Credentials", key="dd_save_creds"):
                    os.environ["GNS3_SSH_USER"]   = _ts_user.strip()
                    os.environ["GNS3_SSH_PASS"]   = _ts_pass.strip()
                    if _ts_secret.strip():
                        os.environ["GNS3_SSH_SECRET"] = _ts_secret.strip()
                    st.success("✅ Credentials saved for this session.")
                    st.caption("Add to `.env` file to persist: `ROUTER_DEFAULT_USERNAME=admin`")

                st.divider()
                st.markdown("**Quick credential test** — tries SSH login without running any commands:")
                _test_ip = st.text_input("Device IP to test", key="dd_cred_test_ip",
                                          placeholder="192.168.96.128")
                if st.button("🔌 Test SSH Login", key="dd_test_ssh"):
                    if _test_ip:
                        with st.spinner(f"Testing SSH to {_test_ip}..."):
                            try:
                                from netmiko import ConnectHandler
                                _conn = ConnectHandler(
                                    device_type=os.environ.get("GNS3_DEVICE_TYPE","cisco_ios"),
                                    host=_test_ip.strip(),
                                    port=22,
                                    username=os.environ.get("GNS3_SSH_USER","admin"),
                                    password=os.environ.get("GNS3_SSH_PASS","admin"),
                                    timeout=15, auth_timeout=15, fast_cli=False,
                                )
                                _out = _conn.send_command("show version | include uptime")
                                _conn.disconnect()
                                st.success(f"✅ Login successful!\n```\n{_out[:200]}\n```")
                            except Exception as _e:
                                st.error(f"❌ Login failed: {_e}")
                                st.markdown("""
                                **Common fixes:**
                                - Verify username/password above match your GNS3 router config
                                - On your GNS3 router run:
                                  ```
                                  username admin privilege 15 secret cisco
                                  line vty 0 4
                                   login local
                                   transport input ssh
                                  crypto key generate rsa modulus 1024
                                  ```
                                - Make sure the device IP is reachable (`ping` it first)
                                """)
                    else:
                        st.warning("Enter a device IP to test.")

            with st.expander("ℹ️ How Auto-Discovery Works"):
                st.markdown("""
                **Mac/Linux Terminal → Auto-Discovery Pipeline:**

                1. Open your Mac Terminal and ping any GNS3 router:
                   ```
                   ping 192.168.0.1
                   ```
                2. NetBrain AI detects the ICMP reply within ~10 seconds
                3. The device appears in the **Pending Approval** section above
                4. Click **Approve** — it joins your network inventory
                5. Click **🤖 AI Network Troubleshooting** to SSH in, run diagnostics, and get an AI-generated fix plan
                6. Review the fix commands, then click **APPROVE & APPLY FIXES** to execute them

                **Subnet Scan:** Use the scanner above to discover all live devices on a /24 subnet at once.

                **Manual Add:** Enter any IP in the "Ping & Discover" box to check reachability and add it directly.

                **Auth failed?** Open the **SSH Credentials** section above and click **Test SSH Login**.
                """)


# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: LOCAL ROUTER ACCESS
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "local_router":
    if LRA_AVAILABLE:
        render_local_access_ui(_get_lra_manager())
    else:
        st.error("❌ Local_Router_Access module could not be loaded.")
        st.markdown("""
        **To fix this:**
        1. Make sure `Local_Router_Access.py` is in the **root** of your repository (same folder as `app.py`)
        2. Install dependencies: `pip install paramiko requests`
        3. Restart the Streamlit app
        """)
        with st.expander("📋 Quick manual access (fallback)"):
            st.markdown("Use these links to access your app on the local network:")
            import socket
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as _s:
                    _s.connect(("8.8.8.8", 80))
                    _local_ip = _s.getsockname()[0]
            except Exception:
                _local_ip = "127.0.0.1"
            _port = int(os.environ.get("STREAMLIT_PORT", 8501))
            st.code(f"http://localhost:{_port}", language="text")
            st.code(f"http://{_local_ip}:{_port}", language="text")


# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: NLP — AI ASSISTANT
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "nlp":
    st.markdown("""
    <style>
    .ai-assistant-wrap {
        max-width: 860px; margin: 0 auto;
    }
    .ai-msg-user {
        background: #1e3a5f;
        border-left: 3px solid #3b82f6;
        border-radius: 8px;
        padding: .7rem 1rem;
        margin: .5rem 0;
        color: #e2e8f0;
    }
    .ai-msg-bot {
        background: #0f2132;
        border-left: 3px solid #22d3ee;
        border-radius: 8px;
        padding: .7rem 1rem;
        margin: .5rem 0;
        color: #e2e8f0;
    }
    .ai-msg-label-user { color: #93c5fd; font-size:.75rem; margin-bottom:.3rem; font-weight:600; }
    .ai-msg-label-bot  { color: #22d3ee; font-size:.75rem; margin-bottom:.3rem; font-weight:600; }
    .ai-shadow-hint {
        color: #334155; font-size: 1.1rem; text-align: center;
        padding: 2rem 0 1rem 0; font-style: italic;
    }
    .ai-typing {
        color: #22d3ee; font-size:.85rem; padding:.4rem 1rem;
        animation: blink 1s step-start infinite;
    }
    @keyframes blink { 50% { opacity: 0; } }
    </style>
    """, unsafe_allow_html=True)

    st.markdown("<div class='ai-assistant-wrap'>", unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown("""
    <div style='text-align:center; padding: 1.5rem 0 .5rem 0;'>
        <div style='font-size:2.5rem'>🤖</div>
        <div style='font-size:1.4rem; font-weight:700; color:#f1f5f9;'>AI Assistant</div>
        <div style='font-size:.85rem; color:#64748b; margin-top:.3rem;'>
            Ask anything about your network · Diagnose issues · Generate configs
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Init chat history ─────────────────────────────────────────────────────
    if "nlp_messages" not in st.session_state:
        st.session_state["nlp_messages"] = []
    if "nlp_devices_ctx" not in st.session_state:
        st.session_state["nlp_devices_ctx"] = ""

    # ── Build device context for AI ───────────────────────────────────────────
    try:
        from core.device_discovery import get_discovery_engine
        _disc = get_discovery_engine()
        _approved_devs = _disc.get_approved()
        if _approved_devs:
            _dev_lines = "\n".join(
                f"- {d.hostname or d.ip} ({d.ip}) type={d.device_type} ports={d.open_ports}"
                for d in _approved_devs
            )
            st.session_state["nlp_devices_ctx"] = f"Approved network devices:\n{_dev_lines}"
    except Exception:
        pass

    # ── Suggested prompts ─────────────────────────────────────────────────────
    if not st.session_state["nlp_messages"]:
        st.markdown(
            "<div class='ai-shadow-hint'>✨ AI Assistant — ask me anything about your network</div>",
            unsafe_allow_html=True
        )
        st.markdown("**Quick actions:**")
        _suggestions = [
            "Show me the health of all approved devices",
            "What is BGP and when should I use it?",
            "Generate OSPF config for R1 on 192.168.1.0/24",
            "What does 'show ip interface brief' output tell me?",
            "How do I configure SSH on a Cisco router?",
            "Explain the difference between EIGRP and OSPF",
        ]
        _sg_cols = st.columns(3)
        for idx, sg in enumerate(_suggestions):
            with _sg_cols[idx % 3]:
                if st.button(sg, key=f"nlp_sg_{idx}", use_container_width=True):
                    st.session_state["nlp_messages"].append({"role": "user", "content": sg})
                    st.rerun()

    # ── Chat history ──────────────────────────────────────────────────────────
    for msg in st.session_state["nlp_messages"]:
        if msg["role"] == "user":
            st.markdown(
                f"<div class='ai-msg-user'>"
                f"<div class='ai-msg-label-user'>👤 You</div>{msg['content']}"
                f"</div>", unsafe_allow_html=True
            )
        else:
            st.markdown(
                f"<div class='ai-msg-bot'>"
                f"<div class='ai-msg-label-bot'>🤖 AI Assistant</div>{msg['content']}"
                f"</div>", unsafe_allow_html=True
            )

    # ── Generate AI reply for latest user message ─────────────────────────────
    msgs = st.session_state["nlp_messages"]
    if msgs and msgs[-1]["role"] == "user" and (
        len(msgs) < 2 or msgs[-2]["role"] != "user"
    ):
        _last_q = msgs[-1]["content"]
        with st.spinner("🤖 AI Assistant is thinking…"):
            try:
                _dev_ctx = st.session_state.get("nlp_devices_ctx", "")
                _history = "\n".join(
                    f"{'User' if m['role']=='user' else 'Assistant'}: {m['content']}"
                    for m in msgs[-10:-1]
                )
                _sys_prompt = (
                    "You are NetBrain AI Assistant — an expert network engineer and Cisco IOS specialist. "
                    "You help with network troubleshooting, configuration, diagnostics, and best practices. "
                    "Be concise, technical, and actionable. Use bullet points for lists. "
                    "When generating IOS configs, use proper formatting with indentation.\n\n"
                    + (f"{_dev_ctx}\n\n" if _dev_ctx else "")
                    + (f"Conversation so far:\n{_history}\n\n" if _history else "")
                )
                _full_prompt = _sys_prompt + f"User question: {_last_q}"
                _reply = call_ai(_full_prompt) or "I'm unable to respond right now. Check your OPENROUTER_API_KEY."
            except Exception as _e:
                _reply = f"Error: {_e}"
        st.session_state["nlp_messages"].append({"role": "assistant", "content": _reply})
        st.rerun()

    # ── Input box ─────────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    with st.container():
        _in_col, _btn_col, _clr_col = st.columns([7, 1, 1])
        with _in_col:
            _user_input = st.text_input(
                label="message",
                label_visibility="collapsed",
                placeholder="💬 Ask AI Assistant — e.g. 'Why is my interface down?' or 'Generate OSPF config'",
                key="nlp_input",
            )
        with _btn_col:
            _send = st.button("Send ➤", key="nlp_send", type="primary",
                              use_container_width=True)
        with _clr_col:
            if st.button("🗑 Clear", key="nlp_clear", use_container_width=True):
                st.session_state["nlp_messages"] = []
                st.rerun()

        if _send and _user_input.strip():
            st.session_state["nlp_messages"].append(
                {"role": "user", "content": _user_input.strip()}
            )
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)






    st.header("🧠 NetBrain AI — Autonomous Network Operations")
    st.info("Select a workspace from the sidebar.")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**🖥 Dashboard**\nLive NOC with device health cards and event feed")
    c2.markdown("**🔄 Workflows**\nApprove/reject fixes, watch 7-step pipeline")
    c3.markdown("**⚙️ Admin**\nConfigure tunnel, credentials, thresholds")
