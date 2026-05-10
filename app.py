import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------

st.set_page_config(
    page_title="NetBrain AI",
    layout="wide"
)

# ---------------------------------------------------
# HTML START
# IMPORTANT:
# Paste your COMPLETE existing 2100+ line HTML code
# INSIDE the triple quotes below.
# ---------------------------------------------------

html_code = r"""

PASTE YOUR COMPLETE EXISTING HTML CODE HERE

IMPORTANT:
1. Do NOT remove anything from your existing HTML.
2. Paste the FULL code exactly as Claude generated.
3. Replace all special dashes:
   —
   with normal dash:
   -

4. Do NOT paste Python code inside this section.
5. Only HTML/CSS/JS inside this block.

Example:

<!DOCTYPE html>
<html lang="en">

<head>
<meta charset="UTF-8">
<title>NetBrain AI - Enterprise Network Intelligence Platform</title>

<style>
body{
    background:#0f172a;
    color:white;
}
</style>

</head>

<body>

<h1>NetBrain AI</h1>

</body>
</html>

"""

# ---------------------------------------------------
# HTML RENDER
# ---------------------------------------------------

components.html(
    html_code,
    height=5000,
    scrolling=True
)
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------

st.set_page_config(
    page_title="NetBrain AI",
    layout="wide"
)

# ---------------------------------------------------
# HTML START
# IMPORTANT:
# Paste your COMPLETE existing 2100+ line HTML code
# INSIDE the triple quotes below.
# ---------------------------------------------------

html_code = r"""

PASTE YOUR COMPLETE EXISTING HTML CODE HERE

IMPORTANT:
1. Do NOT remove anything from your existing HTML.
2. Paste the FULL code exactly as Claude generated.
3. Replace all special dashes:
   —
   with normal dash:
   -

4. Do NOT paste Python code inside this section.
5. Only HTML/CSS/JS inside this block.

Example:

<!DOCTYPE html>
<html lang="en">

<head>
<meta charset="UTF-8">
<title>NetBrain AI - Enterprise Network Intelligence Platform</title>

<style>
body{
    background:#0f172a;
    color:white;
}
</style>

</head>

<body>

<h1>NetBrain AI</h1>

</body>
</html>

"""

# ---------------------------------------------------
# HTML RENDER
# ---------------------------------------------------

components.html(
    html_code,
    height=5000,
    scrolling=True
)
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>NetBrain AI — Enterprise Network Intelligence Platform</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Mono:wght@300;400;500&family=Fraunces:wght@600;700&display=swap" rel="stylesheet"/>
<style>
/* ═══════════════════════════════════════════
   DESIGN TOKENS — Light Professional
═══════════════════════════════════════════ */
:root {
  /* Surface */
  --white: #ffffff;
  --surface-0: #f7f8fa;
  --surface-1: #eef0f4;
  --surface-2: #e3e6ec;
  --border: #d9dde6;
  --border-strong: #b8bfcc;

  /* Brand — deep navy + electric teal accent */
  --brand-900: #0a1628;
  --brand-800: #0f2042;
  --brand-700: #1a3260;
  --brand-600: #1e4080;
  --brand-500: #2356a8;
  --brand-400: #3b74d0;
  --brand-200: #c8d9f5;
  --brand-100: #e4edfc;
  --brand-50:  #f0f5fd;

  /* Accent */
  --accent: #0077cc;
  --accent-light: #e0f0ff;
  --accent-hover: #005fa3;

  /* Status */
  --green-700: #14613a;
  --green-500: #1e8f55;
  --green-100: #d4f0e1;
  --green-50:  #edfaf4;
  --amber-700: #7a4a00;
  --amber-500: #b06a00;
  --amber-100: #fde8b8;
  --amber-50:  #fff8ea;
  --red-700:   #8b1a1a;
  --red-500:   #c0392b;
  --red-100:   #fad5d2;
  --red-50:    #fef5f5;
  --purple-700:#4a2080;
  --purple-500:#6b35b5;
  --purple-100:#e8d9fa;
  --purple-50: #f5f0fd;

  /* Type */
  --text-primary:   #0f1b2d;
  --text-secondary: #4a5568;
  --text-tertiary:  #7a8799;
  --text-inverse:   #ffffff;

  /* Spacing */
  --sidebar-w: 248px;
  --topbar-h:  56px;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;

  /* Shadow */
  --shadow-xs: 0 1px 3px rgba(15,27,45,.06), 0 1px 2px rgba(15,27,45,.04);
  --shadow-sm: 0 2px 8px rgba(15,27,45,.08), 0 1px 3px rgba(15,27,45,.05);
  --shadow-md: 0 4px 16px rgba(15,27,45,.1), 0 2px 6px rgba(15,27,45,.06);
}

/* ═══════════════════════════════════════════ RESET ═════ */
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'DM Sans',sans-serif;background:var(--surface-0);color:var(--text-primary);height:100vh;overflow:hidden;display:flex;flex-direction:column;font-size:14px;line-height:1.5}
button{font-family:'DM Sans',sans-serif;cursor:pointer;border:none;background:none}
input,textarea{font-family:'DM Sans',sans-serif}
a{text-decoration:none;color:inherit}

/* ═══════════════════════════════════════════ SCROLLBAR ═ */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:10px}
::-webkit-scrollbar-thumb:hover{background:var(--border-strong)}

/* ══════════════════════════════════════════ TOP BAR ════ */
.topbar{
  height:var(--topbar-h);min-height:var(--topbar-h);flex-shrink:0;
  background:var(--brand-900);
  display:flex;align-items:center;padding:0 0 0 0;
  position:relative;z-index:200;
  box-shadow:0 1px 0 rgba(255,255,255,.06);
}
.topbar-brand{
  width:var(--sidebar-w);min-width:var(--sidebar-w);
  display:flex;align-items:center;gap:10px;padding:0 20px;
  border-right:1px solid rgba(255,255,255,.08);height:100%
}
.brand-mark{
  width:32px;height:32px;border-radius:8px;
  background:linear-gradient(135deg,var(--brand-400),var(--accent));
  display:flex;align-items:center;justify-content:center;
  font-size:17px;flex-shrink:0;
  box-shadow:0 0 0 1px rgba(255,255,255,.12)
}
.brand-text{display:flex;flex-direction:column}
.brand-name{font-family:'Fraunces',serif;font-size:16px;font-weight:700;color:#fff;letter-spacing:-.2px;line-height:1.1}
.brand-tag{font-size:10px;color:rgba(255,255,255,.4);letter-spacing:.8px;text-transform:uppercase;font-family:'DM Mono',monospace}
.topbar-center{flex:1;display:flex;align-items:center;gap:10px;padding:0 20px}
.global-search{
  flex:1;max-width:520px;height:34px;
  background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);
  border-radius:8px;display:flex;align-items:center;gap:8px;padding:0 12px;
  transition:.2s;cursor:text
}
.global-search:focus-within{background:rgba(255,255,255,.11);border-color:rgba(255,255,255,.2)}
.global-search input{
  flex:1;background:none;border:none;outline:none;
  color:#fff;font-size:13px;font-family:'DM Sans',sans-serif
}
.global-search input::placeholder{color:rgba(255,255,255,.35)}
.gs-icon{color:rgba(255,255,255,.35);font-size:14px;flex-shrink:0}
.gs-hint{font-size:11px;color:rgba(255,255,255,.25);font-family:'DM Mono',monospace;flex-shrink:0}
.topbar-right{display:flex;align-items:center;gap:6px;padding:0 16px}
.persona-switcher{
  display:flex;align-items:center;gap:0;
  background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);
  border-radius:8px;overflow:hidden;height:30px
}
.ps-btn{
  padding:0 12px;font-size:12px;font-weight:500;color:rgba(255,255,255,.45);
  cursor:pointer;transition:.15s;height:100%;display:flex;align-items:center;gap:5px;
  border-right:1px solid rgba(255,255,255,.08)
}
.ps-btn:last-child{border-right:none}
.ps-btn.active{background:rgba(255,255,255,.14);color:#fff}
.ps-btn:hover:not(.active){color:rgba(255,255,255,.7)}
.topbar-icon-btn{
  width:30px;height:30px;border-radius:7px;
  display:flex;align-items:center;justify-content:center;
  color:rgba(255,255,255,.5);font-size:15px;cursor:pointer;transition:.15s
}
.topbar-icon-btn:hover{background:rgba(255,255,255,.08);color:#fff}
.notif-btn{position:relative}
.notif-dot{
  position:absolute;top:4px;right:4px;width:7px;height:7px;
  border-radius:50%;background:#ff4b4b;
  border:1.5px solid var(--brand-900)
}
.avatar-btn{
  width:30px;height:30px;border-radius:8px;
  background:linear-gradient(135deg,var(--brand-500),var(--accent));
  display:flex;align-items:center;justify-content:center;
  font-size:12px;font-weight:600;color:#fff;cursor:pointer;
  box-shadow:0 0 0 1px rgba(255,255,255,.15)
}

/* ══════════════════════════════════════════ LAYOUT ═════ */
.layout{display:flex;flex:1;overflow:hidden}

/* ══════════════════════════════════════════ SIDEBAR ════ */
.sidebar{
  width:var(--sidebar-w);min-width:var(--sidebar-w);
  background:var(--white);
  border-right:1px solid var(--border);
  display:flex;flex-direction:column;overflow-y:auto;overflow-x:hidden;
  flex-shrink:0
}
.nav-group-label{
  padding:18px 18px 6px;
  font-size:10px;font-weight:600;color:var(--text-tertiary);
  letter-spacing:1.2px;text-transform:uppercase;font-family:'DM Mono',monospace
}
.nav-item{
  display:flex;align-items:center;gap:10px;
  padding:8px 18px;font-size:13px;font-weight:500;
  color:var(--text-secondary);cursor:pointer;
  border-left:3px solid transparent;transition:.12s;
  white-space:nowrap;position:relative
}
.nav-item:hover{background:var(--surface-0);color:var(--text-primary)}
.nav-item.active{
  color:var(--accent);background:var(--accent-light);
  border-left-color:var(--accent)
}
.nav-icon{
  width:20px;height:20px;border-radius:6px;
  display:flex;align-items:center;justify-content:center;
  font-size:13px;flex-shrink:0
}
.nav-item.active .nav-icon{background:var(--accent-light)}
.nav-badge{
  margin-left:auto;font-size:10px;font-weight:600;
  padding:1px 7px;border-radius:20px;
  font-family:'DM Mono',monospace;letter-spacing:.3px
}
.badge-red{background:var(--red-100);color:var(--red-700)}
.badge-amber{background:var(--amber-100);color:var(--amber-700)}
.badge-green{background:var(--green-100);color:var(--green-700)}
.badge-blue{background:var(--brand-100);color:var(--brand-600)}
.badge-purple{background:var(--purple-100);color:var(--purple-700)}
.nav-divider{height:1px;background:var(--border);margin:8px 18px}
.sidebar-footer{
  margin-top:auto;padding:14px 16px;
  border-top:1px solid var(--border)
}
.plan-card{
  background:var(--surface-0);border:1px solid var(--border);
  border-radius:var(--radius-md);padding:12px;margin-bottom:10px
}
.plan-name{font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:2px}
.plan-sub{font-size:11px;color:var(--text-tertiary)}
.health-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px}
.health-label{font-size:11px;color:var(--text-secondary)}
.health-val{font-size:11px;font-weight:600;color:var(--green-700);font-family:'DM Mono',monospace}
.health-track{height:4px;background:var(--surface-2);border-radius:4px;overflow:hidden}
.health-fill{height:100%;background:var(--green-500);border-radius:4px}

/* ══════════════════════════════════════════ CONTENT ════ */
.content{flex:1;overflow-y:auto;overflow-x:hidden;background:var(--surface-0)}
.panel{display:none;flex-direction:column;min-height:100%;padding:24px;gap:20px}
.panel.active{display:flex}

/* ══════════════════════════════════════════ PAGE HDR ═══ */
.page-hdr{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap}
.page-hdr-left{}
.page-title{font-family:'Fraunces',serif;font-size:22px;font-weight:700;color:var(--text-primary);line-height:1.2}
.page-sub{font-size:13px;color:var(--text-secondary);margin-top:3px}
.hdr-actions{display:flex;gap:8px;flex-shrink:0;flex-wrap:wrap}

/* ══════════════════════════════════════════ BUTTONS ════ */
.btn{
  display:inline-flex;align-items:center;gap:6px;
  padding:7px 14px;border-radius:var(--radius-sm);font-size:13px;
  font-weight:500;cursor:pointer;transition:.15s;border:1px solid;
  font-family:'DM Sans',sans-serif;white-space:nowrap;line-height:1
}
.btn-primary{
  background:var(--accent);border-color:var(--accent);color:#fff;
  box-shadow:var(--shadow-xs)
}
.btn-primary:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
.btn-secondary{
  background:var(--white);border-color:var(--border);color:var(--text-secondary);
  box-shadow:var(--shadow-xs)
}
.btn-secondary:hover{border-color:var(--border-strong);color:var(--text-primary)}
.btn-ghost{background:transparent;border-color:transparent;color:var(--text-secondary)}
.btn-ghost:hover{background:var(--surface-1);color:var(--text-primary);border-color:var(--border)}
.btn-danger{background:var(--red-50);border-color:var(--red-100);color:var(--red-700)}
.btn-danger:hover{background:var(--red-100)}
.btn-sm{padding:5px 10px;font-size:12px}

/* ══════════════════════════════════════════ AI INSIGHT ═ */
.ai-insight{
  background:linear-gradient(135deg,var(--brand-50),#fff);
  border:1px solid var(--brand-200);border-radius:var(--radius-md);
  padding:14px 16px;display:flex;gap:12px;align-items:flex-start
}
.ai-insight-icon{
  width:32px;height:32px;border-radius:8px;flex-shrink:0;
  background:linear-gradient(135deg,var(--brand-400),var(--accent));
  display:flex;align-items:center;justify-content:center;font-size:15px
}
.ai-insight-body{flex:1}
.ai-insight-label{
  font-size:10px;font-weight:600;color:var(--accent);
  letter-spacing:1px;text-transform:uppercase;margin-bottom:3px;
  font-family:'DM Mono',monospace
}
.ai-insight-text{font-size:13px;color:var(--text-primary);line-height:1.6}
.ai-insight-text strong{color:var(--brand-700)}
.ai-insight-text code{
  font-family:'DM Mono',monospace;font-size:12px;
  background:var(--brand-100);color:var(--brand-700);
  padding:1px 6px;border-radius:4px
}

/* ══════════════════════════════════════════ STAT CARDS ═ */
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.stat-card{
  background:var(--white);border:1px solid var(--border);
  border-radius:var(--radius-md);padding:18px;
  box-shadow:var(--shadow-xs);position:relative;overflow:hidden;
  transition:.2s;cursor:default
}
.stat-card:hover{box-shadow:var(--shadow-sm);border-color:var(--border-strong)}
.stat-card::after{
  content:'';position:absolute;bottom:0;left:0;right:0;height:3px
}
.stat-card.s-green::after{background:var(--green-500)}
.stat-card.s-red::after{background:var(--red-500)}
.stat-card.s-amber::after{background:var(--amber-500)}
.stat-card.s-blue::after{background:var(--accent)}
.stat-label{font-size:11px;font-weight:600;color:var(--text-tertiary);letter-spacing:.5px;text-transform:uppercase;font-family:'DM Mono',monospace}
.stat-value{font-size:30px;font-weight:700;font-family:'Fraunces',serif;margin:6px 0 4px;line-height:1}
.stat-card.s-green .stat-value{color:var(--green-700)}
.stat-card.s-red .stat-value{color:var(--red-700)}
.stat-card.s-amber .stat-value{color:var(--amber-700)}
.stat-card.s-blue .stat-value{color:var(--brand-700)}
.stat-meta{font-size:12px;color:var(--text-tertiary)}
.stat-icon{position:absolute;right:14px;top:14px;font-size:22px;opacity:.15}

/* ══════════════════════════════════════════ CARDS ══════ */
.card{
  background:var(--white);border:1px solid var(--border);
  border-radius:var(--radius-md);overflow:hidden;box-shadow:var(--shadow-xs)
}
.card-header{
  padding:14px 18px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  background:var(--white)
}
.card-title{
  font-size:13px;font-weight:600;color:var(--text-primary);
  display:flex;align-items:center;gap:7px
}
.card-subtitle{font-size:12px;color:var(--text-tertiary);margin-top:1px}
.card-actions{display:flex;gap:6px;align-items:center}
.card-body{padding:18px}

/* STATUS CHIPS */
.chip{
  display:inline-flex;align-items:center;gap:4px;
  padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;
  font-family:'DM Mono',monospace
}
.chip-green{background:var(--green-100);color:var(--green-700)}
.chip-red{background:var(--red-100);color:var(--red-700)}
.chip-amber{background:var(--amber-100);color:var(--amber-700)}
.chip-blue{background:var(--brand-100);color:var(--brand-600)}
.chip-purple{background:var(--purple-100);color:var(--purple-700)}
.chip-dot{width:5px;height:5px;border-radius:50%;background:currentColor}

/* ══════════════════════════════════════════ 2-COL GRID ═ */
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
.grid-4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.span-2{grid-column:span 2}

/* ══════════════════════════════════════════ TABLE ══════ */
.data-table{width:100%;border-collapse:collapse}
.data-table thead tr{border-bottom:2px solid var(--border)}
.data-table th{
  padding:10px 14px;text-align:left;font-size:11px;font-weight:600;
  color:var(--text-tertiary);letter-spacing:.5px;text-transform:uppercase;
  font-family:'DM Mono',monospace;white-space:nowrap
}
.data-table td{
  padding:11px 14px;font-size:13px;color:var(--text-secondary);
  border-bottom:1px solid var(--surface-1)
}
.data-table tbody tr{transition:.1s}
.data-table tbody tr:hover{background:var(--surface-0)}
.data-table tbody tr:last-child td{border-bottom:none}
.td-primary{color:var(--text-primary) !important;font-weight:500}
.td-mono{font-family:'DM Mono',monospace;font-size:12px !important}
.status-led{width:8px;height:8px;border-radius:50%;display:inline-block}

/* ══════════════════════════════════════════ ALERTS ════ */
.alert-row{
  display:flex;align-items:flex-start;gap:12px;padding:13px 18px;
  border-bottom:1px solid var(--surface-1);transition:.1s;cursor:pointer
}
.alert-row:hover{background:var(--surface-0)}
.alert-row:last-child{border-bottom:none}
.alert-sev{
  width:32px;height:32px;border-radius:8px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:14px
}
.sev-crit{background:var(--red-100)}
.sev-warn{background:var(--amber-100)}
.sev-info{background:var(--brand-100)}
.alert-body{flex:1}
.alert-title{font-size:13px;font-weight:500;color:var(--text-primary);margin-bottom:3px}
.alert-meta{font-size:11px;color:var(--text-tertiary);font-family:'DM Mono',monospace}
.alert-time{font-size:11px;color:var(--text-tertiary);font-family:'DM Mono',monospace;flex-shrink:0;margin-top:2px}
.alert-ai-badge{
  display:inline-flex;align-items:center;gap:4px;
  padding:1px 7px;border-radius:10px;font-size:10px;font-weight:600;
  background:var(--purple-100);color:var(--purple-700);
  font-family:'DM Mono',monospace;margin-top:4px
}

/* ══════════════════════════════════════════ TOPOLOGY ══ */
.topo-surface{
  background:var(--surface-0);border:1px solid var(--border);
  border-radius:var(--radius-sm);overflow:hidden;
  position:relative
}
.topo-toolbar{
  padding:10px 14px;border-bottom:1px solid var(--border);
  display:flex;gap:6px;align-items:center;background:var(--white);flex-wrap:wrap
}
.layer-btn{
  padding:4px 10px;border-radius:20px;font-size:12px;font-weight:500;
  border:1px solid var(--border);background:var(--white);color:var(--text-secondary);
  cursor:pointer;transition:.12s
}
.layer-btn.active{background:var(--accent);border-color:var(--accent);color:#fff}
.layer-btn:hover:not(.active){border-color:var(--border-strong);color:var(--text-primary)}

/* ══════════════════════════════════════════ CHAT ═══════ */
.chat-wrap{display:flex;flex-direction:column;height:calc(100vh - var(--topbar-h));overflow:hidden}
.chat-topbar{
  padding:14px 20px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
  background:var(--white);flex-shrink:0
}
.chat-info .chat-name{font-size:15px;font-weight:600;color:var(--text-primary)}
.chat-info .chat-status{font-size:12px;color:var(--text-tertiary);margin-top:1px}
.chat-tags{display:flex;gap:6px}
.chat-messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px}
.msg{display:flex;gap:10px;max-width:88%}
.msg.user-msg{align-self:flex-end;flex-direction:row-reverse}
.msg-av{
  width:28px;height:28px;border-radius:7px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:13px
}
.ai-av{background:linear-gradient(135deg,var(--brand-400),var(--accent))}
.user-av{background:linear-gradient(135deg,var(--purple-500),var(--purple-700))}
.msg-bubble{padding:10px 14px;border-radius:10px;font-size:13px;line-height:1.65}
.ai-bubble{
  background:var(--white);border:1px solid var(--border);
  color:var(--text-primary);border-top-left-radius:2px;
  box-shadow:var(--shadow-xs)
}
.user-bubble{
  background:var(--accent);color:#fff;
  border-top-right-radius:2px
}
.msg-bubble code{
  font-family:'DM Mono',monospace;font-size:12px;
  background:var(--surface-1);color:var(--brand-700);
  padding:1px 5px;border-radius:4px
}
.user-bubble code{background:rgba(255,255,255,.2);color:#fff}
.msg-bubble pre{
  font-family:'DM Mono',monospace;font-size:12px;
  background:var(--brand-900);color:#7dd3a8;
  padding:12px;border-radius:8px;margin-top:8px;overflow-x:auto;
  line-height:1.7
}
.typing-indicator{display:flex;gap:4px;padding:10px 14px;align-items:center}
.typing-dot{
  width:7px;height:7px;border-radius:50%;background:var(--border-strong);
  animation:tdot 1.2s infinite
}
.typing-dot:nth-child(2){animation-delay:.2s}
.typing-dot:nth-child(3){animation-delay:.4s}
@keyframes tdot{0%,60%,100%{transform:translateY(0);opacity:.5}30%{transform:translateY(-6px);opacity:1}}
.quick-chips{display:flex;gap:6px;flex-wrap:wrap;padding:0 20px 10px}
.qchip{
  padding:5px 11px;border-radius:20px;font-size:12px;font-weight:500;
  background:var(--white);border:1px solid var(--border);color:var(--text-secondary);
  cursor:pointer;transition:.12s;white-space:nowrap
}
.qchip:hover{border-color:var(--accent);color:var(--accent);background:var(--accent-light)}
.chat-input-area{
  padding:14px 20px;border-top:1px solid var(--border);
  display:flex;gap:10px;background:var(--white);flex-shrink:0;align-items:flex-end
}
.chat-input{
  flex:1;background:var(--surface-0);border:1px solid var(--border);
  border-radius:10px;padding:9px 14px;font-size:13px;color:var(--text-primary);
  outline:none;resize:none;transition:.15s;max-height:100px;
  font-family:'DM Sans',sans-serif;line-height:1.5
}
.chat-input:focus{border-color:var(--accent);background:var(--white)}
.chat-input::placeholder{color:var(--text-tertiary)}
.send-btn{
  width:36px;height:36px;border-radius:8px;
  background:var(--accent);color:#fff;border:none;
  display:flex;align-items:center;justify-content:center;
  cursor:pointer;transition:.15s;flex-shrink:0;font-size:16px
}
.send-btn:hover{background:var(--accent-hover)}

/* ══════════════════════════════════════════ CLI ════════ */
.cli-wrap{
  background:var(--brand-900);border:1px solid var(--border);
  border-radius:var(--radius-md);overflow:hidden;
  display:flex;flex-direction:column;flex:1;min-height:360px;
  box-shadow:var(--shadow-md)
}
.cli-bar{
  background:#111e35;padding:10px 16px;
  display:flex;align-items:center;gap:10px;border-bottom:1px solid rgba(255,255,255,.06)
}
.cli-dots{display:flex;gap:6px}
.cli-dot{width:11px;height:11px;border-radius:50%}
.cli-title{font-family:'DM Mono',monospace;font-size:12px;color:rgba(255,255,255,.3);margin-left:4px}
.cli-badge{
  margin-left:auto;padding:2px 8px;border-radius:10px;
  background:rgba(0,119,204,.25);border:1px solid rgba(0,119,204,.4);
  font-size:11px;color:#7ab8f0;font-family:'DM Mono',monospace
}
.cli-output{
  flex:1;padding:14px 18px;overflow-y:auto;
  font-family:'DM Mono',monospace;font-size:13px;line-height:1.9;color:#a8c4e0
}
.cli-output::-webkit-scrollbar{width:4px}
.cli-output::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1)}
.cli-prompt{color:#4aa3df}
.cli-cmd-text{color:#e8f0fe}
.cli-out-text{color:#7dd3a8}
.cli-warn-text{color:#fbbf24}
.cli-err-text{color:#f87171}
.cli-ai-text{color:#c4b5fd}
.cli-input-bar{
  background:#111e35;border-top:1px solid rgba(255,255,255,.06);
  padding:10px 18px;display:flex;align-items:center;gap:10px
}
.cli-label{font-family:'DM Mono',monospace;font-size:13px;color:#4aa3df;flex-shrink:0}
.cli-text-input{
  flex:1;background:none;border:none;outline:none;
  font-family:'DM Mono',monospace;font-size:13px;color:#e8f0fe
}
.cli-text-input::placeholder{color:rgba(255,255,255,.2)}
.cli-cursor-blink{
  display:inline-block;width:8px;height:14px;
  background:#4aa3df;vertical-align:text-bottom;
  animation:cblink 1s step-end infinite
}
@keyframes cblink{0%,100%{opacity:1}50%{opacity:0}}

/* ══════════════════════════════════════════ LEARNING ═══ */
.track-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.track-card{
  background:var(--white);border:1px solid var(--border);
  border-radius:var(--radius-md);padding:18px;cursor:pointer;
  transition:.18s;box-shadow:var(--shadow-xs);position:relative;overflow:hidden
}
.track-card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:3px
}
.track-card.tc-blue::before{background:var(--accent)}
.track-card.tc-green::before{background:var(--green-500)}
.track-card.tc-amber::before{background:var(--amber-500)}
.track-card.tc-red::before{background:var(--red-500)}
.track-card.tc-purple::before{background:var(--purple-500)}
.track-card.tc-brand::before{background:var(--brand-500)}
.track-card:hover{box-shadow:var(--shadow-md);transform:translateY(-2px);border-color:var(--border-strong)}
.track-icon{font-size:26px;margin-bottom:10px}
.track-name{font-size:14px;font-weight:600;color:var(--text-primary);margin-bottom:3px}
.track-desc{font-size:12px;color:var(--text-tertiary);margin-bottom:12px;line-height:1.5}
.prog-bar{height:5px;background:var(--surface-1);border-radius:4px;overflow:hidden;margin-bottom:5px}
.prog-fill{height:100%;border-radius:4px;transition:.4s}
.prog-txt{font-size:11px;color:var(--text-tertiary);font-family:'DM Mono',monospace}

/* ══════════════════════════════════════════ COMPLIANCE ═ */
.compliance-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.comp-card{
  background:var(--white);border:1px solid var(--border);
  border-radius:var(--radius-md);padding:18px;box-shadow:var(--shadow-xs)
}
.comp-framework{font-size:10px;font-weight:600;color:var(--text-tertiary);letter-spacing:1px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:6px}
.comp-score{font-size:32px;font-weight:700;font-family:'Fraunces',serif;margin:4px 0;line-height:1}
.comp-desc{font-size:12px;color:var(--text-tertiary);margin-top:2px}
.comp-bar{height:4px;background:var(--surface-2);border-radius:4px;overflow:hidden;margin-top:10px}
.comp-fill{height:100%;border-radius:4px}

/* ══════════════════════════════════════════ VOICE ══════ */
.voice-stage{
  display:flex;flex-direction:column;align-items:center;
  justify-content:center;flex:1;gap:24px;padding:40px;
  background:var(--white);border:1px solid var(--border);
  border-radius:var(--radius-md);box-shadow:var(--shadow-xs);
  min-height:340px
}
.voice-orb{
  width:110px;height:110px;border-radius:50%;cursor:pointer;
  background:linear-gradient(135deg,var(--brand-100),var(--accent-light));
  border:2px solid var(--brand-200);display:flex;align-items:center;
  justify-content:center;font-size:40px;transition:.3s;position:relative
}
.voice-orb:hover{box-shadow:0 8px 30px rgba(0,119,204,.15)}
.voice-orb.on{
  background:linear-gradient(135deg,var(--green-100),var(--accent-light));
  border-color:var(--green-500);animation:orb-pulse 1.8s infinite
}
@keyframes orb-pulse{0%,100%{box-shadow:0 0 0 0 rgba(30,143,85,.25)}50%{box-shadow:0 0 0 20px rgba(30,143,85,0)}}
.voice-status{font-size:15px;color:var(--text-secondary);font-weight:500}
.voice-transcript{
  background:var(--surface-0);border:1px solid var(--border);
  border-radius:var(--radius-md);padding:14px 18px;
  font-size:13px;color:var(--text-primary);
  font-family:'DM Mono',monospace;line-height:1.7;
  width:100%;max-width:520px;min-height:70px
}

/* ══════════════════════════════════════════ TWIN ═══════ */
.twin-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:0}
.twin-m{
  background:var(--white);border:1px solid var(--border);border-radius:var(--radius-md);
  padding:14px;text-align:center;box-shadow:var(--shadow-xs)
}
.twin-val{font-size:22px;font-weight:700;font-family:'Fraunces',serif;color:var(--brand-700)}
.twin-lbl{font-size:11px;color:var(--text-tertiary);margin-top:2px}

/* ══════════════════════════════════════════ DESIGN ═════ */
.design-card{
  background:var(--white);border:1px solid var(--border);border-radius:var(--radius-md);
  padding:18px;cursor:pointer;transition:.18s;box-shadow:var(--shadow-xs);
  display:flex;gap:14px;align-items:flex-start
}
.design-card:hover{box-shadow:var(--shadow-md);border-color:var(--border-strong)}
.design-icon{
  width:40px;height:40px;border-radius:10px;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;font-size:20px
}
.design-card-body .dc-name{font-size:14px;font-weight:600;color:var(--text-primary);margin-bottom:3px}
.design-card-body .dc-desc{font-size:12px;color:var(--text-tertiary);line-height:1.5}
.design-card-body .dc-tags{display:flex;gap:5px;margin-top:8px;flex-wrap:wrap}

/* ══════════════════════════════════════════ ANIMATIONS ═ */
@keyframes fadeUp{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.panel.active > *{animation:fadeUp .22s ease both}
.panel.active > *:nth-child(2){animation-delay:.04s}
.panel.active > *:nth-child(3){animation-delay:.08s}
.panel.active > *:nth-child(4){animation-delay:.12s}
.panel.active > *:nth-child(5){animation-delay:.16s}

/* ══════════════════════════════════════════ STATUS BAR ═ */
.status-ticker{
  height:28px;background:var(--brand-900);display:flex;align-items:center;
  padding:0 16px;gap:16px;flex-shrink:0;border-top:1px solid rgba(255,255,255,.06)
}
.ticker-live{display:flex;align-items:center;gap:6px;font-size:11px;color:rgba(255,255,255,.4);font-family:'DM Mono',monospace}
.live-dot{width:6px;height:6px;border-radius:50%;background:#1e8f55;animation:pulse-live 2s infinite}
@keyframes pulse-live{0%,100%{opacity:1}50%{opacity:.4}}
.ticker-items{flex:1;overflow:hidden;display:flex;gap:24px}
.ticker-item{font-size:11px;color:rgba(255,255,255,.3);font-family:'DM Mono',monospace;white-space:nowrap}
.ticker-item.ti-warn{color:rgba(251,191,36,.6)}
.ticker-item.ti-err{color:rgba(248,113,113,.6)}
.ticker-sep{color:rgba(255,255,255,.12)}

/* ══════════════════════════════════════════ RESPONSIVE ═ */
@media(max-width:1100px){
  .stats-grid{grid-template-columns:1fr 1fr}
  .grid-2,.grid-3,.track-grid,.compliance-grid{grid-template-columns:1fr}
  .span-2{grid-column:span 1}
  .twin-metrics{grid-template-columns:1fr 1fr}
}
@media(max-width:760px){
  :root{--sidebar-w:52px}
  .nav-item span:not(.nav-icon),.nav-badge,.nav-group-label,.brand-text,.sidebar-footer{display:none}
  .topbar-brand{padding:0 10px;justify-content:center}
  .stats-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<!-- ═════════════════════ TOP BAR ═════════════════════ -->
<div class="topbar">
  <div class="topbar-brand">
    <div class="brand-mark">🧠</div>
    <div class="brand-text">
      <div class="brand-name">NetBrain AI</div>
      <div class="brand-tag">Network Intelligence</div>
    </div>
  </div>
  <div class="topbar-center">
    <div class="global-search" onclick="document.getElementById('gsInput').focus()">
      <span class="gs-icon">⌕</span>
      <input id="gsInput" placeholder="Search devices, ask AI, run commands…" onkeydown="gsKey(event)"/>
      <span class="gs-hint">⏎ AI</span>
    </div>
  </div>
  <div class="topbar-right">
    <!-- Persona switcher -->
    <div class="persona-switcher">
      <div class="ps-btn active" id="ps-ccna" onclick="setPersona('ccna',this)">🎓 CCNA</div>
      <div class="ps-btn" id="ps-noc" onclick="setPersona('noc',this)">🖥 NOC</div>
      <div class="ps-btn" id="ps-arch" onclick="setPersona('arch',this)">🏗 Architect</div>
    </div>
    <div class="topbar-icon-btn notif-btn" onclick="showPanel('alerts')">
      🔔<span class="notif-dot"></span>
    </div>
    <div class="topbar-icon-btn">⚙</div>
    <div class="avatar-btn">AK</div>
  </div>
</div>

<!-- ═════════════════════ LAYOUT ══════════════════════ -->
<div class="layout">

  <!-- ════ SIDEBAR ════ -->
  <nav class="sidebar">

    <div class="nav-group-label">Operations</div>
    <div class="nav-item active" onclick="showPanel('overview')">
      <div class="nav-icon">📊</div><span>Overview</span>
    </div>
    <div class="nav-item" onclick="showPanel('topology')">
      <div class="nav-icon">🗺</div><span>Topology</span>
    </div>
    <div class="nav-item" onclick="showPanel('alerts')">
      <div class="nav-icon">🚨</div><span>Alerts &amp; Outages</span>
      <span class="nav-badge badge-red">7</span>
    </div>
    <div class="nav-item" onclick="showPanel('troubleshoot')">
      <div class="nav-icon">🔧</div><span>Troubleshooting</span>
    </div>
    <div class="nav-item" onclick="showPanel('automation')">
      <div class="nav-icon">⚙</div><span>Automation</span>
      <span class="nav-badge badge-green">3</span>
    </div>
    <div class="nav-item" onclick="showPanel('compliance')">
      <div class="nav-icon">🛡</div><span>Compliance</span>
    </div>
    <div class="nav-item" onclick="showPanel('security')">
      <div class="nav-icon">🔒</div><span>Security Ops</span>
      <span class="nav-badge badge-amber">2</span>
    </div>

    <div class="nav-divider"></div>
    <div class="nav-group-label">AI Intelligence</div>
    <div class="nav-item" onclick="showPanel('chat')">
      <div class="nav-icon">🤖</div><span>AI Assistant</span>
      <span class="nav-badge badge-purple">NLP</span>
    </div>
    <div class="nav-item" onclick="showPanel('voice')">
      <div class="nav-icon">🎙</div><span>Voice Ops</span>
    </div>
    <div class="nav-item" onclick="showPanel('cli')">
      <div class="nav-icon">💻</div><span>CLI Assistant</span>
    </div>
    <div class="nav-item" onclick="showPanel('design')">
      <div class="nav-icon">🏗</div><span>Network Design</span>
    </div>
    <div class="nav-item" onclick="showPanel('twin')">
      <div class="nav-icon">👾</div><span>Digital Twin</span>
    </div>
    <div class="nav-item" onclick="showPanel('observability')">
      <div class="nav-icon">📡</div><span>Observability</span>
    </div>

    <div class="nav-divider"></div>
    <div class="nav-group-label">Learning</div>
    <div class="nav-item" onclick="showPanel('learn')">
      <div class="nav-icon">📚</div><span>Learning Hub</span>
    </div>
    <div class="nav-item" onclick="showPanel('certs')">
      <div class="nav-icon">🏆</div><span>Certifications</span>
    </div>
    <div class="nav-item" onclick="showPanel('playbooks')">
      <div class="nav-icon">📋</div><span>Runbooks</span>
    </div>

    <div class="nav-divider"></div>
    <div class="nav-group-label">Business</div>
    <div class="nav-item" onclick="showPanel('executive')">
      <div class="nav-icon">📈</div><span>Executive View</span>
    </div>
    <div class="nav-item" onclick="showPanel('finops')">
      <div class="nav-icon">💰</div><span>FinOps &amp; Cost</span>
    </div>

    <div class="sidebar-footer">
      <div class="plan-card">
        <div class="plan-name">🚀 Free Tier — Replit</div>
        <div class="plan-sub">Claude API · SQLite · No sleep</div>
      </div>
      <div class="health-row">
        <span class="health-label">Platform health</span>
        <span class="health-val">97%</span>
      </div>
      <div class="health-track"><div class="health-fill" style="width:97%"></div></div>
    </div>
  </nav>

  <!-- ════ CONTENT ════ -->
  <div class="content" id="mainContent">

    <!-- ══════ OVERVIEW ══════ -->
    <div class="panel active" id="panel-overview">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Network Overview</div>
          <div class="page-sub">847 managed devices · Real-time telemetry · Last sync 12s ago</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-secondary btn-sm" onclick="showPanel('chat')">💬 Ask AI</button>
          <button class="btn btn-primary btn-sm">⬇ Export Report</button>
        </div>
      </div>

      <!-- AI INSIGHT -->
      <div class="ai-insight">
        <div class="ai-insight-icon">🧠</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">AI Insight · NLP Engine</div>
          <div class="ai-insight-text">
            <strong>BGP session flapping detected</strong> on <code>PE-MUM-01 → AS65002</code> — 3 flaps in the last hour. Root cause correlated to upstream ISP route withdrawal. Similar incident on 2024-11-14 resolved by ISP escalation in ~40 min.
            <strong>Recommended:</strong> monitor 10 min, then open ISP ticket if persists. 142 prefixes at risk.
          </div>
        </div>
      </div>

      <!-- STATS -->
      <div class="stats-grid">
        <div class="stat-card s-green">
          <div class="stat-icon">✅</div>
          <div class="stat-label">Devices Online</div>
          <div class="stat-value">831</div>
          <div class="stat-meta">of 847 · 16 degraded</div>
        </div>
        <div class="stat-card s-red">
          <div class="stat-icon">🚨</div>
          <div class="stat-label">Active Alerts</div>
          <div class="stat-value">7</div>
          <div class="stat-meta">3 critical · 4 warning</div>
        </div>
        <div class="stat-card s-blue">
          <div class="stat-icon">🔄</div>
          <div class="stat-label">BGP Sessions</div>
          <div class="stat-value">248</div>
          <div class="stat-meta">247 established · 1 active</div>
        </div>
        <div class="stat-card s-amber">
          <div class="stat-icon">⚡</div>
          <div class="stat-label">Avg Latency</div>
          <div class="stat-value">14ms</div>
          <div class="stat-meta">↑ +2ms from 7-day baseline</div>
        </div>
      </div>

      <div class="grid-2">
        <!-- TOPOLOGY PREVIEW -->
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">🗺 Live Topology Snapshot</div>
              <div class="card-subtitle">Click devices for AI analysis</div>
            </div>
            <div class="card-actions">
              <span class="chip chip-green"><span class="chip-dot"></span>Live</span>
              <button class="btn btn-ghost btn-sm" onclick="showPanel('topology')">Full view →</button>
            </div>
          </div>
          <div class="topo-surface" style="height:240px">
            <svg viewBox="0 0 480 230" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
              <rect width="480" height="230" fill="#f7f8fa"/>
              <!-- Links -->
              <line x1="240" y1="55" x2="110" y2="120" stroke="#b8bfcc" stroke-width="1.5"/>
              <line x1="240" y1="55" x2="240" y2="125" stroke="#f59e0b" stroke-width="2" stroke-dasharray="4 3"/>
              <line x1="240" y1="55" x2="370" y2="120" stroke="#b8bfcc" stroke-width="1.5"/>
              <line x1="110" y1="133" x2="65" y2="190" stroke="#d9dde6" stroke-width="1"/>
              <line x1="110" y1="133" x2="155" y2="190" stroke="#d9dde6" stroke-width="1"/>
              <line x1="240" y1="138" x2="240" y2="190" stroke="#d9dde6" stroke-width="1"/>
              <line x1="370" y1="133" x2="325" y2="190" stroke="#d9dde6" stroke-width="1"/>
              <line x1="370" y1="133" x2="415" y2="190" stroke="#d9dde6" stroke-width="1"/>
              <!-- Core -->
              <circle cx="240" cy="42" r="20" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
              <text x="240" y="38" text-anchor="middle" fill="#1e4080" font-size="11" font-family="DM Mono">CORE</text>
              <text x="240" y="50" text-anchor="middle" fill="#2356a8" font-size="8" font-family="DM Mono">RTR-01</text>
              <!-- Dist -->
              <rect x="84" y="120" width="52" height="26" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
              <text x="110" y="136" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-W</text>
              <rect x="214" y="125" width="52" height="26" rx="5" fill="#fff8ea" stroke="#b06a00" stroke-width="1.5"/>
              <text x="240" y="137" text-anchor="middle" fill="#7a4a00" font-size="9" font-family="DM Mono">DIST-C⚠</text>
              <rect x="344" y="120" width="52" height="26" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
              <text x="370" y="136" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-E</text>
              <!-- Access -->
              <circle cx="65" cy="195" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
              <circle cx="155" cy="195" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
              <circle cx="240" cy="195" r="9" fill="#fef5f5" stroke="#c0392b" stroke-width="1.5"/>
              <circle cx="325" cy="195" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
              <circle cx="415" cy="195" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
              <text x="240" y="215" text-anchor="middle" fill="#c0392b" font-size="8" font-family="DM Mono">DOWN</text>
              <!-- Legend -->
              <circle cx="24" cy="18" r="5" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
              <text x="33" y="22" fill="#4a5568" font-size="8" font-family="DM Sans">Up</text>
              <circle cx="60" cy="18" r="5" fill="#fff8ea" stroke="#b06a00" stroke-width="1"/>
              <text x="69" y="22" fill="#4a5568" font-size="8" font-family="DM Sans">Warning</text>
              <circle cx="112" cy="18" r="5" fill="#fef5f5" stroke="#c0392b" stroke-width="1"/>
              <text x="121" y="22" fill="#4a5568" font-size="8" font-family="DM Sans">Down</text>
            </svg>
          </div>
        </div>

        <!-- ALERTS -->
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">🚨 Active Alerts</div>
              <div class="card-subtitle">AI root-cause correlated</div>
            </div>
            <div class="card-actions">
              <span class="chip chip-red">7 active</span>
              <button class="btn btn-ghost btn-sm" onclick="showPanel('alerts')">All →</button>
            </div>
          </div>
          <div id="alertsList">
            <div class="alert-row">
              <div class="alert-sev sev-crit">🔴</div>
              <div class="alert-body">
                <div class="alert-title">BGP session flapping — PE-MUM-01</div>
                <div class="alert-meta">Routing · AS65002 · 142 prefixes at risk</div>
                <div class="alert-ai-badge">🧠 AI: ISP upstream issue</div>
              </div>
              <div class="alert-time">2m</div>
            </div>
            <div class="alert-row">
              <div class="alert-sev sev-crit">🔴</div>
              <div class="alert-body">
                <div class="alert-title">Interface Down — Gi0/0/3 on SW-ACC-14</div>
                <div class="alert-meta">Access layer · VLAN 120 · 47 users</div>
              </div>
              <div class="alert-time">8m</div>
            </div>
            <div class="alert-row">
              <div class="alert-sev sev-warn">🟡</div>
              <div class="alert-body">
                <div class="alert-title">High CPU — CORE-RTR-01 (88%)</div>
                <div class="alert-meta">OSPF SPF recalculation suspected</div>
                <div class="alert-ai-badge">🧠 AI: Related to BGP flap</div>
              </div>
              <div class="alert-time">14m</div>
            </div>
            <div class="alert-row">
              <div class="alert-sev sev-warn">🟡</div>
              <div class="alert-body">
                <div class="alert-title">VPN Tunnel Down — Branch-HYD</div>
                <div class="alert-meta">IPSec · DPD timeout · 1 site offline</div>
              </div>
              <div class="alert-time">45m</div>
            </div>
          </div>
        </div>
      </div>

      <!-- DEVICE TABLE -->
      <div class="card">
        <div class="card-header">
          <div>
            <div class="card-title">📋 Critical Device Inventory</div>
            <div class="card-subtitle">Live telemetry · Click any row for AI analysis</div>
          </div>
          <div class="card-actions">
            <input type="text" placeholder="Filter…" style="padding:5px 10px;border:1px solid var(--border);border-radius:6px;font-size:12px;outline:none;background:var(--surface-0);width:160px"/>
            <button class="btn btn-secondary btn-sm">⬇ Export</button>
          </div>
        </div>
        <table class="data-table">
          <thead>
            <tr>
              <th>Status</th><th>Hostname</th><th>IP Address</th>
              <th>Vendor / OS</th><th>Role</th><th>CPU</th><th>Memory</th><th>Uptime</th><th>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr onclick="showPanel('chat');sendQuick('Analyze CORE-RTR-01 health and give recommendations')">
              <td><span class="status-led" style="background:var(--amber-500)"></span></td>
              <td class="td-primary td-mono">CORE-RTR-01</td>
              <td class="td-mono">10.0.0.1</td>
              <td>Cisco IOS-XR 7.5</td>
              <td><span class="chip chip-blue">Core Router</span></td>
              <td style="color:var(--amber-700);font-family:'DM Mono',monospace;font-weight:600">88%</td>
              <td class="td-mono">62%</td>
              <td class="td-mono">127d 4h</td>
              <td><button class="btn btn-ghost btn-sm">🧠 AI</button></td>
            </tr>
            <tr onclick="showPanel('chat');sendQuick('Diagnose BGP issue on PE-MUM-01')">
              <td><span class="status-led" style="background:var(--red-500)"></span></td>
              <td class="td-primary td-mono">PE-MUM-01</td>
              <td class="td-mono">10.0.1.1</td>
              <td>Cisco IOS-XR 7.7</td>
              <td><span class="chip chip-blue">PE Router</span></td>
              <td class="td-mono">34%</td>
              <td class="td-mono">48%</td>
              <td class="td-mono">89d 12h</td>
              <td><button class="btn btn-ghost btn-sm">🧠 AI</button></td>
            </tr>
            <tr>
              <td><span class="status-led" style="background:var(--green-500)"></span></td>
              <td class="td-primary td-mono">DIST-SW-W</td>
              <td class="td-mono">10.1.1.4</td>
              <td>Arista EOS 4.28</td>
              <td><span class="chip chip-green">Dist Switch</span></td>
              <td class="td-mono">22%</td>
              <td class="td-mono">55%</td>
              <td class="td-mono">214d 8h</td>
              <td><button class="btn btn-ghost btn-sm">🧠 AI</button></td>
            </tr>
            <tr onclick="showPanel('chat');sendQuick('SW-ACC-14 is down, help me troubleshoot and find root cause')">
              <td><span class="status-led" style="background:var(--red-500)"></span></td>
              <td class="td-primary td-mono">SW-ACC-14</td>
              <td class="td-mono">10.2.14.1</td>
              <td>Cisco IOS 15.2</td>
              <td><span class="chip chip-amber">Access SW</span></td>
              <td style="color:var(--text-tertiary)" class="td-mono">—</td>
              <td style="color:var(--text-tertiary)" class="td-mono">—</td>
              <td><span class="chip chip-red">DOWN</span></td>
              <td><button class="btn btn-danger btn-sm">🔧 Fix</button></td>
            </tr>
            <tr>
              <td><span class="status-led" style="background:var(--green-500)"></span></td>
              <td class="td-primary td-mono">FW-EDGE-01</td>
              <td class="td-mono">192.168.1.1</td>
              <td>Palo Alto PAN-OS 11</td>
              <td><span class="chip chip-purple">Firewall</span></td>
              <td class="td-mono">18%</td>
              <td class="td-mono">41%</td>
              <td class="td-mono">210d 6h</td>
              <td><button class="btn btn-ghost btn-sm">🧠 AI</button></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- ══════ AI CHAT ══════ -->
    <div class="panel" id="panel-chat" style="padding:0;gap:0;overflow:hidden;height:calc(100vh - 84px)">
      <div class="chat-wrap">
        <div class="chat-topbar">
          <div class="chat-info">
            <div class="chat-name">🤖 NetBrain AI Assistant</div>
            <div class="chat-status">NLP · Multi-turn · Context-aware · Persona: <strong id="chatPersonaLabel">CCNA Mode</strong></div>
          </div>
          <div class="chat-tags">
            <span class="chip chip-purple">NLP Active</span>
            <span class="chip chip-blue">RAG On</span>
            <span class="chip chip-green">Persona: <span id="chatPersonaChip">CCNA</span></span>
          </div>
        </div>
        <div class="chat-messages" id="chatMessages">
          <div class="msg">
            <div class="msg-av ai-av">🧠</div>
            <div class="msg-bubble ai-bubble">
              Hello! I'm your <strong>AI Network Brain</strong> — powered by NLP that understands networking naturally.<br><br>
              I serve all three roles simultaneously:<br>
              🎓 <strong>CCNA mode</strong> — explains concepts from scratch with analogies<br>
              🖥 <strong>NOC mode</strong> — fast triage, CLI commands, runbook execution<br>
              🏗 <strong>Architect mode</strong> — design, sizing, vendor selection, BOM<br><br>
              Just ask naturally — I detect your level from how you phrase things. What shall we work on?
            </div>
          </div>
        </div>
        <div class="quick-chips">
          <div class="qchip" onclick="sendQuick('Why is my OSPF neighbor not forming?')">OSPF neighbor down</div>
          <div class="qchip" onclick="sendQuick('Explain BGP path selection in simple terms')">BGP explained simply</div>
          <div class="qchip" onclick="sendQuick('Generate Cisco config for VLAN 100 with SVI 192.168.100.1/24')">Generate VLAN config</div>
          <div class="qchip" onclick="sendQuick('Design an SD-WAN for 50 branches with dual ISP and cloud breakout')">SD-WAN design</div>
          <div class="qchip" onclick="sendQuick('What is MPLS L3VPN and how does it work? Start from basics.')">MPLS L3VPN</div>
          <div class="qchip" onclick="sendQuick('Troubleshoot high CPU on Cisco IOS-XR router')">High CPU fix</div>
        </div>
        <div class="chat-input-area">
          <textarea class="chat-input" id="chatInput" placeholder="Ask anything — 'BGP not forming with ISP' or 'Design a zero-trust campus for 3000 users'…" onkeydown="chatKey(event)" rows="1"></textarea>
          <button class="send-btn" onclick="sendChat()">➤</button>
        </div>
      </div>
    </div>

    <!-- ══════ TOPOLOGY ══════ -->
    <div class="panel" id="panel-topology">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Network Topology</div>
          <div class="page-sub">Live topology map · All domains · Click any device for AI analysis</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-secondary btn-sm">📥 Import LLDP</button>
          <button class="btn btn-secondary btn-sm">🔍 Find Path</button>
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Analyze my network topology for single points of failure and redundancy gaps')">🧠 AI Analyze</button>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">💡</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">NLP Topology Query</div>
          <div class="ai-insight-text">Ask in natural language: <strong>"Show devices in OSPF area 0"</strong> · <strong>"Which links carry more than 80% utilization?"</strong> · <strong>"Find all single points of failure"</strong></div>
        </div>
      </div>
      <div class="card" style="flex:1">
        <div class="topo-toolbar">
          <button class="layer-btn active">🌐 All</button>
          <button class="layer-btn">🔄 L3 Routing</button>
          <button class="layer-btn">🔀 L2 Switching</button>
          <button class="layer-btn">🔒 Security</button>
          <button class="layer-btn">☁ Cloud</button>
          <button class="layer-btn">📡 Wireless</button>
          <button class="layer-btn">⚡ SD-WAN</button>
          <button class="btn btn-primary btn-sm" style="margin-left:auto" onclick="showPanel('chat');sendQuick('I am looking at my topology. Ask me questions to understand my network better.')">💬 Ask AI about topology</button>
        </div>
        <div style="height:420px;background:var(--surface-0);padding:10px;overflow:hidden">
          <svg viewBox="0 0 680 400" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
            <rect width="680" height="400" fill="#f7f8fa"/>
            <!-- Internet cloud -->
            <ellipse cx="340" cy="35" rx="70" ry="22" fill="#f5f0fd" stroke="#6b35b5" stroke-width="1" stroke-dasharray="5 3"/>
            <text x="340" y="40" text-anchor="middle" fill="#6b35b5" font-size="11" font-family="DM Mono">INTERNET / ISP</text>
            <!-- FW -->
            <line x1="340" y1="57" x2="340" y2="95" stroke="#6b35b5" stroke-width="1.5"/>
            <rect x="305" y="95" width="70" height="28" rx="6" fill="#f5f0fd" stroke="#6b35b5" stroke-width="1"/>
            <text x="340" y="113" text-anchor="middle" fill="#4a2080" font-size="10" font-family="DM Mono">FW-EDGE-01</text>
            <!-- Core routers -->
            <line x1="340" y1="123" x2="180" y2="175" stroke="#b8bfcc" stroke-width="1.5"/>
            <line x1="340" y1="123" x2="340" y2="175" stroke="#b8bfcc" stroke-width="2"/>
            <line x1="340" y1="123" x2="500" y2="175" stroke="#b8bfcc" stroke-width="1.5"/>
            <circle cx="180" cy="192" r="24" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
            <text x="180" y="189" text-anchor="middle" fill="#1e4080" font-size="10" font-family="DM Mono">CORE</text>
            <text x="180" y="202" text-anchor="middle" fill="#2356a8" font-size="8" font-family="DM Mono">RTR-01</text>
            <circle cx="340" cy="192" r="24" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
            <text x="340" y="189" text-anchor="middle" fill="#1e4080" font-size="10" font-family="DM Mono">PE</text>
            <text x="340" y="202" text-anchor="middle" fill="#2356a8" font-size="8" font-family="DM Mono">MUM-01</text>
            <circle cx="500" cy="192" r="24" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/>
            <text x="500" y="189" text-anchor="middle" fill="#1e4080" font-size="10" font-family="DM Mono">PE</text>
            <text x="500" y="202" text-anchor="middle" fill="#2356a8" font-size="8" font-family="DM Mono">DEL-01</text>
            <!-- Dist layer -->
            <line x1="180" y1="216" x2="120" y2="268" stroke="#d9dde6" stroke-width="1"/>
            <line x1="180" y1="216" x2="240" y2="268" stroke="#d9dde6" stroke-width="1"/>
            <line x1="340" y1="216" x2="340" y2="268" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4 3"/>
            <line x1="500" y1="216" x2="440" y2="268" stroke="#d9dde6" stroke-width="1"/>
            <line x1="500" y1="216" x2="560" y2="268" stroke="#d9dde6" stroke-width="1"/>
            <rect x="94" y="268" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
            <text x="120" y="282" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-W</text>
            <rect x="214" y="268" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
            <text x="240" y="282" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-E</text>
            <rect x="314" y="268" width="52" height="22" rx="5" fill="#fff8ea" stroke="#b06a00" stroke-width="1.5"/>
            <text x="340" y="278" text-anchor="middle" fill="#7a4a00" font-size="9" font-family="DM Mono">DIST-C</text>
            <text x="340" y="289" text-anchor="middle" fill="#b06a00" font-size="7" font-family="DM Mono">⚠ warn</text>
            <rect x="414" y="268" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
            <text x="440" y="282" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-N</text>
            <rect x="534" y="268" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/>
            <text x="560" y="282" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-S</text>
            <!-- Access layer -->
            <line x1="120" y1="290" x2="80" y2="340" stroke="#eef0f4" stroke-width="1"/>
            <line x1="120" y1="290" x2="160" y2="340" stroke="#eef0f4" stroke-width="1"/>
            <line x1="240" y1="290" x2="200" y2="340" stroke="#eef0f4" stroke-width="1"/>
            <line x1="240" y1="290" x2="280" y2="340" stroke="#eef0f4" stroke-width="1"/>
            <line x1="440" y1="290" x2="420" y2="340" stroke="#eef0f4" stroke-width="1"/>
            <line x1="560" y1="290" x2="540" y2="340" stroke="#eef0f4" stroke-width="1"/>
            <line x1="560" y1="290" x2="600" y2="340" stroke="#eef0f4" stroke-width="1"/>
            <rect x="64" y="340" width="32" height="18" rx="4" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/>
            <text x="80" y="352" text-anchor="middle" fill="#14613a" font-size="8" font-family="DM Mono">ACC-1</text>
            <rect x="144" y="340" width="32" height="18" rx="4" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/>
            <text x="160" y="352" text-anchor="middle" fill="#14613a" font-size="8" font-family="DM Mono">ACC-2</text>
            <rect x="184" y="340" width="32" height="18" rx="4" fill="#fef5f5" stroke="#c0392b" stroke-width="1.2"/>
            <text x="200" y="350" text-anchor="middle" fill="#8b1a1a" font-size="8" font-family="DM Mono">ACC-14</text>
            <text x="200" y="360" text-anchor="middle" fill="#c0392b" font-size="7" font-family="DM Mono">↓DOWN</text>
            <rect x="264" y="340" width="32" height="18" rx="4" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/>
            <text x="280" y="352" text-anchor="middle" fill="#14613a" font-size="8" font-family="DM Mono">ACC-4</text>
            <rect x="404" y="340" width="32" height="18" rx="4" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/>
            <text x="420" y="352" text-anchor="middle" fill="#14613a" font-size="8" font-family="DM Mono">ACC-5</text>
            <rect x="524" y="340" width="32" height="18" rx="4" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/>
            <text x="540" y="352" text-anchor="middle" fill="#14613a" font-size="8" font-family="DM Mono">ACC-6</text>
            <rect x="584" y="340" width="32" height="18" rx="4" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/>
            <text x="600" y="352" text-anchor="middle" fill="#14613a" font-size="8" font-family="DM Mono">ACC-7</text>
          </svg>
        </div>
      </div>
    </div>

    <!-- ══════ ALERTS ══════ -->
    <div class="panel" id="panel-alerts">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Alerts &amp; Outage Management</div>
          <div class="page-sub">AI root-cause correlation · Auto-suppression · War room</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-secondary btn-sm">🔕 Suppress</button>
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Correlate all 7 active alerts and give me a prioritized action plan with root cause analysis')">🧠 AI Root Cause All</button>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">🚨</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">AI Correlation Engine</div>
          <div class="ai-insight-text"><strong>7 alerts correlated into 2 root causes.</strong> Primary: ISP instability on AS65002 causing BGP flap → OSPF recalculation → high CPU (alerts 1, 3, 4 are symptoms). Secondary: Physical failure on SW-ACC-14 Gi0/0/3 (alerts 2, 5 are symptoms). Fix root causes, not symptoms.</div>
        </div>
      </div>
      <div class="card">
        <div class="card-header">
          <div class="card-title">All Active Alerts</div>
          <div class="card-actions">
            <span class="chip chip-red">3 critical</span>
            <span class="chip chip-amber">4 warning</span>
          </div>
        </div>
        <div class="alert-row">
          <div class="alert-sev sev-crit">🔴</div>
          <div class="alert-body">
            <div class="alert-title">BGP session flapping — PE-MUM-01 → AS65002</div>
            <div class="alert-meta">Routing · 3 flaps/hr · 142 prefixes at risk · Root cause: ISP</div>
            <div class="alert-ai-badge">🧠 AI Root Cause: Upstream ISP BGP withdrawal → Escalate to ISP</div>
          </div>
          <div class="alert-time">2m ago</div>
        </div>
        <div class="alert-row">
          <div class="alert-sev sev-crit">🔴</div>
          <div class="alert-body">
            <div class="alert-title">Interface Down — Gi0/0/3 on SW-ACC-14</div>
            <div class="alert-meta">Access layer · VLAN 120 · 47 users impacted</div>
            <div class="alert-ai-badge">🧠 AI Root Cause: Physical port failure or cable issue</div>
          </div>
          <div class="alert-time">8m ago</div>
        </div>
        <div class="alert-row">
          <div class="alert-sev sev-crit">🔴</div>
          <div class="alert-body">
            <div class="alert-title">Lateral Movement Detected — 10.2.14.0/24</div>
            <div class="alert-meta">Security · Port scan · Possible breach · Isolate immediately</div>
            <div class="alert-ai-badge">🧠 AI: Correlates with ACC-14 being down — may be cause</div>
          </div>
          <div class="alert-time">22m ago</div>
        </div>
        <div class="alert-row">
          <div class="alert-sev sev-warn">🟡</div>
          <div class="alert-body">
            <div class="alert-title">High CPU — CORE-RTR-01 (88%)</div>
            <div class="alert-meta">Routing · OSPF SPF recalculation · Symptom of BGP flap</div>
          </div>
          <div class="alert-time">14m ago</div>
        </div>
        <div class="alert-row">
          <div class="alert-sev sev-warn">🟡</div>
          <div class="alert-body">
            <div class="alert-title">OSPF Neighbor Timeout — Area 0 segment</div>
            <div class="alert-meta">Routing · DR/BDR election in progress · Segment 10.10.40.0/24</div>
          </div>
          <div class="alert-time">31m ago</div>
        </div>
        <div class="alert-row">
          <div class="alert-sev sev-warn">🟡</div>
          <div class="alert-body">
            <div class="alert-title">VPN Tunnel Down — Branch-HYD</div>
            <div class="alert-meta">IPSec · DPD timeout · Branch office offline</div>
          </div>
          <div class="alert-time">45m ago</div>
        </div>
        <div class="alert-row">
          <div class="alert-sev sev-warn">🟡</div>
          <div class="alert-body">
            <div class="alert-title">14 Unpatched CVEs on Edge Devices</div>
            <div class="alert-meta">Security · 3 critical severity · FW-EDGE-01, FW-EDGE-02</div>
          </div>
          <div class="alert-time">2h ago</div>
        </div>
      </div>
    </div>

    <!-- ══════ TROUBLESHOOT ══════ -->
    <div class="panel" id="panel-troubleshoot">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">AI Troubleshooting</div>
          <div class="page-sub">Describe symptoms in plain English — AI diagnoses, generates CLI, guides step-by-step</div>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">🔧</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">NLP Troubleshoot Engine</div>
          <div class="ai-insight-text">Say <strong>"BGP not forming with ISP since morning, no config changes"</strong> — I'll check topology, config, run CLI remotely, correlate logs, find root cause and provide exact fix commands for your vendor.</div>
        </div>
      </div>
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><div class="card-title">🔥 Common Issue Fast-Launch</div></div>
          <div class="card-body" style="display:flex;flex-direction:column;gap:8px">
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('BGP neighbor stuck in Active state, troubleshoot step by step for Cisco IOS-XR')">BGP neighbor not establishing</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('OSPF adjacency stuck in EXSTART/EXCHANGE, what are the causes and how to fix?')">OSPF stuck in EXSTART</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('VLAN traffic not passing between trunk links, systematic troubleshooting guide')">VLAN trunk issue</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('SD-WAN failover not happening when primary link fails, how to diagnose?')">SD-WAN failover broken</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('High packet loss on MPLS backbone, how to isolate and diagnose with LSP ping/trace?')">MPLS packet loss</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('IPSec VPN tunnel flapping, DPD timeout issue, how to stabilize?')">IPSec VPN flapping</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('Spanning tree loop detected, how to find the port and fix immediately?')">STP loop detected</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('BGP route not being advertised to peer even though it is in routing table')">BGP route not advertised</button>
          </div>
        </div>
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">🧠 AI Diagnosis — Describe Your Problem</div>
              <div class="card-subtitle">Natural language · Any vendor · Any protocol</div>
            </div>
            <span class="chip chip-purple">NLP</span>
          </div>
          <div class="card-body" style="display:flex;flex-direction:column;gap:10px">
            <textarea id="troubleInput" style="width:100%;background:var(--surface-0);border:1px solid var(--border);border-radius:8px;padding:12px;font-size:13px;color:var(--text-primary);resize:vertical;min-height:100px;outline:none;font-family:'DM Sans',sans-serif;line-height:1.6" placeholder="Describe the problem naturally:&#10;e.g. 'Users in Finance VLAN 100 cannot reach internet since 9am. Other VLANs are fine. No changes were made last night.'"></textarea>
            <div class="grid-2" style="gap:8px">
              <select style="padding:7px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--white);color:var(--text-primary);outline:none">
                <option>Vendor: Any</option>
                <option>Cisco IOS/IOS-XR</option>
                <option>Juniper Junos</option>
                <option>Arista EOS</option>
                <option>Palo Alto</option>
                <option>Fortinet</option>
              </select>
              <select style="padding:7px 10px;border:1px solid var(--border);border-radius:6px;font-size:13px;background:var(--white);color:var(--text-primary);outline:none">
                <option>Severity: Unknown</option>
                <option>🔴 Critical — production down</option>
                <option>🟡 Major — degraded</option>
                <option>🟢 Minor — no user impact</option>
              </select>
            </div>
            <button class="btn btn-primary" onclick="troubleshoot()">🧠 Analyze &amp; Diagnose</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════ CLI ASSISTANT ══════ -->
    <div class="panel" id="panel-cli">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">CLI Assistant</div>
          <div class="page-sub">NL → CLI translation · Multi-vendor · Real-time explanation</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-secondary btn-sm">📋 Command History</button>
          <button class="btn btn-primary btn-sm">⬇ Export Script</button>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">💻</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">NL → CLI Engine</div>
          <div class="ai-insight-text">Type plain English like <strong>"enable OSPF on GigabitEthernet 0/0 in area 0"</strong> and get exact Cisco/Juniper/Arista CLI. Or paste a command and ask <strong>"what does this config line do?"</strong></div>
        </div>
      </div>
      <div class="cli-wrap">
        <div class="cli-bar">
          <div class="cli-dots">
            <div class="cli-dot" style="background:#ff5f57"></div>
            <div class="cli-dot" style="background:#ffbd2e"></div>
            <div class="cli-dot" style="background:#28c941"></div>
          </div>
          <span class="cli-title">CORE-RTR-01 # Cisco IOS-XR 7.5.2 — NLP-Assisted Terminal</span>
          <span class="cli-badge">NL→CLI Active</span>
        </div>
        <div class="cli-output" id="cliOutput">
          <div><span class="cli-out-text">NetBrain AI CLI Assistant v1.0 — Natural Language Mode ON</span></div>
          <div><span class="cli-out-text">Connected: CORE-RTR-01 | IOS-XR 7.5.2 | Vendor: Cisco</span></div>
          <div><span class="cli-out-text">Type CLI commands OR plain English. Use ↑↓ for history.</span></div>
          <div>&nbsp;</div>
          <div><span class="cli-prompt">User ❯ </span><span class="cli-cmd-text">show me bgp summary</span></div>
          <div><span class="cli-ai-text">▸ AI translated: </span><span class="cli-out-text">show bgp all summary</span></div>
          <div>&nbsp;</div>
          <div><span class="cli-out-text">BGP router identifier 10.0.0.1, local AS number 65001</span></div>
          <div><span class="cli-out-text">Neighbor        AS        MsgRcvd   MsgSent   Up/Down     State/PfxRcd</span></div>
          <div><span class="cli-out-text">10.0.1.1     65002       14823     14801   5d 02:14   Established / 142</span></div>
          <div><span class="cli-warn-text">10.0.2.1     65003         341       340   0d 00:04   Active ← NOT ESTABLISHED</span></div>
          <div><span class="cli-out-text">10.0.3.1     65004        8912      8890   2d 11:22   Established / 87</span></div>
          <div>&nbsp;</div>
          <div><span class="cli-ai-text">▸ AI Analysis: Peer 10.0.2.1 (AS65003) stuck in Active state.</span></div>
          <div><span class="cli-ai-text">  Check: (1) TCP 179 reachability (2) auth mismatch (3) AS number</span></div>
          <div><span class="cli-ai-text">  Run: show bgp neighbors 10.0.2.1 | include State</span></div>
          <div>&nbsp;</div>
          <div><span class="cli-prompt">CORE-RTR-01# </span><span class="cli-cursor-blink"></span></div>
        </div>
        <div class="cli-input-bar">
          <span class="cli-label">NL/CLI ❯</span>
          <input class="cli-text-input" id="cliInput" placeholder='Type CLI or plain English — e.g. "show ospf neighbors on all interfaces"' onkeydown="cliKey(event)"/>
        </div>
      </div>
    </div>

    <!-- ══════ LEARNING HUB ══════ -->
    <div class="panel" id="panel-learn">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Learning Hub</div>
          <div class="page-sub">AI-adaptive · Detects your level automatically · CCNA → CCIE → Expert architect</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('I want to learn networking. Ask me what I already know and build a custom learning plan for me.')">🧠 Build My Learning Plan</button>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">🎓</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">Adaptive NLP Learning Engine</div>
          <div class="ai-insight-text">I detect your level from how you phrase questions. Ask <strong>"what is a VLAN?"</strong> → I teach from scratch. Ask <strong>"explain 802.1Q Q-in-Q double-tagging edge cases"</strong> → I go expert-level. No need to configure anything.</div>
        </div>
      </div>
      <div class="track-grid">
        <div class="track-card tc-blue" onclick="showPanel('chat');sendQuick('Start a lesson on routing fundamentals — OSPF, BGP, EIGRP. Assess my level first.')">
          <div class="track-icon">🌐</div>
          <div class="track-name">Routing Fundamentals</div>
          <div class="track-desc">OSPF · BGP · EIGRP · IS-IS · Policy routing · Redistribution</div>
          <div class="prog-bar"><div class="prog-fill" style="width:65%;background:var(--accent)"></div></div>
          <div class="prog-txt">65% complete</div>
        </div>
        <div class="track-card tc-green" onclick="showPanel('chat');sendQuick('Teach me switching — VLANs, STP, EtherChannel. Start from CCNA level.')">
          <div class="track-icon">🔀</div>
          <div class="track-name">Switching &amp; VLANs</div>
          <div class="track-desc">STP · EtherChannel · VTP · Port security · Campus fabric</div>
          <div class="prog-bar"><div class="prog-fill" style="width:40%;background:var(--green-500)"></div></div>
          <div class="prog-txt">40% complete</div>
        </div>
        <div class="track-card tc-amber" onclick="showPanel('chat');sendQuick('Explain SD-WAN concepts, architecture, and how it compares to MPLS.')">
          <div class="track-icon">🛣️</div>
          <div class="track-name">SD-WAN &amp; SASE</div>
          <div class="track-desc">Cisco Viptela · Versa · Cato · Zscaler · Zero Trust WAN</div>
          <div class="prog-bar"><div class="prog-fill" style="width:20%;background:var(--amber-500)"></div></div>
          <div class="prog-txt">20% complete</div>
        </div>
        <div class="track-card tc-red" onclick="showPanel('chat');sendQuick('Teach me network security — firewalls, ACL, Zero Trust, ZTNA. CCNA to expert.')">
          <div class="track-icon">🔒</div>
          <div class="track-name">Network Security</div>
          <div class="track-desc">Firewall · ACL · Zero Trust · ZTNA · Micro-segmentation</div>
          <div class="prog-bar"><div class="prog-fill" style="width:55%;background:var(--red-500)"></div></div>
          <div class="prog-txt">55% complete</div>
        </div>
        <div class="track-card tc-purple" onclick="showPanel('chat');sendQuick('Explain datacenter networking — VXLAN, EVPN, Leaf-Spine. Explain it like I am a CCNA.')">
          <div class="track-icon">🏢</div>
          <div class="track-name">Datacenter Networking</div>
          <div class="track-desc">VXLAN · EVPN · Leaf-Spine · AI GPU fabric · Storage net</div>
          <div class="prog-bar"><div class="prog-fill" style="width:10%;background:var(--purple-500)"></div></div>
          <div class="prog-txt">10% complete</div>
        </div>
        <div class="track-card tc-brand" onclick="showPanel('chat');sendQuick('Teach cloud networking — AWS VPC, Azure VNet, hybrid cloud, Kubernetes networking.')">
          <div class="track-icon">☁️</div>
          <div class="track-name">Cloud Networking</div>
          <div class="track-desc">AWS · Azure · GCP · Hybrid · Kubernetes · Container net</div>
          <div class="prog-bar"><div class="prog-fill" style="width:30%;background:var(--brand-500)"></div></div>
          <div class="prog-txt">30% complete</div>
        </div>
      </div>
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><div class="card-title">📋 Today's AI-Generated Lab</div><span class="chip chip-blue">AI Generated</span></div>
          <div class="card-body">
            <div style="font-size:14px;font-weight:600;margin-bottom:6px">Lab: OSPF Multi-Area with Route Summarization</div>
            <div style="font-size:13px;color:var(--text-secondary);line-height:1.7;margin-bottom:14px">Configure 3-area OSPF topology. Summarize Area 1 and Area 2 prefixes into backbone. Verify convergence. Identify DR/BDR on each broadcast segment. Analyze LSDB.</div>
            <div style="display:flex;gap:8px">
              <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Help me step by step through the OSPF multi-area lab with route summarization. I am CCNA level.')">🧠 AI Guided Lab</button>
              <button class="btn btn-secondary btn-sm">📄 Download Guide</button>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">🏆 Certification Tracks</div></div>
          <div class="card-body" style="display:flex;flex-direction:column;gap:10px">
            <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <span style="font-size:20px">📘</span>
              <div style="flex:1">
                <div style="font-size:13px;font-weight:600">CCNA 200-301</div>
                <div style="font-size:11px;color:var(--text-tertiary)">Foundation · Routing · Switching · Security basics</div>
              </div>
              <span class="chip chip-green">Ready</span>
            </div>
            <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <span style="font-size:20px">📗</span>
              <div style="flex:1">
                <div style="font-size:13px;font-weight:600">CCNP Enterprise</div>
                <div style="font-size:11px;color:var(--text-tertiary)">Advanced routing · SD-Access · SD-WAN · QoS</div>
              </div>
              <span class="chip chip-amber">In Progress</span>
            </div>
            <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <span style="font-size:20px">📕</span>
              <div style="flex:1">
                <div style="font-size:13px;font-weight:600">CCIE Enterprise Infrastructure</div>
                <div style="font-size:11px;color:var(--text-tertiary)">Expert design · Implementation · Troubleshoot lab</div>
              </div>
              <span class="chip chip-red">Advanced</span>
            </div>
            <div style="display:flex;align-items:center;gap:12px;padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <span style="font-size:20px">🌐</span>
              <div style="flex:1">
                <div style="font-size:13px;font-weight:600">Service Provider — CCNP/CCIE SP</div>
                <div style="font-size:11px;color:var(--text-tertiary)">MPLS · SRv6 · 5G transport · BGP-LU</div>
              </div>
              <span class="chip chip-blue">Available</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════ COMPLIANCE ══════ -->
    <div class="panel" id="panel-compliance">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Compliance &amp; Security Posture</div>
          <div class="page-sub">Automated policy validation · AI gap analysis · All frameworks</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-secondary btn-sm">📋 Schedule Scan</button>
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Run a full compliance analysis and tell me the top 5 gaps I need to fix immediately')">🧠 AI Gap Analysis</button>
        </div>
      </div>
      <div class="compliance-grid">
        <div class="comp-card">
          <div class="comp-framework">CIS Benchmark</div>
          <div class="comp-score" style="color:var(--green-700)">91%</div>
          <div class="comp-desc">23 violations of 256 controls</div>
          <div class="comp-bar"><div class="comp-fill" style="width:91%;background:var(--green-500)"></div></div>
        </div>
        <div class="comp-card">
          <div class="comp-framework">NIST CSF 2.0</div>
          <div class="comp-score" style="color:var(--amber-700)">78%</div>
          <div class="comp-desc">Identity controls gap detected</div>
          <div class="comp-bar"><div class="comp-fill" style="width:78%;background:var(--amber-500)"></div></div>
        </div>
        <div class="comp-card">
          <div class="comp-framework">PCI DSS 4.0</div>
          <div class="comp-score" style="color:var(--green-700)">96%</div>
          <div class="comp-desc">Cardholder network isolated</div>
          <div class="comp-bar"><div class="comp-fill" style="width:96%;background:var(--green-500)"></div></div>
        </div>
        <div class="comp-card">
          <div class="comp-framework">ISO 27001</div>
          <div class="comp-score" style="color:var(--green-700)">88%</div>
          <div class="comp-desc">Audit trail 100% complete</div>
          <div class="comp-bar"><div class="comp-fill" style="width:88%;background:var(--green-500)"></div></div>
        </div>
        <div class="comp-card">
          <div class="comp-framework">Zero Trust Maturity</div>
          <div class="comp-score" style="color:var(--amber-700)">62%</div>
          <div class="comp-desc">Micro-segmentation partial</div>
          <div class="comp-bar"><div class="comp-fill" style="width:62%;background:var(--amber-500)"></div></div>
        </div>
        <div class="comp-card">
          <div class="comp-framework">Firmware CVEs</div>
          <div class="comp-score" style="color:var(--red-700)">14</div>
          <div class="comp-desc">3 critical unpatched CVEs</div>
          <div class="comp-bar"><div class="comp-fill" style="width:30%;background:var(--red-500)"></div></div>
        </div>
      </div>
    </div>

    <!-- ══════ VOICE OPS ══════ -->
    <div class="panel" id="panel-voice">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Voice Operations</div>
          <div class="page-sub">Hands-free NOC · Multilingual · NLP voice commands</div>
        </div>
      </div>
      <div class="grid-2">
        <div class="card" style="flex:1">
          <div class="card-header"><div class="card-title">🎙 Voice Command Center</div></div>
          <div class="voice-stage">
            <div class="voice-orb" id="vOrb" onclick="toggleVoice()">🎙</div>
            <div class="voice-status" id="vStatus">Click orb to start voice command</div>
            <div class="voice-transcript" id="vTranscript">Voice transcript will appear here…<br><br><span style="color:var(--text-tertiary)">Try: "Show me all BGP neighbors" · "What alerts are critical right now?" · "Explain OSPF DR election"</span></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;justify-content:center">
              <div class="qchip">Show BGP summary</div>
              <div class="qchip">List critical alerts</div>
              <div class="qchip">Check OSPF neighbors</div>
              <div class="qchip">Device inventory</div>
            </div>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">📋 Voice Runbooks</div></div>
          <div class="card-body" style="display:flex;flex-direction:column;gap:8px">
            <div style="padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <div style="font-size:13px;font-weight:600;margin-bottom:3px">🔴 Outage Response</div>
              <div style="font-size:12px;color:var(--text-tertiary)">Voice-guided 8-step outage process. Hands-free during incidents.</div>
            </div>
            <div style="padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <div style="font-size:13px;font-weight:600;margin-bottom:3px">🔧 BGP Troubleshoot</div>
              <div style="font-size:12px;color:var(--text-tertiary)">Voice-assisted BGP diagnostic runbook. Asks yes/no at each step.</div>
            </div>
            <div style="padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <div style="font-size:13px;font-weight:600;margin-bottom:3px">🔄 Shift Handover</div>
              <div style="font-size:12px;color:var(--text-tertiary)">Dictate shift notes. AI summarizes and sends to next NOC team.</div>
            </div>
            <div style="padding:10px;background:var(--surface-0);border:1px solid var(--border);border-radius:8px">
              <div style="font-size:13px;font-weight:600;margin-bottom:3px">📊 Morning Health Check</div>
              <div style="font-size:12px;color:var(--text-tertiary)">Voice-driven daily network health briefing. 90 seconds summary.</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════ NETWORK DESIGN ══════ -->
    <div class="panel" id="panel-design">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Network Design Assistant</div>
          <div class="page-sub">AI-powered architecture · Hardware sizing · BOM · Implementation roadmap</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('I need to design a network. Ask me all the requirements — users, locations, vendors, budget, cloud, and I will answer. Then give me a complete architecture.')">🧠 Start AI Design Session</button>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">🏗</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">Design AI — Requirements → Architecture</div>
          <div class="ai-insight-text">Tell me requirements in plain English: <strong>"50 branch offices, dual ISP, 300 users/branch, Azure integration, SASE, under $2M budget"</strong> → I produce full architecture, vendor selection, hardware list, BOM, and 90-day implementation roadmap.</div>
        </div>
      </div>
      <div class="grid-3">
        <div class="design-card" onclick="showPanel('chat');sendQuick('Design a complete enterprise campus network for 3000 users with 3-tier hierarchy, SD-Access, wireless, and security')">
          <div class="design-icon" style="background:var(--brand-100)">🏢</div>
          <div class="design-card-body">
            <div class="dc-name">Enterprise Campus</div>
            <div class="dc-desc">3-tier hierarchy · SD-Access · Wireless · Identity · Zero Trust</div>
            <div class="dc-tags"><span class="chip chip-blue">Cisco</span><span class="chip chip-green">Arista</span></div>
          </div>
        </div>
        <div class="design-card" onclick="showPanel('chat');sendQuick('Design SD-WAN for 50 branch offices with dual ISP failover, cloud breakout, and SASE integration')">
          <div class="design-icon" style="background:var(--amber-50)">🛣️</div>
          <div class="design-card-body">
            <div class="dc-name">SD-WAN Design</div>
            <div class="dc-desc">Multi-branch · Dual ISP · SASE · ZIA/ZPA · Application SLA</div>
            <div class="dc-tags"><span class="chip chip-amber">Viptela</span><span class="chip chip-blue">Versa</span></div>
          </div>
        </div>
        <div class="design-card" onclick="showPanel('chat');sendQuick('Design a datacenter leaf-spine fabric with VXLAN EVPN for 10000 servers including AI GPU cluster networking')">
          <div class="design-icon" style="background:var(--purple-50)">🏭</div>
          <div class="design-card-body">
            <div class="dc-name">Datacenter Fabric</div>
            <div class="dc-desc">VXLAN · EVPN · Leaf-Spine · AI GPU fabric · RoCE · InfiniBand</div>
            <div class="dc-tags"><span class="chip chip-purple">Arista</span><span class="chip chip-blue">NVIDIA</span></div>
          </div>
        </div>
        <div class="design-card" onclick="showPanel('chat');sendQuick('Design hybrid cloud network connecting on-premises datacenter to AWS and Azure with SD-WAN and security')">
          <div class="design-icon" style="background:var(--green-50)">☁️</div>
          <div class="design-card-body">
            <div class="dc-name">Hybrid Cloud</div>
            <div class="dc-desc">AWS · Azure · Direct Connect · ExpressRoute · SDWAN breakout</div>
            <div class="dc-tags"><span class="chip chip-green">AWS</span><span class="chip chip-blue">Azure</span></div>
          </div>
        </div>
        <div class="design-card" onclick="showPanel('chat');sendQuick('Design a complete Zero Trust network architecture for enterprise with micro-segmentation and ZTNA')">
          <div class="design-icon" style="background:var(--red-50)">🔐</div>
          <div class="design-card-body">
            <div class="dc-name">Zero Trust Architecture</div>
            <div class="dc-desc">ZTNA · Micro-segmentation · Identity · Palo Alto · Zscaler</div>
            <div class="dc-tags"><span class="chip chip-red">ZT</span><span class="chip chip-purple">SASE</span></div>
          </div>
        </div>
        <div class="design-card" onclick="showPanel('chat');sendQuick('Design 5G transport network for mobile operator with SR-MPLS, SRv6, network slicing and mobile backhaul')">
          <div class="design-icon" style="background:var(--brand-50)">📡</div>
          <div class="design-card-body">
            <div class="dc-name">5G Transport / SP</div>
            <div class="dc-desc">SR-MPLS · SRv6 · Network slicing · Mobile backhaul · Metro-E</div>
            <div class="dc-tags"><span class="chip chip-blue">Nokia</span><span class="chip chip-green">Cisco</span></div>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════ DIGITAL TWIN ══════ -->
    <div class="panel" id="panel-twin">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Digital Twin</div>
          <div class="page-sub">Live clone of your network · Test changes safely · What-if simulations</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-secondary btn-sm">⏺ New Simulation</button>
          <button class="btn btn-primary btn-sm">🔄 Sync Live Network</button>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">👾</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">Digital Twin AI Engine</div>
          <div class="ai-insight-text">I maintain a <strong>live behavioral clone</strong> of your network. Ask <strong>"What happens if PE-MUM-01 fails?"</strong> and I simulate the failure, show impacted services, calculate failover time, and recommend mitigation — all before it happens in production.</div>
        </div>
      </div>
      <div class="twin-metrics">
        <div class="twin-m"><div class="twin-val">847</div><div class="twin-lbl">Devices Cloned</div></div>
        <div class="twin-m"><div class="twin-val">99.2%</div><div class="twin-lbl">Config Accuracy</div></div>
        <div class="twin-m"><div class="twin-val">3</div><div class="twin-lbl">Active Simulations</div></div>
        <div class="twin-m"><div class="twin-val">14s</div><div class="twin-lbl">Last Sync</div></div>
      </div>
      <div class="grid-2">
        <div class="card">
          <div class="card-header"><div class="card-title">⚡ What-If Scenarios</div></div>
          <div class="card-body" style="display:flex;flex-direction:column;gap:8px">
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('Simulate what happens if CORE-RTR-01 completely fails. Show affected services, failover time, and recommendations.')">Simulate CORE-RTR-01 failure</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('What is the blast radius if ISP link on PE-MUM-01 goes down completely?')">ISP link failure — PE-MUM-01</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('Validate impact of adding a new OSPF area 10 with 5 new routes before applying to production')">Add OSPF area 10</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('Test a BGP route-policy change impact on traffic engineering before applying to production')">BGP route-policy change</button>
            <button class="btn btn-secondary" onclick="showPanel('chat');sendQuick('Simulate firmware upgrade on PE-MUM-01 and predict risk and impact')">Firmware upgrade validation</button>
          </div>
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">📊 Running Simulation Results</div><span class="chip chip-amber">Running</span></div>
          <div class="card-body">
            <div style="background:var(--surface-0);border:1px solid var(--border);border-radius:8px;padding:14px;font-family:'DM Mono',monospace;font-size:12px;line-height:2;color:var(--text-secondary)">
              <div style="color:var(--amber-700);font-weight:600">▶ Scenario: ISP link failure on PE-MUM-01</div>
              <div>  Affected BGP prefixes: <strong style="color:var(--text-primary)">142 routes</strong></div>
              <div>  Estimated failover time: <strong style="color:var(--text-primary)">~3.2 seconds</strong></div>
              <div>  Services impacted: <strong style="color:var(--red-700)">3 critical, 7 minor</strong></div>
              <div>  Alternate path: <strong style="color:var(--text-primary)">PE-DEL-01 → AS65004</strong></div>
              <div style="color:var(--green-700)">  Recommendation: Enable BFD → reduce to 0.3s failover</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ══════ SECURITY OPS ══════ -->
    <div class="panel" id="panel-security">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Security Operations</div>
          <div class="page-sub">Threat correlation · Zero Trust validation · Firewall intelligence</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Do a full security posture analysis. Check for lateral movement, unpatched CVEs, firewall gaps, and Zero Trust readiness.')">🧠 AI Security Audit</button>
        </div>
      </div>
      <div class="stats-grid">
        <div class="stat-card s-red"><div class="stat-icon">⚠</div><div class="stat-label">Threats Active</div><div class="stat-value">2</div><div class="stat-meta">Lateral movement attempt</div></div>
        <div class="stat-card s-amber"><div class="stat-icon">🔓</div><div class="stat-label">CVEs Unpatched</div><div class="stat-value">14</div><div class="stat-meta">3 critical severity</div></div>
        <div class="stat-card s-green"><div class="stat-icon">🛡</div><div class="stat-label">FW Rule Health</div><div class="stat-value">98%</div><div class="stat-meta">Shadow rules cleaned</div></div>
        <div class="stat-card s-blue"><div class="stat-icon">🔐</div><div class="stat-label">Zero Trust Score</div><div class="stat-value">62%</div><div class="stat-meta">Improving steadily</div></div>
      </div>
    </div>

    <!-- ══════ AUTOMATION ══════ -->
    <div class="panel" id="panel-automation">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Network Automation</div>
          <div class="page-sub">Ansible · Terraform · Self-healing · Config push · Workflow orchestration</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Generate an Ansible playbook to configure OSPF on 10 routers with area 0 and MD5 authentication')">🧠 Generate Playbook</button>
        </div>
      </div>
      <div class="stats-grid">
        <div class="stat-card s-green"><div class="stat-label">Jobs This Week</div><div class="stat-value">342</div><div class="stat-meta">99.7% success rate</div></div>
        <div class="stat-card s-blue"><div class="stat-label">Running Now</div><div class="stat-value">3</div><div class="stat-meta">Config push jobs</div></div>
        <div class="stat-card s-amber"><div class="stat-label">Self-Healed</div><div class="stat-value">12</div><div class="stat-meta">Auto-remediated issues</div></div>
        <div class="stat-card s-red"><div class="stat-label">Failed</div><div class="stat-value">1</div><div class="stat-meta">Review required</div></div>
      </div>
    </div>

    <!-- ══════ EXECUTIVE VIEW ══════ -->
    <div class="panel" id="panel-executive">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Executive Dashboard</div>
          <div class="page-sub">Business impact · SLA reporting · Risk scores · Board-ready metrics</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-primary btn-sm">📄 Board Report</button>
        </div>
      </div>
      <div class="stats-grid">
        <div class="stat-card s-green"><div class="stat-label">Network Uptime</div><div class="stat-value">99.94%</div><div class="stat-meta">SLA target: 99.9%  ✅</div></div>
        <div class="stat-card s-blue"><div class="stat-label">MTTR</div><div class="stat-value">18m</div><div class="stat-meta">↓ 40% vs last quarter</div></div>
        <div class="stat-card s-amber"><div class="stat-label">Risk Score</div><div class="stat-value">Medium</div><div class="stat-meta">14 CVEs · 2 threats</div></div>
        <div class="stat-card s-green"><div class="stat-label">Automation Rate</div><div class="stat-value">78%</div><div class="stat-meta">↑ 12% this quarter</div></div>
      </div>
    </div>

    <!-- ══════ FINOPS ══════ -->
    <div class="panel" id="panel-finops">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">FinOps &amp; Cost Intelligence</div>
          <div class="page-sub">License optimization · Cloud cost · Hardware lifecycle · Savings opportunities</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Analyze our network spend and identify top 5 cost optimization opportunities')">🧠 AI Cost Analysis</button>
        </div>
      </div>
      <div class="stats-grid">
        <div class="stat-card s-blue"><div class="stat-label">Annual Network Spend</div><div class="stat-value">$4.2M</div><div class="stat-meta">Within budget</div></div>
        <div class="stat-card s-green"><div class="stat-label">Identified Savings</div><div class="stat-value">$380K</div><div class="stat-meta">License + cloud rightsizing</div></div>
        <div class="stat-card s-amber"><div class="stat-label">EoL Hardware</div><div class="stat-value">34</div><div class="stat-meta">Devices need replacement</div></div>
        <div class="stat-card s-red"><div class="stat-label">Wasted Licenses</div><div class="stat-value">18%</div><div class="stat-meta">Unused entitlements</div></div>
      </div>
    </div>

    <!-- ══════ OBSERVABILITY ══════ -->
    <div class="panel" id="panel-observability">
      <div class="page-hdr">
        <div class="page-hdr-left">
          <div class="page-title">Observability &amp; Analytics</div>
          <div class="page-sub">Streaming telemetry · AI anomaly detection · Digital experience monitoring</div>
        </div>
        <div class="hdr-actions">
          <button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Analyze network telemetry and predict potential failures in the next 24 hours')">🧠 Predict Failures</button>
        </div>
      </div>
      <div class="ai-insight">
        <div class="ai-insight-icon">📡</div>
        <div class="ai-insight-body">
          <div class="ai-insight-label">AI Anomaly Prediction</div>
          <div class="ai-insight-text"><strong>3 anomalies predicted in next 4 hours:</strong> CORE-RTR-01 memory approaching 85% threshold at current growth rate · DIST-SW-C link utilization trending toward saturation · Branch-DEL VPN latency increasing — potential tunnel issue forming.</div>
        </div>
      </div>
      <div class="stats-grid">
        <div class="stat-card s-blue"><div class="stat-label">Telemetry Streams</div><div class="stat-value">1,847</div><div class="stat-meta">Active gRPC streams</div></div>
        <div class="stat-card s-green"><div class="stat-label">Anomalies Prevented</div><div class="stat-value">38</div><div class="stat-meta">This month</div></div>
        <div class="stat-card s-amber"><div class="stat-label">Predicted Issues</div><div class="stat-value">3</div><div class="stat-meta">Next 4 hours</div></div>
        <div class="stat-card s-green"><div class="stat-label">User Experience</div><div class="stat-value">96%</div><div class="stat-meta">Digital experience score</div></div>
      </div>
    </div>

    <!-- PLACEHOLDER panels -->
    <div class="panel" id="panel-certs">
      <div class="page-hdr"><div class="page-hdr-left"><div class="page-title">Certification Tracks</div><div class="page-sub">CCNA · CCNP · CCIE · SP · Security · Wireless</div></div></div>
      <div class="ai-insight"><div class="ai-insight-icon">🏆</div><div class="ai-insight-body"><div class="ai-insight-label">AI Certification Tutor</div><div class="ai-insight-text">Click <strong>AI Assistant</strong> and say <strong>"Help me prepare for CCNA"</strong> — I build a custom study plan, quiz you, explain weak areas, and track your progress.</div></div></div>
      <div class="card"><div class="card-body" style="text-align:center;padding:40px"><button class="btn btn-primary" onclick="showPanel('chat');sendQuick('I want to prepare for CCNA 200-301. Assess my current level and build a study plan.')">🧠 Start AI Certification Prep</button></div></div>
    </div>
    <div class="panel" id="panel-playbooks">
      <div class="page-hdr"><div class="page-hdr-left"><div class="page-title">Runbooks &amp; Playbooks</div><div class="page-sub">AI-generated · Vendor-specific · Step-by-step</div></div><div class="hdr-actions"><button class="btn btn-primary btn-sm" onclick="showPanel('chat');sendQuick('Generate a detailed runbook for BGP neighbor troubleshooting on Cisco IOS-XR')">🧠 Generate Runbook</button></div></div>
      <div class="ai-insight"><div class="ai-insight-icon">📋</div><div class="ai-insight-body"><div class="ai-insight-label">AI Runbook Generator</div><div class="ai-insight-text">Ask me to generate a runbook for any scenario — <strong>"BGP troubleshooting on IOS-XR"</strong> · <strong>"VLAN migration procedure"</strong> · <strong>"DC failover playbook"</strong> — I generate vendor-specific, step-by-step guides instantly.</div></div></div>
    </div>

  </div><!-- /content -->
</div><!-- /layout -->

<!-- STATUS TICKER -->
<div class="status-ticker">
  <div class="ticker-live"><span class="live-dot"></span>LIVE</div>
  <div class="ticker-items">
    <span class="ticker-item ti-err" id="tickerItem">BGP Flap · PE-MUM-01 · AS65002</span>
    <span class="ticker-sep">·</span>
    <span class="ticker-item ti-warn">CPU 88% · CORE-RTR-01</span>
    <span class="ticker-sep">·</span>
    <span class="ticker-item">Digital Twin synced · 14s ago</span>
    <span class="ticker-sep">·</span>
    <span class="ticker-item">Automation: 342 jobs completed this week</span>
    <span class="ticker-sep">·</span>
    <span class="ticker-item ti-warn">14 CVEs unpatched · 3 critical</span>
  </div>
  <div style="font-size:11px;color:rgba(255,255,255,.2);font-family:'DM Mono',monospace" id="tickerTime"></div>
</div>

<script>
/* ══ PANEL NAVIGATION ══ */
const navMap={
  overview:0,topology:1,alerts:2,troubleshoot:3,automation:4,compliance:5,security:6,
  chat:7,voice:8,cli:9,design:10,twin:11,observability:12,
  learn:13,certs:14,playbooks:15,executive:16,finops:17
};
function showPanel(id){
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  const p=document.getElementById('panel-'+id);
  if(p){p.classList.add('active');}
  document.querySelectorAll('.nav-item').forEach(n=>n.classList.remove('active'));
  const items=document.querySelectorAll('.nav-item');
  const idx=navMap[id];
  if(idx!=null&&items[idx]) items[idx].classList.add('active');
  if(id==='chat') setTimeout(()=>{const ci=document.getElementById('chatInput');if(ci)ci.focus();},80);
  if(id==='cli') setTimeout(()=>{const ci=document.getElementById('cliInput');if(ci)ci.focus();},80);
}

/* ══ PERSONA ══ */
const personas={
  ccna:{label:'CCNA Mode',chip:'CCNA',prompt:'I am a CCNA-level student. Please explain things clearly with analogies and step-by-step guidance.'},
  noc:{label:'NOC Engineer',chip:'NOC',prompt:'I am a NOC engineer. Be concise, operational, give me commands and runbooks.'},
  arch:{label:'Expert Architect',chip:'Architect',prompt:'I am a network architect. Go expert-level, skip basics, focus on design, trade-offs, and scalability.'}
};
let currentPersona='ccna';
function setPersona(p,el){
  currentPersona=p;
  document.querySelectorAll('.ps-btn').forEach(b=>b.classList.remove('active'));
  el.classList.add('active');
  document.getElementById('chatPersonaLabel').textContent=personas[p].label;
  document.getElementById('chatPersonaChip').textContent=personas[p].chip;
}

/* ══ AI CHAT ══ */
const aiResponses={
  bgp:`**BGP Neighbor Troubleshooting Analysis**

Peer in **Active** state = TCP session not established. Systematic approach:

**Step 1 — Test TCP reachability:**
\`\`\`
ping 10.0.2.1 source Loopback0
telnet 10.0.2.1 179
\`\`\`

**Step 2 — Check neighbor configuration:**
\`\`\`
show bgp neighbors 10.0.2.1 | include State|AS|Hold|Auth
\`\`\`

**Step 3 — Common causes (in order of probability):**
• Wrong \`remote-as\` configured (most common)
• MD5 authentication mismatch
• ACL/firewall blocking TCP port 179
• Wrong \`update-source\` interface
• eBGP multihop missing for loopback peers

What does Step 1 show? I'll narrow it down further.`,

  ospf:`**OSPF Neighbor Analysis**

EXSTART/EXCHANGE stuck = almost always **MTU mismatch** between the two interfaces.

**Immediate fix (verify first):**
\`\`\`
show interface Gi0/0 | include MTU
show ip ospf interface Gi0/0
\`\`\`

**If MTU differs, either fix MTU or:**
\`\`\`
interface GigabitEthernet0/0
 ip ospf mtu-ignore
\`\`\`

**Other causes:**
• Duplicate Router-ID in the area
• Area type mismatch (stub vs normal)
• Hello/Dead timer mismatch (less common — EXSTART wouldn't be the symptom)
• DBD master/slave election issue on non-broadcast networks`,

  vlan:`**VLAN Troubleshooting — Systematic Approach**

\`\`\`
show vlan brief                    ! Is VLAN in active state?
show interfaces trunk              ! Is VLAN in allowed list?
show spanning-tree vlan 100        ! Is port in forwarding state?
show mac address-table vlan 100    ! Any MACs learned?
\`\`\`

**Top causes in order:**
1. VLAN not in **allowed** list on trunk ← most common
2. VLAN not created on one switch
3. STP blocking the port (check BLK state)
4. Native VLAN mismatch causing drops
5. Missing \`switchport trunk encapsulation dot1q\` on older Catalyst

Which switch/interface are you troubleshooting? I'll give exact commands.`,

  sdwan:`**SD-WAN Architecture for 50 Branches**

**Recommended Design: Cisco Viptela (free for lab) or Versa Networks**

\`\`\`
Architecture:
┌─────────────────────────────────┐
│  vManage (NMS)  vBond (Orch)    │  ← Control plane (cloud hosted)
│  vSmart (Controller) ×2         │
└──────────────┬──────────────────┘
               │ OMP (Overlay Management Protocol)
    ┌──────────┴──────────┐
    │  Hub DC             │
    │  vEdge / cEdge      │
    └──────────┬──────────┘
        ┌──────┴──────┐
   MPLS │         Internet │  ← Dual underlay transport
        └──────┬──────┘
     Branch vEdge (×50)
     • App-aware routing
     • Cloud breakout to Azure/M365
     • SASE integration (Zscaler/Umbrella)
\`\`\`

**For zero-budget start:** Use Cisco DevNet always-on sandbox.
Want me to generate the full BOM and implementation roadmap?`,

  learn:`**Let me assess your level first!**

I'll ask you 3 quick questions:

**Q1:** In your own words, what does a router do that a switch doesn't?

*(Answer naturally — don't worry about being "correct". Your phrasing tells me your level automatically, and I'll adapt all future explanations to match.)*`,

  design:`**Starting Network Design Session**

Let me gather your requirements. I'll ask one at a time:

**Question 1 of 8:** How many physical locations (sites/branches) does this network need to connect?

*(e.g. "1 main office and 20 branches" or "3 datacenters across India")*`,

  default:`I understand your question about **{q}**.

As your AI Network Brain, I have full knowledge across:
• **All routing protocols** — OSPF, BGP, EIGRP, IS-IS, MPLS, SRv6
• **All vendors** — Cisco, Juniper, Arista, Palo Alto, Fortinet, Aruba
• **All domains** — WAN, LAN, DC, Cloud, Wireless, Security, SP/5G
• **All levels** — CCNA explanation to CCIE-depth architecture

Could you give me more context? What's your environment (vendor, platform), and what have you already tried?`
};

function getResponse(msg){
  const m=msg.toLowerCase();
  if(m.includes('bgp')||m.includes('neighbor')||m.includes('as65')) return aiResponses.bgp;
  if(m.includes('ospf')||m.includes('exstart')||m.includes('dr election')) return aiResponses.ospf;
  if(m.includes('vlan')||m.includes('trunk')||m.includes('stp')) return aiResponses.vlan;
  if(m.includes('sdwan')||m.includes('sd-wan')||m.includes('branch')||m.includes('viptela')) return aiResponses.sdwan;
  if(m.includes('learn')||m.includes('ccna')||m.includes('study')||m.includes('level')) return aiResponses.learn;
  if(m.includes('design')||m.includes('architect')||m.includes('requirement')) return aiResponses.design;
  return aiResponses.default.replace('{q}',msg.length>50?msg.substring(0,50)+'…':msg);
}

function fmtMsg(t){
  return t
    .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
    .replace(/`([^`\n]+)`/g,'<code>$1</code>')
    .replace(/```([\s\S]*?)```/g,'<pre>$1</pre>')
    .replace(/\n/g,'<br>');
}

function appendMsg(role,content){
  const msgs=document.getElementById('chatMessages');
  const div=document.createElement('div');
  div.className=`msg ${role==='ai'?'':'user-msg'}`;
  div.innerHTML=`<div class="msg-av ${role==='ai'?'ai-av':'user-av'}">${role==='ai'?'🧠':'👤'}</div><div class="msg-bubble ${role==='ai'?'ai-bubble':'user-bubble'}">${fmtMsg(content)}</div>`;
  msgs.appendChild(div);
  msgs.scrollTop=msgs.scrollHeight;
  return div;
}

function sendChat(){
  const inp=document.getElementById('chatInput');
  const val=inp.value.trim();
  if(!val) return;
  appendMsg('user',val);
  inp.value='';inp.style.height='auto';
  // typing indicator
  const msgs=document.getElementById('chatMessages');
  const typing=document.createElement('div');
  typing.className='msg';
  typing.innerHTML=`<div class="msg-av ai-av">🧠</div><div class="msg-bubble ai-bubble"><div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div></div>`;
  msgs.appendChild(typing);
  msgs.scrollTop=msgs.scrollHeight;
  const delay=1000+Math.random()*800;
  setTimeout(()=>{
    typing.querySelector('.msg-bubble').innerHTML=fmtMsg(getResponse(val));
    msgs.scrollTop=msgs.scrollHeight;
  },delay);
}

function sendQuick(q){
  showPanel('chat');
  setTimeout(()=>{
    const inp=document.getElementById('chatInput');
    if(inp){inp.value=q;sendChat();}
  },120);
}

function chatKey(e){
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendChat();}
}

function troubleshoot(){
  const val=document.getElementById('troubleInput').value.trim();
  if(!val){alert('Please describe the problem first.');return;}
  showPanel('chat');
  setTimeout(()=>{sendQuick('Troubleshoot this issue: '+val);},150);
}

/* ══ CLI ENGINE ══ */
const cliHist=[];let cliIdx=0;
const nlMap={
  'bgp summary':'show bgp all summary','show bgp':'show bgp all summary',
  'ospf neighbor':'show ip ospf neighbor','ospf neighbors':'show ip ospf neighbor',
  'routing table':'show route ipv4','interface status':'show interfaces status',
  'cpu':'show processes cpu sorted','memory':'show memory summary',
  'version':'show version','inventory':'show inventory'
};
function nlToCli(input){
  const low=input.toLowerCase();
  for(const[k,v] of Object.entries(nlMap)){if(low.includes(k))return{cmd:v,translated:true};}
  if(low.startsWith('show ')||low.startsWith('ping ')||low.startsWith('trace')||low.startsWith('debug ')||low.startsWith('config')||low.startsWith('no '))
    return{cmd:input,translated:false};
  return{cmd:'! AI-generated: '+input,translated:true};
}
function addCliLine(html){
  const out=document.getElementById('cliOutput');
  const last=out.lastChild;
  const d=document.createElement('div');d.innerHTML=html;
  out.insertBefore(d,last);
  out.scrollTop=out.scrollHeight;
}
function cliKey(e){
  const inp=document.getElementById('cliInput');
  if(e.key==='Enter'){
    const val=inp.value.trim();if(!val)return;
    cliHist.push(val);cliIdx=cliHist.length;
    const{cmd,translated}=nlToCli(val);
    if(translated){
      addCliLine(`<span class="cli-prompt">User ❯ </span><span class="cli-cmd-text">${val}</span>`);
      addCliLine(`<span class="cli-ai-text">▸ AI translated: </span><span class="cli-out-text">${cmd}</span>`);
    } else {
      addCliLine(`<span class="cli-prompt">CORE-RTR-01# </span><span class="cli-cmd-text">${val}</span>`);
    }
    addCliLine(`<span class="cli-out-text">% Simulated output for: ${cmd}</span>`);
    addCliLine(`&nbsp;`);
    inp.value='';
  }
  if(e.key==='ArrowUp'&&cliIdx>0){cliIdx--;inp.value=cliHist[cliIdx]||'';}
  if(e.key==='ArrowDown'&&cliIdx<cliHist.length){cliIdx++;inp.value=cliHist[cliIdx]||'';}
}

/* ══ VOICE ══ */
let vOn=false;
const vLines=['Analyzing BGP neighbor table…','Checking OSPF adjacency states…','Fetching device inventory…','Running topology correlation…','Predicting anomalies from telemetry…','Correlating active alerts…'];
let vTimer;
function toggleVoice(){
  vOn=!vOn;
  const orb=document.getElementById('vOrb');
  const st=document.getElementById('vStatus');
  const tr=document.getElementById('vTranscript');
  if(vOn){
    orb.classList.add('on');orb.textContent='🔴';
    st.textContent='Listening… speak your command';
    let i=0;
    vTimer=setInterval(()=>{tr.textContent=vLines[i%vLines.length];i++;},1800);
  } else {
    orb.classList.remove('on');orb.textContent='🎙';
    st.textContent='Click orb to start voice command';
    clearInterval(vTimer);
    tr.innerHTML='Voice command completed.<br><br><span style="color:var(--green-700)">✓ BGP summary: 3 peers. 1 in Active state on PE-MUM-01. 3 critical alerts active. All other systems nominal.</span>';
  }
}

/* ══ GLOBAL SEARCH ══ */
function gsKey(e){
  if(e.key==='Enter'){
    const val=document.getElementById('gsInput').value.trim();
    if(val){document.getElementById('gsInput').value='';sendQuick(val);}
  }
}

/* ══ LAYER BUTTONS ══ */
document.querySelectorAll('.layer-btn').forEach(b=>{
  b.addEventListener('click',()=>{
    document.querySelectorAll('.layer-btn').forEach(x=>x.classList.remove('active'));
    b.classList.add('active');
  });
});

/* ══ TICKER CLOCK ══ */
function updateClock(){
  const now=new Date();
  document.getElementById('tickerTime').textContent=
    now.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
}
setInterval(updateClock,1000);updateClock();

/* ══ AUTO-RESIZE TEXTAREA ══ */
document.getElementById('chatInput').addEventListener('input',function(){
  this.style.height='auto';
  this.style.height=Math.min(this.scrollHeight,100)+'px';
});

/* ══ INITIAL LOAD ANIMATION ══ */
window.addEventListener('load',()=>{
  document.querySelectorAll('.nav-item').forEach((el,i)=>{
    el.style.opacity='0';el.style.transform='translateX(-8px)';
    setTimeout(()=>{el.style.transition='.2s ease';el.style.opacity='1';el.style.transform='translateX(0)';},i*25);
  });
});
</script>
</body>
</html>
