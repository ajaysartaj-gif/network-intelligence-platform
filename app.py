"""
(cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app.py b/app.py
index 63f04e39cd9bc1d42534e252668d8fc282648737..28779cbc4299f76972ac66c9ea3eb8958a2a6b5a 100644
--- a/app.py
+++ b/app.py
@@ -1,29 +1,33 @@
 NetBrain AI — Autonomous Network Operating System
 app.py — Main entry point (Streamlit)
 
+Operational note:
+  This file must contain Python source only. Do not paste git apply / shell
+  patch commands into app.py; apply patch snippets from a terminal instead.
+
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
 
 # ── Stdlib + 3rd-party imports ────────────────────────────
 import sys, os, logging, re, hashlib, time, threading, copy, random
 from pathlib import Path
@@ -1670,104 +1674,67 @@ def build_synthesis_prompt(query: str, results: List[DeviceResult]) -> str:
                    f"Status: {r.status}\n"
                    f"{r.output}")
         device_sections.append(section)
 
     device_context = "\n\n".join(device_sections)
     ok_count = sum(1 for r in results if r.status == "ok")
 
     return (f'Multi-device query: "{query}"\n'
             f'{len(results)} devices queried ({ok_count} successful):\n\n'
             f'{device_context}\n\n'
             f'Provide:\n'
             f'1. DIRECT ANSWER — answer the query using device data\n'
             f'2. FINDINGS — notable findings per device (focus on anomalies)\n'
             f'3. RISKS — any risks or issues detected\n'
             f'4. RECOMMENDED ACTIONS — prioritized next steps\n'
             f'Use specific device hostnames. Be concise.')
 
 
 # ══ SYSTEM A — AI ENGINE ═════════════════════════════
 
 import os, logging, time
 from typing import Optional
 import streamlit as st
 
 
-# ── Model config ──────────────────────────────────────────
-OPENROUTER_BASE     = "https://openrouter.ai/api/v1"
-OPENROUTER_MODEL    = "anthropic/claude-sonnet-4-5"
-OPENROUTER_HEADERS  = {
-    "HTTP-Referer": "https://netbrain-ai.streamlit.app",
-    "X-Title": "NetBrain AI",
-}
+# ── Model config + prompt registry ─────────────────────────────
+from config.ai import (
+    OPENROUTER_BASE,
+    OPENROUTER_MODEL,
+    OPENROUTER_HEADERS,
+    NETWORK_SYSTEM,
+    PERSONAS,
+)
 
 # ── Safe import ───────────────────────────────────────────
 try:
     from openai import OpenAI
     _OPENAI_OK = True
 except ImportError:
     _OPENAI_OK = False
     logger.warning("openai package missing — AI disabled")
 
-# ══════════════════════════════════════════════════════════
-# NETWORK EXPERTISE SYSTEM PROMPT
-# ══════════════════════════════════════════════════════════
-NETWORK_SYSTEM = """You are NetBrain AI — an AI-Native Autonomous Network Operating System.
-
-You are NOT a chatbot. You are an operational intelligence engine embedded in every workflow.
-
-Deep expertise across:
-- Routing: BGP OSPF EIGRP IS-IS MPLS SR-MPLS SRv6 Segment-Routing multicast policy-routing
-- Switching: VLANs STP RSTP MSTP EtherChannel VXLAN EVPN MACsec SD-Access
-- WAN: SD-WAN(Viptela/Versa/VeloCloud) DMVPN SASE ZTNA cloud-WAN MPLS-L3VPN
-- Security: Zero-Trust ZTNA micro-segmentation firewall ACL IPSec IDS/IPS SIEM
-- Datacenter: Leaf-Spine ACI VXLAN-EVPN RoCE InfiniBand AI-fabric GPU-networking
-- Cloud: AWS(VPC TGW DirectConnect) Azure(VNet ExpressRoute VWAN) GCP Kubernetes CNI
-- Service Provider: L3VPN L2VPN SR-MPLS SRv6 5G-transport BGP-LU carrier-ethernet
-- Wireless: CAPWAP 802.11ax WiFi6 WPA3 roaming RF-optimization wireless-assurance
-- Monitoring: SNMP gRPC streaming-telemetry NetFlow syslog anomaly-detection
-- Automation: Ansible Terraform NETCONF RESTCONF gRPC Python-netmiko intent-based
-
-Vendors: Cisco Juniper Arista PaloAlto Fortinet Aruba Nokia Huawei Versa Zscaler Cato Netskope VMware
-
-RESPONSE RULES:
-1. Be operationally specific — name devices, IPs, protocols, exact CLI
-2. Always show: Summary → Evidence → Root Cause → Business Impact → Actions → Rollback
-3. Include AI confidence % for analysis
-4. Generate CLI that works on the stated vendor
-5. Translate technical issues to business language when impact is discussed
-6. Learn from context: if similar incident mentioned, reference it explicitly"""
-
-PERSONAS = {
-    "fresher":  "Persona: BEGINNER STUDENT. Explain everything with analogies. Define every acronym inline. Use simple language. Step-by-step guidance. Encourage and reassure. Visual descriptions.",
-    "ccna":     "Persona: CCNA ENGINEER. Explain with context and reasoning. Show CLI with line-by-line explanation. Guide through troubleshooting systematically. Reference exam topics where relevant.",
-    "noc":      "Persona: NOC ENGINEER. BE CONCISE. Lead immediately with probable root cause. Give exact CLI to verify and fix. Include rollback. Mention escalation path. Time is critical.",
-    "architect":"Persona: SENIOR ARCHITECT. Expert level — skip basics entirely. Focus on design trade-offs, scalability, HA, redundancy, vendor comparison. Reference RFCs and standards. Provide BOM context.",
-    "manager":  "Persona: OPERATIONS MANAGER. Business language only. Avoid technical jargon. Focus on user impact, revenue risk, SLA performance, decisions needed, timeline to resolve.",
-    "security": "Persona: SECURITY ENGINEER. Threat context first. Attack vectors. Compliance implications. Zero Trust alignment. SIEM correlation opportunities. Containment actions. CVE references.",
-}
-
 # ══════════════════════════════════════════════════════════
 # KEY MANAGEMENT (no hardcoding)
 # ══════════════════════════════════════════════════════════
 def get_api_key() -> str:
     """Retrieve API key from Streamlit secrets or environment. Never hardcode."""
     try:
         return st.secrets.get("OPENROUTER_API_KEY", "")
     except Exception:
         return os.environ.get("OPENROUTER_API_KEY", "")
 
 # ══════════════════════════════════════════════════════════
 # CORE AI CALL
 # ══════════════════════════════════════════════════════════
 @st.cache_resource
 def _get_client():
     key = get_api_key()
     if not key or not _OPENAI_OK:
         return None
     return OpenAI(api_key=key, base_url=OPENROUTER_BASE)
 
 
 def call_ai(
     messages: list,
     persona: str = "noc",
     max_tokens: int = 2000,
@@ -3221,559 +3188,59 @@ def get_service_impact(device_id: str) -> List[KGNode]:
     """Find all services affected if a device fails."""
     affected = []
     for node in NODES:
         if node.node_type == "service":
             chain = get_impact_chain(node.id)
             if any(item["node"].id == device_id for item in chain):
                 affected.append(node)
     return affected
 
 
 def search_graph(query: str) -> List[KGNode]:
     """Search graph nodes by label or metadata."""
     ql = query.lower()
     return [n for n in NODES if ql in n.label.lower() or
             any(ql in str(v).lower() for v in n.metadata.values())]
 
 
 def get_all_nodes_by_type(node_type: str) -> List[KGNode]:
     return [n for n in NODES if n.node_type == node_type]
 
 
 def get_spof_nodes() -> List[KGNode]:
     return [n for n in NODES if n.metadata.get("spof") is True]
 
 
-# ══ UI COMPONENTS ════════════════════════════════════
-
-import streamlit as st
-from typing import Optional, List
-
-
-# ══════════════════════════════════════════════════════════
-# DESIGN TOKENS
-# ══════════════════════════════════════════════════════════
-DESIGN_SYSTEM_CSS = """
-<style>
-/* ── Imports ── */
-@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&family=Fraunces:wght@600;700;900&display=swap');
-
-/* ── Reset & Base ── */
-*{box-sizing:border-box}
-html,body,[class*="css"]{font-family:'Inter',sans-serif!important;font-size:14px}
-.stApp{background:#0d1117!important}
-#MainMenu,footer,header{visibility:hidden}
-div.block-container{padding:0!important;max-width:100%!important}
-section[data-testid="stSidebar"]{display:none!important}
-
-/* ── Streamlit overrides ── */
-div[data-testid="stButton"] button{
-  border-radius:8px!important;font-weight:600!important;
-  font-family:'Inter',sans-serif!important;transition:all .15s!important;
-}
-div[data-testid="stTextInput"] input,
-div[data-testid="stTextArea"] textarea,
-div[data-testid="stSelectbox"] select{border-radius:8px!important}
-div[data-testid="stExpander"]{
-  border-radius:10px!important;border:1px solid #21262d!important;
-  background:#161b22!important;
-}
-div[data-testid="stExpander"] summary{color:#e6edf3!important}
-.stAlert{border-radius:10px!important}
-div[data-testid="stMetric"]{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:14px!important}
-div[data-testid="stMetric"] label{color:#8b949e!important}
-div[data-testid="stMetric"] div{color:#e6edf3!important}
-
-/* ── Colors ── */
-:root{
-  --bg-base:#0d1117;
-  --bg-surface:#161b22;
-  --bg-elevated:#1c2128;
-  --bg-overlay:#21262d;
-  --border-subtle:#21262d;
-  --border-default:#30363d;
-  --border-muted:#6e7681;
-  --text-primary:#e6edf3;
-  --text-secondary:#8b949e;
-  --text-tertiary:#6e7681;
-  --accent-blue:#2f81f7;
-  --accent-blue-subtle:#1f6feb22;
-  --accent-green:#3fb950;
-  --accent-green-subtle:#238636;
-  --accent-amber:#d29922;
-  --accent-amber-subtle:#9e6a0322;
-  --accent-red:#f85149;
-  --accent-red-subtle:#da363022;
-  --accent-purple:#bc8cff;
-  --accent-purple-subtle:#6e40c922;
-  --accent-teal:#39d353;
-  --glass-bg:rgba(22,27,34,0.85);
-  --glass-border:rgba(48,54,61,0.8);
-}
-
-/* ── Top Command Bar ── */
-.nb-topbar{
-  background:linear-gradient(180deg,#161b22 0%,#0d1117 100%);
-  border-bottom:1px solid var(--border-default);
-  padding:0 20px;height:54px;
-  display:flex;align-items:center;gap:14px;
-  position:sticky;top:0;z-index:1000;
-  box-shadow:0 1px 0 rgba(0,0,0,.5),0 4px 16px rgba(0,0,0,.3);
-}
-.nb-logo{display:flex;align-items:center;gap:10px;flex-shrink:0}
-.nb-logo-mark{
-  width:30px;height:30px;border-radius:8px;flex-shrink:0;
-  background:linear-gradient(135deg,#1f6feb,#2f81f7);
-  display:flex;align-items:center;justify-content:center;
-  font-size:16px;box-shadow:0 0 12px rgba(47,129,247,.35);
-}
-.nb-logo-name{font-family:'Fraunces',serif;font-size:17px;font-weight:900;color:var(--text-primary);letter-spacing:-.3px}
-.nb-logo-ver{font-size:9px;color:var(--text-tertiary);letter-spacing:1px;text-transform:uppercase;font-family:'JetBrains Mono',monospace}
-.nb-divider-v{width:1px;height:22px;background:var(--border-default);flex-shrink:0}
-.nb-search{
-  flex:1;max-width:540px;height:34px;
-  background:var(--bg-elevated);border:1px solid var(--border-default);
-  border-radius:10px;display:flex;align-items:center;gap:8px;padding:0 12px;
-  transition:all .2s;
-}
-.nb-search:focus-within{
-  border-color:var(--accent-blue);
-  box-shadow:0 0 0 3px var(--accent-blue-subtle);
-}
-.nb-search input{
-  flex:1;background:none;border:none;outline:none;
-  color:var(--text-primary);font-size:13px;font-family:'Inter',sans-serif;
-}
-.nb-search input::placeholder{color:var(--text-tertiary)}
-.nb-search-ico{color:var(--text-tertiary);font-size:13px;flex-shrink:0}
-.nb-search-hint{font-size:10px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;flex-shrink:0;white-space:nowrap}
-
-/* Status chips */
-.nb-status-row{display:flex;gap:4px;align-items:center}
-.nb-chip{
-  font-size:10px;padding:3px 8px;border-radius:12px;
-  font-family:'JetBrains Mono',monospace;font-weight:600;
-  display:inline-flex;align-items:center;gap:4px;white-space:nowrap;
-}
-.chip-ok   {background:rgba(63,185,80,.12);color:#3fb950;border:1px solid rgba(63,185,80,.25)}
-.chip-warn {background:rgba(210,153,34,.12);color:#d29922;border:1px solid rgba(210,153,34,.25)}
-.chip-err  {background:rgba(248,81,73,.12);color:#f85149;border:1px solid rgba(248,81,73,.25)}
-.chip-info {background:rgba(47,129,247,.12);color:#2f81f7;border:1px solid rgba(47,129,247,.25)}
-.chip-dot  {width:5px;height:5px;border-radius:50%;background:currentColor;animation:blink-dot 2s infinite}
-@keyframes blink-dot{0%,100%{opacity:1}50%{opacity:.4}}
-
-/* Persona switcher */
-.nb-persona-sw{
-  display:flex;background:var(--bg-elevated);border:1px solid var(--border-default);
-  border-radius:8px;overflow:hidden;height:28px;flex-shrink:0;
-}
-.nb-p-btn{
-  padding:0 10px;font-size:11px;font-weight:600;color:var(--text-tertiary);
-  cursor:pointer;height:100%;display:flex;align-items:center;gap:3px;
-  border:none;background:none;transition:all .15s;white-space:nowrap;
-  font-family:'Inter',sans-serif;border-right:1px solid var(--border-default);
-}
-.nb-p-btn:last-child{border-right:none}
-.nb-p-btn:hover{color:var(--text-secondary)}
-.nb-p-btn.active{background:rgba(47,129,247,.15);color:var(--accent-blue)}
-.nb-avatar{
-  width:28px;height:28px;border-radius:7px;flex-shrink:0;
-  background:linear-gradient(135deg,#1f6feb,#2f81f7);
-  display:flex;align-items:center;justify-content:center;
-  font-size:11px;font-weight:700;color:#fff;cursor:pointer;
-}
-
-/* ── Workspace Navigation ── */
-.nb-workspace-nav{
-  background:var(--bg-surface);border-bottom:1px solid var(--border-default);
-  padding:0 20px;height:44px;display:flex;align-items:center;gap:2px;overflow-x:auto;
-}
-.nb-workspace-nav::-webkit-scrollbar{height:0}
-.nb-ws-tab{
-  padding:0 14px;height:100%;display:flex;align-items:center;gap:7px;
-  font-size:12px;font-weight:600;color:var(--text-tertiary);cursor:pointer;
-  border-bottom:2px solid transparent;transition:all .15s;white-space:nowrap;
-  background:none;border-top:none;border-left:none;border-right:none;
-  font-family:'Inter',sans-serif;
-}
-.nb-ws-tab:hover{color:var(--text-secondary);background:var(--bg-elevated)}
-.nb-ws-tab.active{color:var(--accent-blue);border-bottom-color:var(--accent-blue)}
-.nb-ws-badge{
-  font-size:9px;padding:1px 5px;border-radius:8px;font-weight:700;
-  background:var(--accent-red-subtle);color:var(--accent-red);
-  font-family:'JetBrains Mono',monospace;min-width:16px;text-align:center;
-}
-
-/* ── AI Command Bar ── */
-.ai-cmd-wrap{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:12px;padding:14px 16px;margin-bottom:16px;
-  transition:all .2s;position:relative;
-}
-.ai-cmd-wrap:focus-within{
-  border-color:var(--accent-blue);
-  box-shadow:0 0 0 3px var(--accent-blue-subtle),0 4px 20px rgba(0,0,0,.3);
-}
-.ai-cmd-pulse{
-  width:7px;height:7px;border-radius:50%;background:var(--accent-green);
-  animation:pulse-green 2s infinite;display:inline-block;margin-right:6px;
-}
-@keyframes pulse-green{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(.7)}}
-.ai-cmd-label{
-  font-size:10px;font-weight:700;color:var(--text-tertiary);
-  letter-spacing:1px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;
-  margin-bottom:8px;display:flex;align-items:center;
-}
-
-/* ── Metric Cards ── */
-.nb-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}
-.nb-metric{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:10px;padding:14px 16px;position:relative;overflow:hidden;
-  cursor:default;transition:all .2s;
-}
-.nb-metric:hover{border-color:var(--border-muted);background:var(--bg-elevated)}
-.nb-metric::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
-.nb-m-green::before{background:linear-gradient(90deg,var(--accent-green),#238636)}
-.nb-m-red::before{background:linear-gradient(90deg,var(--accent-red),#b91c1c)}
-.nb-m-amber::before{background:linear-gradient(90deg,var(--accent-amber),#9e6a03)}
-.nb-m-blue::before{background:linear-gradient(90deg,var(--accent-blue),#1f6feb)}
-.nb-m-purple::before{background:linear-gradient(90deg,var(--accent-purple),#6e40c9)}
-.nb-m-lbl{font-size:10px;font-weight:600;color:var(--text-tertiary);letter-spacing:.6px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;margin-bottom:6px}
-.nb-m-val{font-family:'Fraunces',serif;font-size:26px;font-weight:700;line-height:1;margin-bottom:4px}
-.nb-m-green .nb-m-val{color:var(--accent-green)}.nb-m-red .nb-m-val{color:var(--accent-red)}.nb-m-amber .nb-m-val{color:var(--accent-amber)}.nb-m-blue .nb-m-val{color:var(--accent-blue)}.nb-m-purple .nb-m-val{color:var(--accent-purple)}
-.nb-m-meta{font-size:11px;color:var(--text-tertiary)}
-.nb-m-icon{position:absolute;right:12px;top:12px;font-size:18px;opacity:.1}
-
-/* ── AI Insight Card ── */
-.nb-ai-insight{
-  background:linear-gradient(135deg,rgba(31,111,235,.08) 0%,var(--bg-surface) 100%);
-  border:1px solid rgba(47,129,247,.2);border-left:3px solid var(--accent-blue);
-  border-radius:0 10px 10px 0;padding:12px 14px;margin-bottom:14px;
-}
-.nb-ai-hdr{
-  font-size:9px;font-weight:700;color:var(--accent-blue);
-  letter-spacing:1.2px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;
-  margin-bottom:5px;display:flex;align-items:center;gap:6px;
-}
-.nb-ai-body{font-size:13px;color:var(--text-primary);line-height:1.65}
-.nb-ai-body strong{color:#79c0ff}
-.nb-ai-body code{
-  font-family:'JetBrains Mono',monospace;font-size:12px;
-  background:rgba(47,129,247,.12);color:#79c0ff;
-  padding:1px 5px;border-radius:4px;
-}
-.nb-conf{display:flex;align-items:center;gap:8px;margin-top:6px}
-.nb-conf-track{flex:1;height:3px;background:var(--border-default);border-radius:4px;overflow:hidden}
-.nb-conf-fill{height:100%;border-radius:4px}
-.conf-high .nb-conf-fill{background:linear-gradient(90deg,var(--accent-green),#238636)}
-.conf-med  .nb-conf-fill{background:linear-gradient(90deg,var(--accent-amber),#9e6a03)}
-.conf-low  .nb-conf-fill{background:linear-gradient(90deg,var(--accent-red),#b91c1c)}
-.nb-conf-pct{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;width:32px}
-.conf-high .nb-conf-pct{color:var(--accent-green)}.conf-med .nb-conf-pct{color:var(--accent-amber)}.conf-low .nb-conf-pct{color:var(--accent-red)}
-
-/* ── Cards ── */
-.nb-card{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:10px;overflow:hidden;margin-bottom:12px;
-}
-.nb-card-hdr{
-  padding:12px 16px;border-bottom:1px solid var(--border-subtle);
-  display:flex;align-items:center;justify-content:space-between;
-  background:var(--bg-surface);
-}
-.nb-card-title{font-size:13px;font-weight:700;color:var(--text-primary);display:flex;align-items:center;gap:7px}
-.nb-card-body{padding:14px 16px}
-
-/* ── Tags ── */
-.nb-tag{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;font-family:'JetBrains Mono',monospace}
-.tag-red    {background:var(--accent-red-subtle);color:var(--accent-red);border:1px solid rgba(248,81,73,.2)}
-.tag-amber  {background:var(--accent-amber-subtle);color:var(--accent-amber);border:1px solid rgba(210,153,34,.2)}
-.tag-green  {background:var(--accent-green-subtle);color:var(--accent-green);border:1px solid rgba(63,185,80,.2)}
-.tag-blue   {background:var(--accent-blue-subtle);color:var(--accent-blue);border:1px solid rgba(47,129,247,.2)}
-.tag-purple {background:var(--accent-purple-subtle);color:var(--accent-purple);border:1px solid rgba(188,140,255,.2)}
-.tag-slate  {background:var(--bg-elevated);color:var(--text-secondary);border:1px solid var(--border-default)}
-
-/* ── Device Cards ── */
-.nb-dev-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;margin-bottom:16px}
-.nb-dev{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:10px;padding:11px;cursor:pointer;transition:all .15s;
-  position:relative;overflow:hidden;
-}
-.nb-dev:hover{border-color:var(--border-muted);background:var(--bg-elevated);transform:translateY(-1px)}
-.nb-dev::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
-.dev-up::before   {background:var(--accent-green)}
-.dev-warn::before {background:var(--accent-amber);animation:pulse-bar 2s infinite}
-.dev-critical::before{background:var(--accent-red);animation:pulse-bar 1s infinite}
-@keyframes pulse-bar{0%,100%{opacity:1}50%{opacity:.4}}
-.nb-dev-hn{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--text-primary);margin-bottom:2px}
-.nb-dev-role{font-size:11px;color:var(--text-secondary);margin-bottom:2px}
-.nb-dev-site{font-size:10px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace}
-.nb-dev-metrics{display:flex;gap:8px;margin-top:8px}
-.nb-dev-m{flex:1;text-align:center}
-.nb-dev-mv{font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700}
-.nb-dev-ml{font-size:9px;color:var(--text-tertiary);text-transform:uppercase;letter-spacing:.4px}
-.mv-ok{color:var(--accent-green)}.mv-warn{color:var(--accent-amber)}.mv-crit{color:var(--accent-red)}
-
-/* ── Chat Bubbles ── */
-.nb-chat-user{
-  background:var(--accent-blue);color:#fff;
-  border-radius:12px 12px 2px 12px;padding:10px 14px;margin:4px 0;
-  display:inline-block;max-width:80%;font-size:13px;line-height:1.6;
-  box-shadow:0 2px 8px rgba(47,129,247,.25);
-}
-.nb-chat-ai{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:12px 12px 12px 2px;padding:12px 16px;margin:4px 0;
-  display:inline-block;max-width:90%;font-size:13px;line-height:1.65;
-  color:var(--text-primary);box-shadow:0 2px 8px rgba(0,0,0,.2);
-}
-.nb-chat-ai code{
-  font-family:'JetBrains Mono',monospace;font-size:12px;
-  background:var(--bg-elevated);color:#79c0ff;
-  padding:1px 5px;border-radius:4px;
-}
-.nb-chat-ai pre{
-  font-family:'JetBrains Mono',monospace;font-size:12px;
-  background:#0d1117;color:#3fb950;
-  padding:12px;border-radius:8px;border:1px solid var(--border-default);
-  margin-top:8px;overflow-x:auto;line-height:1.7;
-}
-.nb-chat-ai strong{color:#79c0ff}
-.nb-meta-row{display:flex;gap:4px;flex-wrap:wrap;margin-top:5px}
-.nb-mp{
-  font-size:10px;padding:2px 7px;border-radius:8px;
-  font-family:'JetBrains Mono',monospace;font-weight:600;display:inline-flex;align-items:center;gap:3px;
-}
-.mp-rag{background:rgba(57,211,83,.1);color:var(--accent-teal);border:1px solid rgba(57,211,83,.2)}
-.mp-nlp{background:rgba(188,140,255,.1);color:var(--accent-purple);border:1px solid rgba(188,140,255,.2)}
-.mp-per{background:rgba(63,185,80,.1);color:var(--accent-green);border:1px solid rgba(63,185,80,.2)}
-.mp-inc{background:rgba(210,153,34,.1);color:var(--accent-amber);border:1px solid rgba(210,153,34,.2)}
-
-/* ── Timeline ── */
-.nb-timeline-item{display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border-subtle);align-items:flex-start}
-.nb-timeline-item:last-child{border-bottom:none}
-.nb-tl-dot{width:28px;height:28px;border-radius:7px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:13px}
-.tl-crit{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.2)}
-.tl-warn{background:rgba(210,153,34,.12);border:1px solid rgba(210,153,34,.2)}
-.tl-ok  {background:rgba(63,185,80,.12);border:1px solid rgba(63,185,80,.2)}
-.tl-ai  {background:rgba(47,129,247,.12);border:1px solid rgba(47,129,247,.2)}
-.tl-info{background:rgba(188,140,255,.12);border:1px solid rgba(188,140,255,.2)}
-.nb-tl-body{flex:1}
-.nb-tl-title{font-size:13px;font-weight:500;color:var(--text-primary);margin-bottom:2px}
-.nb-tl-meta{font-size:11px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;margin-bottom:3px}
-.nb-tl-ai{font-size:11px;color:var(--accent-blue);background:rgba(47,129,247,.08);border-radius:5px;padding:2px 7px;display:inline-block}
-
-/* ── War Room ── */
-.nb-warroom{
-  background:linear-gradient(135deg,rgba(248,81,73,.05) 0%,var(--bg-surface) 100%);
-  border:1px solid rgba(248,81,73,.2);border-radius:12px;overflow:hidden;
-  margin-bottom:16px;box-shadow:0 4px 24px rgba(248,81,73,.08);
-}
-.nb-wr-hdr{
-  background:linear-gradient(135deg,#3d0f0a,#5c1a12);
-  padding:14px 18px;display:flex;align-items:center;gap:12px;
-}
-.nb-wr-pulse{
-  width:9px;height:9px;border-radius:50%;background:#fca5a5;
-  animation:wr-pulse 1s infinite;flex-shrink:0;
-}
-@keyframes wr-pulse{0%,100%{opacity:1;box-shadow:0 0 0 0 rgba(252,165,165,.4)}50%{opacity:.6;box-shadow:0 0 0 6px transparent}}
-.nb-wr-title{font-family:'Fraunces',serif;font-size:14px;font-weight:700;color:#fff;flex:1}
-
-/* ── Autonomous Actions ── */
-.nb-auto-action{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:10px;padding:11px;margin-bottom:8px;
-  display:flex;gap:10px;align-items:flex-start;
-  transition:border-color .15s;
-}
-.nb-auto-action:hover{border-color:var(--border-muted)}
-.nb-aa-ico{width:30px;height:30px;border-radius:7px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px}
-.aa-exec{background:rgba(63,185,80,.12);border:1px solid rgba(63,185,80,.2)}
-.aa-pend{background:rgba(210,153,34,.12);border:1px solid rgba(210,153,34,.2)}
-.aa-fail{background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.2)}
-.nb-aa-title{font-size:13px;font-weight:500;color:var(--text-primary);margin-bottom:2px}
-.nb-aa-meta{font-size:11px;color:var(--text-tertiary);font-family:'JetBrains Mono',monospace;margin-bottom:3px}
-.nb-aa-ai{font-size:11px;color:var(--accent-purple);background:rgba(188,140,255,.08);border-radius:5px;padding:2px 7px;display:inline-block}
-
-/* ── Device output terminal ── */
-.nb-terminal{
-  font-family:'JetBrains Mono',monospace;font-size:11px;
-  background:#0d1117;color:#3fb950;padding:10px;border-radius:7px;
-  border:1px solid var(--border-default);
-  max-height:130px;overflow-y:auto;line-height:1.7;white-space:pre-wrap;
-  margin-top:6px;
-}
-.nb-terminal::-webkit-scrollbar{width:3px}
-.nb-terminal::-webkit-scrollbar-thumb{background:var(--border-default)}
-
-/* ── Risk bar ── */
-.nb-risk-wrap{display:flex;align-items:center;gap:8px;margin-top:7px}
-.nb-risk-track{flex:1;height:5px;background:var(--border-default);border-radius:4px;overflow:hidden}
-.nb-risk-fill{height:100%;border-radius:4px}
-.risk-low  .nb-risk-fill{background:linear-gradient(90deg,var(--accent-green),#238636)}
-.risk-med  .nb-risk-fill{background:linear-gradient(90deg,var(--accent-amber),#9e6a03)}
-.risk-high .nb-risk-fill{background:linear-gradient(90deg,var(--accent-red),#b91c1c)}
-.nb-risk-score{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;width:30px;text-align:right}
-.risk-low  .nb-risk-score{color:var(--accent-green)}
-.risk-med  .nb-risk-score{color:var(--accent-amber)}
-.risk-high .nb-risk-score{color:var(--accent-red)}
-
-/* ── Change card ── */
-.nb-change-card{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:10px;padding:14px;margin-bottom:10px;cursor:pointer;
-  transition:all .15s;
-}
-.nb-change-card:hover{border-color:var(--border-muted);background:var(--bg-elevated)}
-
-/* ── Topology wrapper ── */
-.nb-topo-wrap{background:var(--bg-elevated);border:1px solid var(--border-default);border-radius:10px;overflow:hidden}
-.nb-topo-bar{
-  padding:8px 12px;border-bottom:1px solid var(--border-default);
-  display:flex;gap:5px;align-items:center;background:var(--bg-surface);flex-wrap:wrap;
-}
-.nb-layer-btn{
-  padding:3px 9px;border-radius:14px;font-size:11px;font-weight:600;
-  border:1px solid var(--border-default);background:var(--bg-elevated);
-  color:var(--text-secondary);cursor:pointer;transition:all .12s;
-  font-family:'Inter',sans-serif;
-}
-.nb-layer-btn.active{background:rgba(47,129,247,.15);border-color:var(--accent-blue);color:var(--accent-blue)}
-.nb-layer-btn:hover:not(.active){border-color:var(--border-muted);color:var(--text-primary)}
-
-/* ── Design Studio ── */
-.nb-design-studio{
-  background:linear-gradient(135deg,rgba(31,111,235,.06) 0%,rgba(188,140,255,.04) 100%);
-  border:1px solid rgba(47,129,247,.15);border-radius:14px;padding:20px;margin-bottom:16px;
-}
-.nb-ds-title{font-family:'Fraunces',serif;font-size:17px;font-weight:700;color:var(--text-primary);margin-bottom:4px}
-.nb-ds-sub{font-size:12px;color:var(--text-secondary);margin-bottom:16px}
-
-/* ── Knowledge Graph ── */
-.nb-kg-node{
-  background:var(--bg-surface);border:1px solid var(--border-default);
-  border-radius:10px;padding:12px;cursor:pointer;transition:all .15s;
-}
-.nb-kg-node:hover{border-color:var(--accent-blue);background:var(--bg-elevated)}
-.nb-kg-node.selected{border-color:var(--accent-blue);background:rgba(47,129,247,.06);box-shadow:0 0 0 2px var(--accent-blue-subtle)}
-.nb-kg-type{font-size:9px;font-weight:700;color:var(--text-tertiary);letter-spacing:1px;text-transform:uppercase;font-family:'JetBrains Mono',monospace;margin-bottom:4px}
-.nb-kg-name{font-size:13px;font-weight:600;color:var(--text-primary);margin-bottom:2px}
-.nb-kg-meta{font-size:11px;color:var(--text-tertiary)}
-
-/* ── Autonomous mode ── */
-.nb-auto-modes{display:flex;gap:8px;margin-bottom:14px}
-.nb-mode-btn{
-  flex:1;padding:10px;border-radius:10px;
-  border:1px solid var(--border-default);background:var(--bg-elevated);
-  cursor:pointer;text-align:center;transition:all .15s;font-family:'Inter',sans-serif;
-}
-.nb-mode-btn.selected-human{border-color:var(--accent-blue);background:rgba(47,129,247,.08)}
-.nb-mode-btn.selected-semi{border-color:var(--accent-amber);background:rgba(210,153,34,.08)}
-.nb-mode-btn.selected-full{border-color:var(--accent-purple);background:rgba(188,140,255,.08)}
-.nb-mode-title{font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:2px}
-.nb-mode-desc{font-size:11px;color:var(--text-tertiary);line-height:1.4}
-
-/* ── Responsive ── */
-@media(max-width:1100px){
-  .nb-metrics{grid-template-columns:1fr 1fr}
-  .nb-dev-grid{grid-template-columns:1fr 1fr 1fr}
-}
-@media(max-width:768px){
-  .nb-metrics{grid-template-columns:1fr}
-  .nb-dev-grid{grid-template-columns:1fr 1fr}
-}
-</style>
-"""
-
-
-def inject_css():
-    st.markdown(DESIGN_SYSTEM_CSS, unsafe_allow_html=True)
-
-
-# ══════════════════════════════════════════════════════════
-# COMPONENT FUNCTIONS
-# ══════════════════════════════════════════════════════════
-def ai_insight_card(label: str, text: str, confidence: Optional[int] = None, sources: Optional[List[str]] = None):
-    conf_html = ""
-    if confidence is not None:
-        cls = "conf-high" if confidence >= 80 else "conf-med" if confidence >= 60 else "conf-low"
-        conf_html = f'<div class="nb-conf {cls}"><span class="nb-conf-pct">{confidence}%</span><div class="nb-conf-track"><div class="nb-conf-fill" style="width:{confidence}%"></div></div><span style="font-size:10px;color:var(--text-tertiary)">AI Confidence</span></div>'
-    src_html = ""
-    if sources:
-        src_html = "<div style='margin-top:4px'>" + "".join(
-            f'<span style="font-size:10px;padding:1px 6px;border-radius:5px;background:rgba(57,211,83,.1);color:#39d353;font-family:JetBrains Mono,monospace;margin:1px">{s}</span>'
-            for s in sources if s) + "</div>"
-    st.markdown(f"""<div class="nb-ai-insight">
-      <div class="nb-ai-hdr">🧠 {label}</div>
-      <div class="nb-ai-body">{text}</div>
-      {conf_html}{src_html}
-    </div>""", unsafe_allow_html=True)
-
-
-def metric_grid(metrics: List[dict]):
-    """
-    metrics: [{"label":"..","value":"..","meta":"..","color":"green|red|amber|blue|purple","icon":""}]
-    """
-    cols = st.columns(len(metrics))
-    for col, m in zip(cols, metrics):
-        with col:
-            cc = m.get("color","blue")
-            st.markdown(f"""<div class="nb-metric nb-m-{cc}">
-              <div class="nb-m-icon">{m.get('icon','')}</div>
-              <div class="nb-m-lbl">{m['label']}</div>
-              <div class="nb-m-val">{m['value']}</div>
-              <div class="nb-m-meta">{m['meta']}</div>
-            </div>""", unsafe_allow_html=True)
-
-
-def render_chat_message(role: str, content: str, meta: Optional[dict] = None):
-    if role == "user":
-        st.markdown(f'<div style="text-align:right;margin:5px 0"><span class="nb-chat-user">{content}</span></div>', unsafe_allow_html=True)
-    else:
-        st.markdown(f'<div style="margin:5px 0"><span class="nb-chat-ai">{content}</span></div>', unsafe_allow_html=True)
-        if meta:
-            pills = ""
-            if meta.get("persona_used"): pills += f'<span class="nb-mp mp-per">👤 {meta["persona_used"]}</span>'
-            if meta.get("rag_topics"):   pills += "".join(f'<span class="nb-mp mp-rag">📚 {t}</span>' for t in (meta.get("rag_topics") or [])[:2] if t)
-            if meta.get("similar_incidents"): pills += f'<span class="nb-mp mp-inc">💡 {str(meta["similar_incidents"][0])[:35]}</span>'
-            ents = meta.get("entities") or {}
-            if ents.get("protocols"): pills += f'<span class="nb-mp mp-nlp">🧬 {", ".join(ents["protocols"][:3])}</span>'
-            if pills:
-                st.markdown(f'<div class="nb-meta-row">{pills}</div>', unsafe_allow_html=True)
-
-
-def section_header(title: str, subtitle: str = ""):
-    sub = f'<div style="font-size:12px;color:var(--text-tertiary);margin-top:2px">{subtitle}</div>' if subtitle else ""
-    st.markdown(f'<div style="margin-bottom:14px"><div style="font-family:Fraunces,serif;font-size:18px;font-weight:700;color:var(--text-primary)">{title}</div>{sub}</div>', unsafe_allow_html=True)
-
-
-def risk_bar(score: int):
-    cls = "risk-low" if score < 30 else "risk-med" if score < 65 else "risk-high"
-    st.markdown(f'<div class="nb-risk-wrap {cls}"><div class="nb-risk-track"><div class="nb-risk-fill" style="width:{score}%"></div></div><span class="nb-risk-score">{score}</span></div>', unsafe_allow_html=True)
+# ══ UI COMPONENTS ════════════════════════════════════════
+from ui.components import (
+    inject_css,
+    ai_insight_card,
+    metric_grid,
+    render_chat_message,
+    section_header,
+    risk_bar,
+)
 
 
 
 # ── Compatibility aliases ─────────────────────────────────
 nlp_extract = extract
 def rag_search(query, n=4, vendor_filter=None, protocol_filter=None):
     return search(query, n, vendor_filter, protocol_filter)
 mdq_run = run_query
 
 
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
@@ -3892,78 +3359,62 @@ def render_topbar():
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
-WORKSPACES = [
-    ("operations",  "⚡",  "Operations"),
-    ("incident",    "🚨",  "Incidents"),
-    ("topology",    "🗺",  "Topology"),
-    ("observe",     "📡",  "Observability"),
-    ("troubleshoot","🔧",  "Diagnose"),
-    ("change",      "📋",  "Changes"),
-    ("autonomous",  "🤖",  "Autonomous"),
-    ("twin",        "👾",  "Digital Twin"),
-    ("security",    "🔒",  "Security"),
-    ("compliance",  "🛡",  "Compliance"),
-    ("design",      "🏗",  "Design"),
-    ("mdq",         "⚡",  "Multi-Device"),
-    ("nlp",         "🧬",  "NLP"),
-    ("rag",         "📚",  "Knowledge"),
-    ("learn",       "📖",  "Learn"),
-    ("devices",     "🖧",  "Devices"),
-    ("executive",   "📈",  "Executive"),
-    ("finops",      "💰",  "FinOps"),
-    ("audit",       "🔐",  "Audit"),
-]
+from config.workspaces import WORKSPACES
 
-def render_workspace_nav():
+@st.cache_data(ttl=10)
+def get_workspace_badges() -> dict:
+    """Return lightweight navigation badge counts without re-querying every rerun."""
     active_incs = len(get_incidents("active"))
     pending_chg = len([c for c in get_changes() if c["status"] == "pending"])
-    pending_auto= len([a for a in get_auto_actions() if a["status"] == "pending_approval"])
+    pending_auto = len([a for a in get_auto_actions() if a["status"] == "pending_approval"])
+    return {"incident": active_incs, "change": pending_chg, "autonomous": pending_auto}
 
-    badges = {"incident": active_incs, "change": pending_chg, "autonomous": pending_auto}
+def render_workspace_nav():
+    badges = get_workspace_badges()
 
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
 
EOF
)
