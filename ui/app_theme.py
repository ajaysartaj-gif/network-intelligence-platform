"""
ui/app_theme.py
===============

Polished, high-contrast visual theme for the NetBrain AI platform.

PRESENTATION ONLY — no application logic. app.py activates it with one call:

    from ui.app_theme import inject_theme
    inject_theme()

This stylesheet is intentionally aggressive: many of app.py's elements use
inline styles (e.g. background:#161b22 on the top status boxes), which normally
beat class selectors. We override them with attribute selectors and high
specificity so the whole UI is transformed without touching any markup/logic.
All existing class names are preserved: .approval-card .alert-critical
.dev-card .step-box .terminal
"""
from __future__ import annotations

APP_THEME_CSS = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root{
  --bg-base:#070b12;
  --bg-1:#0e151f;
  --bg-2:#141d2a;
  --bg-3:#1b2533;
  --line:#243043;
  --line-soft:#1a2331;
  --tx-1:#f0f4fa;
  --tx-2:#9aa9bd;
  --tx-3:#5d6b7e;
  --blue:#4c8dff;
  --blue-deep:#2563eb;
  --green:#3fd27a;
  --amber:#f5b942;
  --red:#ff5f56;
  --purple:#b07cff;
  --glow:rgba(76,141,255,.45);
}

/* ── Canvas ── */
html,body,[class*="css"]{font-family:'Inter',-apple-system,sans-serif!important}
.stApp{
  background:
    radial-gradient(1100px 520px at 12% -8%, rgba(76,141,255,.10), transparent 58%),
    radial-gradient(900px 480px at 100% -5%, rgba(176,124,255,.08), transparent 55%),
    linear-gradient(180deg,#080d15,#070b12)!important;
}
#MainMenu,footer{visibility:hidden}
.block-container{padding-top:1.2rem!important}

h1,h2,h3,h4{color:var(--tx-1)!important;letter-spacing:-.02em!important;font-weight:800!important}
h3{font-size:1.18rem!important;margin-bottom:.5rem!important}
/* Accent bar before section headers (Device Health, Live Event Feed, etc.) */
.main h3::before{
  content:"";display:inline-block;width:4px;height:18px;border-radius:2px;
  margin-right:10px;vertical-align:-3px;
  background:linear-gradient(180deg,var(--blue),var(--purple));
}
p,span,label,li{color:var(--tx-2)}
hr{border-color:var(--line-soft)!important}

/* ════════ SIDEBAR ════════ */
section[data-testid="stSidebar"]{
  background:linear-gradient(180deg,#0c1320,#070b12)!important;
  border-right:1px solid var(--line-soft)!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button{
  width:100%!important;text-align:left!important;justify-content:flex-start!important;
  background:transparent!important;border:1px solid transparent!important;
  color:var(--tx-2)!important;font-weight:600!important;font-size:13.5px!important;
  border-radius:11px!important;padding:11px 14px!important;margin:2px 0!important;
  transition:all .18s ease!important;
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button:hover{
  background:var(--bg-2)!important;color:var(--tx-1)!important;
  border-color:var(--line)!important;transform:translateX(3px);
}
section[data-testid="stSidebar"] div[data-testid="stButton"] button[kind="primary"]{
  background:linear-gradient(135deg,var(--blue),var(--blue-deep))!important;
  color:#fff!important;border:none!important;
  box-shadow:0 6px 18px var(--glow)!important;
}

/* ════════ BUTTONS (main) ════════ */
div[data-testid="stButton"] button{
  border-radius:11px!important;font-weight:600!important;transition:all .18s ease!important;
  border:1px solid var(--line)!important;background:var(--bg-2)!important;color:var(--tx-1)!important;
}
div[data-testid="stButton"] button:hover{
  border-color:var(--blue)!important;transform:translateY(-1px);box-shadow:0 8px 22px rgba(0,0,0,.4)!important;
}
div[data-testid="stButton"] button[kind="primary"]{
  background:linear-gradient(135deg,var(--blue),var(--blue-deep))!important;border:none!important;color:#fff!important;
  box-shadow:0 6px 20px var(--glow)!important;
}

/* ════════ INPUTS ════════ */
div[data-testid="stTextInput"] input,div[data-testid="stTextArea"] textarea,
div[data-testid="stNumberInput"] input,div[data-baseweb="select"]>div{
  border-radius:11px!important;background:var(--bg-2)!important;
  border:1px solid var(--line)!important;color:var(--tx-1)!important;
}
div[data-testid="stTextInput"] input:focus,div[data-testid="stTextArea"] textarea:focus{
  border-color:var(--blue)!important;box-shadow:0 0 0 3px var(--glow)!important;
}

/* ════════ NATIVE METRICS ════════ */
div[data-testid="stMetric"]{
  background:linear-gradient(165deg,var(--bg-1),var(--bg-2))!important;
  border:1px solid var(--line-soft)!important;border-radius:16px!important;
  padding:18px 20px!important;box-shadow:0 2px 4px rgba(0,0,0,.4)!important;
  position:relative;overflow:hidden;transition:all .2s ease;
}
div[data-testid="stMetric"]:hover{transform:translateY(-2px);box-shadow:0 10px 30px rgba(0,0,0,.45)!important;border-color:var(--line)!important}
div[data-testid="stMetric"]::before{content:"";position:absolute;top:0;left:0;width:100%;height:2px;background:linear-gradient(90deg,var(--blue),transparent)}
div[data-testid="stMetric"] label{color:var(--tx-3)!important;font-size:11px!important;letter-spacing:.09em!important;text-transform:uppercase!important;font-weight:700!important}
div[data-testid="stMetric"] [data-testid="stMetricValue"]{color:var(--tx-1)!important;font-weight:900!important;font-size:2rem!important}

/* ════════ OVERRIDE app.py INLINE-STYLED BOXES ════════
   The top status boxes & device cards use inline background:#161b22.
   We override those inline styles by attribute-matching them. */
.main div[style*="#161b22"]{
  background:linear-gradient(165deg,var(--bg-1),var(--bg-2))!important;
  border-radius:16px!important;
  box-shadow:0 4px 18px rgba(0,0,0,.4)!important;
  transition:all .2s ease!important;
}
.main div[style*="#161b22"]:hover{
  transform:translateY(-2px)!important;box-shadow:0 12px 34px rgba(0,0,0,.5)!important;
}
/* Big numbers inside those boxes */
.main div[style*="#161b22"] div[style*="font-size:28px"],
.main div[style*="#161b22"] div[style*="font-size: 28px"]{
  font-weight:900!important;letter-spacing:-.02em!important;
}
/* The small caption labels under the numbers */
.main div[style*="#161b22"] div[style*="#8b949e"]{
  color:var(--tx-3)!important;text-transform:uppercase!important;
  letter-spacing:.09em!important;font-weight:700!important;font-size:10.5px!important;
}

/* ════════ TABS ════════ */
div[data-testid="stTabs"] button[role="tab"]{color:var(--tx-2)!important;font-weight:600!important}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:var(--tx-1)!important;border-bottom:2px solid var(--blue)!important}

/* ════════ EXPANDER ════════ */
div[data-testid="stExpander"]{
  border-radius:14px!important;border:1px solid var(--line-soft)!important;
  background:var(--bg-1)!important;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.3);
}
div[data-testid="stExpander"] summary{color:var(--tx-1)!important;font-weight:600!important}
div[data-testid="stExpander"] summary:hover{color:var(--blue)!important}

/* ════════ ALERTS / INFO PANELS ════════ */
.stAlert{border-radius:14px!important;border:1px solid var(--line)!important}
div[data-baseweb="notification"]{border-radius:14px!important}

/* ════════ DATAFRAMES ════════ */
.dataframe{border-radius:12px!important;overflow:hidden!important;border:1px solid var(--line-soft)!important}
.dataframe th{background:var(--bg-3)!important;color:var(--tx-1)!important;font-weight:700!important;
  text-transform:uppercase;font-size:10.5px;letter-spacing:.06em;border:none!important}
.dataframe td{background:var(--bg-1)!important;color:var(--tx-2)!important;border-color:var(--line-soft)!important}

/* ════════ APP-SPECIFIC CLASSES (preserved, enhanced) ════════ */
.approval-card{
  background:linear-gradient(165deg,var(--bg-1),var(--bg-2))!important;
  border:1px solid var(--line);border-left:4px solid var(--amber);
  border-radius:16px;padding:20px 22px;margin:12px 0;
  box-shadow:0 10px 34px rgba(0,0,0,.45),0 0 30px rgba(245,185,66,.06);
  animation:cardIn .35s cubic-bezier(.16,1,.3,1);
}
@keyframes cardIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}

.alert-critical{
  background:linear-gradient(135deg,rgba(255,95,86,.16),rgba(255,95,86,.05));
  border:1px solid rgba(255,95,86,.32);border-left:4px solid var(--red);
  border-radius:12px;padding:12px 16px;margin:6px 0;color:var(--tx-1);
  box-shadow:0 0 26px rgba(255,95,86,.10);
}
.dev-card{
  background:linear-gradient(165deg,var(--bg-1),var(--bg-2))!important;
  border:1px solid var(--line-soft);border-radius:16px;padding:16px;margin:6px 0;
  box-shadow:0 4px 16px rgba(0,0,0,.4);transition:all .2s ease;
}
.dev-card:hover{transform:translateY(-2px);box-shadow:0 12px 30px rgba(0,0,0,.5);border-color:var(--line)}
.step-box{border-radius:12px;padding:12px;text-align:center;background:var(--bg-2);border:1px solid var(--line-soft);transition:all .3s ease}
.terminal{
  background:#05080d;border:1px solid var(--line);border-radius:12px;padding:14px 16px;
  font-family:'JetBrains Mono',monospace;font-size:12px;line-height:1.6;
  max-height:320px;overflow-y:auto;color:#7ee787;box-shadow:inset 0 2px 14px rgba(0,0,0,.5);
}

/* ════════ STATUS PILL HELPERS ════════ */
.nb-pill{display:inline-flex;align-items:center;gap:5px;font-size:11px;font-weight:600;
  font-family:'JetBrains Mono',monospace;padding:4px 11px;border-radius:999px;white-space:nowrap}
.nb-pill-ok{background:rgba(63,210,122,.14);color:var(--green);border:1px solid rgba(63,210,122,.3)}
.nb-pill-warn{background:rgba(245,185,66,.14);color:var(--amber);border:1px solid rgba(245,185,66,.3)}
.nb-pill-err{background:rgba(255,95,86,.14);color:var(--red);border:1px solid rgba(255,95,86,.3)}
.nb-pill-info{background:rgba(76,141,255,.14);color:var(--blue);border:1px solid rgba(76,141,255,.3)}
.nb-pill .dot{width:6px;height:6px;border-radius:50%;background:currentColor;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}

/* ════════ SCROLLBARS ════════ */
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:var(--bg-base)}
::-webkit-scrollbar-thumb{background:var(--line)!important;border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:var(--tx-3)!important}
</style>
"""


def inject_theme() -> None:
    """Inject the polished theme. Call once near the top of app.py."""
    import streamlit as st
    st.markdown(APP_THEME_CSS, unsafe_allow_html=True)


def pill(text: str, kind: str = "info") -> str:
    """HTML status pill. kind: ok|warn|err|info."""
    cls = {"ok": "nb-pill-ok", "warn": "nb-pill-warn",
           "err": "nb-pill-err", "info": "nb-pill-info"}.get(kind, "nb-pill-info")
    return f'<span class="nb-pill {cls}"><span class="dot"></span>{text}</span>'
