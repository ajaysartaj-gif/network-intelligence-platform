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
from core.intent_engine import IntentEngine, IntentResult, INTENT_CONFIG
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
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Free model by default (no cost, no credit card). Override via the
# Groq model — completely free, no credits needed
def _resolve_model() -> str:
    try:
        import streamlit as _st
        m = _st.secrets.get("GROQ_MODEL", "")
    except Exception:
        m = ""
    if not m:
        m = os.environ.get("GROQ_MODEL", "")
    return (m or "llama-3.3-70b-versatile").strip()

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
        "NETBRAIN_LIVE_ONLY", "GROQ_API_KEY",
        # Operational Memory shared brain (Postgres/Supabase). When present,
        # all instances read/write ONE cloud brain in real time; absent, the
        # service falls back to a local SQLite file automatically.
        "NETBRAIN_MEMORY_DSN", "NETBRAIN_MEMORY_DB",
        # RAG / embedding store config (so knowledge config travels too).
        "NETBRAIN_RAG_DIR", "NETBRAIN_RAG_EMBED_MODEL", "NETBRAIN_RAG_MIN_SCORE",
    ]
    for k in keys:
        try:
            val = st.secrets.get(k, None)
        except Exception:
            val = None
        # Only fill from secrets if not already set in the environment.
        if val is not None and str(val).strip() and not os.environ.get(k):
            os.environ[k] = str(val).strip()

    # Per-device credential overrides live in a nested [device_credentials]
    # table in secrets.toml. Discovery runs in worker threads that must not
    # touch st.secrets, so serialize the table into a plain env var (JSON)
    # that core.topology.credentials reads. Keeps per-device passwords in the
    # gitignored secrets file, never in committed inventory.
    if not os.environ.get("GNS3_DEVICE_CREDENTIALS_JSON"):
        try:
            table = st.secrets.get("device_credentials", None)
        except Exception:
            table = None
        if table:
            try:
                import json as _json
                # st.secrets entries are Mapping-like; coerce to plain dicts.
                plain = {str(ip): dict(vals) for ip, vals in dict(table).items()}
                os.environ["GNS3_DEVICE_CREDENTIALS_JSON"] = _json.dumps(plain)
            except Exception:
                pass


# Copy secrets → env BEFORE any engine/monitor is constructed.
_load_secrets_into_env()


# Plug the standalone intelligence services into the Capability Registry once
# at startup, so the backbone reports their live status. Best-effort: a missing
# subsystem never blocks app launch.
def _bind_capabilities() -> None:
    try:
        from core.intelligence.operational_memory import bind_memory_capability
        bind_memory_capability()
    except Exception:
        pass
    try:
        from core.knowledge.enterprise import bind_knowledge_capability
        bind_knowledge_capability()
    except Exception:
        pass
    try:
        from core.intelligence.reasoning import bind_reasoning_capability
        bind_reasoning_capability()
    except Exception:
        pass
    # Expanded memory: register the expert faculties and bind the derived-memory
    # pillars (Experience/Failure/Pattern/Procedural/Semantic/Temporal/…) plus
    # upgrade Continuous Learning + Prediction now that the feedback loop exists.
    try:
        from core.intelligence.memory import wire_memory_system
        wire_memory_system()
    except Exception:
        pass


_bind_capabilities()


def _resolve_api_key() -> str:
    # 1. Streamlit Secrets (works on Cloud + local .streamlit/secrets.toml)
    try:
        key = st.secrets.get("GROQ_API_KEY", "")
        if key and key.strip():
            return key.strip()
    except Exception:
        pass
    # 2. os.environ
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if key:
        return key
    # 3. .env file in repo root
    try:
        from dotenv import load_dotenv
        _repo = os.path.dirname(os.path.abspath(__file__))
        _env  = os.path.join(_repo, ".env")
        if os.path.exists(_env):
            load_dotenv(_env, override=True)
            key = os.environ.get("GROQ_API_KEY", "").strip()
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
        return OpenAI(api_key=key, base_url=GROQ_BASE_URL)
    except Exception:
        return None


def call_ai(prompt: str) -> str:
    # Step 1: check key
    key = _resolve_api_key()
    if not key:
        return "AI is unavailable — GROQ_API_KEY not found in .streamlit/secrets.toml or .env"

    # Step 2: check openai package
    if not OPENAI_AVAILABLE:
        return "AI is unavailable — openai package not installed. Run: pip install openai"

    # Step 3: create client
    try:
        client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
    except Exception as e:
        return f"AI is unavailable — could not create client: {e}"

    # Step 4: call API — return the real error so it is visible in the chat
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
            max_tokens=800,
            temperature=0.1,
        )
        return resp.choices[0].message.content
    except Exception as e:
        # Surface the real error — do not swallow it
        err = str(e)
        logger.warning(f"AI call failed: {err}")
        return f"AI Error: {err}"

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
    ("dashboard",  "🖥",  "Dashboard"),
    ("copilot",    "✨",  "Network Copilot"),
    ("Workflows",  "🤖",  "AI Action"),
    ("incident",   "🚨",  "Incidents"),
    ("topology",   "🗺",  "Topology"),
    ("Observability", "📡", "Observability"),
    ("security",   "🔒",  "Security"),
    ("executive",  "📈",  "Executive"),
    ("intelligence", "🧠", "Intelligence"),
    ("admin",      "⚙️",  "Admin"),
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
    color  = {"critical": "#ff4560", "warning": "#ffb300", "healthy": "#00e676"}.get(status, "#4a617a")
    icon   = {"critical": "🔴", "warning": "🟡", "healthy": "🟢"}.get(status, "⚫")

    cpu_bar  = int(m.cpu)
    mem_bar  = int(m.memory)
    cpu_col  = "#ff4560" if m.cpu >= 90 else "#ffb300" if m.cpu >= 70 else "#00e676"
    mem_col  = "#ff4560" if m.memory >= 90 else "#ffb300" if m.memory >= 70 else "#00e676"

    st.markdown(f"""
    <div style="background:linear-gradient(145deg,#080e1a,#0d1626);
                border:1px solid {color}44; border-left:3px solid {color};
                border-radius:14px; padding:16px 18px; margin:6px 0;
                box-shadow:0 4px 16px rgba(0,0,0,.35),0 0 24px {color}0a;
                transition:all .2s ease;">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
            <div>
                <span style="font-weight:700; color:#e8f0fc; font-size:14px; letter-spacing:-.01em;">{icon} {hostname}</span>
                <div style="font-size:11px; color:#4a617a; margin-top:2px; font-family:'JetBrains Mono',monospace;">
                    {'✅ Reachable' if reachable else '❌ Unreachable'}
                </div>
            </div>
            <div style="background:{color}18; border:1px solid {color}44; border-radius:20px;
                        padding:3px 10px; font-size:10px; color:{color}; font-weight:700;
                        letter-spacing:.06em; font-family:'JetBrains Mono',monospace;">
                {status.upper()}
            </div>
        </div>
        <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
            <span style="font-size:10px; color:#4a617a; font-weight:600; letter-spacing:.05em; text-transform:uppercase;">HEALTH</span>
            <span style="font-size:13px; font-weight:800; color:{color};">{score:.0f}%</span>
        </div>
        <div style="font-size:10.5px; color:#4a617a; margin-bottom:4px; display:flex; justify-content:space-between;">
            <span>CPU</span><span style="color:#8ba3c0;">{m.cpu:.1f}%</span>
        </div>
        <div style="background:#0d1626; border-radius:4px; height:5px; margin-bottom:8px; overflow:hidden;">
            <div style="background:linear-gradient(90deg,{cpu_col},{cpu_col}aa); width:{min(cpu_bar,100)}%; height:5px; border-radius:4px; transition:width .3s ease;"></div>
        </div>
        <div style="font-size:10.5px; color:#4a617a; margin-bottom:4px; display:flex; justify-content:space-between;">
            <span>MEM</span><span style="color:#8ba3c0;">{m.memory:.1f}%</span>
        </div>
        <div style="background:#0d1626; border-radius:4px; height:5px; margin-bottom:10px; overflow:hidden;">
            <div style="background:linear-gradient(90deg,{mem_col},{mem_col}aa); width:{min(mem_bar,100)}%; height:5px; border-radius:4px;"></div>
        </div>
        <div style="font-size:10.5px; color:#4a617a; font-family:'JetBrains Mono',monospace; display:flex; gap:10px; flex-wrap:wrap;">
            <span>⏱ {m.latency_ms:.0f}ms</span>
            <span>📉 {m.packet_loss_pct:.2f}%</span>
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
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px;">
            <span style="background:rgba(255,179,0,.15);border:1px solid rgba(255,179,0,.4);
                         border-radius:6px;padding:3px 10px;font-size:10px;font-weight:700;
                         color:#ffb300;letter-spacing:.08em;font-family:'JetBrains Mono',monospace;">
                ⚡ APPROVAL REQUIRED</span>
            <span style="font-size:13px;font-weight:700;color:#e8f0fc;letter-spacing:-.01em;">
                {run.anomaly_type.replace('_',' ').upper()}</span>
        </div>
        <div style="font-size:14px;color:#c8d6e8;margin-top:6px;font-weight:500;">
            {sev_icon} {a_desc}
        </div>
        <div style="font-size:11.5px;color:#4a617a;margin-top:8px;display:flex;gap:16px;flex-wrap:wrap;">
            <span>🖧 Target: <b style="color:#e8f0fc;">{headline_target}</b></span>
            <span>⚠️ State: <b style="color:#ffb300;">{a_state or 'n/a'}</b></span>
            <span>🔖 Incident: <b style="color:#8ba3c0;">{run.incident_id}</b></span>
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
    st.markdown(
        """<div style="padding:16px 10px 12px;text-align:center;">
             <div style="font-size:11px;letter-spacing:.25em;font-weight:700;color:#4d8fff;
                         font-family:'JetBrains Mono',monospace;margin-bottom:4px;">◈ NETBRAIN</div>
             <div style="font-size:22px;font-weight:900;letter-spacing:-.03em;
                         background:linear-gradient(135deg,#00d4ff,#4d8fff);
                         -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                         background-clip:text;font-family:'Space Grotesk','Inter',sans-serif;">
               Network AI</div>
             <div style="font-size:9px;color:#4a617a;letter-spacing:.15em;font-weight:600;
                         font-family:'JetBrains Mono',monospace;margin-top:3px;">
               AUTONOMOUS NOC PLATFORM</div>
           </div>
           <div style="height:1px;background:linear-gradient(90deg,transparent,#4d8fff44,transparent);
                       margin:0 -10px 14px;"></div>""",
        unsafe_allow_html=True,
    )

    # Health score ring
    op_summary = orchestrator.state.get_operational_summary()
    score = op_summary.get("operational_score", 100)
    score_color = "#ff4560" if score < 60 else "#ffb300" if score < 80 else "#00e676"
    _score_label = "CRITICAL" if score < 60 else "DEGRADED" if score < 80 else "HEALTHY"
    st.markdown(
        f"""<div style="text-align:center;padding:14px 10px;
                        background:linear-gradient(145deg,#080e1a,#0d1626);
                        border-radius:14px;border:1px solid {score_color}33;
                        border-top:2px solid {score_color};margin-bottom:10px;
                        box-shadow:0 4px 20px rgba(0,0,0,.3),0 0 30px {score_color}08;">
                <div style="font-size:42px;font-weight:900;color:{score_color};
                            letter-spacing:-.04em;line-height:1;
                            font-family:'Space Grotesk','Inter',sans-serif;">{score:.0f}</div>
                <div style="font-size:9px;color:{score_color}88;letter-spacing:.12em;
                            font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace;">
                    {_score_label}</div>
                <div style="font-size:9px;color:#4a617a;letter-spacing:.08em;
                            margin-top:1px;font-family:'JetBrains Mono',monospace;">HEALTH SCORE</div>
            </div>""",
        unsafe_allow_html=True,
    )

    # Quick stats
    incidents_open   = sum(1 for i in orchestrator.state.get_all_incidents().values()
                           if i["status"] in {"new", "investigating"})
    anomaly_count    = len(orchestrator.telemetry.detect_anomalies())
    active_wf        = len(tracker.get_active_runs())
    pending_approvals_count = len(getattr(monitor, "pending_approvals", {}))

    _inc_color  = "#ff4560" if incidents_open  > 0 else "#00e676"
    _ano_color  = "#ffb300" if anomaly_count   > 0 else "#00e676"
    _wf_color   = "#4d8fff"
    _apr_color  = "#ff4560" if pending_approvals_count > 0 else "#4a617a"

    st.markdown(
        f"""
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:10px 0;">
          <div style="background:linear-gradient(145deg,#080e1a,#0d1626);
                      border:1px solid {_inc_color}44;border-top:2px solid {_inc_color};
                      border-radius:10px;padding:12px 10px;text-align:center;">
            <div style="font-size:26px;font-weight:900;color:{_inc_color};
                        font-family:'Space Grotesk','Inter',sans-serif;line-height:1;">
              {incidents_open}</div>
            <div style="font-size:9px;color:#4a617a;letter-spacing:.1em;
                        font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace;">
              INCIDENTS</div>
          </div>
          <div style="background:linear-gradient(145deg,#080e1a,#0d1626);
                      border:1px solid {_ano_color}44;border-top:2px solid {_ano_color};
                      border-radius:10px;padding:12px 10px;text-align:center;">
            <div style="font-size:26px;font-weight:900;color:{_ano_color};
                        font-family:'Space Grotesk','Inter',sans-serif;line-height:1;">
              {anomaly_count}</div>
            <div style="font-size:9px;color:#4a617a;letter-spacing:.1em;
                        font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace;">
              ANOMALIES</div>
          </div>
          <div style="background:linear-gradient(145deg,#080e1a,#0d1626);
                      border:1px solid {_wf_color}44;border-top:2px solid {_wf_color};
                      border-radius:10px;padding:12px 10px;text-align:center;">
            <div style="font-size:26px;font-weight:900;color:{_wf_color};
                        font-family:'Space Grotesk','Inter',sans-serif;line-height:1;">
              {active_wf}</div>
            <div style="font-size:9px;color:#4a617a;letter-spacing:.1em;
                        font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace;">
              WORKFLOWS</div>
          </div>
          <div style="background:linear-gradient(145deg,#080e1a,#0d1626);
                      border:1px solid {_apr_color}44;border-top:2px solid {_apr_color};
                      border-radius:10px;padding:12px 10px;text-align:center;">
            <div style="font-size:26px;font-weight:900;color:{_apr_color};
                        font-family:'Space Grotesk','Inter',sans-serif;line-height:1;">
              {pending_approvals_count}</div>
            <div style="font-size:9px;color:#4a617a;letter-spacing:.1em;
                        font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace;">
              APPROVALS</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if pending_approvals_count:
        st.markdown(
            f"""<div style="background:linear-gradient(135deg,#ff456022,#ff456008);
                            border:1px solid #ff456066;border-left:3px solid #ff4560;
                            border-radius:8px;padding:8px 12px;margin-top:4px;
                            font-size:11px;color:#ff4560;font-weight:600;
                            font-family:'JetBrains Mono',monospace;">
                  ⚠ {pending_approvals_count} fix(es) awaiting approval
                </div>""",
            unsafe_allow_html=True,
        )

    st.divider()

    # Navigation
    st.markdown(
        "<div style='font-size:10px;font-weight:700;letter-spacing:.12em;color:#4a617a;"
        "text-transform:uppercase;margin-bottom:6px;font-family:\"JetBrains Mono\",monospace;'>"
        "Navigation</div>",
        unsafe_allow_html=True,
    )
    current_ws = st.session_state["workspace"]
    for ws_id, icon, label in WORKSPACES:
        badge = f" ({pending_approvals_count})" if ws_id == "Workflows" and pending_approvals_count else ""
        btn_type = "primary" if ws_id == current_ws else "secondary"
        if st.button(f"{icon} {label}{badge}", key=f"ws_{ws_id}",
                     use_container_width=True, type=btn_type):
            st.session_state["workspace"] = ws_id
            st.rerun()

    st.divider()
    st.markdown(
        "<div style='font-size:10px;font-weight:700;letter-spacing:.12em;color:#4a617a;"
        "text-transform:uppercase;margin-bottom:6px;font-family:\"JetBrains Mono\",monospace;'>"
        "System</div>",
        unsafe_allow_html=True,
    )
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
    st.markdown(
        "<div style='font-size:10px;font-weight:700;letter-spacing:.12em;color:#4a617a;"
        "text-transform:uppercase;margin-bottom:6px;font-family:\"JetBrains Mono\",monospace;'>"
        "GNS3 / Tunnel</div>",
        unsafe_allow_html=True,
    )
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
    score_color = "#ff4560" if score < 60 else "#ffb300" if score < 80 else "#00e676"
    pending_cnt = len(getattr(monitor, "pending_approvals", {}))
    _inc_color  = "#ff4560" if open_inc else "#1c2d44"
    _anom_color = "#ffb300" if anomalies else "#1c2d44"
    _pend_color = "#ffb300" if pending_cnt else "#1c2d44"

    def _stat_card(value, label, accent, icon=""):
        return f"""
        <div style="flex:1;min-width:130px;background:linear-gradient(145deg,#080e1a,#0d1626);
                    border:1px solid {accent}33;border-left:3px solid {accent};border-radius:14px;
                    padding:16px 18px;position:relative;overflow:hidden;
                    box-shadow:0 4px 20px rgba(0,0,0,.3),0 0 30px {accent}08;">
            <div style="position:absolute;top:0;right:0;width:60px;height:60px;
                        background:radial-gradient(circle at 80% 20%,{accent}10,transparent 70%);"></div>
            <div style="font-size:30px;font-weight:900;color:{accent};letter-spacing:-.03em;
                        font-family:'Space Grotesk','Inter',sans-serif;">{value}</div>
            <div style="font-size:10px;color:#4a617a;letter-spacing:.1em;text-transform:uppercase;
                        font-weight:700;margin-top:4px;font-family:'JetBrains Mono',monospace;">
                {icon} {label}</div>
        </div>"""

    st.markdown(f"""
    <div style="display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap;">
        {_stat_card(f"{score:.0f}%", "Health Score", score_color, "❤")}
        {_stat_card(open_inc, "Open Incidents", _inc_color, "🚨")}
        {_stat_card(len(anomalies), "Anomalies", _anom_color, "⚡")}
        {_stat_card(pending_cnt, "Awaiting Approval", _pend_color, "⏳")}
        {_stat_card(st.session_state['total_fixes_executed'], "Fixes Applied", "#00e676", "✅")}
    </div>""", unsafe_allow_html=True)

    # ── Alert ticker ──────────────────────────────────────────────────────────
    live_alerts = st.session_state["live_alerts"]
    critical_alerts = [a for a in live_alerts if a["severity"] in ("critical", "high")]
    if critical_alerts:
        msgs = "  &nbsp;·&nbsp;  ".join(
            f"🔴 {a['message']} <span style='color:#4a617a'>({a['timestamp'][-8:]})</span>"
            for a in critical_alerts[:4]
        )
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,rgba(255,69,96,.12),rgba(255,69,96,.04));
                    border:1px solid rgba(255,69,96,.3);border-radius:10px;
                    padding:10px 16px;font-size:12px;color:#ff7a8a;margin-bottom:14px;
                    display:flex;align-items:center;gap:10px;overflow:hidden;
                    box-shadow:0 0 30px rgba(255,69,96,.06);">
            <span style="background:rgba(255,69,96,.2);border:1px solid rgba(255,69,96,.4);
                         border-radius:6px;padding:2px 8px;font-size:10px;font-weight:700;
                         color:#ff4560;letter-spacing:.08em;white-space:nowrap;
                         font-family:'JetBrains Mono',monospace;">🚨 LIVE</span>
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{msgs}</span>
        </div>""", unsafe_allow_html=True)

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
                    st.warning("AI is unavailable (check GROQ_API_KEY). "
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
# WORKSPACE: INTELLIGENCE (the AI Brain — powered by Operational Memory)
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "intelligence":
    try:
        from ui.intelligence_center import render_intelligence_center
        render_intelligence_center()
    except Exception as _ic_exc:
        st.markdown("## 🧠 Intelligence Center")
        st.error(f"Intelligence Center failed to load: {_ic_exc}")

# ══════════════════════════════════════════════════════════════════════════════
# WORKSPACE: ADMIN
# ══════════════════════════════════════════════════════════════════════════════
elif workspace == "admin":
    st.markdown("## ⚙️ Administration")
    st.caption("Configure connection settings, credentials, thresholds, and system actions.")

    tab_conn, tab_creds, tab_thresh, tab_actions, tab_aicfg, tab_devices, tab_topology = st.tabs(
        ["Connection", "Credentials", "Thresholds", "System Actions", "🧠 AI Config", "🖧 Devices", "🗺️ Network Topology"]
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
GROQ_API_KEY = "your-key-here"
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
        st.markdown("### Groq AI Key")
        with st.form("ai_form"):
            new_ai_key = st.text_input("GROQ_API_KEY", value=os.environ.get("GROQ_API_KEY",""),
                                       type="password")
            if st.form_submit_button("Save AI Key"):
                os.environ["GROQ_API_KEY"] = new_ai_key
                st.success("AI key updated. Restart the app if the AI client was already cached.")

        st.caption(f"Current model: `{MODEL_NAME}`  ·  set `OPENROUTER_MODEL` in Secrets to change it.")
        if st.button("🔌 Test AI Connection"):
            with st.spinner("Calling Groq..."):
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
                               "`llama-3.3-70b-versatile`, `openrouter/free`.")

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
                st.caption("Check that GROQ_API_KEY is set in Secrets.")

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

            # ════════════════════════════════════════════════════════════════
            # DEVICE INFO — collapsible, select devices to scope AI
            # ════════════════════════════════════════════════════════════════
            _di_approved = disc.get_approved() if DISC_OK else []

            # Session-state for scope selection (persists across reruns)
            _scope_key = "ai_scope_selected_ips"
            if _scope_key not in st.session_state:
                st.session_state[_scope_key] = set()

            # Auto-clean: remove disapproved IPs from scope
            _approved_ips_now = {d.ip for d in _di_approved}
            st.session_state[_scope_key] = {
                ip for ip in st.session_state[_scope_key] if ip in _approved_ips_now
            }

            # ── Robot icon overlay using a label trick ────────────────────
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

            # ── Scope indicator banner — always visible ───────────────────
            _scope_ips = st.session_state[_scope_key]
            _scope_count = len(_scope_ips)
            if _scope_count == 0:
                _scope_msg = (
                    "🛑 **AI Scope:** No devices selected → AI is **disabled**.<br>"
                    "<span style='color:#94a3b8;font-size:.78rem'>"
                    "Open <b>📋 Device Info</b> below and check at least one device "
                    "to enable the AI Assistant.</span>"
                )
                _scope_color = "#dc2626"
            else:
                _scope_names = ", ".join(
                    (d.hostname or d.ip) for d in _di_approved if d.ip in _scope_ips
                )
                _scope_msg = (
                    f"🎯 **AI Scope:** {_scope_count} device{'s' if _scope_count != 1 else ''} "
                    f"selected → <code style='color:#22d3ee'>{_scope_names}</code><br>"
                    f"<span style='color:#94a3b8;font-size:.78rem'>"
                    f"AI will run commands ONLY on these devices. Other devices will not be touched.</span>"
                )
                _scope_color = "#16a34a"

            st.markdown(
                f"<div style='background:#0c1826;border-left:3px solid {_scope_color};"
                f"border-radius:6px;padding:.55rem .9rem;margin:.5rem 0 .6rem 0;"
                f"color:#cbd5e1;font-size:.85rem'>{_scope_msg}</div>",
                unsafe_allow_html=True,
            )

            # ── AI submission — STAGE 1: Propose Plan ─────────────────────
            if _ai_q and _ai_q != st.session_state.get("devices_ai_last_q"):
                st.session_state["devices_ai_last_q"] = _ai_q

                # ── HARD GATE: no selection = no AI action ─────────────────
                if not _scope_ips:
                    st.session_state["devices_ai_last_ans"] = (
                        "🛑 **AI is disabled — no devices selected.**\n\n"
                        "Open the **📋 Device Info** table below and check at least one "
                        "device to scope the AI. AI will not run on any device until you "
                        "explicitly select one."
                    )
                    st.session_state["devices_ai_last_result"] = {}
                    st.session_state["devices_ai_plan"] = None
                else:
                    _targets = [d for d in _di_approved if d.ip in _scope_ips]
                    try:
                        _ie_scope = IntentEngine(
                            ai_call=call_ai,
                            approved_devices=_targets,
                        )
                        _scope_label = (
                            ", ".join((d.hostname or d.ip) for d in _targets)
                            if len(_targets) <= 5
                            else f"{len(_targets)} devices"
                        )
                        with st.spinner(f"🧠 NetBrain AI thinking about {_scope_label}…"):
                            _ie_res = _ie_scope.propose_plan(
                                query=_ai_q,
                                devices=_targets,
                            )
                        st.session_state["devices_ai_last_ans"] = (
                            IntentEngine.format_for_chat(_ie_res, _scope_label)
                        )
                        # Save plan + result for stage 2
                        st.session_state["devices_ai_plan"] = (
                            _ie_res.plan if _ie_res.plan_pending else None
                        )
                        st.session_state["devices_ai_last_result"] = {
                            "plan_pending":   _ie_res.plan_pending,
                            "needs_approval": _ie_res.needs_approval,
                            "fix_commands":   _ie_res.fix_commands,
                            "commands_per_device": _ie_res.commands_per_device,
                            "verify_commands": _ie_res.verify_commands,
                            "target_ips":     [d.ip for d in _targets],
                            "scope_label":    _scope_label,
                            "query":          _ai_q,
                        }
                    except Exception as _ie_err:
                        st.session_state["devices_ai_last_ans"] = (
                            f"⚠️ Engine error: {_ie_err}"
                        )
                        st.session_state["devices_ai_last_result"] = {}
                        st.session_state["devices_ai_plan"] = None

            # ── Show answer ───────────────────────────────────────────────
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

                _ai_pend = st.session_state.get("devices_ai_last_result", {})

                # ── STAGE 1 APPROVAL: Plan pending → Run Plan / Cancel ────
                if _ai_pend.get("plan_pending") and st.session_state.get("devices_ai_plan"):
                    _pcol1, _pcol2 = st.columns(2)
                    with _pcol1:
                        if st.button(
                            f"✅ Run Plan on {_ai_pend.get('scope_label', 'devices')}",
                            key="devices_ai_run_plan",
                            type="primary",
                            use_container_width=True,
                        ):
                            _plan = st.session_state["devices_ai_plan"]
                            _ips = _ai_pend["target_ips"]
                            _tdevs = [d for d in _di_approved if d.ip in _ips]
                            try:
                                _ie2 = IntentEngine(
                                    ai_call=call_ai,
                                    approved_devices=_tdevs,
                                )
                                with st.spinner(
                                    f"🔌 Running plan on {_ai_pend['scope_label']} & analyzing…"
                                ):
                                    _ie_res2 = _ie2.execute_plan(
                                        plan=_plan,
                                        all_devices=_tdevs,
                                    )
                                st.session_state["devices_ai_last_ans"] = (
                                    IntentEngine.format_for_chat(_ie_res2, _ai_pend["scope_label"])
                                )
                                st.session_state["devices_ai_last_result"] = {
                                    "plan_pending":   False,
                                    "needs_approval": _ie_res2.needs_approval,
                                    "fix_commands":   _ie_res2.fix_commands,
                                    "target_ips":     _ai_pend["target_ips"],
                                    "scope_label":    _ai_pend["scope_label"],
                                }
                                st.session_state["devices_ai_plan"] = None
                            except Exception as _ee:
                                st.session_state["devices_ai_last_ans"] = (
                                    f"⚠️ Execute error: {_ee}"
                                )
                            st.rerun()

                    with _pcol2:
                        if st.button(
                            "❌ Cancel Plan",
                            key="devices_ai_cancel_plan",
                            use_container_width=True,
                        ):
                            st.session_state["devices_ai_last_ans"] = (
                                "❌ Plan cancelled. No commands were run."
                            )
                            st.session_state["devices_ai_last_result"] = {}
                            st.session_state["devices_ai_plan"] = None
                            st.rerun()

                # ── STAGE 2 APPROVAL: Config fix pending → Deploy / Discard ──
                elif _ai_pend.get("needs_approval") and _ai_pend.get("fix_commands"):
                    _pcol1, _pcol2 = st.columns(2)
                    with _pcol1:
                        if st.button(
                            f"✅ Deploy Fix to {_ai_pend.get('scope_label', 'devices')}",
                            key="devices_ai_deploy",
                            type="primary",
                            use_container_width=True,
                        ):
                            _ips = _ai_pend["target_ips"]
                            _tdevs = [d for d in _di_approved if d.ip in _ips]
                            _dep_log = []
                            for _td in _tdevs:
                                with st.spinner(f"⚙️ Deploying on {_td.hostname or _td.ip}…"):
                                    try:
                                        # Use the SAME connection layer as topology
                                        # discovery (SSH→Telnet fallback + per-device
                                        # credentials + device_type normalization),
                                        # instead of a brittle SSH-only ConnectHandler.
                                        # That mismatch is why deploy failed with "TCP
                                        # connection failed" on devices discovery polls
                                        # fine.
                                        from core.topology.discovery import (
                                            _establish_connection, _base_platform,
                                        )
                                        from core.topology.credentials import resolve_device_credentials
                                        _du, _dp, _dsec = resolve_device_credentials(_td.ip)
                                        _dbase = _base_platform(getattr(_td, "device_type", ""))
                                        _dconn, _dmethod = _establish_connection(
                                            _td, _dbase, _du, _dp, _dsec,
                                        )
                                        try:
                                            _dconn.enable()
                                        except Exception:
                                            pass
                                        # Session/mode commands must NOT be sent as
                                        # standalone send_command() calls. `enable` is
                                        # already handled by _dconn.enable() above, and
                                        # `configure terminal`/`end`/`exit` are handled by
                                        # send_config_set() itself. Sending "configure
                                        # terminal" via send_command() flips the prompt to
                                        # (config)# and netmiko hangs waiting for the base
                                        # prompt -- the exact cause of the deploy error.
                                        _SKIP_CMDS = {
                                            "enable", "configure terminal", "conf t",
                                            "end", "exit", "write memory", "wr", "wr mem",
                                            "copy running-config startup-config",
                                            "copy run start",
                                        }
                                        # Per-device commands grounded in THIS router's real
                                        # interfaces. Fall back to the merged list only if a
                                        # per-device set wasn't generated (legacy/safety).
                                        _pdcmds = (_ai_pend.get("commands_per_device") or {}).get(
                                            _td.ip, _ai_pend.get("fix_commands", [])
                                        )
                                        _cfgc = [
                                            _s for c in _pdcmds if "[CONFIG]" in c
                                            for _s in [c.replace("[CONFIG]", "").strip()]
                                            if _s and _s.lower() not in _SKIP_CMDS
                                        ]
                                        _execc = [
                                            _s for c in _pdcmds if "[EXEC]" in c
                                            for _s in [c.replace("[EXEC]", "").strip()]
                                            if _s and _s.lower() not in _SKIP_CMDS
                                        ]
                                        _logs = []
                                        if not _cfgc and not _execc:
                                            _logs.append("(no applicable config for this router — "
                                                         "its interfaces don't match the request)")
                                        for _ec in _execc:
                                            # send_command_timing reads until output
                                            # settles instead of matching an exact prompt
                                            # pattern -- avoids "Pattern not detected" on
                                            # GNS3 routers whose prompt echo is flaky.
                                            _o = _dconn.send_command_timing(_ec, read_timeout=20)
                                            _logs.append(f"$ {_ec}\n{_o}")
                                        if _cfgc:
                                            # cmd_verify=False disables per-command prompt
                                            # echo verification -- the source of the
                                            # "Pattern not detected: 'R1#'" error on lab
                                            # devices. The config still applies; we just
                                            # don't demand a perfectly-echoed prompt after
                                            # each line. read_timeout is generous for slow
                                            # GNS3 links.
                                            _o = _dconn.send_config_set(
                                                _cfgc, cmd_verify=False, read_timeout=60,
                                            )
                                            _logs.append(f"[CONFIG]\n{_o}")
                                        # ── SAVE, then PROVE the outcome with the AI-driven
                                        # OUTCOME CONTRACT. Nothing here is hardcoded per
                                        # protocol: the AI derives the post-conditions for
                                        # THIS intent (including persistence — so "forgot
                                        # write memory" is impossible by construction),
                                        # runs the checks live, re-polls anything still
                                        # converging, and interprets each result by reading
                                        # the evidence. Works for OSPF, BGP, interfaces,
                                        # any vendor — the model decides what success means.
                                        if _cfgc:
                                            try:
                                                _sv = _dconn.save_config()
                                                _logs.append(f"[SAVE] {_sv}")
                                            except Exception as _se:
                                                _logs.append(f"[SAVE] FAILED: {_se}")

                                        _contract = None
                                        if _cfgc:
                                            try:
                                                from core.intelligence.outcome_contract import OutcomeContractEngine
                                                _oce = OutcomeContractEngine(ai_call=call_ai)

                                                def _run_show(cmd, _c=_dconn):
                                                    try:
                                                        return _c.send_command(cmd, read_timeout=30, expect_string=r"#")
                                                    except Exception as _e:
                                                        return f"(command error: {_e})"

                                                _contract = _oce.enforce(
                                                    intent=_ai_pend.get("query") or _ai_pend.get("scope_label") or "configuration change",
                                                    device_name=_td.hostname or _td.ip,
                                                    applied_commands=_cfgc,
                                                    run_command=_run_show,
                                                    device_facts="",
                                                    converge_timeout_s=45,
                                                    poll_interval_s=5,
                                                )
                                                _logs.append(_contract.to_log())

                                                # ── AUTO-WRITE OPERATIONAL MEMORY ──
                                                # Every verified change records itself: the
                                                # platform accumulates experience automatically,
                                                # no manual step. Protocol is derived from the
                                                # intent; site comes from the device.
                                                try:
                                                    from core.intelligence.operational_memory import get_operational_memory
                                                    _intent_l = (_ai_pend.get("query") or "").lower()
                                                    _proto = next((p for p in
                                                        ("ospf","bgp","eigrp","rip","isis","mpls","vlan",
                                                         "interface","acl","nat","hsrp","vrrp","stp")
                                                        if p in _intent_l), "")
                                                    get_operational_memory().record_from_contract(
                                                        _contract,
                                                        site=getattr(_td, "site_name", "") or "",
                                                        protocol=_proto,
                                                        operator="",
                                                        commands=_cfgc,
                                                    )
                                                    # ── CONSOLIDATE INTO DERIVED MEMORY ──
                                                    # Same verified contract fans out into every
                                                    # derived memory (procedural/experience/failure/
                                                    # pattern/temporal/trust/verification/…), so the
                                                    # platform turns this episode into expertise, not
                                                    # just a log line.
                                                    try:
                                                        from core.intelligence.memory import get_memory_system
                                                        get_memory_system().record_from_contract(
                                                            _contract,
                                                            site=getattr(_td, "site_name", "") or "",
                                                            protocol=_proto,
                                                            operator="",
                                                            commands=_cfgc,
                                                        )
                                                    except Exception as _cme:
                                                        _logs.append(f"[MEMORY+] not consolidated: {_cme}")
                                                except Exception as _me:
                                                    _logs.append(f"[MEMORY] not recorded: {_me}")
                                            except Exception as _ce:
                                                _logs.append(f"[CONTRACT] could not run outcome contract: {_ce}")

                                        _dconn.disconnect()

                                        # ── OUTCOME HEADER reflects the proven contract ──
                                        if _contract is not None:
                                            if _contract.satisfied:
                                                _hdr = f"✅ **{_td.hostname or _td.ip}** — outcome verified ({_contract.summary})"
                                            else:
                                                _hdr = f"⚠️ **{_td.hostname or _td.ip}** — applied, outcome NOT fully proven: {_contract.summary}"
                                        elif _cfgc:
                                            _hdr = f"✅ **{_td.hostname or _td.ip}** — applied & saved"
                                        else:
                                            _hdr = f"✅ **{_td.hostname or _td.ip}**"
                                        _dep_log.append(
                                            _hdr + "\n```\n" + "\n".join(_logs) + "\n```"
                                        )
                                    except Exception as _de:
                                        _dep_log.append(
                                            f"❌ **{_td.hostname or _td.ip}**: {_de}"
                                        )
                            st.session_state["devices_ai_last_ans"] = (
                                "**✅ Deployment complete**\n\n" + "\n\n".join(_dep_log)
                            )
                            st.session_state["devices_ai_last_result"] = {}
                            st.rerun()
                    with _pcol2:
                        if st.button(
                            "❌ Discard Fix",
                            key="devices_ai_discard",
                            use_container_width=True,
                        ):
                            st.session_state["devices_ai_last_ans"] = (
                                "❌ Fix discarded. No changes were made."
                            )
                            st.session_state["devices_ai_last_result"] = {}
                            st.rerun()

            # ════════════════════════════════════════════════════════════════
            # DEVICE INFO — select devices to scope AI
            # ════════════════════════════════════════════════════════════════
            with st.expander(
                f"📋 Device Info  ({len(_di_approved)} approved · "
                f"{_scope_count} selected for AI scope)",
                expanded=False,
            ):
                if not _di_approved:
                    st.caption("No approved devices yet. Approve from the Pending section below.")
                else:
                    # ── Search + bulk actions row ──────────────────────────
                    _di_sc1, _di_sc2, _di_sc3 = st.columns([3, 1, 1])
                    with _di_sc1:
                        _di_query = st.text_input(
                            label="device_info_search",
                            label_visibility="collapsed",
                            placeholder="🔍  Search by hostname, IP, site, or city…",
                            key="device_info_search_input",
                        )
                    with _di_sc2:
                        if st.button("☑ Select All", key="di_select_all",
                                     use_container_width=True):
                            st.session_state[_scope_key] = set(_approved_ips_now)
                            st.rerun()
                    with _di_sc3:
                        if st.button("✖ Clear", key="di_clear_all",
                                     use_container_width=True):
                            st.session_state[_scope_key] = set()
                            st.rerun()

                    _di_q = (_di_query or "").strip().lower()
                    _di_filtered = [
                        d for d in _di_approved
                        if not _di_q
                        or _di_q in (d.hostname or "").lower()
                        or _di_q in d.ip.lower()
                        or _di_q in (d.site_name or "").lower()
                        or _di_q in (d.city or "").lower()
                    ]

                    if not _di_filtered:
                        st.caption(f"No devices match '{_di_query}'.")
                    else:
                        # ── Table header ───────────────────────────────────
                        _h0, _h1, _h2, _h3, _h4, _h5, _h6 = st.columns(
                            [0.5, 1.7, 1.6, 1.2, 1.3, 1.7, 1.0]
                        )
                        _h0.markdown("<small style='color:#475569'><b>✓</b></small>", unsafe_allow_html=True)
                        _h1.markdown("<small style='color:#475569'><b>HOSTNAME</b></small>", unsafe_allow_html=True)
                        _h2.markdown("<small style='color:#475569'><b>IP ADDRESS</b></small>", unsafe_allow_html=True)
                        _h3.markdown("<small style='color:#475569'><b>OEM</b></small>", unsafe_allow_html=True)
                        _h4.markdown("<small style='color:#475569'><b>TYPE</b></small>", unsafe_allow_html=True)
                        _h5.markdown("<small style='color:#475569'><b>SITE</b></small>", unsafe_allow_html=True)
                        _h6.markdown("<small style='color:#475569'><b>STATUS</b></small>", unsafe_allow_html=True)
                        st.markdown(
                            "<hr style='margin:.2rem 0;border-color:#1e3a52'>",
                            unsafe_allow_html=True,
                        )

                        # ── Table rows with checkboxes ─────────────────────
                        for _d in _di_filtered:
                            _sess = disc.get_session(_d.ip) if DISC_OK else None
                            _live = bool(_sess and _sess.status in ("complete", "running"))
                            _is_in_scope = _d.ip in st.session_state[_scope_key]
                            _site_compact = (
                                f"{_d.site_name} · {_d.city}"
                                if _d.site_name else "—"
                            )

                            _c0, _c1, _c2, _c3, _c4, _c5, _c6 = st.columns(
                                [0.5, 1.7, 1.6, 1.2, 1.3, 1.7, 1.0]
                            )
                            with _c0:
                                _chk = st.checkbox(
                                    _d.ip,
                                    value=_is_in_scope,
                                    key=f"di_chk_{_d.ip}",
                                    label_visibility="collapsed",
                                )
                                if _chk and not _is_in_scope:
                                    st.session_state[_scope_key].add(_d.ip)
                                    st.rerun()
                                elif not _chk and _is_in_scope:
                                    st.session_state[_scope_key].discard(_d.ip)
                                    st.rerun()
                            _c1.markdown(
                                f"<span style='color:#e2e8f0;font-weight:600;font-family:monospace;font-size:.85rem'>"
                                f"{_d.hostname or '—'}</span>",
                                unsafe_allow_html=True,
                            )
                            _c2.markdown(
                                f"<span style='color:#94a3b8;font-family:monospace;font-size:.8rem'>{_d.ip}</span>",
                                unsafe_allow_html=True,
                            )
                            _c3.markdown(
                                f"<span style='color:#fbbf24;font-size:.8rem'>{_d.vendor or 'Unknown'}</span>",
                                unsafe_allow_html=True,
                            )
                            _c4.markdown(
                                f"<span style='color:#67e8f9;font-size:.78rem'>{_d.device_type or '—'}</span>",
                                unsafe_allow_html=True,
                            )
                            _c5.markdown(
                                f"<span style='color:#94a3b8;font-size:.78rem' "
                                f"title='{_d.site_name}, {_d.city}, {_d.country}, {_d.region}'>"
                                f"{_site_compact}</span>",
                                unsafe_allow_html=True,
                            )
                            _c6.markdown(
                                f"<span style='color:{'#4ade80' if _live else '#475569'};font-size:.78rem;font-weight:600'>"
                                f"{'● Online' if _live else '○ Idle'}</span>",
                                unsafe_allow_html=True,
                            )

                        st.caption(
                            f"Showing {len(_di_filtered)} of {len(_di_approved)} approved devices · "
                            f"{_scope_count} selected for AI scope. "
                            "Devices disappear automatically when disapproved."
                        )

            st.divider()

            # ── Top action bar ────────────────────────────────────────────────
            col_ping, col_refresh = st.columns([3, 1])
            with col_ping:
                manual_ip = st.text_input(
                    "Ping a specific IP",
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

            # ── Range Scan (RFC 1918) ───────────────────────────────────────────
            with st.expander("🌐 Range Scan — RFC 1918 private space", expanded=False):
                from core.discovery import (
                    RFC1918_RANGES, get_local_subnets, host_count,
                    estimate_scan_seconds, format_duration, parse_cidr,
                    get_range_scanner,
                )

                st.caption(
                    "Discovers devices by TCP-probing SSH/Telnet/HTTP/HTTPS "
                    "ports — no ICMP subprocess per host, so this scales to "
                    "large ranges without requiring sudo."
                )

                _selected_cidrs: List[str] = []

                # — Auto-detected local subnets —
                _local_subnets = get_local_subnets()
                if _local_subnets:
                    st.markdown("**Your machine's connected subnets** (auto-detected)")
                    _local_opts = {
                        f"{s.interface}: {s.cidr} ({s.host_count:,} hosts)": s.cidr
                        for s in _local_subnets
                    }
                    _picked_local = st.multiselect(
                        "local_subnets", list(_local_opts.keys()),
                        default=list(_local_opts.keys()),
                        label_visibility="collapsed", key="dd_local_subnets",
                    )
                    _selected_cidrs += [_local_opts[k] for k in _picked_local]
                else:
                    st.caption(
                        "Local subnet auto-detection unavailable "
                        "(install `psutil` to enable)."
                    )

                # — RFC 1918 presets —
                st.markdown("**RFC 1918 private ranges**")
                for preset in RFC1918_RANGES:
                    _secs = estimate_scan_seconds(preset.host_count, concurrency=300, timeout_sec=0.4)
                    _eta = format_duration(_secs)
                    _label = f"{preset.label} — {preset.host_count:,} hosts, {_eta}"
                    if preset.recommended:
                        _chk = st.checkbox(_label, key=f"dd_rfc_{preset.cidr}")
                        if _chk:
                            _selected_cidrs.append(preset.cidr)
                    else:
                        _c1, _c2 = st.columns([3, 2])
                        with _c1:
                            _chk = st.checkbox(_label, key=f"dd_rfc_{preset.cidr}")
                        with _c2:
                            _confirm = st.checkbox(
                                "I accept the multi-hour scan time",
                                key=f"dd_rfc_confirm_{preset.cidr}",
                            )
                        if _chk and _confirm:
                            _selected_cidrs.append(preset.cidr)
                        elif _chk and not _confirm:
                            st.caption("⚠️ Confirm the time tradeoff to include this range.")

                # — Custom CIDR —
                st.markdown("**Custom range**")
                _custom_cidr = st.text_input(
                    "custom_cidr", placeholder="192.168.96.0/24",
                    label_visibility="collapsed", key="dd_custom_cidr",
                )
                if _custom_cidr.strip():
                    if parse_cidr(_custom_cidr.strip()):
                        _selected_cidrs.append(_custom_cidr.strip())
                    else:
                        st.error(f"'{_custom_cidr}' isn't a valid CIDR (e.g. 192.168.96.0/24).")

                # — Summary + start —
                _total_hosts = sum(host_count(c) for c in _selected_cidrs)
                if _selected_cidrs:
                    _total_secs = estimate_scan_seconds(_total_hosts, concurrency=300, timeout_sec=0.4)
                    st.info(
                        f"**{len(_selected_cidrs)} range(s) selected** · "
                        f"{_total_hosts:,} addresses · est. {format_duration(_total_secs)}"
                    )

                _net_eq_only = st.checkbox(
                    "🛡️ Networking equipment only",
                    value=True, key="dd_net_eq_only",
                    help="In an enterprise network, a range scan finds servers, "
                         "CCTV, printers, etc. alongside real network gear. With "
                         "this on, a device is only added to the pending queue if "
                         "its banner positively matches a known network vendor "
                         "(Cisco, Juniper, Arista, Palo Alto, Fortinet, Aruba, "
                         "Huawei, Check Point, and others). Everything else shows "
                         "up below as filtered, not silently dropped.",
                )

                _active_job_key = "dd_range_scan_job_id"
                _scan_running = False
                if st.session_state.get(_active_job_key):
                    _prog = get_range_scanner().get_progress(st.session_state[_active_job_key])
                    _scan_running = bool(_prog and _prog.status == "running")

                _s1, _s2 = st.columns(2)
                with _s1:
                    if st.button(
                        "🚀 Start Range Scan", type="primary", width='stretch',
                        disabled=(not _selected_cidrs or _scan_running),
                        key="dd_start_range_scan",
                    ):
                        job_id = disc.scan_ranges(_selected_cidrs, network_equipment_only=_net_eq_only)
                        st.session_state[_active_job_key] = job_id
                        st.rerun()
                with _s2:
                    if st.button(
                        "⏹ Cancel Scan", width='stretch',
                        disabled=not _scan_running, key="dd_cancel_range_scan",
                    ):
                        get_range_scanner().cancel(st.session_state[_active_job_key])
                        st.rerun()

                # — Live progress —
                if st.session_state.get(_active_job_key):
                    _prog = get_range_scanner().get_progress(st.session_state[_active_job_key])
                    if _prog:
                        st.progress(_prog.percent() / 100.0)
                        _status_icon = {"running": "🔵", "done": "✅",
                                         "cancelled": "⏹", "error": "🔴"}.get(_prog.status, "•")
                        st.caption(
                            f"{_status_icon} {_prog.status.upper()} · "
                            f"{_prog.scanned:,} / {_prog.total_addresses:,} scanned · "
                            f"{len(_prog.found)} found · {_prog.elapsed_sec():.0f}s elapsed"
                        )
                        if _prog.status == "running":
                            st.caption("Click **🔄 Refresh** above to update progress.")
                        elif _prog.status == "done":
                            st.success(f"Scan complete — {len(_prog.found)} device(s) added to pending queue.")
                        elif _prog.error:
                            st.error(f"Scan error: {_prog.error}")

                # — Filtered non-network devices (transparency, not a silent drop) —
                _filtered = disc.get_filtered_non_network()
                if _filtered:
                    with st.expander(f"🚫 Filtered — {len(_filtered)} non-network device(s)", expanded=False):
                        st.caption(
                            "These answered a TCP probe but didn't match a known "
                            "network-vendor banner signature — likely servers, "
                            "CCTV, printers, or other non-networking devices. If "
                            "one of these IS real network gear, tell me the IP "
                            "and banner text below and I'll add its signature."
                        )
                        for f in _filtered[-50:]:
                            st.caption(f"`{f['ip']}` — {f['banner']}")
                        if st.button("Clear filtered list", key="dd_clear_filtered"):
                            disc.clear_filtered_non_network()
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
                from core.device_inventory_meta import REGIONS, countries_for_region

                for dev in pending:
                    ports_str = ", ".join(str(p) for p in dev.open_ports) or "none detected"
                    _display_name = dev.hostname if dev.hostname else "Resolving name..."
                    _name_style = "color:#f1f5f9" if dev.hostname else "color:#94a3b8;font-style:italic"
                    _vendor_str = dev.vendor or "Unknown"
                    with st.container():
                        st.markdown(f"""
                        <div class='dd-card dd-card-pending'>
                          <span class='dd-hostname' style='{_name_style}'>{_display_name}</span>
                          &nbsp;&nbsp;<span class='dd-ip'>{dev.ip}</span>
                          &nbsp;&nbsp;<span class='dd-badge dd-badge-pending'>⏳ PENDING</span>
                          <br><span class='dd-meta'>
                            OEM: {_vendor_str} &nbsp;·&nbsp;
                            Type: {dev.device_type} &nbsp;·&nbsp;
                            Source: {dev.source} &nbsp;·&nbsp;
                            Open ports: {ports_str} &nbsp;·&nbsp;
                            First seen: {dev.first_seen}
                          </span>
                        </div>
                        """, unsafe_allow_html=True)

                        _form_open_key = f"approve_form_open_{dev.ip}"

                        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])
                        with btn_col1:
                            if st.button(f"✅ Approve", key=f"approve_{dev.ip}",
                                         use_container_width=True, type="primary"):
                                st.session_state[_form_open_key] = True
                                st.rerun()
                        with btn_col2:
                            if st.button(f"❌ Reject", key=f"reject_{dev.ip}",
                                         use_container_width=True):
                                disc.reject_device(dev.ip)
                                st.rerun()
                        with btn_col3:
                            _type_options = ["cisco_ios", "cisco_ios_xe", "cisco_nxos",
                                              "juniper_junos", "arista_eos", "paloalto_panos",
                                              "fortinet", "aruba_os", "linux", "cisco_ios_telnet"]
                            override_type = st.selectbox(
                                "Override device type",
                                _type_options,
                                key=f"dtype_{dev.ip}",
                                index=_type_options.index(dev.device_type)
                                       if dev.device_type in _type_options else 0,
                            )
                            dev.device_type = override_type

                        # ── Site metadata form — required before approval completes ──
                        if st.session_state.get(_form_open_key):
                            with st.container():
                                st.markdown(
                                    "<div style='background:#0c1826;border:1px solid #1e3a52;"
                                    "border-radius:8px;padding:.75rem 1rem;margin:.4rem 0'>"
                                    "<span style='color:#22d3ee;font-size:.78rem;font-weight:700;"
                                    "text-transform:uppercase;letter-spacing:.04em'>"
                                    "📍 Site Details Required to Approve</span></div>",
                                    unsafe_allow_html=True,
                                )
                                _r1, _r2 = st.columns(2)
                                with _r1:
                                    _sel_region = st.selectbox(
                                        "Region", REGIONS,
                                        key=f"region_{dev.ip}",
                                    )
                                with _r2:
                                    _country_opts = countries_for_region(_sel_region)
                                    _sel_country = st.selectbox(
                                        "Country", _country_opts,
                                        key=f"country_{dev.ip}",
                                    )
                                _r3, _r4 = st.columns(2)
                                with _r3:
                                    _sel_city = st.text_input(
                                        "City", key=f"city_{dev.ip}",
                                        placeholder="e.g. Bengaluru",
                                    )
                                with _r4:
                                    _sel_site = st.text_input(
                                        "Site Name", key=f"site_{dev.ip}",
                                        placeholder="e.g. DC-Blr-01",
                                    )

                                _fc1, _fc2 = st.columns(2)
                                with _fc1:
                                    if st.button(
                                        "✅ Confirm Approval",
                                        key=f"confirm_approve_{dev.ip}",
                                        type="primary",
                                        use_container_width=True,
                                    ):
                                        if not (_sel_region and _sel_country
                                                and _sel_city.strip() and _sel_site.strip()):
                                            st.error(
                                                "All four fields (Region, Country, City, "
                                                "Site Name) are required before approval."
                                            )
                                        else:
                                            ok = disc.approve_device(
                                                dev.ip,
                                                approved_by="admin",
                                                region=_sel_region,
                                                country=_sel_country,
                                                city=_sel_city.strip(),
                                                site_name=_sel_site.strip(),
                                            )
                                            if ok:
                                                st.session_state.pop(_form_open_key, None)
                                                st.success(
                                                    f"✅ {dev.ip} approved — "
                                                    f"{_sel_site.strip()}, {_sel_city.strip()}, "
                                                    f"{_sel_country}, {_sel_region}"
                                                )
                                                st.rerun()
                                            else:
                                                st.error("Approval failed — please retry.")
                                with _fc2:
                                    if st.button(
                                        "✖ Cancel",
                                        key=f"cancel_approve_{dev.ip}",
                                        use_container_width=True,
                                    ):
                                        st.session_state.pop(_form_open_key, None)
                                        st.rerun()

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
                    _site_str = (
                        f"{dev.site_name}, {dev.city}, {dev.country} ({dev.region})"
                        if dev.site_name else "Site: not set"
                    )

                    st.markdown(f"""
                    <div class='dd-card {_card_cls}'>
                      <span class='dd-hostname'>{_live_name}</span>
                      &nbsp;&nbsp;<span class='dd-ip'>{dev.ip}</span>
                      &nbsp;&nbsp;<span class='dd-badge dd-badge-approved'>✅ APPROVED</span>
                      &nbsp;&nbsp;<span class='dd-meta'>{_health_icon} Health: <span class='{_health_cls}'>{_health}</span>
                      &nbsp;·&nbsp; Status: {sess_status or "idle"}
                      &nbsp;·&nbsp; Steps: {len(session.steps) if session else 0}</span>
                      <br><span class='dd-meta'>
                        OEM: {dev.vendor or "Unknown"} &nbsp;·&nbsp;
                        Type: {dev.device_type} &nbsp;·&nbsp;
                        Ports: {", ".join(str(p) for p in dev.open_ports) or "—"} &nbsp;·&nbsp;
                        Added: {dev.first_seen}
                      </span>
                      <br><span class='dd-meta'>📍 {_site_str}</span>
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

                    # Button 3 — AI Diagnose (login required)
                    # Compute login status here so it's available for both
                    # the AI Diagnose button and the chat bar below
                    _login_ok_early = (
                        session is not None
                        and session.status == "complete"
                        and any(
                            s.get("name") in ("Login", "SSH Login") and s.get("ok")
                            for s in (session.steps or [])
                        )
                    )
                    with _b3:
                        if st.button(
                            "⏳ Running…" if _ts_running else "🤖 AI Diagnose",
                            key=f"ai_ts_{dev.ip}",
                            disabled=_ts_running,
                            type="primary",
                            use_container_width=True,
                            help="Full diagnostics + AI fix plan (login required)",
                        ):
                            if not _login_ok_early:
                                st.warning("🔐 Please click **Login** first before running AI Diagnose.")
                                st.rerun()
                            else:
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
                    # Login is mandatory before any chat operation
                    # Reuse _login_ok_early computed above for AI Diagnose button
                    _login_ok = _login_ok_early
                    with _bai:
                        if _login_ok:
                            _ai_nlp_q = st.text_input(
                                label=f"ai_nlp_{dev.ip}",
                                label_visibility="collapsed",
                                placeholder="🤖  AI Assistant — ask about config, logs, BGP, traps, debug...",
                                key=f"ai_nlp_input_{dev.ip}",
                            )
                        else:
                            st.text_input(
                                label=f"ai_nlp_{dev.ip}",
                                label_visibility="collapsed",
                                placeholder="🔐  Login required before using AI Assistant...",
                                key=f"ai_nlp_input_{dev.ip}",
                                disabled=True,
                            )
                            _ai_nlp_q = ""

                    st.markdown("</div>", unsafe_allow_html=True)

                    # Show login required notice below the bar
                    if not _login_ok:
                        st.warning(
                            "🔐 **Login required** — click the **Login** button above "
                            "to establish an SSH session before using AI Assistant.",
                            icon="🔐",
                        )

                    # ── Handle AI Assistant NLP submission ────────────────────
                    _nlp_last_key = f"ai_nlp_last_{dev.ip}"
                    if _login_ok and _ai_nlp_q and _ai_nlp_q != st.session_state.get(_nlp_last_key):
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
                            # ── Intent Engine — enterprise-grade NLP handler ──
                            try:
                                _ie = IntentEngine(
                                    ai_call=call_ai,
                                    approved_devices=disc.get_approved(),
                                )
                                with st.spinner(f"🧠 NetBrain AI working on {dev.ip}…"):
                                    _ie_result: IntentResult = _ie.handle(
                                        query=_ai_nlp_q,
                                        primary_device=dev,
                                        session_output=(session.output if session else ""),
                                        session_diagnosis=(session.ai_diagnosis if session else ""),
                                    )

                                # If config change proposed — store for approval workflow
                                if _ie_result.needs_approval and _ie_result.fix_commands:
                                    st.session_state[_pending_key] = _ie_result.fix_commands

                                    # Take pre-change snapshot
                                    _snap_key = f"ai_nlp_presnap_{dev.ip}"
                                    try:
                                        from netmiko import ConnectHandler as _CH
                                        _scfg = dict(
                                            device_type=dev.device_type or "cisco_ios",
                                            host=dev.ip,
                                            port=int(dev.ssh_port or 22),
                                            username=os.environ.get("GNS3_SSH_USER", "admin"),
                                            password=os.environ.get("GNS3_SSH_PASS", "admin"),
                                            timeout=60, auth_timeout=60,
                                            fast_cli=False, global_delay_factor=4,
                                        )
                                        _sec = os.environ.get("GNS3_SSH_SECRET", "")
                                        if _sec:
                                            _scfg["secret"] = _sec
                                        _sc = _CH(**_scfg)
                                        try:
                                            _sc.enable()
                                        except Exception:
                                            pass
                                        _snap_raw = _sc.send_command(
                                            "show running-config", read_timeout=30, expect_string=r"#"
                                        )
                                        _sc.disconnect()
                                        st.session_state[_snap_key] = _snap_raw
                                        _snap_status = "✅ " + str(len(_snap_raw.splitlines())) + " lines captured"
                                    except Exception as _se:
                                        st.session_state[_snap_key] = ""
                                        _snap_status = "⚠️ Snapshot failed: " + str(_se)

                                    # Store rollback plan too
                                    if _ie_result.rollback_commands:
                                        st.session_state[f"ai_nlp_rollback_cmds_{dev.ip}"] = (
                                            _ie_result.rollback_commands
                                        )

                                _nlp_reply = IntentEngine.format_for_chat(
                                    _ie_result, dev.hostname or dev.ip
                                )
                                # Append snapshot status if config change
                                if _ie_result.needs_approval and _ie_result.fix_commands:
                                    _nlp_reply += f"\n\n📸 **Pre-change snapshot:** {_snap_status}"

                            except Exception as _ie_err:
                                logger.warning(f"IntentEngine failed: {_ie_err} — falling back")
                                _nlp_reply = f"⚠️ Intent engine error: {_ie_err}"

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
                                _snap_key = f"ai_nlp_presnap_{dev.ip}"
                                _snap_val = st.session_state.get(_snap_key, "")

                                # Show snapshot preview
                                _snap_lines = len(_snap_val.splitlines()) if _snap_val else 0
                                if _snap_val:
                                    with st.expander(
                                        f"📸 Pre-change snapshot — {_snap_lines} lines captured "
                                        f"(will be restored on ↩️ Undo)",
                                        expanded=False
                                    ):
                                        _trunc = _snap_val[:3000] + ("\n... (truncated)" if len(_snap_val)>3000 else "")
                                        st.code(_trunc, language="text")
                                else:
                                    st.warning("⚠️ No snapshot available — rollback will not be possible after deploy.")

                                st.warning(f"⚠️ **{len(_pend)} command(s) ready to deploy on {dev.hostname or dev.ip}. Approve?**")
                                _col_yes, _col_no = st.columns(2)
                                with _col_yes:
                                    if st.button("✅ Deploy Now", key=f"nlp_approve_{dev.ip}",
                                                 type="primary", use_container_width=True):
                                        _exec_log = []
                                        _creds_exec = {
                                            "username":      os.environ.get("GNS3_SSH_USER", "admin"),
                                            "password":      os.environ.get("GNS3_SSH_PASS", "admin"),
                                            "enable_secret": os.environ.get("GNS3_SSH_SECRET", ""),
                                        }
                                        try:
                                            from netmiko import ConnectHandler

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
                                            )
                                            if _creds_exec["enable_secret"]:
                                                _cfg_exec["secret"] = _creds_exec["enable_secret"]

                                            with st.spinner("⚙️ Connecting to " + dev.ip + "…"):
                                                _conn_exec = ConnectHandler(**_cfg_exec)
                                                try:
                                                    _conn_exec.enable()
                                                except Exception:
                                                    pass

                                            # ── USE PRE-CAPTURED SNAPSHOT (taken at approval time) ──
                                            # Snapshot was already captured when AI proposed the commands.
                                            # Reuse it — no need to SSH again just for this.
                                            _snap_key = f"ai_nlp_presnap_{dev.ip}"
                                            _pre_snapshot = st.session_state.get(_snap_key, "")
                                            if not _pre_snapshot:
                                                # Fallback: capture now if somehow missing
                                                try:
                                                    _pre_snapshot = _conn_exec.send_command(
                                                        "show running-config",
                                                        read_timeout=30,
                                                        expect_string=r"#",
                                                    )
                                                except Exception as _snap_err:
                                                    _exec_log.append("⚠️ Snapshot unavailable: " + str(_snap_err))

                                            # Strip terminal-only commands that send_config_set handles itself
                                            _strip_cmds = {"end", "exit", "write memory", "wr", "wr mem"}
                                            _config_cmds = [
                                                c.replace("[CONFIG]", "").strip()
                                                for c in _pend
                                                if "[CONFIG]" in c
                                                and c.replace("[CONFIG]", "").strip()
                                                and c.replace("[CONFIG]", "").strip().lower() not in _strip_cmds
                                            ]
                                            _exec_cmds = [
                                                c.replace("[EXEC]", "").strip()
                                                for c in _pend
                                                if "[EXEC]" in c
                                                and c.replace("[EXEC]", "").strip()
                                            ]

                                            # ── Execute EXEC-mode commands ────────────
                                            with st.spinner("⚙️ Executing on " + dev.ip + "…"):
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

                                            # ── Store SNAPSHOT for rollback (not pattern-matched commands) ──
                                            if _pre_snapshot:
                                                st.session_state[f"ai_nlp_rollback_{dev.ip}"] = _pre_snapshot
                                                _deploy_result += (
                                                    "\n\n🔄 **Rollback available** — "
                                                    "click **↩️ Undo** below to restore the "
                                                    "exact pre-change config."
                                                )

                                        except Exception as _ex_err:
                                            _deploy_result = "❌ Deployment failed: " + str(_ex_err)

                                        st.session_state.pop(f"ai_nlp_pending_cmds_{dev.ip}", None)
                                        st.session_state.pop(f"ai_nlp_presnap_{dev.ip}", None)
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
                                            import re as _re_rb

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

                                            with st.spinner("↩️ Restoring pre-change config on " + dev.ip + "…"):
                                                _conn_rb = ConnectHandler(**_cfg_rb)
                                                try:
                                                    _conn_rb.enable()
                                                except Exception:
                                                    pass

                                                # _rb_cmds is the full running-config snapshot (a string)
                                                # Parse it into config lines, skipping header boilerplate
                                                _skip_prefixes = (
                                                    "!", "Building configuration",
                                                    "Current configuration", "version ",
                                                    "boot-start", "boot-end", "no service pad",
                                                    "service ", "hostname ", "logging ",
                                                    "enable secret", "enable password",
                                                    "username ", "aaa ", "crypto ",
                                                    "spanning-tree ", "vtp ", "cdp ",
                                                    "ip ssh ", "ip domain", "line con",
                                                    "line vty", "line aux", "end",
                                                )
                                                _raw_lines = _rb_cmds.splitlines()
                                                _restore_lines = []
                                                for _rl in _raw_lines:
                                                    _rs = _rl.strip()
                                                    if not _rs:
                                                        continue
                                                    if any(_rs.startswith(_p) for _p in _skip_prefixes):
                                                        continue
                                                    _restore_lines.append(_rs)

                                                if _restore_lines:
                                                    _o = _conn_rb.send_config_set(
                                                        _restore_lines,
                                                        read_timeout=60,
                                                        enter_config_mode=True,
                                                        exit_config_mode=True,
                                                    )
                                                    _rb_log.append("[RESTORED FROM SNAPSHOT]\n" + _o)
                                                    try:
                                                        _conn_rb.save_config()
                                                    except Exception:
                                                        pass
                                                _conn_rb.disconnect()

                                            _rb_result = (
                                                "↩️ **Rollback completed on "
                                                + (dev.hostname or dev.ip) + "**\n\n"
                                                + "Pre-change configuration restored from snapshot.\n\n"
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

                **Range Scan:** Open the **🌐 Range Scan (RFC 1918)** panel above — it auto-detects your machine's connected subnets, lets you pick RFC 1918 presets (192.168.0.0/16, 172.16.0.0/12, 10.0.0.0/8) or enter a custom CIDR, then scans all of them in one cancellable, progress-tracked job.

                **Manual Add:** Enter any IP in the "Ping & Discover" box to check reachability and add it directly.

                **Auth failed?** Open the **SSH Credentials** section above and click **Test SSH Login**.
                """)

    # ── Network Topology tab ─────────────────────────────────────────────────
    with tab_topology:
        st.markdown("### 🗺️ Network Topology")
        st.caption(
            "Site-wise automatic topology discovery via CDP/LLDP. Pick a site, "
            "click Build, and NetBrain AI maps every router, switch, AP, and "
            "firewall with their live uplink ports."
        )

        try:
            from core.device_discovery import get_discovery_engine
            from core.topology import (
                build_topology_for_site, list_available_sites,
                export_topology_to_pptx, export_topology_to_pdf, export_topology_to_vdx,
                TopologyChatEngine,
            )
            from core.topology.plotly_view import build_topology_figure
            TOPO_OK = True
        except ImportError as _topo_imp_err:
            TOPO_OK = False
            st.error(f"Topology module unavailable: {_topo_imp_err}")

        if TOPO_OK:
            _topo_disc = get_discovery_engine()
            _topo_devices = _topo_disc.get_approved()
            _sites = list_available_sites(_topo_devices)

            if not _sites:
                st.info(
                    "No sites yet. Approve devices in the **🖧 Devices** tab "
                    "with Region/Country/City/Site Name set — they'll appear "
                    "here automatically."
                )
            else:
                _site_labels = [
                    f"{s['site_name']} — {s['city']}, {s['country']} ({s['region']}) "
                    f"· {s['device_count']} device(s)"
                    for s in _sites
                ]
                _site_idx = st.selectbox(
                    "Select a site",
                    range(len(_sites)),
                    format_func=lambda i: _site_labels[i],
                    key="topo_site_select",
                )
                _picked = _sites[_site_idx]

                _view_mode_label = st.radio(
                    "View",
                    ["🔌 Physical", "🌐 Logical (L3)"],
                    horizontal=True, key="topo_view_mode",
                    help=(
                        "Physical: actual CDP/LLDP cabling, port-to-port. "
                        "Logical (L3): same links, colored by whether the IP "
                        "subnet on each end actually matches — catches cables "
                        "that are physically connected but not really talking at L3."
                    ),
                )
                _view_mode = "logical" if "Logical" in _view_mode_label else "physical"

                _bcol1, _bcol2 = st.columns([1, 1])
                with _bcol1:
                    _build_clicked = st.button(
                        "🔍 Build Topology", type="primary",
                        use_container_width=True, key="topo_build_btn",
                    )
                with _bcol2:
                    _force_refresh = st.checkbox(
                        "Force refresh (ignore cache)", key="topo_force_refresh",
                    )

                _graph_key = f"topo_graph_{_picked['region']}_{_picked['country']}_{_picked['city']}_{_picked['site_name']}"

                if _build_clicked:
                    with st.spinner(f"Discovering topology for {_picked['site_name']} via CDP/LLDP…"):
                        _graph = build_topology_for_site(
                            site_name=_picked["site_name"], city=_picked["city"],
                            country=_picked["country"], region=_picked["region"],
                            all_approved_devices=_topo_devices,
                            use_cache=not _force_refresh,
                        )
                        st.session_state[_graph_key] = _graph

                _graph = st.session_state.get(_graph_key)

                if _graph and _graph.node_count() > 0:
                    st.success(
                        f"✅ {_graph.node_count()} device(s), {_graph.link_count()} link(s) "
                        f"· polled {_graph.devices_polled} device(s) · built {_graph.built_at[:19]} UTC"
                    )
                    if _graph.devices_failed:
                        with st.expander(f"⚠️ {len(_graph.devices_failed)} device(s) failed discovery"):
                            for f in _graph.devices_failed:
                                st.caption(f"• {f}")

                    _fig = build_topology_figure(_graph, view_mode=_view_mode)
                    if _fig:
                        st.plotly_chart(
                            _fig, use_container_width=True,
                            config={
                                "toImageButtonOptions": {
                                    "format": "png",
                                    "filename": f"topology_{_graph.site_name or 'export'}",
                                    "scale": 3,   # renders at 3x pixel density -- fixes the blurry default
                                },
                                "displaylogo": False,
                            },
                        )
                        if _view_mode == "logical":
                            st.caption(
                                "🟢 solid = subnets match · 🔴 dashed = subnets differ on a "
                                "physically-connected link (likely misconfiguration) · "
                                "⚪ dotted = no L3 data for that device/vendor yet."
                            )
                        st.caption(
                            "📷 uses the camera icon above for a quick PNG. For a crisp, "
                            "fully editable diagram, use the PPTX/PDF/Visio downloads below instead — "
                            "those are vector formats, not an exported screenshot."
                        )

                    with st.expander("🔌 Links table", expanded=False):
                        _link_rows = [{
                            "Device A": _graph.nodes[l.device_a_ip].label() if l.device_a_ip in _graph.nodes else l.device_a_ip,
                            "Port A": l.device_a_port,
                            "Device B": _graph.nodes[l.device_b_ip].label() if l.device_b_ip in _graph.nodes else l.device_b_ip,
                            "Port B": l.device_b_port,
                            "Protocol": l.protocol.upper(),
                        } for l in _graph.links]
                        if _link_rows:
                            st.dataframe(_link_rows, use_container_width=True, hide_index=True)
                        else:
                            st.caption("No links discovered.")

                    # ── Export buttons ──
                    st.markdown("#### 📤 Export Diagram")
                    st.caption(
                        "PPTX and Visio (.vdx) produce real, movable shapes you can "
                        "rearrange. PDF is a clean vector diagram but, like all PDFs, "
                        "isn't shape-editable — that's a PDF format limitation, not "
                        "an export limitation."
                    )
                    _e1, _e2, _e3 = st.columns(3)
                    _fname_base = f"topology_{_picked['site_name'].replace(' ', '_')}"
                    with _e1:
                        try:
                            _pptx_bytes = export_topology_to_pptx(_graph)
                        except Exception as _ex:
                            _pptx_bytes = None
                            st.caption(f"PPTX unavailable: {_ex}")
                        if _pptx_bytes:
                            st.download_button(
                                "⬇️ PowerPoint (.pptx)", data=_pptx_bytes,
                                file_name=f"{_fname_base}.pptx",
                                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                                use_container_width=True,
                            )
                        elif _pptx_bytes is not None:
                            st.caption("PPTX needs python-pptx:\n`pip install python-pptx`")
                    with _e2:
                        try:
                            _pdf_bytes = export_topology_to_pdf(_graph)
                        except Exception as _ex:
                            _pdf_bytes = None
                            st.caption(f"PDF unavailable: {_ex}")
                        if _pdf_bytes:
                            st.download_button(
                                "⬇️ PDF", data=_pdf_bytes,
                                file_name=f"{_fname_base}.pdf", mime="application/pdf",
                                use_container_width=True,
                            )
                        else:
                            # Don't silently hide the button — tell the user why
                            # and how to fix it (reportlab not installed is the
                            # usual cause; requirements.txt lists it, but the
                            # environment may not have been re-installed).
                            st.caption("📄 PDF needs reportlab:\n`pip install reportlab`")
                    with _e3:
                        try:
                            _vdx_bytes = export_topology_to_vdx(_graph)
                        except Exception as _ex:
                            _vdx_bytes = None
                            st.caption(f"Visio unavailable: {_ex}")
                        if _vdx_bytes:
                            st.download_button(
                                "⬇️ Visio (.vdx)", data=_vdx_bytes,
                                file_name=f"{_fname_base}.vdx", mime="application/xml",
                                use_container_width=True,
                            )

                    # ── AI chat over this topology ──
                    st.markdown("#### 💬 Ask AI about this topology")
                    _topo_chat_key = f"topo_chat_history_{_graph_key}"
                    if _topo_chat_key not in st.session_state:
                        st.session_state[_topo_chat_key] = []

                    for _role, _msg in st.session_state[_topo_chat_key]:
                        with st.chat_message(_role):
                            st.markdown(_msg)

                    _topo_q = st.chat_input(
                        "e.g. what connects to R1? which devices are firewalls?",
                        key="topo_chat_input",
                    )
                    if _topo_q:
                        st.session_state[_topo_chat_key].append(("user", _topo_q))
                        with st.chat_message("user"):
                            st.markdown(_topo_q)
                        with st.chat_message("assistant"):
                            with st.spinner("Thinking…"):
                                _chat_engine = TopologyChatEngine(ai_call=call_ai)
                                _answer = _chat_engine.ask(_topo_q, _graph)
                                st.markdown(_answer)
                        st.session_state[_topo_chat_key].append(("assistant", _answer))

                elif _graph is not None:
                    st.warning(
                        "No devices/links discovered for this site. Check that "
                        "devices support CDP/LLDP and SSH credentials are correct."
                    )
                else:
                    st.caption("Click **Build Topology** to discover this site's devices and connectivity.")


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
                _reply = call_ai(_full_prompt) or "I'm unable to respond right now. Check your GROQ_API_KEY."
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


# ── NETWORK COPILOT ───────────────────────────────────────────────────────────
if workspace == "copilot":

    # ── Copilot CSS ──────────────────────────────────────────────────────────
    st.markdown("""
    <style>
    /* Hide default streamlit padding for clean canvas */
    .copilot-canvas { background: transparent; }

    /* ── Device Selector Table ── */
    .device-table {
        background: #0e151f;
        border: 1px solid #1b2533;
        border-radius: 14px;
        overflow: hidden;
        margin-bottom: 0;
    }
    .device-table-header {
        display: grid;
        grid-template-columns: 40px 1fr 1fr 90px;
        padding: 10px 16px;
        background: #141d2a;
        border-bottom: 1px solid #1b2533;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
        color: #5d6b7e;
    }
    .device-row {
        display: grid;
        grid-template-columns: 40px 1fr 1fr 90px;
        padding: 10px 16px;
        border-bottom: 1px solid #111827;
        align-items: center;
        font-size: 13px;
        transition: background .15s;
    }
    .device-row:last-child { border-bottom: none; }
    .device-row:hover { background: #141d2a; }
    .device-status-dot {
        width: 8px; height: 8px;
        border-radius: 50%;
        display: inline-block;
        margin-right: 6px;
    }

    /* ── Chat Window ── */
    .copilot-chat-window {
        background: #0a0f18;
        border: 1px solid #1b2533;
        border-radius: 18px;
        padding: 24px 28px 16px 28px;
        min-height: 420px;
        display: flex;
        flex-direction: column;
        gap: 16px;
        position: relative;
    }
    .copilot-msg-user {
        align-self: flex-end;
        background: linear-gradient(135deg, #2563eb, #4c8dff);
        color: #fff;
        border-radius: 18px 18px 4px 18px;
        padding: 12px 18px;
        max-width: 72%;
        font-size: 14px;
        line-height: 1.55;
        box-shadow: 0 4px 20px rgba(76,141,255,.25);
    }
    .copilot-msg-ai {
        align-self: flex-start;
        background: #141d2a;
        border: 1px solid #1b2533;
        color: #c8d6e8;
        border-radius: 18px 18px 18px 4px;
        padding: 14px 18px;
        max-width: 82%;
        font-size: 14px;
        line-height: 1.6;
        box-shadow: 0 4px 16px rgba(0,0,0,.3);
    }
    .copilot-msg-ai code {
        background: #0e151f;
        border: 1px solid #243043;
        border-radius: 6px;
        padding: 1px 6px;
        font-size: 12.5px;
        color: #4c8dff;
        font-family: 'JetBrains Mono', monospace;
    }
    .copilot-msg-ai pre {
        background: #070b12;
        border: 1px solid #243043;
        border-radius: 10px;
        padding: 12px 16px;
        overflow-x: auto;
        font-size: 12px;
        color: #7dd3a8;
        margin: 8px 0 0 0;
        font-family: 'JetBrains Mono', monospace;
    }
    .copilot-label-user {
        font-size: 10.5px;
        font-weight: 700;
        color: #4c8dff;
        letter-spacing: .06em;
        text-align: right;
        margin-bottom: 4px;
        margin-right: 2px;
    }
    .copilot-label-ai {
        font-size: 10.5px;
        font-weight: 700;
        color: #3fd27a;
        letter-spacing: .06em;
        margin-bottom: 4px;
        margin-left: 2px;
    }
    .copilot-empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        flex: 1;
        gap: 12px;
        padding: 60px 0 40px 0;
        opacity: .55;
    }
    .copilot-empty-icon {
        font-size: 48px;
        filter: drop-shadow(0 0 20px rgba(76,141,255,.4));
    }
    .copilot-empty-text {
        font-size: 15px;
        color: #5d6b7e;
        font-weight: 500;
        text-align: center;
        line-height: 1.5;
    }

    /* ── Input bar ── */
    .copilot-input-wrap {
        background: #0e151f;
        border: 1px solid #243043;
        border-radius: 16px;
        padding: 4px 6px 4px 16px;
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
        box-shadow: 0 0 0 0 rgba(76,141,255,0);
        transition: box-shadow .2s;
    }
    .copilot-input-wrap:focus-within {
        border-color: #4c8dff !important;
        box-shadow: 0 0 0 3px rgba(76,141,255,.18) !important;
    }
    /* Selected device chip */
    .copilot-chip {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        background: rgba(76,141,255,.15);
        border: 1px solid rgba(76,141,255,.3);
        border-radius: 20px;
        padding: 3px 10px 3px 8px;
        font-size: 12px;
        color: #7ab3ff;
        font-weight: 600;
        white-space: nowrap;
    }
    .copilot-no-device-warn {
        background: rgba(245,185,66,.08);
        border: 1px solid rgba(245,185,66,.25);
        border-radius: 10px;
        padding: 10px 14px;
        font-size: 13px;
        color: #f5b942;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .copilot-approval-box {
        background: #0e151f;
        border: 1px solid #243043;
        border-left: 4px solid #f5b942;
        border-radius: 12px;
        padding: 14px 18px;
        margin-top: 8px;
    }
    .copilot-title {
        font-size: 26px;
        font-weight: 800;
        color: #f0f4fa;
        letter-spacing: -.03em;
        margin: 0;
        line-height: 1.1;
    }
    .copilot-sub {
        font-size: 13.5px;
        color: #5d6b7e;
        margin-top: 4px;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── Session state init ────────────────────────────────────────────────────
    if "copilot_messages"       not in st.session_state: st.session_state["copilot_messages"]       = []
    if "copilot_selected_devs"  not in st.session_state: st.session_state["copilot_selected_devs"]  = []
    if "copilot_pending_cmds"   not in st.session_state: st.session_state["copilot_pending_cmds"]   = {}
    if "copilot_snapshots"      not in st.session_state: st.session_state["copilot_snapshots"]      = {}
    if "copilot_last_input"     not in st.session_state: st.session_state["copilot_last_input"]     = ""
    if "copilot_rollback"       not in st.session_state: st.session_state["copilot_rollback"]       = {}

    # ── Load approved devices ─────────────────────────────────────────────────
    try:
        from core.device_discovery import get_discovery_engine
        _cp_disc   = get_discovery_engine()
        _cp_devs   = _cp_disc.get_approved() or []
    except Exception:
        _cp_devs = []

    # ── Page header ───────────────────────────────────────────────────────────
    _hdr_l, _hdr_r = st.columns([3, 1])
    with _hdr_l:
        st.markdown("""
        <div style="padding:8px 0 20px 0">
          <div class="copilot-title">✨ Network Copilot</div>
          <div class="copilot-sub">
            Select devices, then talk to your network in plain English.
          </div>
        </div>""", unsafe_allow_html=True)
    with _hdr_r:
        _sel_count = len(st.session_state["copilot_selected_devs"])
        if _sel_count:
            st.markdown(f"""
            <div style="text-align:right;padding-top:14px">
              <span style="font-size:22px;font-weight:800;color:#4c8dff">{_sel_count}</span>
              <span style="font-size:13px;color:#5d6b7e;margin-left:4px">device{"s" if _sel_count!=1 else ""} selected</span>
            </div>""", unsafe_allow_html=True)

    # ── Main layout: device panel + chat ─────────────────────────────────────
    _left_col, _right_col = st.columns([1, 2], gap="large")

    # ════════════════════════════════════════════
    # LEFT — Device Selector
    # ════════════════════════════════════════════
    with _left_col:
        st.markdown("""
        <div style="font-size:11px;font-weight:700;letter-spacing:.1em;
                    text-transform:uppercase;color:#5d6b7e;margin-bottom:10px">
          🖧 Approved Devices — Select targets
        </div>""", unsafe_allow_html=True)

        if not _cp_devs:
            st.markdown("""
            <div style="background:#0e151f;border:1px dashed #1b2533;border-radius:12px;
                        padding:24px;text-align:center;color:#5d6b7e;font-size:13px">
              No approved devices yet.<br>
              <span style="font-size:11px">Go to <b>Dashboard</b> → approve a device first.</span>
            </div>""", unsafe_allow_html=True)
        else:
            # Select All / Clear All
            _sa_col, _ca_col = st.columns(2)
            with _sa_col:
                if st.button("☑ Select All", key="cp_sel_all", use_container_width=True):
                    st.session_state["copilot_selected_devs"] = [d.ip for d in _cp_devs]
                    st.rerun()
            with _ca_col:
                if st.button("✕ Clear All", key="cp_clr_all", use_container_width=True):
                    st.session_state["copilot_selected_devs"] = []
                    st.rerun()

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            # Device rows — drag-and-drop-style checklist
            for _cpd in _cp_devs:
                _is_sel = _cpd.ip in st.session_state["copilot_selected_devs"]
                _hn     = getattr(_cpd, "hostname", None) or _cpd.ip
                _dtype  = getattr(_cpd, "device_type", "cisco_ios") or "cisco_ios"
                _sess   = _cp_disc.get_session(_cpd.ip)
                _online = _sess is not None and getattr(_sess, "status", "") == "complete"
                _dot_color = "#3fd27a" if _online else "#5d6b7e"
                _bg     = "rgba(76,141,255,.08)" if _is_sel else "transparent"
                _border = "rgba(76,141,255,.35)" if _is_sel else "#1b2533"

                st.markdown(f"""
                <div style="background:{_bg};border:1px solid {_border};border-radius:10px;
                            padding:10px 14px;margin-bottom:6px;transition:all .15s">
                  <div style="display:flex;align-items:center;justify-content:space-between">
                    <div>
                      <span style="color:#f0f4fa;font-weight:700;font-size:13px">{_hn}</span>
                      <span style="display:block;font-size:11px;color:#5d6b7e;
                                   font-family:'JetBrains Mono',monospace;margin-top:2px">
                        <span style="display:inline-block;width:8px;height:8px;
                                     border-radius:50%;background:{_dot_color};
                                     margin-right:5px;vertical-align:middle"></span>
                        {_cpd.ip} · {_dtype}
                      </span>
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

                _tog_label = "✓ Selected" if _is_sel else "+ Select"
                _tog_type  = "primary" if _is_sel else "secondary"
                if st.button(_tog_label, key=f"cp_tog_{_cpd.ip}", use_container_width=True):
                    _sel = st.session_state["copilot_selected_devs"]
                    if _cpd.ip in _sel:
                        _sel.remove(_cpd.ip)
                    else:
                        _sel.append(_cpd.ip)
                    st.session_state["copilot_selected_devs"] = _sel
                    st.rerun()

        # Rollback section in left panel
        _rb_devs = [ip for ip, snap in st.session_state["copilot_rollback"].items() if snap]
        if _rb_devs:
            st.markdown("<hr style='border-color:#1b2533;margin:16px 0'>", unsafe_allow_html=True)
            st.markdown("""
            <div style="font-size:11px;font-weight:700;letter-spacing:.1em;
                        text-transform:uppercase;color:#f5b942;margin-bottom:8px">
              ↩️ Rollback Available
            </div>""", unsafe_allow_html=True)
            for _rb_ip in _rb_devs:
                _rb_hn = next((getattr(d,"hostname",d.ip) for d in _cp_devs if d.ip == _rb_ip), _rb_ip)
                st.markdown(f"""
                <div style="font-size:12px;color:#9aa9bd;margin-bottom:6px">
                  📸 {_rb_hn} ({_rb_ip})
                </div>""", unsafe_allow_html=True)
                _rb1, _rb2 = st.columns(2)
                with _rb1:
                    if st.button("↩️ Undo", key=f"cp_rb_{_rb_ip}", use_container_width=True):
                        _snap = st.session_state["copilot_rollback"].get(_rb_ip, "")
                        if _snap:
                            _rb_creds = {
                                "username":      os.environ.get("GNS3_SSH_USER","admin"),
                                "password":      os.environ.get("GNS3_SSH_PASS","admin"),
                                "enable_secret": os.environ.get("GNS3_SSH_SECRET",""),
                            }
                            _rb_dev_obj = next((d for d in _cp_devs if d.ip == _rb_ip), None)
                            try:
                                from netmiko import ConnectHandler
                                _rb_cfg = dict(
                                    device_type=getattr(_rb_dev_obj,"device_type","cisco_ios"),
                                    host=_rb_ip,
                                    port=22, username=_rb_creds["username"],
                                    password=_rb_creds["password"],
                                    timeout=60, auth_timeout=60,
                                    fast_cli=False, global_delay_factor=4,
                                )
                                if _rb_creds["enable_secret"]:
                                    _rb_cfg["secret"] = _rb_creds["enable_secret"]
                                with st.spinner(f"↩️ Restoring {_rb_ip}…"):
                                    _rb_conn = ConnectHandler(**_rb_cfg)
                                    try: _rb_conn.enable()
                                    except: pass
                                    _skip = ("!","Building configuration","Current configuration",
                                             "version ","boot-","no service","service ",
                                             "hostname ","logging ","enable secret","enable password",
                                             "username ","aaa ","crypto ","spanning-tree ","end")
                                    _rb_lines = [l.strip() for l in _snap.splitlines()
                                                 if l.strip() and not any(l.strip().startswith(s) for s in _skip)]
                                    if _rb_lines:
                                        _rb_conn.send_config_set(_rb_lines, read_timeout=60)
                                        try: _rb_conn.save_config()
                                        except: pass
                                    _rb_conn.disconnect()
                                st.session_state["copilot_rollback"].pop(_rb_ip, None)
                                st.session_state["copilot_messages"].append({
                                    "role": "assistant",
                                    "content": f"↩️ **Rollback completed on {_rb_hn} ({_rb_ip})** — pre-change config restored.",
                                    "devices": [_rb_ip],
                                })
                                st.rerun()
                            except Exception as _rbe:
                                st.error(f"Rollback failed: {_rbe}")
                with _rb2:
                    if st.button("🗑 Discard", key=f"cp_rb_dis_{_rb_ip}", use_container_width=True):
                        st.session_state["copilot_rollback"].pop(_rb_ip, None)
                        st.rerun()

    # ════════════════════════════════════════════
    # RIGHT — Chat Window
    # ════════════════════════════════════════════
    with _right_col:
        # ── Chat messages ─────────────────────────────────────────────────
        _msgs = st.session_state["copilot_messages"]

        if not _msgs:
            # Empty state
            st.markdown("""
            <div style="background:#0a0f18;border:1px solid #1b2533;border-radius:18px;
                        padding:0 28px;min-height:420px;display:flex;flex-direction:column;
                        align-items:center;justify-content:center;gap:12px">
              <div style="font-size:52px;filter:drop-shadow(0 0 24px rgba(76,141,255,.45))">✨</div>
              <div style="font-size:17px;font-weight:700;color:#f0f4fa;text-align:center;
                          letter-spacing:-.01em">What do you want to do today in your network?</div>
              <div style="font-size:13px;color:#5d6b7e;text-align:center;max-width:340px;
                          line-height:1.6">
                Select devices on the left, then type a question or command below.<br>
                AI will plan, show you the commands, and wait for your approval.
              </div>
              <div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:8px">
                <span style="background:#0e151f;border:1px solid #1b2533;border-radius:20px;
                             padding:6px 14px;font-size:12px;color:#5d6b7e">configure OSPF</span>
                <span style="background:#0e151f;border:1px solid #1b2533;border-radius:20px;
                             padding:6px 14px;font-size:12px;color:#5d6b7e">check BGP neighbors</span>
                <span style="background:#0e151f;border:1px solid #1b2533;border-radius:20px;
                             padding:6px 14px;font-size:12px;color:#5d6b7e">add loopback interface</span>
                <span style="background:#0e151f;border:1px solid #1b2533;border-radius:20px;
                             padding:6px 14px;font-size:12px;color:#5d6b7e">show routing table</span>
              </div>
            </div>""", unsafe_allow_html=True)
        else:
            # Messages
            st.markdown('<div class="copilot-chat-window">', unsafe_allow_html=True)
            import html as _html_mod
            for _cm in _msgs[-20:]:
                _cr  = _cm["role"]
                _ctxt = _cm.get("content","")
                _cdevs = _cm.get("devices", [])
                _dev_chips = ""
                if _cdevs:
                    _dev_chips = "".join(
                        f'<span class="copilot-chip">🖧 {next((getattr(d,"hostname",d.ip) for d in _cp_devs if d.ip==ip), ip)}</span>'
                        for ip in _cdevs
                    )
                if _cr == "user":
                    st.markdown(f"""
                    <div style="display:flex;flex-direction:column;align-items:flex-end;margin-bottom:4px">
                      <div class="copilot-label-user">👤 You</div>
                      {"<div style='display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;margin-bottom:6px'>" + _dev_chips + "</div>" if _dev_chips else ""}
                      <div class="copilot-msg-user">{_html_mod.escape(_ctxt)}</div>
                    </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f'<div class="copilot-label-ai">✨ Network Copilot</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="copilot-msg-ai">', unsafe_allow_html=True)
                    st.markdown(_ctxt)
                    st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)

        # ── Pending approval boxes ─────────────────────────────────────────
        _cp_pending = st.session_state.get("copilot_pending_cmds", {})
        if _cp_pending:
            st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
            for _pdev_ip, _pcmds in list(_cp_pending.items()):
                _pdev_hn = next((getattr(d,"hostname",d.ip) for d in _cp_devs if d.ip==_pdev_ip), _pdev_ip)
                _strip_c = {"end","exit","write memory","wr","wr mem"}
                _cfg_c   = [c.replace("[CONFIG]","").strip() for c in _pcmds
                            if "[CONFIG]" in c and c.replace("[CONFIG]","").strip().lower() not in _strip_c]
                _exec_c  = [c.replace("[EXEC]","").strip() for c in _pcmds if "[EXEC]" in c]
                _all_display = _cfg_c + _exec_c

                st.markdown(f"""
                <div class="copilot-approval-box">
                  <div style="font-size:12px;font-weight:700;color:#f5b942;margin-bottom:8px">
                    ⚠️ Ready to deploy on <span style="color:#f0f4fa">{_pdev_hn}</span>
                    <span style="color:#5d6b7e;font-weight:400"> ({_pdev_ip})</span>
                  </div>
                  <pre style="background:#070b12;border:1px solid #243043;border-radius:8px;
                              padding:10px 14px;font-size:12px;color:#7dd3a8;
                              font-family:'JetBrains Mono',monospace;margin:0 0 12px 0;
                              overflow-x:auto">{chr(10).join(_all_display)}</pre>
                </div>""", unsafe_allow_html=True)

                # Show snapshot info
                _snap_val = st.session_state.get("copilot_snapshots", {}).get(_pdev_ip, "")
                if _snap_val:
                    with st.expander(f"📸 Pre-change snapshot — {len(_snap_val.splitlines())} lines (click to review)", expanded=False):
                        _trunc = _snap_val[:3000] + ("\n... (truncated)" if len(_snap_val)>3000 else "")
                        st.code(_trunc, language="text")

                _ap_col, _ca_col2 = st.columns(2)
                with _ap_col:
                    if st.button(f"✅ Deploy on {_pdev_hn}", key=f"cp_deploy_{_pdev_ip}", type="primary", use_container_width=True):
                        _d_creds = {
                            "username":      os.environ.get("GNS3_SSH_USER","admin"),
                            "password":      os.environ.get("GNS3_SSH_PASS","admin"),
                            "enable_secret": os.environ.get("GNS3_SSH_SECRET",""),
                        }
                        _d_dev = next((d for d in _cp_devs if d.ip==_pdev_ip), None)
                        _d_log = []
                        try:
                            from netmiko import ConnectHandler
                            _dcfg = dict(
                                device_type=getattr(_d_dev,"device_type","cisco_ios"),
                                host=_pdev_ip, port=22,
                                username=_d_creds["username"], password=_d_creds["password"],
                                timeout=60, auth_timeout=60, fast_cli=False, global_delay_factor=4,
                            )
                            if _d_creds["enable_secret"]: _dcfg["secret"] = _d_creds["enable_secret"]
                            with st.spinner(f"⚙️ Deploying on {_pdev_hn}…"):
                                _dconn = ConnectHandler(**_dcfg)
                                try: _dconn.enable()
                                except: pass
                                if _exec_c:
                                    for _ec in _exec_c:
                                        _o = _dconn.send_command(_ec, read_timeout=30, expect_string=r"#")
                                        _d_log.append(f"$ {_ec}\n{_o}")
                                if _cfg_c:
                                    _o = _dconn.send_config_set(_cfg_c, read_timeout=30)
                                    _d_log.append(f"[CONFIG MODE]\n{_o}")
                                    try: _dconn.save_config()
                                    except: pass
                                _dconn.disconnect()
                            _d_result = (
                                f"✅ **Deployed successfully on {_pdev_hn} ({_pdev_ip})**\n\n"
                                f"```\n" + "\n".join(_d_log) + "\n```"
                            )
                            if _snap_val:
                                st.session_state["copilot_rollback"][_pdev_ip] = _snap_val
                                _d_result += "\n\n🔄 **Rollback available** — click ↩️ Undo in the left panel."
                        except Exception as _de:
                            _d_result = f"❌ Deployment failed on {_pdev_hn}: {_de}"
                        st.session_state["copilot_pending_cmds"].pop(_pdev_ip, None)
                        st.session_state["copilot_snapshots"].pop(_pdev_ip, None)
                        st.session_state["copilot_messages"].append({
                            "role": "assistant", "content": _d_result, "devices": [_pdev_ip],
                        })
                        st.rerun()
                with _ca_col2:
                    if st.button(f"❌ Cancel", key=f"cp_cancel_{_pdev_ip}", use_container_width=True):
                        st.session_state["copilot_pending_cmds"].pop(_pdev_ip, None)
                        st.session_state["copilot_snapshots"].pop(_pdev_ip, None)
                        st.session_state["copilot_messages"].append({
                            "role": "assistant",
                            "content": f"❌ Cancelled — no changes made to **{_pdev_hn}** ({_pdev_ip}).",
                            "devices": [_pdev_ip],
                        })
                        st.rerun()

        # ── Input bar ─────────────────────────────────────────────────────
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

        # Show selected device chips above input
        _sel_ips = st.session_state["copilot_selected_devs"]
        if _sel_ips:
            _chips_html = "".join(
                f'<span class="copilot-chip">🖧 {next((getattr(d,"hostname",d.ip) for d in _cp_devs if d.ip==ip), ip)}</span>'
                for ip in _sel_ips
            )
            st.markdown(f"""
            <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;
                        padding:8px 12px;background:#0e151f;border:1px solid #1b2533;
                        border-radius:10px">
              <span style="font-size:11px;color:#5d6b7e;margin-right:4px;align-self:center">Targeting:</span>
              {_chips_html}
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div class="copilot-no-device-warn">
              ⚠️ No devices selected — select at least one device on the left before sending a command.
            </div>""", unsafe_allow_html=True)

        # Input + send
        _inp_col, _btn_col2 = st.columns([5, 1])
        with _inp_col:
            _cp_input = st.text_input(
                label="copilot_input",
                label_visibility="collapsed",
                placeholder="What do you want to do today in your network?",
                key="copilot_text_input",
                disabled=len(_sel_ips) == 0,
            )
        with _btn_col2:
            _cp_send = st.button("Send ➤", key="copilot_send", type="primary",
                                 use_container_width=True, disabled=len(_sel_ips)==0)

        # Clear chat
        if _msgs:
            if st.button("🗑 Clear conversation", key="cp_clear", use_container_width=False):
                st.session_state["copilot_messages"]     = []
                st.session_state["copilot_pending_cmds"] = {}
                st.session_state["copilot_snapshots"]    = {}
                st.rerun()

        # ── Process input ──────────────────────────────────────────────────
        if _cp_send and _cp_input and _cp_input.strip():
            _q = _cp_input.strip()

            # Guard: must have devices selected
            if not _sel_ips:
                st.warning("⚠️ Please select at least one device first.")
                st.stop()

            # Add user message
            st.session_state["copilot_messages"].append({
                "role": "user", "content": _q, "devices": list(_sel_ips),
            })

            # Build device context for AI
            _dev_ctx_parts = []
            for _dip in _sel_ips:
                _dd = next((d for d in _cp_devs if d.ip==_dip), None)
                if _dd:
                    _dhn = getattr(_dd,"hostname",_dip) or _dip
                    _dty = getattr(_dd,"device_type","cisco_ios")
                    _dev_ctx_parts.append(f"- {_dhn} ({_dip})  type={_dty}")
            _dev_ctx = "\n".join(_dev_ctx_parts)

            _cp_sys = f"""You are Network Copilot — an expert AI network engineer with LIVE SSH access.

SELECTED DEVICES (you can ONLY act on these):
{_dev_ctx}

RULES:
1. For READ-ONLY queries (show, check, verify, explain, what is, why) — answer directly. No commands needed.
2. For CONFIGURATION requests — for each device separately:
   a. Explain what you will do in 1-2 sentences.
   b. List commands prefixed with [CONFIG] for config-mode or [EXEC] for exec-mode.
   c. End the command block for each device with: DEPLOY_DEVICE:<ip>
3. NEVER act on any device not in the selected list above.
4. NEVER generate: reload, erase, write erase, no ip routing, no router (destructive commands).
5. Be concise and technically precise."""

            with st.spinner("✨ Network Copilot is thinking…"):
                try:
                    _cp_reply = call_ai(_cp_sys + f"\n\nOperator: {_q}\nNetwork Copilot:")
                except Exception as _cpe:
                    _cp_reply = f"AI Error: {_cpe}"

            if not _cp_reply:
                _cp_reply = "AI is unavailable. Please check your GROQ_API_KEY in .streamlit/secrets.toml"

            # Parse response for per-device deploy blocks
            _cp_final_msg = _cp_reply
            _has_deploy   = "DEPLOY_DEVICE:" in _cp_reply

            if _has_deploy:
                import re as _re_cp
                # Split by DEPLOY_DEVICE markers
                _cp_blocks = _re_cp.split(r"DEPLOY_DEVICE:(\S+)", _cp_reply)
                # _cp_blocks = [text_before, ip, text_after, ip2, text_after2, ...]
                _cp_clean_msg = _cp_blocks[0].strip()

                for _bi in range(1, len(_cp_blocks)-1, 2):
                    _block_ip  = _cp_blocks[_bi].strip()
                    _block_txt = _cp_blocks[_bi+1] if _bi+1 < len(_cp_blocks) else ""

                    # Only act on selected devices
                    if _block_ip not in _sel_ips:
                        continue

                    # Extract commands
                    _b_cmds = [l.strip() for l in (_cp_blocks[0] + _block_txt).splitlines()
                               if l.strip().startswith("[CONFIG]") or l.strip().startswith("[EXEC]")]

                    if _b_cmds:
                        # Take snapshot before storing pending
                        _snap_creds = {
                            "username":      os.environ.get("GNS3_SSH_USER","admin"),
                            "password":      os.environ.get("GNS3_SSH_PASS","admin"),
                            "enable_secret": os.environ.get("GNS3_SSH_SECRET",""),
                        }
                        _snap_dev = next((d for d in _cp_devs if d.ip==_block_ip), None)
                        try:
                            from netmiko import ConnectHandler
                            _scfg2 = dict(
                                device_type=getattr(_snap_dev,"device_type","cisco_ios"),
                                host=_block_ip, port=22,
                                username=_snap_creds["username"],
                                password=_snap_creds["password"],
                                timeout=60, auth_timeout=60,
                                fast_cli=False, global_delay_factor=4,
                            )
                            if _snap_creds["enable_secret"]: _scfg2["secret"] = _snap_creds["enable_secret"]
                            _sc2 = ConnectHandler(**_scfg2)
                            try: _sc2.enable()
                            except: pass
                            _snap2 = _sc2.send_command("show running-config", read_timeout=30, expect_string=r"#")
                            _sc2.disconnect()
                            st.session_state["copilot_snapshots"][_block_ip] = _snap2
                        except Exception:
                            st.session_state["copilot_snapshots"][_block_ip] = ""

                        st.session_state["copilot_pending_cmds"][_block_ip] = _b_cmds

                # Clean up the message shown to user
                _cp_final_msg = _re_cp.sub(r"DEPLOY_DEVICE:\S+", "", _cp_clean_msg).strip()
                if st.session_state["copilot_pending_cmds"]:
                    _cp_final_msg += "\n\n⚠️ **Review the commands above and click Deploy to apply.**"

            st.session_state["copilot_messages"].append({
                "role": "assistant", "content": _cp_final_msg, "devices": list(_sel_ips),
            })
            st.rerun()
