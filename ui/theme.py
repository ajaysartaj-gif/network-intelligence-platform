"""
ui/app_theme.py
===============

Polished visual theme for the NetBrain AI platform. This module contains ONLY
presentation (CSS + tiny render helpers). It changes no application logic.

app.py activates it with a single call:

    from ui.app_theme import inject_theme
    inject_theme()

All CSS class names already used by app.py are preserved and enhanced, so
existing markup keeps working:
    .approval-card  .alert-critical  .dev-card  .step-box  .terminal
Plus Streamlit-native containers (metrics, buttons, inputs, expanders, tabs).
"""
from __future__ import annotations

# ── The full design-system stylesheet ────────────────────────────────────────
APP_THEME_CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root{
  --bg-base:#0a0e14;
  --bg-surface:#121821;
  --bg-elevated:#171f2b;
  --bg-overlay:#1e2733;
  --border-subtle:#1f2730;
  --border-default:#2b3543;
  --text-primary:#e8eef5;
  --text-secondary:#94a3b5;
  --text-tertiary:#5f6b7a;
  --accent:#3b82f6;
  --accent-glow:rgba(59,130,246,.35);
  --green:#3fb950;
  --amber:#e3b341;
  --red:#f85149;
  --purple:#a371f7;
  --radius:14px;
  --radius-sm:10px;
  --shadow-sm:0 1px 2px rgba(0,0,0,.4);
  --shadow-md:0 6px 24px rgba(0,0,0,.35);
  --shadow-lg:0 18px 50px rgba(0,0,0,.45);
}

/* ── Base ── */
html,body,[class*="css"]{font-family:'Inter',-apple-system,sans-serif!important}
.stApp{
  background:
    radial-gradient(1200px 600px at 15% -10%, rgba(59,130,246,.08), transparent 60%),
    radial-gradient(1000px 500px at 100% 0%, rgba(163,113,247,.06), transparent 55%),
    var(--bg-base)!important;
}
#MainMenu,footer{visibility:hidden}
h1,h2,h3,h4{color:var(--text-primary)!important;letter-spacing:-.02em!important;font-weight:700!important}
h2{font-size:1.5rem!important}
p,span,label,li{color:var(--text-secondary)}
a{color:var(--accent)!important;text-decoration:none}
code,kbd,pre{font-family:'JetBrains Mono',monospace!important}
hr{border-color:var(--border-subtle)!important;margin:1rem 0!important}

/* ── Sidebar ── */
section[data-testid="stSidebar"]{
  background:linear-gradient(180deg,var(--bg-surface),var(--bg-base))!important;
  border-right:1px solid var(--border-subtle)!important;
}
section[data-testid="stSidebar"] *{color:var(--text-secondary)}

/* ── Sidebar nav buttons ── */
section[data-testid="stSidebar"] div[data-testid="stButton"] button{
  width:100%!important;text-align:left!important;justify-content:flex-start!important;
  background:transparent!important;border:1px solid transparent!important;
  color:var(--text-secondary)!important;font-weight:600!important;
  border-radius:var(--radius-sm)!important;padding:10px 14px!important;
  transition:all .18s ease!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover{
  background:var(--bg-elevated)!important;color:var(--text-primary)!important;
  border-color:var(--border-default)!important;transform:translateX(2px);
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"]{
  background:linear-gradient(135deg,var(--accent),#2563eb)!important;
  color:#fff!important;border:none!important;
  box-shadow:0 4px 14px var(--accent-glow)!important;
}

/* ── Buttons (main area) ── */
div[data-testid="stButton"] button{
  border-radius:var(--radius-sm)!important;font-weight:600!important;
  font-family:'Inter',sans-serif!important;transition:all .18s ease!important;
  border:1px solid var(--border-default)!important;
  background:var(--bg-elevated)!important;color:var(--text-primary)!important;
}
div[data-testid="stButton"] button:hover{
  border-color:var(--accent)!important;transform:translateY(-1px);
  box-shadow:var(--shadow-md)!important;
}
div[data-testid="stButton"] button[kind="primary"]{
  background:linear-gradient(135deg,var(--accent),#2563eb)!important;
  border:none!important;color:#fff!important;
  box-shadow:0 4px 16px var(--accent-glow)!important;
}
div[data-testid="stButton"] button[kind="primary"]:hover{
  box-shadow:0 6px 22px var(--accent-glow)!important;filter:brightness(1.06);
}

/* ── Inputs ── */
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input,
div[data-baseweb="select"]>div{
  border-radius:var(--radius-sm)!important;
  background:var(--bg-elevated)!important;
  border:1px solid var(--border-default)!important;
  color:var(--text-primary)!important;
}
div[data-testid="stTextInput"] input:focus,
div[data-testid="stTextArea"] textarea:focus{
  border-color:var(--accent)!important;
  box-shadow:0 0 0 3px var(--accent-glow)!important;
}

/* ── Metric cards ── */
div[data-testid="stMetric"],[data-testid="metric-container"]{
  background:linear-gradient(160deg,var(--bg-surface),var(--bg-elevated))!important;
  border:1px solid var(--border-subtle)!important;
  border-radius:var(--radius)!important;padding:16px 18px!important;
  box-shadow:var(--shadow-sm)!important;transition:all .2s ease;
  position:relative;overflow:hidden;
}
div[data-testid="stMetric"]:hover{
  border-color:var(--border-default)!important;box-shadow:var(--shadow-md)!important;
  transform:translateY(-2px);
}
div[data-testid="stMetric"]::before{
  content:"";position:absolute;top:0;left:0;width:100%;height:2px;
  background:linear-gradient(90deg,var(--accent),transparent);opacity:.6;
}
div[data-testid="stMetric"] label{color:var(--text-tertiary)!important;
  font-size:11px!important;letter-spacing:.08em!important;text-transform:uppercase!important;font-weight:600!important}
div[data-testid="stMetric"] [data-testid="stMetricValue"]{
  color:var(--text-primary)!important;font-weight:800!important;font-size:1.9rem!important}

/* ── Tabs ── */
div[data-testid="stTabs"] button[role="tab"]{
  color:var(--text-secondary)!important;font-weight:600!important;border-radius:8px 8px 0 0!important;
}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{
  color:var(--text-primary)!important;
  border-bottom:2px solid var(--accent)!important;
}

/* ── Expander ── */
div[data-testid="stExpander"]{
  border-radius:var(--radius)!important;border:1px solid var(--border-subtle)!important;
  background:var(--bg-surface)!important;overflow:hidden;box-shadow:var(--shadow-sm);
}
div[data-testid="stExpander"] summary{color:var(--text-primary)!important;font-weight:600!important}
div[data-testid="stExpander"] summary:hover{color:var(--accent)!important}

/* ── Alerts ── */
.stAlert{border-radius:var(--radius)!important;border:1px solid var(--border-default)!important}

/* ── DataFrames ── */
.dataframe{border-radius:var(--radius-sm)!important;overflow:hidden!important;
  border:1px solid var(--border-subtle)!important}
.dataframe th{background:var(--bg-overlay)!important;color:var(--text-primary)!important;
  font-weight:600!important;border:none!important;text-transform:uppercase;font-size:11px;letter-spacing:.05em}
.dataframe td{background:var(--bg-surface)!important;color:var(--text-secondary)!important;
  border-color:var(--border-subtle)!important}

/* ════════════════════════════════════════════════════════════════════
   App-specific classes (PRESERVED names, enhanced styling)
   ════════════════════════════════════════════════════════════════════ */

/* Approval card — the hero element of the AI Action page */
.approval-card{
  background:linear-gradient(160deg,var(--bg-surface),var(--bg-elevated));
  border:1px solid var(--border-default);
  border-left:4px solid var(--amber);
  border-radius:var(--radius);
  padding:18px 20px;margin:10px 0;
  box-shadow:var(--shadow-md);
  position:relative;
  animation:cardIn .35s cubic-bezier(.16,1,.3,1);
}
.approval-card::after{
  content:"";position:absolute;inset:0;border-radius:var(--radius);
  box-shadow:0 0 0 1px rgba(227,179,65,.10),0 0 30px rgba(227,179,65,.06);
  pointer-events:none;
}
@keyframes cardIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}

/* Critical alert banner */
.alert-critical{
  background:linear-gradient(135deg,rgba(248,81,73,.14),rgba(248,81,73,.05));
  border:1px solid rgba(248,81,73,.3);
  border-left:4px solid var(--red);
  border-radius:var(--radius-sm);
  padding:12px 16px;margin:6px 0;color:var(--text-primary);
  box-shadow:0 0 24px rgba(248,81,73,.08);
}

/* Device health card */
.dev-card{
  background:linear-gradient(160deg,var(--bg-surface),var(--bg-elevated));
  border:1px solid var(--border-subtle);
  border-radius:var(--radius);padding:16px;margin:6px 0;
  box-shadow:var(--shadow-sm);transition:all .2s ease;
}
.dev-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-md);border-color:var(--border-default)}

/* Step pipeline boxes */
.step-box{
  border-radius:var(--radius-sm);padding:12px;text-align:center;
  background:var(--bg-elevated);border:1px solid var(--border-subtle);
  transition:all .3s ease;
}

/* Terminal / log output */
.terminal{
  background:#070b10;border:1px solid var(--border-default);
  border-radius:var(--radius-sm);padding:14px 16px;
  font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.6;
  max-height:320px;overflow-y:auto;color:#7ee787;
  box-shadow:inset 0 2px 12px rgba(0,0,0,.4);
}
.terminal::-webkit-scrollbar{width:8px}
.terminal::-webkit-scrollbar-thumb{background:var(--border-default);border-radius:4px}

/* Reusable pill/badge helpers (optional, for future use) */
.nb-pill{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;
  font-family:'JetBrains Mono',monospace;padding:4px 10px;border-radius:999px;white-space:nowrap}
.nb-pill-ok{background:rgba(63,185,80,.13);color:var(--green);border:1px solid rgba(63,185,80,.28)}
.nb-pill-warn{background:rgba(227,179,65,.13);color:var(--amber);border:1px solid rgba(227,179,65,.28)}
.nb-pill-err{background:rgba(248,81,73,.13);color:var(--red);border:1px solid rgba(248,81,73,.28)}
.nb-pill-info{background:rgba(59,130,246,.13);color:var(--accent);border:1px solid rgba(59,130,246,.28)}
.nb-pill .dot{width:6px;height:6px;border-radius:50%;background:currentColor;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* Section header helper */
.nb-section{display:flex;align-items:center;gap:10px;margin:8px 0 4px}
.nb-section .bar{width:3px;height:18px;border-radius:2px;background:linear-gradient(180deg,var(--accent),var(--purple))}
.nb-section .title{font-size:1.15rem;font-weight:700;color:var(--text-primary);letter-spacing:-.01em}

/* Scrollbar (global) */
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:var(--bg-base)}
::-webkit-scrollbar-thumb{background:var(--border-default);border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:var(--text-tertiary)}
</style>
"""


def inject_theme() -> None:
    """Inject the polished theme. Call once near the top of app.py."""
    import streamlit as st
    st.markdown(APP_THEME_CSS, unsafe_allow_html=True)


# ── Optional presentation helpers (pure markup; app.py may use later) ─────────
def pill(text: str, kind: str = "info") -> str:
    """Return HTML for a status pill. kind: ok|warn|err|info."""
    cls = {"ok": "nb-pill-ok", "warn": "nb-pill-warn",
           "err": "nb-pill-err", "info": "nb-pill-info"}.get(kind, "nb-pill-info")
    return f'<span class="nb-pill {cls}"><span class="dot"></span>{text}</span>'


def section_header(title: str) -> str:
    """Return HTML for a styled section header with an accent bar."""
    return (f'<div class="nb-section"><div class="bar"></div>'
            f'<div class="title">{title}</div></div>')
