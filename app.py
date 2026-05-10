"""
NetBrain AI — AI-Native Autonomous Network Operating System
=============================================================
NOT a dashboard. NOT a monitoring portal.
An AI-Native Autonomous Network Operating System.

Architecture:
- Contextual Operational Workspaces (not pages)
- Incident War Room (not alert list)
- AI embedded in every module (not just chatbot)
- Network Knowledge Graph (not static views)
- Operational Memory (learns continuously)
- Business Impact Layer (not just device metrics)
- Autonomous Operations Center
"""

import streamlit as st
st.set_page_config(
    page_title="NetBrain AI — Autonomous Network OS",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="collapsed",
    menu_items={"About": "NetBrain AI — Autonomous Network Operating System v2.0"}
)

import os, re, json, sqlite3, threading, hashlib, time
from datetime import datetime, timedelta
import pandas as pd

# ── Safe optional imports ──────────────────────────────────
try:
    import anthropic; CLAUDE_OK = True
except: CLAUDE_OK = False
try:
    from netmiko import ConnectHandler; NETMIKO_OK = True
except: NETMIKO_OK = False
try:
    import spacy; _nlp = spacy.load("en_core_web_sm"); SPACY_OK = True
except: SPACY_OK = False; _nlp = None
try:
    import chromadb; from sentence_transformers import SentenceTransformer
    _cc = chromadb.PersistentClient(path="./chroma_db")
    _emb = SentenceTransformer("all-MiniLM-L6-v2"); _col = None; RAG_OK = True
except: RAG_OK = False; _cc = _emb = _col = None

# ══════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════
DB = "netbrain.db"
def db():
    c = sqlite3.connect(DB, check_same_thread=False); c.row_factory = sqlite3.Row; return c

def init_db():
    con = db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS devices (id INTEGER PRIMARY KEY AUTOINCREMENT, hostname TEXT, ip TEXT, vendor TEXT DEFAULT 'cisco_ios', username TEXT, password TEXT, port INTEGER DEFAULT 22, role TEXT, site TEXT, status TEXT DEFAULT 'up', cpu INTEGER DEFAULT 0, memory INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS incidents (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, root_cause TEXT, resolution TEXT, devices TEXT, protocols TEXT, severity TEXT, status TEXT DEFAULT 'active', business_impact TEXT, affected_users INTEGER DEFAULT 0, confidence INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, resolved_at TEXT);
        CREATE TABLE IF NOT EXISTS changes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT, device TEXT, change_type TEXT, risk_level TEXT, status TEXT DEFAULT 'pending', ai_risk_score INTEGER DEFAULT 0, ai_recommendation TEXT, created_by TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS chat_history (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT, persona TEXT, workspace TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS autonomous_actions (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, device TEXT, trigger TEXT, ai_confidence INTEGER, status TEXT DEFAULT 'pending', result TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS knowledge_graph (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, source_type TEXT, target TEXT, target_type TEXT, relationship TEXT, metadata TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    """)
    if con.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0:
        con.executemany("INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site,status,cpu,memory) VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
            ("CORE-RTR-01","10.0.0.1","cisco_ios_xr","admin","admin123",22,"Core Router","HQ","warn",88,62),
            ("PE-MUM-01","10.0.1.1","cisco_ios_xr","admin","admin123",22,"PE Router","Mumbai","critical",34,48),
            ("PE-DEL-01","10.0.2.1","cisco_ios_xr","admin","admin123",22,"PE Router","Delhi","up",22,41),
            ("DIST-SW-W","10.1.1.1","cisco_ios","admin","admin123",22,"Dist Switch","HQ-West","up",18,35),
            ("DIST-SW-C","10.1.2.1","cisco_ios","admin","admin123",22,"Dist Switch","HQ-Central","warn",45,71),
            ("FW-EDGE-01","192.168.1.1","paloalto_panos","admin","admin123",22,"Firewall","DMZ","up",18,55),
            ("SW-ACC-14","10.2.14.1","cisco_ios","admin","admin123",22,"Access Switch","HQ-Floor2","critical",0,0),
            ("WLC-HQ-01","10.3.1.1","cisco_ios","admin","admin123",22,"WLC","HQ","up",22,38),
        ])
    if con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0:
        con.executemany("INSERT INTO incidents(title,description,root_cause,resolution,devices,protocols,severity,status,business_impact,affected_users,confidence) VALUES(?,?,?,?,?,?,?,?,?,?,?)", [
            ("BGP Session Flapping — PE-MUM-01","BGP peer AS65002 flapping 3x/hr causing route instability","Upstream ISP BGP prefix withdrawal causing hold-timer expiry","Increase BGP hold-timer to 90s. Open ISP ticket. Enable BFD for sub-second detection.","PE-MUM-01","BGP","critical","active","142 prefixes withdrawn. Mumbai branch SaaS access degraded. 340 users impacted.",340,87),
            ("Interface Down — SW-ACC-14 Gi0/0/3","Physical interface failure on access switch","Physical port failure or cable disconnect","Replace cable or SFP. Check port for physical damage.","SW-ACC-14","Layer2","critical","active","VLAN 120 users unable to access corporate network. 47 users impacted.",47,94),
            ("OSPF Adjacency Lost — 2024-11-14","OSPF neighbor lost between CORE and DIST","MTU mismatch on GigabitEthernet interface","Added ip ospf mtu-ignore on both interfaces","CORE-RTR-01,DIST-SW-W","OSPF","major","resolved","Brief routing disruption. Self-recovered in 4 minutes.",0,96),
        ])
    if con.execute("SELECT COUNT(*) FROM changes").fetchone()[0] == 0:
        con.executemany("INSERT INTO changes(title,description,device,change_type,risk_level,status,ai_risk_score,ai_recommendation,created_by) VALUES(?,?,?,?,?,?,?,?,?)", [
            ("BGP hold-timer update — PE-MUM-01","Increase BGP hold-timer from 60s to 90s on PE-MUM-01 to reduce flapping","PE-MUM-01","config","low",  "approved",15,"Low risk. Timer change only. No protocol restart required. Recommend BFD simultaneously.","NOC-Engineer"),
            ("IOS-XR firmware upgrade — CORE-RTR-01","Upgrade from 7.5.2 to 7.7.1 on core router","CORE-RTR-01","firmware","high","pending",72,"HIGH RISK. Core router. Maintenance window required. Digital twin test first. Rollback plan mandatory.","Architect"),
            ("New VLAN 150 — DIST-SW-W","Add VLAN 150 for new HR subnet deployment","DIST-SW-W","vlan","low","pending",8,"Low risk. VLAN addition only. No impact to existing VLANs. Recommend testing on DEV switch first.","NOC-Engineer"),
        ])
    if con.execute("SELECT COUNT(*) FROM autonomous_actions").fetchone()[0] == 0:
        con.executemany("INSERT INTO autonomous_actions(action,device,trigger,ai_confidence,status,result) VALUES(?,?,?,?,?,?)", [
            ("BFD enabled on BGP peer 10.0.2.1","PE-MUM-01","BGP flap detected — 3 events in 60 min",91,"executed","BFD session established. Detection time reduced to 300ms."),
            ("SNMP trap forwarded to NOC","SW-ACC-14","Interface down — Gi0/0/3",99,"executed","Ticket INC0047821 created. NOC notified via Slack."),
            ("BGP hold-timer increase staged","PE-MUM-01","Recurring BGP flap pattern — 3rd occurrence",78,"pending_approval","Awaiting NOC engineer approval. Estimated risk: LOW."),
        ])
    con.commit(); con.close()

def get_devices(): con=db(); r=con.execute("SELECT * FROM devices").fetchall(); con.close(); return [dict(x) for x in r]
def get_incidents(status=None):
    con=db()
    q = "SELECT * FROM incidents" + (f" WHERE status='{status}'" if status else "") + " ORDER BY created_at DESC"
    r=con.execute(q).fetchall(); con.close(); return [dict(x) for x in r]
def get_changes(): con=db(); r=con.execute("SELECT * FROM changes ORDER BY created_at DESC").fetchall(); con.close(); return [dict(x) for x in r]
def get_auto_actions(): con=db(); r=con.execute("SELECT * FROM autonomous_actions ORDER BY created_at DESC").fetchall(); con.close(); return [dict(x) for x in r]
def save_device(h,ip,v,u,p,port,role,site): con=db(); con.execute("INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site) VALUES(?,?,?,?,?,?,?,?)",(h,ip,v,u,p,port,role,site)); con.commit(); con.close()
def add_incident(title,desc,sev,devices,protocols,business_impact,affected_users,confidence): con=db(); con.execute("INSERT INTO incidents(title,description,severity,devices,protocols,business_impact,affected_users,confidence) VALUES(?,?,?,?,?,?,?,?)",(title,desc,sev,devices,protocols,business_impact,affected_users,confidence)); con.commit(); con.close()
init_db()

# ══════════════════════════════════════════════════════════
# CLAUDE AI ENGINE
# ══════════════════════════════════════════════════════════
NET_SYSTEM = """You are NetBrain AI — an AI-Native Autonomous Network Operating System.
You are NOT a chatbot. You are an intelligent operational AI embedded in every workflow.

Core capabilities:
- Deep networking expertise: BGP OSPF EIGRP IS-IS MPLS SRv6 VXLAN EVPN SD-WAN SASE Zero-Trust IPSec
- Vendors: Cisco Juniper Arista PaloAlto Fortinet Aruba Nokia Huawei Versa Zscaler
- Operational intelligence: RCA topology blast-radius change-risk compliance autonomous-remediation
- Business context: translate technical failures to business impact revenue risk SLA breach

Response style rules:
- Be specific. Name devices, IPs, protocols, commands.
- Always include CLI when relevant.
- Show confidence percentage for analysis.
- Explain WHY not just WHAT.
- Structure: Summary → Evidence → Root Cause → Business Impact → Recommended Actions → Rollback
- Adapt depth to persona (CCNA=explain everything, NOC=concise+actionable, Architect=deep+design)."""

PERSONAS = {
    "fresher": "Helping a networking student. Use simple language. Explain every term. Use analogies. Be encouraging. Show step-by-step. Visual descriptions.",
    "ccna":    "Helping CCNA engineer. Explain with context. Define acronyms inline. Show CLI with explanation. Guide troubleshooting steps.",
    "noc":     "Helping NOC engineer during operations. CONCISE. Lead with probable root cause immediately. Exact CLI commands. Rollback steps. Escalation path.",
    "architect":"Helping senior network architect. Expert level. Skip basics. Design trade-offs. Scalability HA redundancy. RFC references. BOM context.",
    "manager": "Helping operations manager. Business language. Avoid technical jargon. Focus on user impact revenue risk SLA performance decisions needed.",
    "security":"Helping security engineer. Threat context. Attack paths. Compliance. Zero Trust principles. SIEM correlation. Containment actions.",
}

KB = {
    "BGP":"BGP states: Idle→Connect→Active→OpenSent→OpenConfirm→Established. Active=TCP not established. Causes: ACL blocking 179, remote-as wrong, MD5 mismatch, update-source wrong. BGP hold-timer 180s default. BFD for sub-second. Best path: Weight>LocalPref>Originate>AS_PATH>MED>eBGP>IGP. Route reflector: iBGP no full-mesh. AS_PATH prepend for traffic engineering. Communities: no-export 65535:65281.",
    "OSPF":"States: Down→Init→2-Way→ExStart→Exchange→Loading→Full. ExStart stuck=MTU mismatch→ip ospf mtu-ignore. Full=healthy. DR/BDR: priority then RID. Priority 0=never DR. LSAs: 1=Router 2=Network 3=Summary 5=External 7=NSSA. Area 0=backbone. ABR connects areas. Hello 10s, Dead 40s. Must match both ends.",
    "VLAN":"Trunk not passing: show interfaces trunk → switchport trunk allowed vlan add. Native VLAN mismatch=broadcasts. STP: BLK→LIS→LRN→FWD. RSTP <1s. EtherChannel: match speed/duplex/VLAN. LACP active/passive. PortFast access only. BPDU Guard.",
    "SDWAN":"vManage+vBond+vSmart+vEdge. OMP=overlay routing. Colors=transport. App-aware routing: SLA per app. Direct cloud access=breakout for SaaS. TLOC=system-IP+color+encap. ZTP for branch onboarding.",
    "MPLS":"Label: 20-bit+3TC+1S+8TTL. LDP for IGP. RSVP-TE for explicit paths. L3VPN: VRF+RT+RD. L2VPN: VPWS p2p VPLS multipoint. SR: prefix-SID adj-SID no-LDP. SRv6: IPv6 as segments.",
    "SECURITY":"Zero Trust: never-trust always-verify. ZTNA=app-specific. SASE=SD-WAN+SSE. Microsegmentation=east-west. App-ID+User-ID+Content-ID. NAC 802.1X. MFA mandatory. BFD for path validation.",
    "DATACENTER":"Leaf-spine: ECMP no-STP. VXLAN UDP4789 VNI=24bit. EVPN: type2=MAC/IP type3=multicast type5=prefix. Symmetric IRB=anycast-GW. RoCE: PFC+ECN+DCQCN lossless for GPU.",
    "CLOUD":"AWS: VPC TGW Direct-Connect. Azure: VNet ExpressRoute VWAN. GCP: VPC Cloud-Interconnect. Hybrid: IPSec or dedicated. Kubernetes: CNI calico cilium flannel.",
    "WIRELESS":"CAPWAP: control+data tunnels. 802.11ax=WiFi6. RSSI-based roaming. RF: channel width TPC. WPA3. Wireless assurance: client health.",
}

def _get_key():
    try: return st.secrets.get("ANTHROPIC_API_KEY","")
    except: return os.environ.get("ANTHROPIC_API_KEY","")

def ai_call(messages, persona="noc", max_tokens=2000, stream=False):
    key = _get_key()
    if not key: return "⚠️ Set ANTHROPIC_API_KEY in Streamlit Cloud → App Settings → Secrets"
    if not CLAUDE_OK: return "⚠️ anthropic package missing"
    try:
        client = anthropic.Anthropic(api_key=key)
        sys = NET_SYSTEM + "\n\n" + PERSONAS.get(persona, PERSONAS["noc"])
        resp = client.messages.create(model="claude-sonnet-4-20250514", max_tokens=max_tokens, system=sys, messages=messages)
        return resp.content[0].text
    except Exception as e: return f"❌ API error: `{e}`"

def rag(query, n=3):
    global _col
    if RAG_OK and _cc and _emb:
        try:
            if _col is None:
                _col = _cc.get_or_create_collection("netbrain_v2", metadata={"hnsw:space":"cosine"})
                if _col.count() == 0:
                    for t,c in KB.items():
                        words=c.split(); chunks=[" ".join(words[i:i+150]) for i in range(0,len(words),120) if words[i:i+150]]
                        ids=[hashlib.md5(f"{t}_{i}".encode()).hexdigest() for i in range(len(chunks))]
                        embs=_emb.encode(chunks).tolist()
                        _col.add(ids=ids,documents=chunks,embeddings=embs,metadatas=[{"topic":t} for _ in chunks])
            emb=_emb.encode([query]).tolist()
            res=_col.query(query_embeddings=emb,n_results=min(n,_col.count()))
            return [(d,m) for d,m in zip(res["documents"][0],res["metadatas"][0])]
        except: pass
    q=query.lower(); scored=[]
    for t,c in KB.items():
        sc=sum(1 for w in q.split() if len(w)>3 and w in c.lower()); sc+=(5 if t.lower() in q else 0)
        if sc>0: scored.append((sc,t,c))
    scored.sort(reverse=True)
    return [(c[:300],{"topic":t}) for _,t,c in scored[:n]]

def nlp_extract(text):
    ents = {
        "ips": list(dict.fromkeys(re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}(?:\/\d{1,2})?\b', text))),
        "ifaces": list(dict.fromkeys(re.findall(r'\b(?:Gi|Fa|Te|Hu|Et|xe|ge|Lo|Tu)\d+(?:[\/\-]\d+){0,3}\b', text, re.I))),
        "vlans": list(dict.fromkeys(re.findall(r'\bVLAN\s*\d+\b', text, re.I))),
        "as_nums": list(dict.fromkeys(re.findall(r'\bAS\s*\d+\b', text, re.I))),
        "protos": [p for p in ["BGP","OSPF","EIGRP","MPLS","EVPN","VXLAN","STP","BFD","IPSec","SD-WAN","SASE","ZTNA","SRv6"] if p.upper() in text.upper()],
        "vendors": [v for v in ["Cisco","Juniper","Arista","Palo Alto","Fortinet","Aruba","Zscaler","Versa","Nokia","Huawei"] if v.lower() in text.lower()],
        "devices": list(dict.fromkeys(re.findall(r'\b[A-Z]{2,}[-_][A-Z0-9]{2,}[-_][A-Z0-9]+\b', text))),
        "urgency": "critical" if any(w in text.lower() for w in ["down","outage","critical","p1","production","customers","revenue"]) else "high" if any(w in text.lower() for w in ["flapping","degraded","slow","latency","p2"]) else "normal",
        "intent": next((i for i,kws in {
            "incident_rca":["flapping","down","failing","outage","broken","not working","lost"],
            "design":["design","architect","plan","build","create network","topology"],
            "change_request":["change","upgrade","modify","update","add vlan","new config"],
            "query_devices":["show","check","all devices","across","query","fetch"],
            "explain":["explain","what is","how does","why","difference","understand"],
            "generate_config":["generate","write config","create config","configure"],
            "security":["threat","attack","breach","lateral","vulnerability","CVE"],
        }.items() if any(k in text.lower() for k in kws)), "general"),
        "persona_hint": "architect" if any(w in text.lower() for w in ["srv6","evpn","vxlan","bfd","lsdb","route-reflector","sr-mpls"]) else "fresher" if any(w in text.lower() for w in ["what is","explain","how does","beginner","simple","learn"]) else None
    }
    return ents

def pipeline(query, persona="noc", history=None, workspace_context=None):
    ents = nlp_extract(query)
    ep = ents.get("persona_hint") or persona
    ctx_parts = []
    if ents["ips"]: ctx_parts.append(f"IPs:{','.join(ents['ips'])}")
    if ents["protos"]: ctx_parts.append(f"Protocols:{','.join(ents['protos'])}")
    if ents["devices"]: ctx_parts.append(f"Devices:{','.join(ents['devices'])}")
    if ents["vlans"]: ctx_parts.append(f"VLANs:{','.join(ents['vlans'])}")
    enriched = f"[Context: {' | '.join(ctx_parts)}]\n[Intent: {ents['intent']}]\n[Urgency: {ents['urgency']}]\n\n{query}" if ctx_parts else query
    chunks = rag(query, 3)
    incidents = get_incidents("active")
    similar = [i for i in incidents if any(p.lower() in f"{i['title']} {i.get('protocols','')}".lower() for p in ents["protos"])][:1]
    msgs = []
    if chunks:
        kb_text = "\n\n".join(f"[{m.get('topic','KB')}] {c}" for c,m in chunks)
        msgs += [{"role":"user","content":f"KNOWLEDGE BASE:\n{kb_text}"},{"role":"assistant","content":"Knowledge reviewed."}]
    if similar:
        inc = similar[0]
        msgs += [{"role":"user","content":f"ACTIVE INCIDENT CONTEXT:\nTitle:{inc['title']}\nRCA:{inc.get('root_cause','')}\nBusiness:{inc.get('business_impact','')}\nConfidence:{inc.get('confidence',0)}%"},
                 {"role":"assistant","content":"Incident context loaded."}]
    if workspace_context:
        msgs += [{"role":"user","content":f"WORKSPACE CONTEXT:\n{workspace_context}"},{"role":"assistant","content":"Workspace context understood."}]
    if history: msgs += history[-6:]
    msgs.append({"role":"user","content":enriched})
    response = ai_call(msgs, ep, 2000)
    return {"response":response,"entities":ents,"persona_used":ep,"rag_topics":[m.get("topic","") for _,m in chunks],"similar_incidents":[i["title"] for i in similar]}

def run_mdq(query, persona="noc"):
    devices=get_devices(); results=[]
    NL_CMD={"bgp summary":{"cisco_ios":"show ip bgp summary","cisco_ios_xr":"show bgp all summary","juniper_junos":"show bgp summary","arista_eos":"show bgp summary"},
             "ospf neighbor":{"cisco_ios":"show ip ospf neighbor","cisco_ios_xr":"show ospf neighbor","juniper_junos":"show ospf neighbor","arista_eos":"show ip ospf neighbor"},
             "interface":{"cisco_ios":"show interfaces status","cisco_ios_xr":"show interfaces brief","juniper_junos":"show interfaces terse","arista_eos":"show interfaces status"},
             "cpu":{"cisco_ios":"show processes cpu sorted","cisco_ios_xr":"show processes cpu","juniper_junos":"show chassis routing-engine","arista_eos":"show processes top once"},
             "vlan":{"cisco_ios":"show vlan brief","cisco_ios_xr":"show vlan","juniper_junos":"show vlans","arista_eos":"show vlan"},
             "routing table":{"cisco_ios":"show ip route","cisco_ios_xr":"show route ipv4","juniper_junos":"show route","arista_eos":"show ip route"}}
    def resolve(q,v):
        for kw,vm in NL_CMD.items():
            if kw in q.lower(): return vm.get(v,vm.get("cisco_ios","show version"))
        return "show version" if not q.strip().startswith("show") else q.strip()
    def sim(dev,cmd):
        ip=dev.get("ip",""); h=dev.get("hostname","")
        if "bgp" in cmd and "summary" in cmd: out=f"BGP router id {ip}\nNeighbor    AS     Up/Down  State\n10.0.0.1  65001  5d02h14  Established/142\n10.0.1.1  65002  0d00h04  Active\n10.0.2.1  65003  2d11h22  Established/87"
        elif "ospf" in cmd: out="Neighbor ID  Pri  State     Interface\n192.168.1.1    1  FULL/DR   Gi0/0\n192.168.1.2    1  FULL/BDR  Gi0/1\n192.168.1.3    0  EXSTART   Gi0/2"
        elif "cpu" in cmd: out=f"CPU 5sec {dev.get('cpu',0)}%, 1min {max(0,dev.get('cpu',0)-13)}%"
        elif "vlan" in cmd: out="VLAN  Name         Status\n1     default      active\n100   FINANCE      active\n120   BRANCH-HYD   suspend"
        elif "interface" in cmd: out="Interface  Status  Protocol\nGi0/0      up      up\nGi0/1      up      up\nGi0/2      down    down"
        else: out=f"Hostname:{h}\nUptime:127d 4h"
        return {"status":"ok","output":out,"simulated":True}
    def qone(dev):
        cmd=resolve(query,dev.get("vendor","cisco_ios"))
        out=sim(dev,cmd)
        results.append({**{k:dev.get(k,"") for k in ["hostname","ip","vendor","role","site","status"]}, "command":cmd, **out})
    threads=[threading.Thread(target=qone,args=(d,)) for d in devices]
    for t in threads: t.start()
    for t in threads: t.join(timeout=15)
    ctx="\n\n".join(f"=== {r['hostname']} ({r['ip']}) | {r['vendor']} | {r['role']} ===\nCMD:{r['command']}\n{r['output']}" for r in results)
    synth=ai_call([{"role":"user","content":f'Query:"{query}"\n{len(results)} devices:\n{ctx}\n\n1)DIRECT ANSWER 2)ANOMALIES per device 3)RISKS 4)RECOMMENDED ACTIONS. Be specific with hostnames.'}],persona)
    return {"results":results,"synthesis":synth,"count":len(results)}

# ══════════════════════════════════════════════════════════
# DESIGN SYSTEM — Light Professional + Alive
# ══════════════════════════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=DM+Mono:wght@400;500&family=Fraunces:wght@600;700;900&display=swap');

/* ── Reset & Base ── */
*{box-sizing:border-box}
html,body,[class*="css"]{font-family:'DM Sans',sans-serif!important;font-size:14px}
.stApp{background:#f0f2f6!important}
#MainMenu,footer,header{visibility:hidden}

/* ── Top Command Bar ── */
.topbar{
  background:linear-gradient(135deg,#0a1628 0%,#0f2042 100%);
  padding:0 24px;height:56px;display:flex;align-items:center;gap:16px;
  position:sticky;top:0;z-index:1000;
  box-shadow:0 2px 20px rgba(0,0,0,.3);
}
.logo-mark{font-size:22px;filter:drop-shadow(0 0 8px rgba(59,116,208,.6))}
.logo-name{font-family:'Fraunces',serif;font-size:18px;font-weight:900;color:#fff;letter-spacing:-.3px}
.logo-ver{font-size:10px;color:rgba(255,255,255,.35);font-family:'DM Mono',monospace;letter-spacing:.5px}
.tb-search{
  flex:1;max-width:560px;height:36px;
  background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);
  border-radius:10px;display:flex;align-items:center;gap:8px;padding:0 14px;
  transition:.2s;cursor:text
}
.tb-search:focus-within{background:rgba(255,255,255,.13);border-color:rgba(59,116,208,.6);box-shadow:0 0 0 3px rgba(59,116,208,.15)}
.tb-search input{flex:1;background:none;border:none;outline:none;color:#fff;font-size:13px;font-family:'DM Sans',sans-serif}
.tb-search input::placeholder{color:rgba(255,255,255,.35)}
.tb-hint{font-size:11px;color:rgba(255,255,255,.2);font-family:'DM Mono',monospace;white-space:nowrap}
.tb-spacer{flex:1}

/* Status Chips */
.sys-chips{display:flex;gap:5px}
.sys-chip{font-size:10px;padding:3px 8px;border-radius:12px;font-family:'DM Mono',monospace;font-weight:600;cursor:default;display:flex;align-items:center;gap:4px}
.chip-ok{background:rgba(30,143,85,.2);color:#4ade80;border:1px solid rgba(30,143,85,.3)}
.chip-warn{background:rgba(251,191,36,.15);color:#fbbf24;border:1px solid rgba(251,191,36,.25)}
.chip-err{background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.25)}

/* Persona Switcher */
.persona-sw{display:flex;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);border-radius:8px;overflow:hidden;height:30px}
.p-btn{padding:0 11px;font-size:11px;font-weight:600;color:rgba(255,255,255,.4);cursor:pointer;height:100%;display:flex;align-items:center;gap:4px;border:none;background:none;transition:.15s;white-space:nowrap;font-family:'DM Sans',sans-serif}
.p-btn:hover{color:rgba(255,255,255,.75)}
.p-btn.active{background:rgba(255,255,255,.15);color:#fff}
.tb-avatar{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,#3b74d0,#0077cc);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;cursor:pointer;flex-shrink:0}

/* ── Workspace Grid ── */
.ws-shell{display:flex;min-height:calc(100vh - 56px)}
.ws-rail{
  width:64px;min-width:64px;background:#fff;border-right:1px solid #e2e8f0;
  display:flex;flex-direction:column;align-items:center;padding:12px 0;gap:4px;
  flex-shrink:0;
}
.rail-btn{
  width:44px;height:44px;border-radius:12px;display:flex;flex-direction:column;
  align-items:center;justify-content:center;cursor:pointer;transition:.15s;
  border:1px solid transparent;gap:3px;text-decoration:none;background:none;
}
.rail-btn:hover{background:#f1f5f9;border-color:#e2e8f0}
.rail-btn.active{background:#eff6ff;border-color:#bfdbfe}
.rail-ico{font-size:18px;line-height:1}
.rail-lbl{font-size:8px;color:#94a3b8;font-family:'DM Mono',monospace;line-height:1;text-align:center}
.rail-btn.active .rail-lbl{color:#3b82f6}
.rail-badge{
  position:absolute;top:-2px;right:-2px;width:14px;height:14px;
  border-radius:50%;background:#ef4444;color:#fff;
  font-size:8px;display:flex;align-items:center;justify-content:center;
  font-family:'DM Mono',monospace;font-weight:700;border:1.5px solid #fff
}
.rail-sep{width:28px;height:1px;background:#e2e8f0;margin:4px 0}
.ws-main{flex:1;overflow:hidden;display:flex;flex-direction:column}
.ws-content{flex:1;overflow-y:auto;padding:20px}
.ws-content::-webkit-scrollbar{width:4px}
.ws-content::-webkit-scrollbar-thumb{background:#e2e8f0;border-radius:4px}

/* ── AI Command Input ── */
.ai-cmd-bar{
  background:#fff;border:1.5px solid #e2e8f0;border-radius:14px;
  padding:14px 16px;margin-bottom:20px;
  box-shadow:0 2px 12px rgba(0,0,0,.06);
  transition:.2s;
}
.ai-cmd-bar:focus-within{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,.1)}
.ai-cmd-label{font-size:10px;font-weight:600;color:#94a3b8;letter-spacing:1px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.ai-cmd-label::before{content:'';width:6px;height:6px;border-radius:50%;background:#22c55e;animation:pulse-dot 2s infinite;display:inline-block}
@keyframes pulse-dot{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.6;transform:scale(.8)}}

/* ── Workspace Panels ── */
.ws-header{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:18px;gap:12px;flex-wrap:wrap}
.ws-title{font-family:'Fraunces',serif;font-size:22px;font-weight:700;color:#0f172a;line-height:1.2}
.ws-subtitle{font-size:13px;color:#64748b;margin-top:3px}

/* ── AI Insight Bar (inline, not blocking) ── */
.ai-insight{
  background:linear-gradient(135deg,#f0f7ff 0%,#fff 100%);
  border:1px solid #bfdbfe;border-left:4px solid #3b82f6;
  border-radius:0 12px 12px 0;padding:12px 16px;
  margin-bottom:16px;
}
.ai-insight-hdr{font-size:10px;font-weight:700;color:#3b82f6;letter-spacing:1px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:5px;display:flex;align-items:center;gap:6px}
.ai-insight-body{font-size:13px;color:#1e293b;line-height:1.6}
.ai-insight-body strong{color:#1e40af}
.ai-insight-body code{font-family:'DM Mono',monospace;font-size:12px;background:#dbeafe;color:#1e40af;padding:1px 5px;border-radius:4px}
.ai-conf{font-size:11px;color:#64748b;margin-top:5px;font-family:'DM Mono',monospace}

/* ── Metric Cards ── */
.metrics-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px}
.metric-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px;box-shadow:0 1px 4px rgba(0,0,0,.05);position:relative;overflow:hidden;transition:.2s}
.metric-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.08);transform:translateY(-1px)}
.metric-card::after{content:'';position:absolute;bottom:0;left:0;right:0;height:3px}
.mc-green::after{background:linear-gradient(90deg,#22c55e,#16a34a)}.mc-red::after{background:linear-gradient(90deg,#ef4444,#dc2626)}.mc-amber::after{background:linear-gradient(90deg,#f59e0b,#d97706)}.mc-blue::after{background:linear-gradient(90deg,#3b82f6,#2563eb)}.mc-purple::after{background:linear-gradient(90deg,#8b5cf6,#7c3aed)}
.mc-lbl{font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.8px;font-family:'DM Mono',monospace;margin-bottom:6px}
.mc-val{font-family:'Fraunces',serif;font-size:28px;font-weight:700;line-height:1;margin-bottom:4px}
.mc-meta{font-size:12px;color:#94a3b8}
.mc-trend-up{color:#22c55e}.mc-trend-dn{color:#ef4444}.mc-trend-ne{color:#94a3b8}
.mc-icon{position:absolute;right:14px;top:14px;font-size:20px;opacity:.12}
.mc-green .mc-val{color:#15803d}.mc-red .mc-val{color:#b91c1c}.mc-amber .mc-val{color:#92400e}.mc-blue .mc-val{color:#1e40af}.mc-purple .mc-val{color:#5b21b6}

/* ── Incident War Room ── */
.warroom{background:#fff;border:1px solid #fee2e2;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(239,68,68,.1);margin-bottom:20px}
.warroom-hdr{background:linear-gradient(135deg,#7f1d1d,#991b1b);padding:16px 20px;display:flex;align-items:center;gap:12px}
.warroom-pulse{width:10px;height:10px;border-radius:50%;background:#fca5a5;animation:pulse-dot 1s infinite;flex-shrink:0}
.warroom-title{font-family:'Fraunces',serif;font-size:15px;font-weight:700;color:#fff;flex:1}
.warroom-body{padding:0}
.warroom-section{padding:14px 20px;border-bottom:1px solid #fef2f2}
.warroom-section:last-child{border-bottom:none}
.ws-row{display:flex;align-items:flex-start;gap:12px}
.ws-icon{width:30px;height:30px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;flex-shrink:0}
.ws-data{flex:1;font-size:13px;color:#1e293b;line-height:1.6}
.ws-label{font-size:10px;font-weight:700;color:#94a3b8;letter-spacing:.8px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:2px}

/* ── Device Status Grid ── */
.device-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:20px}
.dev-card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px;cursor:pointer;transition:.15s;position:relative}
.dev-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.1);transform:translateY(-1px);border-color:#93c5fd}
.dev-status-bar{position:absolute;top:0;left:0;right:0;height:3px;border-radius:10px 10px 0 0}
.status-up .dev-status-bar{background:linear-gradient(90deg,#22c55e,#16a34a)}
.status-warn .dev-status-bar{background:linear-gradient(90deg,#f59e0b,#d97706)}
.status-critical .dev-status-bar{background:linear-gradient(90deg,#ef4444,#dc2626);animation:blink-bar 1.5s infinite}
@keyframes blink-bar{0%,100%{opacity:1}50%{opacity:.5}}
.dev-hostname{font-family:'DM Mono',monospace;font-size:12px;font-weight:600;color:#0f172a;margin-top:4px}
.dev-role{font-size:11px;color:#64748b;margin:2px 0}
.dev-site{font-size:10px;color:#94a3b8;font-family:'DM Mono',monospace}
.dev-metrics{display:flex;gap:8px;margin-top:8px}
.dev-metric{flex:1;text-align:center}
.dm-val{font-family:'DM Mono',monospace;font-size:13px;font-weight:600}
.dm-lbl{font-size:9px;color:#94a3b8;text-transform:uppercase;letter-spacing:.5px}
.dm-val.high{color:#ef4444}.dm-val.warn{color:#f59e0b}.dm-val.ok{color:#22c55e}
.dev-ai-badge{
  background:#eff6ff;border:1px solid #bfdbfe;border-radius:6px;
  padding:3px 7px;font-size:10px;color:#1d4ed8;font-family:'DM Mono',monospace;
  margin-top:6px;display:inline-flex;align-items:center;gap:3px
}

/* ── Knowledge Graph Node ── */
.kg-node{
  background:#fff;border:1.5px solid #e2e8f0;border-radius:12px;padding:14px;
  cursor:pointer;transition:.2s;position:relative;
}
.kg-node:hover{border-color:#93c5fd;box-shadow:0 4px 20px rgba(59,130,246,.12);transform:translateY(-2px)}
.kg-node.selected{border-color:#3b82f6;background:#eff6ff;box-shadow:0 0 0 3px rgba(59,130,246,.15)}
.kg-type{font-size:9px;font-weight:700;color:#94a3b8;letter-spacing:1px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:4px}
.kg-name{font-size:13px;font-weight:600;color:#0f172a}
.kg-meta{font-size:11px;color:#64748b;margin-top:3px}

/* ── AI Chat Bubbles ── */
.chat-user{background:#1e40af;color:#fff;border-radius:14px 14px 2px 14px;padding:10px 14px;margin:4px 0;display:inline-block;max-width:80%;font-size:13px;line-height:1.6;box-shadow:0 2px 8px rgba(30,64,175,.2)}
.chat-ai{background:#fff;border:1px solid #e2e8f0;border-radius:14px 14px 14px 2px;padding:12px 16px;margin:4px 0;display:inline-block;max-width:88%;font-size:13px;line-height:1.65;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.ai-meta-row{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}
.ai-meta-pill{font-size:10px;padding:2px 7px;border-radius:10px;font-family:'DM Mono',monospace;font-weight:600;display:inline-flex;align-items:center;gap:3px}
.amp-rag{background:#e0f2fe;color:#0369a1}.amp-nlp{background:#ede9fe;color:#5b21b6}.amp-per{background:#dcfce7;color:#15803d}.amp-inc{background:#fef3c7;color:#92400e}

/* ── Timeline ── */
.timeline-item{display:flex;gap:14px;padding:10px 0;border-bottom:1px solid #f1f5f9;align-items:flex-start}
.timeline-item:last-child{border-bottom:none}
.tl-dot{width:28px;height:28px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:13px}
.tl-body{flex:1}
.tl-title{font-size:13px;font-weight:500;color:#0f172a;margin-bottom:2px}
.tl-meta{font-size:11px;color:#94a3b8;font-family:'DM Mono',monospace}
.tl-ai{font-size:12px;color:#1d4ed8;background:#eff6ff;border-radius:6px;padding:3px 8px;margin-top:4px;display:inline-block}
.tl-dot.critical{background:#fee2e2}.tl-dot.major{background:#fef3c7}.tl-dot.info{background:#e0f2fe}.tl-dot.ok{background:#dcfce7}.tl-dot.ai{background:#ede9fe}

/* ── Change Cards ── */
.change-card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:12px;cursor:pointer;transition:.15s}
.change-card:hover{box-shadow:0 4px 16px rgba(0,0,0,.08);border-color:#93c5fd}
.risk-bar{display:flex;align-items:center;gap:8px;margin-top:8px}
.risk-track{flex:1;height:6px;background:#f1f5f9;border-radius:4px;overflow:hidden}
.risk-fill{height:100%;border-radius:4px}
.risk-low .risk-fill{background:linear-gradient(90deg,#22c55e,#16a34a)}
.risk-medium .risk-fill{background:linear-gradient(90deg,#f59e0b,#d97706)}
.risk-high .risk-fill{background:linear-gradient(90deg,#ef4444,#dc2626)}
.risk-score{font-family:'DM Mono',monospace;font-size:12px;font-weight:700;width:30px;text-align:right}
.risk-low .risk-score{color:#15803d}.risk-medium .risk-score{color:#92400e}.risk-high .risk-score{color:#b91c1c}

/* ── Autonomous Ops ── */
.auto-action{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:12px;margin-bottom:8px;display:flex;gap:12px;align-items:flex-start}
.aa-status{width:32px;height:32px;border-radius:8px;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:15px}
.aa-exec{background:#dcfce7}.aa-pend{background:#fef3c7}.aa-fail{background:#fee2e2}
.aa-body{flex:1}
.aa-title{font-size:13px;font-weight:500;color:#0f172a;margin-bottom:3px}
.aa-meta{font-size:11px;color:#64748b;font-family:'DM Mono',monospace;margin-bottom:3px}
.aa-ai{font-size:11px;color:#6d28d9;background:#ede9fe;padding:2px 7px;border-radius:6px;display:inline-block}
.aa-conf{font-size:11px;font-family:'DM Mono',monospace;color:#94a3b8}

/* ── Buttons ── */
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:.15s;border:1.5px solid;font-family:'DM Sans',sans-serif;white-space:nowrap;text-decoration:none}
.btn-primary{background:#1e40af;border-color:#1e40af;color:#fff;box-shadow:0 2px 8px rgba(30,64,175,.25)}
.btn-primary:hover{background:#1d4ed8;border-color:#1d4ed8;box-shadow:0 4px 16px rgba(30,64,175,.35)}
.btn-secondary{background:#fff;border-color:#e2e8f0;color:#475569}
.btn-secondary:hover{border-color:#93c5fd;color:#1e40af}
.btn-danger{background:#fef2f2;border-color:#fecaca;color:#b91c1c}
.btn-success{background:#f0fdf4;border-color:#bbf7d0;color:#15803d}
.btn-sm{padding:5px 11px;font-size:12px}

/* ── Tags ── */
.tag{display:inline-flex;align-items:center;gap:3px;padding:2px 8px;border-radius:20px;font-size:11px;font-weight:600;font-family:'DM Mono',monospace}
.tag-red{background:#fee2e2;color:#b91c1c}.tag-amber{background:#fef3c7;color:#92400e}.tag-green{background:#dcfce7;color:#15803d}.tag-blue{background:#dbeafe;color:#1e40af}.tag-purple{background:#ede9fe;color:#5b21b6}.tag-slate{background:#f1f5f9;color:#475569}

/* ── Section Headers ── */
.sec-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;gap:8px}
.sec-title{font-size:14px;font-weight:700;color:#0f172a;display:flex;align-items:center;gap:6px}
.sec-line{flex:1;height:1px;background:#f1f5f9}

/* ── Cards ── */
.card{background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.05)}
.card-hdr{padding:14px 18px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;justify-content:space-between;gap:10px;background:#fff}
.card-title{font-size:13px;font-weight:700;color:#0f172a;display:flex;align-items:center;gap:7px}
.card-body{padding:16px 18px}

/* ── Topology SVG Wrapper ── */
.topo-wrap{background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;position:relative}
.topo-controls{display:flex;gap:6px;padding:10px 14px;border-bottom:1px solid #e2e8f0;background:#fff;flex-wrap:wrap;align-items:center}
.topo-layer-btn{padding:4px 10px;border-radius:16px;font-size:12px;font-weight:600;border:1.5px solid #e2e8f0;background:#fff;color:#64748b;cursor:pointer;transition:.12s;font-family:'DM Sans',sans-serif}
.topo-layer-btn.active{background:#1e40af;border-color:#1e40af;color:#fff}
.topo-layer-btn:hover:not(.active){border-color:#93c5fd;color:#1e40af}

/* ── Knowledge Graph Panel ── */
.kg-detail{background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:18px;box-shadow:0 4px 20px rgba(0,0,0,.08)}
.kg-detail-hdr{font-family:'Fraunces',serif;font-size:16px;font-weight:700;color:#0f172a;margin-bottom:14px;padding-bottom:10px;border-bottom:1px solid #f1f5f9}
.rel-item{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid #f8fafc;font-size:13px}
.rel-item:last-child{border-bottom:none}
.rel-arrow{color:#94a3b8;font-size:11px;font-family:'DM Mono',monospace}
.rel-node{background:#f1f5f9;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:600;color:#334155;font-family:'DM Mono',monospace;cursor:pointer}
.rel-node:hover{background:#dbeafe;color:#1e40af}
.rel-type{font-size:11px;color:#94a3b8;font-style:italic}

/* ── AI Design Studio ── */
.design-studio{background:linear-gradient(135deg,#f0f7ff 0%,#faf5ff 100%);border:1px solid #c7d2fe;border-radius:16px;padding:24px;margin-bottom:20px}
.studio-title{font-family:'Fraunces',serif;font-size:18px;font-weight:700;color:#1e1b4b;margin-bottom:6px}
.studio-sub{font-size:13px;color:#5b21b6;margin-bottom:20px}

/* ── Autonomous mode buttons ── */
.auto-modes{display:flex;gap:8px;margin-bottom:16px}
.auto-mode-btn{flex:1;padding:10px;border-radius:10px;border:1.5px solid;text-align:center;cursor:pointer;transition:.15s;font-family:'DM Sans',sans-serif}
.mode-human{border-color:#e2e8f0;background:#fff;color:#475569}
.mode-semi{border-color:#dbeafe;background:#eff6ff;color:#1e40af}
.mode-full{border-color:#e9d5ff;background:#faf5ff;color:#5b21b6}
.auto-mode-btn.selected{box-shadow:0 0 0 3px rgba(59,130,246,.2)}
.mode-full.selected{box-shadow:0 0 0 3px rgba(139,92,246,.2)}

/* ── Streamlit overrides ── */
div[data-testid="stButton"] button{border-radius:8px!important;font-weight:600!important;font-family:'DM Sans',sans-serif!important;transition:.15s!important}
div[data-testid="stTextInput"] input,div[data-testid="stTextArea"] textarea,div[data-testid="stSelectbox"]{border-radius:8px!important}
div[data-testid="stExpander"]{border-radius:10px!important}
.stAlert{border-radius:10px!important}
div.block-container{padding:0!important;max-width:100%!important}
section[data-testid="stSidebar"]{display:none!important}

/* ── Confidence indicator ── */
.conf-bar{display:flex;align-items:center;gap:8px;margin-top:6px}
.conf-track{flex:1;height:4px;background:#f1f5f9;border-radius:4px;overflow:hidden}
.conf-fill{height:100%;border-radius:4px}
.conf-high .conf-fill{background:linear-gradient(90deg,#22c55e,#16a34a)}
.conf-med .conf-fill{background:linear-gradient(90deg,#f59e0b,#d97706)}
.conf-low .conf-fill{background:linear-gradient(90deg,#ef4444,#dc2626)}
.conf-pct{font-family:'DM Mono',monospace;font-size:11px;font-weight:700;width:32px}
.conf-high .conf-pct{color:#15803d}.conf-med .conf-pct{color:#92400e}.conf-low .conf-pct{color:#b91c1c}

/* ── RAG source chips ── */
.rag-chip{display:inline-flex;align-items:center;gap:4px;padding:2px 7px;border-radius:6px;font-size:10px;font-family:'DM Mono',monospace;background:#e0f2fe;color:#0369a1;margin:2px}

@media(max-width:900px){
  .metrics-row{grid-template-columns:1fr 1fr}
  .device-grid{grid-template-columns:1fr 1fr}
  .ws-rail{display:none}
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════
def ss(k,v):
    if k not in st.session_state: st.session_state[k]=v
ss("workspace","operations")
ss("persona","noc")
ss("chat_msgs",[])
ss("chat_hist",[])
ss("incident_focus",None)
ss("kg_selected",None)
ss("auto_mode","human")
ss("mdq_res",None)
ss("design_output",None)
ss("workspace_context","")
ss("global_search","")
ss("nlp_live",{})

personas = ["fresher","ccna","noc","architect","manager","security"]
persona_labels = {"fresher":"🌱 Fresher","ccna":"🎓 CCNA","noc":"🖥 NOC","architect":"🏗 Architect","manager":"📊 Manager","security":"🔒 Security"}
workspaces = [
    ("operations","⚡","Operations","Command center"),
    ("incident","🚨","Incidents","War room"),
    ("topology","🗺","Topology","Knowledge graph"),
    ("troubleshoot","🔧","Diagnose","AI RCA engine"),
    ("change","📋","Changes","Safety engine"),
    ("autonomous","🤖","Autonomous","AI operations"),
    ("design","🏗","Design","AI design studio"),
    ("learn","📖","Learn","Adaptive learning"),
]

# ══════════════════════════════════════════════════════════
# TOP COMMAND BAR
# ══════════════════════════════════════════════════════════
def render_topbar():
    stat_claude = CLAUDE_OK and bool(_get_key())
    def chip(lbl,ok,sim=False):
        cls = "chip-ok" if ok else "chip-warn" if sim else "chip-err"
        dot = "●"
        return f'<span class="sys-chip {cls}">{dot} {lbl}</span>'

    st.markdown(f"""
    <div class="topbar">
      <div class="logo-mark">🧠</div>
      <div>
        <div class="logo-name">NetBrain AI</div>
        <div class="logo-ver">AUTONOMOUS NETWORK OS</div>
      </div>
      <div style="width:1px;height:28px;background:rgba(255,255,255,.1);margin:0 4px"></div>
      <div class="sys-chips">
        {chip(f"Claude {'ON' if stat_claude else 'OFF'}", stat_claude)}
        {chip("SSH ⚡sim", True, not NETMIKO_OK) if not NETMIKO_OK else chip("SSH LIVE", True)}
        {chip("NLP ~regex", True, True) if not SPACY_OK else chip("NLP spaCy", True)}
        {chip("RAG keyword", True, True) if not RAG_OK else chip("RAG vector", True)}
      </div>
      <div style="flex:1"></div>
    </div>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# WORKSPACE SHELL
# ══════════════════════════════════════════════════════════
def render_rail():
    active_incidents = len(get_incidents("active"))
    pending_changes = len([c for c in get_changes() if c["status"]=="pending"])
    pending_auto = len([a for a in get_auto_actions() if a["status"]=="pending_approval"])

    icons = {"operations":"⚡","incident":"🚨","topology":"🗺","troubleshoot":"🔧","change":"📋","autonomous":"🤖","design":"🏗","learn":"📖"}
    labels = {"operations":"OPS","incident":"WAR","topology":"GRAPH","troubleshoot":"RCA","change":"CHG","autonomous":"AUTO","design":"DESIGN","learn":"LEARN"}
    badges = {"incident": active_incidents if active_incidents > 0 else None, "change": pending_changes if pending_changes > 0 else None, "autonomous": pending_auto if pending_auto > 0 else None}

    rail_html = '<div class="ws-rail">'
    for ws_id, icon, _, _ in workspaces:
        active_cls = "active" if st.session_state.workspace == ws_id else ""
        badge = badges.get(ws_id)
        badge_html = f'<span class="rail-badge">{badge}</span>' if badge else ""
        rail_html += f'<div class="rail-btn {active_cls}" style="position:relative" title="{labels[ws_id]}">{badge_html}<div class="rail-ico">{icon}</div><div class="rail-lbl">{labels[ws_id]}</div></div>'
        if ws_id in ["incident","change","design"]:
            rail_html += '<div class="rail-sep"></div>'
    rail_html += '</div>'

    # Render rail with Streamlit columns for click handling
    with st.container():
        cols = st.columns([1,9])
        with cols[0]:
            st.markdown("<br>", unsafe_allow_html=True)
            for ws_id, icon, label, _ in workspaces:
                badge = badges.get(ws_id, 0) or ""
                btn_label = f"{icon} {badge}" if badge else icon
                if st.button(btn_label, key=f"rail_{ws_id}", help=label, use_container_width=True):
                    st.session_state.workspace = ws_id
                    st.rerun()

# ══════════════════════════════════════════════════════════
# HELPER COMPONENTS
# ══════════════════════════════════════════════════════════
def ai_insight(label, text, confidence=None, sources=None):
    conf_html = ""
    if confidence:
        cls = "conf-high" if confidence>=80 else "conf-med" if confidence>=60 else "conf-low"
        conf_html = f'<div class="conf-bar {cls}"><span class="conf-pct">{confidence}%</span><div class="conf-track"><div class="conf-fill" style="width:{confidence}%"></div></div><span style="font-size:11px;color:#94a3b8">AI Confidence</span></div>'
    src_html = ""
    if sources:
        src_html = "<div style='margin-top:5px'>" + "".join(f'<span class="rag-chip">📚 {s}</span>' for s in sources if s) + "</div>"
    st.markdown(f"""<div class="ai-insight">
      <div class="ai-insight-hdr">🧠 {label}</div>
      <div class="ai-insight-body">{text}</div>
      {conf_html}{src_html}
    </div>""", unsafe_allow_html=True)

def metric_card(label, value, meta, color="blue", trend=None, icon=""):
    trend_html = f'<span class="mc-trend-{"up" if trend=="up" else "dn" if trend=="dn" else "ne"}">{" ↑" if trend=="up" else " ↓" if trend=="dn" else ""}</span>' if trend else ""
    st.markdown(f"""<div class="metric-card mc-{color}">
      <div class="mc-icon">{icon}</div>
      <div class="mc-lbl">{label}</div>
      <div class="mc-val">{value}{trend_html}</div>
      <div class="mc-meta">{meta}</div>
    </div>""", unsafe_allow_html=True)

def render_msg(role, content, meta=None):
    if role == "user":
        st.markdown(f'<div style="text-align:right;margin:6px 0"><span class="chat-user">{content}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="margin:6px 0"><span class="chat-ai">{content}</span></div>', unsafe_allow_html=True)
        if meta:
            pills = ""
            if meta.get("persona_used"): pills += f'<span class="ai-meta-pill amp-per">👤 {meta["persona_used"]}</span>'
            if meta.get("rag_topics"):   pills += "".join(f'<span class="ai-meta-pill amp-rag">📚 {t}</span>' for t in meta["rag_topics"][:2] if t)
            if meta.get("similar_incidents"): pills += f'<span class="ai-meta-pill amp-inc">💡 {meta["similar_incidents"][0][:30]}</span>'
            ents = meta.get("entities",{})
            if ents.get("protos"): pills += f'<span class="ai-meta-pill amp-nlp">🧬 {", ".join(ents["protos"][:3])}</span>'
            if pills: st.markdown(f'<div class="ai-meta-row">{pills}</div>', unsafe_allow_html=True)

def go_chat(prompt, workspace="troubleshoot", ctx=""):
    st.session_state.chat_msgs.append({"role":"user","content":prompt,"meta":None})
    with st.spinner("🧠 Reasoning…"):
        r = pipeline(prompt, st.session_state.persona, st.session_state.chat_hist, ctx or st.session_state.workspace_context)
    st.session_state.chat_msgs.append({"role":"assistant","content":r["response"],"meta":r})
    st.session_state.chat_hist += [{"role":"user","content":prompt},{"role":"assistant","content":r["response"]}]
    st.session_state.workspace = workspace
    st.rerun()

def sec_header(title, subtitle=None):
    sub = f'<div style="font-size:12px;color:#64748b;margin-top:2px">{subtitle}</div>' if subtitle else ""
    st.markdown(f"""<div style="margin-bottom:16px">
      <div style="font-family:Fraunces,serif;font-size:20px;font-weight:700;color:#0f172a">{title}</div>{sub}
    </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# RENDER TOPBAR
# ══════════════════════════════════════════════════════════
render_topbar()

# ══════════════════════════════════════════════════════════
# PERSONA SELECTOR — horizontal below topbar
# ══════════════════════════════════════════════════════════
p_icons = {"fresher":"🌱","ccna":"🎓","noc":"🖥","architect":"🏗","manager":"📊","security":"🔒"}
p_cols = st.columns(len(personas) + 2)
with p_cols[0]:
    st.markdown("<div style='font-size:11px;color:#94a3b8;font-weight:600;padding-top:8px;font-family:DM Mono,monospace'>PERSONA</div>",unsafe_allow_html=True)
for i, p in enumerate(personas):
    with p_cols[i+1]:
        is_active = st.session_state.persona == p
        btn_style = "primary" if is_active else "secondary"
        if st.button(f"{p_icons[p]} {p.title()}", key=f"persona_{p}", use_container_width=True, type="primary" if is_active else "secondary"):
            st.session_state.persona = p
            st.rerun()

st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# WORKSPACE NAV — horizontal tabs
# ══════════════════════════════════════════════════════════
ws_cols = st.columns(len(workspaces))
for i, (ws_id, icon, label, subtitle) in enumerate(workspaces):
    with ws_cols[i]:
        active_incidents = len(get_incidents("active")) if ws_id == "incident" else 0
        btn_lbl = f"{icon} {label}" + (f" ({active_incidents})" if active_incidents > 0 else "")
        if st.button(btn_lbl, key=f"ws_{ws_id}", use_container_width=True,
                     type="primary" if st.session_state.workspace == ws_id else "secondary"):
            st.session_state.workspace = ws_id
            st.rerun()

st.markdown("<div style='height:2px;background:#f1f5f9;margin:8px 0'></div>", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════
# GLOBAL AI COMMAND BAR
# ══════════════════════════════════════════════════════════
with st.container():
    st.markdown('<div class="ai-cmd-bar"><div class="ai-cmd-label">AI Copilot — Ask anything about your network</div></div>', unsafe_allow_html=True)
    gi, gb, gsel = st.columns([0.72, 0.12, 0.16])
    with gi:
        global_q = st.text_input("", placeholder="'Why is BGP unstable?' · 'Design SD-WAN 50 branches' · 'Show all devices with OSPF issues' · 'Simulate PE-MUM-01 failure'",
                                  label_visibility="collapsed", key="global_input")
    with gb:
        if st.button("⚡ Ask AI", use_container_width=True, type="primary", key="global_ask"):
            if global_q.strip():
                ents = nlp_extract(global_q)
                target_ws = {"incident_rca":"troubleshoot","design":"design","change_request":"change","query_devices":"operations","security":"incident"}.get(ents.get("intent",""), "troubleshoot")
                go_chat(global_q, target_ws)
    with gsel:
        sample_q = st.selectbox("", ["Quick query…","Why is BGP flapping on PE-MUM-01?","Show all devices with issues","Design enterprise campus 3000 users","What happens if CORE-RTR-01 fails?","Explain OSPF DR election","Generate BGP config Cisco IOS-XR","Simulate firmware upgrade risk","Find security gaps in my network","VLAN 100 users cannot reach internet"], label_visibility="collapsed", key="sample_sel")
        if sample_q != "Quick query…" and sample_q:
            ents = nlp_extract(sample_q)
            go_chat(sample_q, "troubleshoot")

# ══════════════════════════════════════════════════════════
# WORKSPACES
# ══════════════════════════════════════════════════════════
ws = st.session_state.workspace

# ─────────────────────── OPERATIONS WORKSPACE ─────────────
if ws == "operations":
    sec_header("⚡ Operations Command Center", "Real-time network intelligence · AI-embedded · Contextual workflows")

    # AI operational pulse
    ai_insight("Operational Intelligence — Real-time",
        "<strong>2 active incidents</strong> — BGP flap PE-MUM-01 (<strong>87% confidence: ISP withdrawal</strong>) + SW-ACC-14 interface down (<strong>94% confidence: physical failure</strong>). "
        "<strong>CORE-RTR-01 CPU at 88%</strong> — correlates with BGP SPF recalculation. "
        "<strong>Autonomous action pending:</strong> BGP hold-timer increase awaiting your approval.",
        confidence=87, sources=["BGP","OSPF","Incident Memory"])

    # Metrics
    mc = st.columns(5)
    with mc[0]: metric_card("Devices Online","831","of 847 · 16 degraded","green","dn","✅")
    with mc[1]: metric_card("Active Incidents","2","BGP + Interface","red",None,"🔴")
    with mc[2]: metric_card("BGP Sessions","248","247 up · 1 active","blue","dn","🔄")
    with mc[3]: metric_card("Auto Actions","3","1 pending approval","amber",None,"🤖")
    with mc[4]: metric_card("Change Queue","3","1 high risk","purple",None,"📋")

    # Device grid
    st.markdown('<div class="sec-hdr"><div class="sec-title">🖧 Live Device Status — Click for AI Analysis</div><div class="sec-line"></div></div>', unsafe_allow_html=True)
    devices = get_devices()
    dev_cols = st.columns(4)
    for i, d in enumerate(devices):
        with dev_cols[i % 4]:
            status = d.get("status","up")
            cpu = d.get("cpu",0); mem = d.get("memory",0)
            cpu_cls = "high" if cpu >= 80 else "warn" if cpu >= 60 else "ok"
            mem_cls = "high" if mem >= 80 else "warn" if mem >= 60 else "ok"
            cpu_disp = f"{cpu}%" if cpu > 0 else "—"
            mem_disp = f"{mem}%" if mem > 0 else "—"
            ai_badge = ""
            if status == "critical": ai_badge = '<div class="dev-ai-badge">🧠 AI: Investigate now</div>'
            elif status == "warn": ai_badge = '<div class="dev-ai-badge">🧠 AI: Monitor closely</div>'
            st.markdown(f"""<div class="dev-card status-{status}">
              <div class="dev-status-bar"></div>
              <div class="dev-hostname">{d['hostname']}</div>
              <div class="dev-role">{d.get('role','')}</div>
              <div class="dev-site">📍 {d.get('site','')}</div>
              <div class="dev-metrics">
                <div class="dev-metric"><div class="dm-val {cpu_cls}">{cpu_disp}</div><div class="dm-lbl">CPU</div></div>
                <div class="dev-metric"><div class="dm-val {mem_cls}">{mem_disp}</div><div class="dm-lbl">MEM</div></div>
              </div>{ai_badge}
            </div>""", unsafe_allow_html=True)
            if st.button(f"AI Analysis", key=f"dev_ai_{d['hostname']}", use_container_width=True):
                ctx = f"Device: {d['hostname']} ({d['ip']}) | Role: {d['role']} | Site: {d['site']} | Status: {status} | CPU: {cpu}% | Memory: {mem}%"
                go_chat(f"Analyze {d['hostname']} ({d['ip']}). Status={status}, CPU={cpu}%, Memory={mem}%. Give health assessment, risks, and recommendations.", "troubleshoot", ctx)

    # Operational timeline
    col_t, col_a = st.columns([0.55, 0.45])
    with col_t:
        st.markdown('<div class="sec-hdr"><div class="sec-title">⏱ Operational Timeline</div><div class="sec-line"></div></div>', unsafe_allow_html=True)
        timeline = [
            ("critical","🔴","2m ago","BGP Session Flapping — PE-MUM-01","AS65002 · 3 flaps · 142 prefixes at risk","AI correlated with ISP route withdrawal — 87% confidence"),
            ("critical","🔴","8m ago","Interface Down — SW-ACC-14 Gi0/0/3","Access layer · VLAN 120 · 47 users impacted","AI: Physical failure. Check cable/SFP. 94% confidence."),
            ("major","🟡","14m ago","High CPU — CORE-RTR-01 (88%)","OSPF SPF recalculation detected","AI: Symptom of BGP flap. Will resolve when BGP stabilizes."),
            ("ai","🤖","18m ago","Autonomous Action: BFD enabled","PE-MUM-01 · Confidence 91%","Executed automatically. BGP detection now 300ms."),
            ("major","🟡","31m ago","OSPF Neighbor Timeout — Area 0","Segment 10.10.40.0/24 · DR election","AI: Related to BGP instability cascade."),
            ("ok","✅","2h ago","Change #3 Approved — BGP hold-timer","Approved by Architect · Risk score: 15/100","Scheduled for next maintenance window."),
        ]
        for sev, ico, time_ago, title, meta_txt, ai_txt in timeline:
            st.markdown(f"""<div class="timeline-item">
              <div class="tl-dot {sev}">{ico}</div>
              <div class="tl-body">
                <div class="tl-title">{title}</div>
                <div class="tl-meta">{time_ago} · {meta_txt}</div>
                <div class="tl-ai">🧠 {ai_txt}</div>
              </div>
            </div>""", unsafe_allow_html=True)

    with col_a:
        st.markdown('<div class="sec-hdr"><div class="sec-title">🤖 Pending AI Actions</div><div class="sec-line"></div></div>', unsafe_allow_html=True)
        auto_actions = get_auto_actions()
        for a in auto_actions:
            status = a.get("status","pending")
            cls = "aa-exec" if status=="executed" else "aa-pend" if "pending" in status else "aa-fail"
            ico = "✅" if status=="executed" else "⏳" if "pending" in status else "❌"
            conf = a.get("ai_confidence",0)
            conf_cls = "conf-high" if conf>=80 else "conf-med" if conf>=60 else "conf-low"
            st.markdown(f"""<div class="auto-action">
              <div class="aa-status {cls}">{ico}</div>
              <div class="aa-body">
                <div class="aa-title">{a['action']}</div>
                <div class="aa-meta">Device: {a.get('device','')} · Trigger: {a.get('trigger','')[:50]}</div>
                <div class="aa-ai">{a.get('result','')[:80]}</div>
                <div class="conf-bar {conf_cls}" style="margin-top:5px"><span class="conf-pct">{conf}%</span><div class="conf-track"><div class="conf-fill" style="width:{conf}%"></div></div></div>
              </div>
            </div>""", unsafe_allow_html=True)
            if "pending" in status:
                ac1, ac2 = st.columns(2)
                with ac1:
                    if st.button("✅ Approve", key=f"approve_{a['id']}", use_container_width=True):
                        con=db(); con.execute(f"UPDATE autonomous_actions SET status='executed' WHERE id={a['id']}"); con.commit(); con.close(); st.rerun()
                with ac2:
                    if st.button("❌ Reject", key=f"reject_{a['id']}", use_container_width=True):
                        con=db(); con.execute(f"UPDATE autonomous_actions SET status='rejected' WHERE id={a['id']}"); con.commit(); con.close(); st.rerun()

# ─────────────────────── INCIDENT WAR ROOM ─────────────────
elif ws == "incident":
    sec_header("🚨 Incident War Room", "AI-native incident operations · Root cause · Business impact · Remediation")

    incidents = get_incidents("active")
    resolved  = get_incidents("resolved")

    if not incidents:
        st.success("✅ No active incidents. All systems operational.")
    else:
        for inc in incidents:
            conf = inc.get("confidence", 0)
            conf_cls = "conf-high" if conf>=80 else "conf-med" if conf>=60 else "conf-low"
            sev_color = "#7f1d1d" if inc["severity"]=="critical" else "#78350f"
            sev_bg = "#991b1b" if inc["severity"]=="critical" else "#b45309"

            st.markdown(f"""<div class="warroom">
              <div class="warroom-hdr" style="background:linear-gradient(135deg,{sev_color},{sev_bg})">
                <div class="warroom-pulse"></div>
                <div class="warroom-title">🚨 {inc['title']}</div>
                <span style="font-size:10px;background:rgba(255,255,255,.15);padding:3px 8px;border-radius:10px;color:#fff;font-family:DM Mono,monospace">{inc['severity'].upper()} · ACTIVE</span>
              </div>
              <div class="warroom-body">
                <div class="warroom-section">
                  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px">
                    <div>
                      <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.8px;font-family:DM Mono,monospace;margin-bottom:5px">AI Root Cause</div>
                      <div style="font-size:13px;color:#0f172a;line-height:1.6">{inc.get('root_cause','Analyzing…')}</div>
                      <div class="conf-bar {conf_cls}" style="margin-top:6px"><span class="conf-pct">{conf}%</span><div class="conf-track"><div class="conf-fill" style="width:{conf}%"></div></div><span style="font-size:11px;color:#94a3b8">AI Confidence</span></div>
                    </div>
                    <div>
                      <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.8px;font-family:DM Mono,monospace;margin-bottom:5px">Business Impact</div>
                      <div style="font-size:13px;color:#0f172a;line-height:1.6">{inc.get('business_impact','Calculating…')}</div>
                      <div style="margin-top:5px"><span style="font-size:12px;font-weight:700;color:#b91c1c">{inc.get('affected_users',0)} users impacted</span></div>
                    </div>
                    <div>
                      <div style="font-size:10px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:.8px;font-family:DM Mono,monospace;margin-bottom:5px">AI Remediation</div>
                      <div style="font-size:13px;color:#0f172a;line-height:1.6">{inc.get('resolution','Generating…')}</div>
                    </div>
                  </div>
                </div>
              </div>
            </div>""", unsafe_allow_html=True)

            ic1, ic2, ic3, ic4 = st.columns(4)
            with ic1:
                if st.button(f"🧠 Deep AI RCA", key=f"inc_rca_{inc['id']}", use_container_width=True, type="primary"):
                    ctx = f"INCIDENT: {inc['title']}\nDevices: {inc['devices']}\nProtocols: {inc['protocols']}\nBusiness Impact: {inc['business_impact']}\nAffected Users: {inc['affected_users']}"
                    go_chat(f"Perform deep root cause analysis for incident: {inc['title']}. Devices: {inc.get('devices','')}. Protocols: {inc.get('protocols','')}. Give comprehensive RCA with evidence, blast radius, affected services, remediation steps, and rollback plan.", "incident", ctx)
            with ic2:
                if st.button("📊 Blast Radius", key=f"inc_blast_{inc['id']}", use_container_width=True):
                    go_chat(f"Analyze complete blast radius for: {inc['title']}. What devices, services, users, applications, and business processes are impacted? Show dependency chain.", "incident")
            with ic3:
                if st.button("🔧 Auto-Remediate", key=f"inc_rem_{inc['id']}", use_container_width=True):
                    go_chat(f"Generate autonomous remediation plan for: {inc['title']}. Include exact CLI commands, execution order, validation steps, and rollback procedure. Assess risk.", "incident")
            with ic4:
                if st.button("✅ Resolve", key=f"inc_resolve_{inc['id']}", use_container_width=True):
                    con=db(); con.execute(f"UPDATE incidents SET status='resolved', resolved_at=datetime('now') WHERE id={inc['id']}"); con.commit(); con.close(); st.rerun()
            st.markdown("---")

    # Recent resolved
    if resolved:
        with st.expander(f"📋 Resolved Incidents ({len(resolved)}) — Operational Memory"):
            for r in resolved[:5]:
                st.markdown(f"""<div class="timeline-item">
                  <div class="tl-dot ok">✅</div>
                  <div class="tl-body">
                    <div class="tl-title">{r['title']}</div>
                    <div class="tl-meta">RCA: {r.get('root_cause','')} · Fix: {r.get('resolution','')[:80]}</div>
                  </div>
                </div>""", unsafe_allow_html=True)

    # Add incident
    with st.expander("➕ Log New Incident"):
        f1, f2 = st.columns(2)
        with f1:
            new_title = st.text_input("Incident title")
            new_devices = st.text_input("Affected devices (comma-separated)")
            new_sev = st.selectbox("Severity", ["critical","major","minor"])
        with f2:
            new_desc = st.text_area("Description", height=80)
            new_impact = st.text_input("Business impact (users/apps affected)")
        if st.button("🚨 Log Incident + AI RCA", type="primary"):
            if new_title:
                add_incident(new_title, new_desc, new_sev, new_devices, "", new_impact, 0, 0)
                go_chat(f"New incident logged: {new_title}. Devices: {new_devices}. Description: {new_desc}. Perform immediate RCA and provide remediation steps.", "incident")

# ─────────────────────── TOPOLOGY WORKSPACE ─────────────────
elif ws == "topology":
    sec_header("🗺 Network Knowledge Graph", "Everything connected · Click any object for AI analysis · Relationship-driven intelligence")

    ai_insight("Topology Intelligence",
        "<strong>Dependency analysis:</strong> PE-MUM-01 is on the critical path for <strong>Mumbai branch SaaS access</strong> (340 users). "
        "SW-ACC-14 failure isolates <strong>Floor 2 users</strong> from DIST-SW-C. "
        "<strong>SPOF detected:</strong> FW-EDGE-01 has no redundant path — single point of failure for internet egress.",
        confidence=91, sources=["Topology","BGP","OSPF"])

    # Topology SVG
    st.markdown("""<div class="topo-wrap">
    <div class="topo-controls">
      <button class="topo-layer-btn active">🌐 All</button>
      <button class="topo-layer-btn">🔄 L3 Routing</button>
      <button class="topo-layer-btn">🔀 L2 Switching</button>
      <button class="topo-layer-btn">🔒 Security</button>
      <button class="topo-layer-btn">☁ Cloud</button>
      <button class="topo-layer-btn">📡 SD-WAN</button>
      <span style="margin-left:auto;font-size:11px;color:#94a3b8;font-family:DM Mono,monospace">Click devices for AI analysis →</span>
    </div>
    <div style="padding:16px;background:#f8fafc;min-height:460px">
    <svg viewBox="0 0 760 440" width="100%" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M2 2L8 5L2 8" fill="none" stroke="#94a3b8" stroke-width="1.5" stroke-linecap="round"/>
        </marker>
        <filter id="glow"><feGaussianBlur stdDeviation="2" result="coloredBlur"/><feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>

      <!-- Internet -->
      <ellipse cx="380" cy="32" rx="80" ry="22" fill="#f5f3ff" stroke="#8b5cf6" stroke-width="1.5" stroke-dasharray="5 3"/>
      <text x="380" y="36" text-anchor="middle" fill="#5b21b6" font-size="11" font-family="DM Mono">INTERNET / ISP</text>

      <!-- FW -->
      <line x1="380" y1="54" x2="380" y2="92" stroke="#8b5cf6" stroke-width="1.5"/>
      <rect x="338" y="92" width="84" height="30" rx="8" fill="#f5f3ff" stroke="#8b5cf6" stroke-width="1.5"/>
      <text x="380" y="108" text-anchor="middle" fill="#4c1d95" font-size="10" font-family="DM Mono" font-weight="600">FW-EDGE-01</text>
      <circle cx="414" cy="98" r="5" fill="#fbbf24"/><text x="424" y="102" fill="#92400e" font-size="8" font-family="DM Mono">SPOF</text>

      <!-- Core routers -->
      <line x1="380" y1="122" x2="180" y2="178" stroke="#e2e8f0" stroke-width="2"/>
      <line x1="380" y1="122" x2="380" y2="178" stroke="#e2e8f0" stroke-width="2.5"/>
      <line x1="380" y1="122" x2="580" y2="178" stroke="#e2e8f0" stroke-width="2"/>

      <!-- CORE-RTR-01 - WARNING -->
      <circle cx="180" cy="200" r="30" fill="#fef3c7" stroke="#f59e0b" stroke-width="2.5"/>
      <text x="180" y="196" text-anchor="middle" fill="#78350f" font-size="10" font-family="DM Mono" font-weight="600">CORE</text>
      <text x="180" y="208" text-anchor="middle" fill="#92400e" font-size="8" font-family="DM Mono">RTR-01</text>
      <text x="180" y="220" text-anchor="middle" fill="#d97706" font-size="8" font-family="DM Mono">CPU 88% ⚠</text>

      <!-- PE-MUM-01 - CRITICAL -->
      <circle cx="380" cy="200" r="30" fill="#fee2e2" stroke="#ef4444" stroke-width="2.5" filter="url(#glow)"/>
      <text x="380" y="194" text-anchor="middle" fill="#7f1d1d" font-size="10" font-family="DM Mono" font-weight="600">PE-MUM</text>
      <text x="380" y="205" text-anchor="middle" fill="#991b1b" font-size="8" font-family="DM Mono">01</text>
      <text x="380" y="218" text-anchor="middle" fill="#dc2626" font-size="8" font-family="DM Mono">BGP FLAP 🔴</text>

      <!-- PE-DEL-01 - UP -->
      <circle cx="580" cy="200" r="28" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="580" y="196" text-anchor="middle" fill="#1e3a8a" font-size="10" font-family="DM Mono" font-weight="600">PE-DEL</text>
      <text x="580" y="208" text-anchor="middle" fill="#1e40af" font-size="8" font-family="DM Mono">01 ✓</text>

      <!-- Distribution layer -->
      <line x1="180" y1="230" x2="120" y2="290" stroke="#e2e8f0" stroke-width="1.5"/>
      <line x1="180" y1="230" x2="280" y2="290" stroke="#e2e8f0" stroke-width="1.5"/>
      <line x1="380" y1="230" x2="380" y2="290" stroke="#f59e0b" stroke-width="2" stroke-dasharray="5 4"/>
      <line x1="580" y1="228" x2="500" y2="290" stroke="#e2e8f0" stroke-width="1.5"/>
      <line x1="580" y1="228" x2="660" y2="290" stroke="#e2e8f0" stroke-width="1.5"/>

      <rect x="88"  y="290" width="64" height="26" rx="6" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="120" y="306" text-anchor="middle" fill="#1e40af" font-size="9" font-family="DM Mono" font-weight="600">DIST-SW-W</text>
      <rect x="248" y="290" width="64" height="26" rx="6" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="280" y="306" text-anchor="middle" fill="#1e40af" font-size="9" font-family="DM Mono" font-weight="600">DIST-SW-E</text>
      <rect x="348" y="290" width="64" height="26" rx="6" fill="#fef3c7" stroke="#f59e0b" stroke-width="1.5"/>
      <text x="380" y="300" text-anchor="middle" fill="#78350f" font-size="9" font-family="DM Mono" font-weight="600">DIST-SW-C</text>
      <text x="380" y="311" text-anchor="middle" fill="#d97706" font-size="8" font-family="DM Mono">⚠ warn</text>
      <rect x="468" y="290" width="64" height="26" rx="6" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="500" y="306" text-anchor="middle" fill="#1e40af" font-size="9" font-family="DM Mono" font-weight="600">DIST-SW-N</text>
      <rect x="628" y="290" width="64" height="26" rx="6" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="660" y="306" text-anchor="middle" fill="#1e40af" font-size="9" font-family="DM Mono" font-weight="600">DIST-SW-S</text>

      <!-- Access layer -->
      <line x1="120" y1="316" x2="80"  y2="375" stroke="#f1f5f9" stroke-width="1"/>
      <line x1="120" y1="316" x2="160" y2="375" stroke="#f1f5f9" stroke-width="1"/>
      <line x1="280" y1="316" x2="240" y2="375" stroke="#f1f5f9" stroke-width="1"/>
      <line x1="280" y1="316" x2="320" y2="375" stroke="#f1f5f9" stroke-width="1"/>
      <line x1="380" y1="316" x2="380" y2="375" stroke="#f87171" stroke-width="1.5" stroke-dasharray="4 3"/>
      <line x1="500" y1="316" x2="480" y2="375" stroke="#f1f5f9" stroke-width="1"/>
      <line x1="660" y1="316" x2="640" y2="375" stroke="#f1f5f9" stroke-width="1"/>
      <line x1="660" y1="316" x2="700" y2="375" stroke="#f1f5f9" stroke-width="1"/>

      <rect x="60"  y="375" width="40" height="18" rx="4" fill="#f0fdf4" stroke="#22c55e" stroke-width="1"/>
      <text x="80"  y="387" text-anchor="middle" fill="#15803d" font-size="8" font-family="DM Mono">ACC-1</text>
      <rect x="140" y="375" width="40" height="18" rx="4" fill="#f0fdf4" stroke="#22c55e" stroke-width="1"/>
      <text x="160" y="387" text-anchor="middle" fill="#15803d" font-size="8" font-family="DM Mono">ACC-2</text>
      <rect x="220" y="375" width="40" height="18" rx="4" fill="#f0fdf4" stroke="#22c55e" stroke-width="1"/>
      <text x="240" y="387" text-anchor="middle" fill="#15803d" font-size="8" font-family="DM Mono">ACC-3</text>
      <rect x="300" y="375" width="40" height="18" rx="4" fill="#f0fdf4" stroke="#22c55e" stroke-width="1"/>
      <text x="320" y="387" text-anchor="middle" fill="#15803d" font-size="8" font-family="DM Mono">ACC-4</text>
      <!-- ACC-14 DOWN -->
      <rect x="360" y="375" width="40" height="18" rx="4" fill="#fef2f2" stroke="#ef4444" stroke-width="1.5"/>
      <text x="380" y="384" text-anchor="middle" fill="#b91c1c" font-size="8" font-family="DM Mono">ACC-14</text>
      <text x="380" y="394" text-anchor="middle" fill="#dc2626" font-size="7" font-family="DM Mono">↓DOWN</text>
      <rect x="460" y="375" width="40" height="18" rx="4" fill="#f0fdf4" stroke="#22c55e" stroke-width="1"/>
      <text x="480" y="387" text-anchor="middle" fill="#15803d" font-size="8" font-family="DM Mono">ACC-5</text>
      <rect x="620" y="375" width="40" height="18" rx="4" fill="#f0fdf4" stroke="#22c55e" stroke-width="1"/>
      <text x="640" y="387" text-anchor="middle" fill="#15803d" font-size="8" font-family="DM Mono">ACC-6</text>
      <rect x="680" y="375" width="40" height="18" rx="4" fill="#f0fdf4" stroke="#22c55e" stroke-width="1"/>
      <text x="700" y="387" text-anchor="middle" fill="#15803d" font-size="8" font-family="DM Mono">ACC-7</text>

      <!-- Legend -->
      <rect x="10" y="8" width="130" height="68" rx="6" fill="white" stroke="#e2e8f0" stroke-width="1"/>
      <circle cx="22" cy="22" r="5" fill="#fee2e2" stroke="#ef4444" stroke-width="1.5"/>
      <text x="32" y="26" fill="#374151" font-size="9" font-family="DM Mono">Critical/Down</text>
      <circle cx="22" cy="38" r="5" fill="#fef3c7" stroke="#f59e0b" stroke-width="1.5"/>
      <text x="32" y="42" fill="#374151" font-size="9" font-family="DM Mono">Warning</text>
      <circle cx="22" cy="54" r="5" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>
      <text x="32" y="58" fill="#374151" font-size="9" font-family="DM Mono">Healthy</text>
      <circle cx="22" cy="69" r="5" fill="#fbbf24" stroke="#f59e0b" stroke-width="1"/>
      <text x="32" y="73" fill="#374151" font-size="9" font-family="DM Mono">SPOF detected</text>
    </svg>
    </div></div>""", unsafe_allow_html=True)

    # Knowledge Graph — Object relationships
    st.markdown("---")
    st.markdown('<div class="sec-hdr"><div class="sec-title">🔗 Knowledge Graph — Select Object for Relationship Analysis</div><div class="sec-line"></div></div>', unsafe_allow_html=True)

    kg_items = [
        ("PE-MUM-01", "PE Router", "10.0.1.1 · Mumbai · BGP AS65001", "critical"),
        ("CORE-RTR-01", "Core Router", "10.0.0.1 · HQ · CPU 88%", "warn"),
        ("FW-EDGE-01", "Firewall", "192.168.1.1 · DMZ · SPOF", "warn"),
        ("SW-ACC-14", "Access Switch", "10.2.14.1 · HQ F2 · DOWN", "critical"),
        ("BGP — AS65002", "Protocol", "ISP peer · flapping · 142 routes", "critical"),
        ("VLAN 120", "Network", "VLAN 120 · HQ-Floor2 · 47 users", "critical"),
        ("Mumbai Branch", "Site", "340 users · SaaS degraded", "warn"),
        ("OSPF Area 0", "Protocol", "Backbone · SPF recalculating", "warn"),
    ]

    kg_cols = st.columns(4)
    for i, (name, obj_type, meta, status) in enumerate(kg_items):
        with kg_cols[i % 4]:
            selected = st.session_state.kg_selected == name
            border_color = "#3b82f6" if selected else ("#ef4444" if status=="critical" else "#f59e0b" if status=="warn" else "#e2e8f0")
            st.markdown(f"""<div class="kg-node {'selected' if selected else ''}" style="border-color:{border_color}">
              <div class="kg-type">{obj_type}</div>
              <div class="kg-name">{name}</div>
              <div class="kg-meta">{meta}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Analyze {name[:15]}", key=f"kg_{name}", use_container_width=True):
                st.session_state.kg_selected = name
                go_chat(f"Knowledge graph analysis for {name} ({obj_type}): Show all dependencies, affected services, related incidents, risks, operational history, and AI recommendations. Make it comprehensive.", "topology", f"Selected object: {name} | Type: {obj_type} | Status: {status}")

    if st.session_state.kg_selected:
        tq = st.text_input("Ask about topology", placeholder=f"Ask about {st.session_state.kg_selected} relationships…", key="topo_q")
        if st.button("🧠 Analyze Relationship", type="primary") and tq:
            go_chat(tq, "topology", f"Focus on: {st.session_state.kg_selected}")

# ─────────────────────── TROUBLESHOOT WORKSPACE ─────────────
elif ws == "troubleshoot":
    sec_header("🔧 AI Diagnosis Engine", "4-engine pipeline: NLP → RAG → Incident Memory → Claude reasoning")

    ai_insight("Diagnosis Pipeline",
        "<strong>NLP extracts entities</strong> from your description → <strong>RAG retrieves</strong> relevant runbooks → "
        "<strong>Incident memory</strong> surfaces past RCAs → <strong>Claude reasons</strong> across all context. "
        "Every answer shows evidence, confidence, and rollback options.",
        confidence=None)

    col_form, col_history = st.columns([0.52, 0.48])

    with col_form:
        st.markdown("**Describe the problem (plain English):**")
        problem = st.text_area("", placeholder="'BGP session keeps flapping to ISP since 2 hours ago. CPU on core router spiked to 88%. OSPF also went down briefly on segment 10.10.40.0/24. No config changes were made.'",
                               height=120, label_visibility="collapsed", key="trouble_desc")
        t1, t2 = st.columns(2)
        vendor = t1.selectbox("Vendor", ["Any","Cisco IOS/IOS-XR","Juniper JunOS","Arista EOS","Palo Alto","Fortinet"])
        sev = t2.selectbox("Severity", ["Unknown","🔴 P1 — Production down","🟡 P2 — Degraded","🟢 P3 — Low impact"])
        affected = st.text_input("Affected devices (if known)", placeholder="PE-MUM-01, CORE-RTR-01")
        if st.button("🧠 Run 4-Engine Diagnosis", type="primary", use_container_width=True) and problem:
            ctx = f"Vendor:{vendor} | Severity:{sev} | Affected:{affected}"
            go_chat(f"Diagnose this network issue:\n{problem}\n\nVendor:{vendor}, Severity:{sev}, Affected devices:{affected}\n\nProvide: 1)Root cause with evidence 2)AI confidence % 3)Business impact 4)Step-by-step fix commands 5)Rollback plan 6)Prevention", "troubleshoot", ctx)

        st.markdown("**Common issues — one click diagnosis:**")
        issues = [
            ("BGP stuck Active","BGP neighbor stuck in Active state, TCP session not establishing. Cisco IOS-XR."),
            ("OSPF EXSTART","OSPF adjacency stuck in EXSTART state, MTU mismatch likely. Give diagnosis and fix."),
            ("VLAN not passing","VLAN traffic not passing on trunk link. Could be STP or allowed VLAN issue."),
            ("SD-WAN failover broken","SD-WAN not failing over to backup ISP when primary link fails. Viptela."),
            ("MPLS packet loss","High packet loss on MPLS backbone. Need to isolate with LSP ping/traceroute."),
            ("IPSec VPN flapping","IPSec VPN tunnel keeps going down and up. DPD timeout issue."),
            ("STP loop","Spanning tree loop detected causing broadcast storm on Floor 2 VLAN."),
            ("BGP route missing","BGP route in table but not being advertised to peer. Route-map issue?"),
        ]
        ic = st.columns(2)
        for i, (lbl, prompt) in enumerate(issues):
            with ic[i % 2]:
                if st.button(lbl, key=f"issue_{lbl}", use_container_width=True):
                    go_chat(prompt, "troubleshoot")

    with col_history:
        st.markdown("**AI Diagnosis History:**")
        if not st.session_state.chat_msgs:
            st.info("💡 Diagnose an issue to see AI reasoning here. Every response shows evidence, confidence, and rollback options.")
        for msg in st.session_state.chat_msgs[-8:]:
            render_msg(msg["role"], msg["content"], msg.get("meta"))
        if st.session_state.chat_msgs:
            follow = st.text_input("Follow-up question", placeholder="'What if that doesn't fix it?' · 'Show me the CLI' · 'What's the rollback?'", key="ts_followup")
            if st.button("Ask", key="ts_ask") and follow:
                go_chat(follow, "troubleshoot")
            if st.button("🗑 Clear", key="ts_clear"):
                st.session_state.chat_msgs = []; st.session_state.chat_hist = []; st.rerun()

# ─────────────────────── CHANGE WORKSPACE ───────────────────
elif ws == "change":
    sec_header("📋 Change Safety Engine", "AI risk scoring · Digital twin pre-validation · Blast radius prediction · Rollback planning")

    ai_insight("Change Safety Intelligence",
        "<strong>3 changes in queue.</strong> IOS-XR firmware upgrade on CORE-RTR-01 scored <strong>72/100 risk — HIGH.</strong> "
        "AI recommends: digital twin test mandatory, maintenance window required, rollback plan pre-staged. "
        "<strong>BGP timer change scored 15/100 — LOW RISK</strong>. Safe to proceed during business hours.",
        confidence=88, sources=["Topology","Incident Memory","Firmware DB"])

    changes = get_changes()
    for chg in changes:
        risk = chg.get("ai_risk_score", 0)
        risk_cls = "risk-high" if risk >= 60 else "risk-medium" if risk >= 30 else "risk-low"
        risk_color = "#b91c1c" if risk >= 60 else "#92400e" if risk >= 30 else "#15803d"
        status_tag = {"approved":"tag-green","pending":"tag-amber","rejected":"tag-red"}.get(chg["status"],"tag-slate")

        with st.expander(f"{'🔴' if risk>=60 else '🟡' if risk>=30 else '🟢'} {chg['title']} — Risk: {risk}/100"):
            cc1, cc2 = st.columns([0.65, 0.35])
            with cc1:
                st.markdown(f"**Device:** `{chg['device']}` | **Type:** {chg['change_type']} | **By:** {chg.get('created_by','')}")
                st.markdown(f"**Description:** {chg['description']}")
                st.markdown(f"""<div class="risk-bar {risk_cls}">
                  <span style="font-size:12px;color:#64748b;font-family:DM Mono,monospace;width:80px">AI Risk Score</span>
                  <div class="risk-track" style="flex:1"><div class="risk-fill" style="width:{risk}%"></div></div>
                  <span class="risk-score">{risk}</span>
                </div>""", unsafe_allow_html=True)
                st.markdown(f"**AI Recommendation:** {chg.get('ai_recommendation','')}")
            with cc2:
                st.markdown(f'<span class="tag {status_tag}">{chg["status"].upper()}</span>', unsafe_allow_html=True)
                if st.button("🧠 Full AI Risk Analysis", key=f"chg_ai_{chg['id']}", use_container_width=True):
                    go_chat(f"Full AI risk analysis for change: {chg['title']}. Device: {chg['device']}. Description: {chg['description']}. Provide: 1)Risk breakdown 2)Blast radius 3)Dependencies affected 4)Rollback plan 5)Pre-change validation checklist 6)Post-change validation", "change")
                if st.button("👾 Digital Twin Test", key=f"chg_twin_{chg['id']}", use_container_width=True):
                    go_chat(f"Simulate this change in digital twin: {chg['title']} on {chg['device']}. Show: impact on topology, traffic, services, predicted downtime, and rollback trigger conditions.", "change")
                if chg["status"] == "pending":
                    ac1, ac2 = st.columns(2)
                    with ac1:
                        if st.button("✅ Approve", key=f"chg_app_{chg['id']}", use_container_width=True):
                            con=db(); con.execute(f"UPDATE changes SET status='approved' WHERE id={chg['id']}"); con.commit(); con.close(); st.rerun()
                    with ac2:
                        if st.button("❌ Reject", key=f"chg_rej_{chg['id']}", use_container_width=True):
                            con=db(); con.execute(f"UPDATE changes SET status='rejected' WHERE id={chg['id']}"); con.commit(); con.close(); st.rerun()

    # New change
    with st.expander("➕ Submit Change Request"):
        nc1, nc2 = st.columns(2)
        with nc1:
            chg_title = st.text_input("Change title")
            chg_device = st.text_input("Target device")
            chg_type = st.selectbox("Change type", ["config","firmware","vlan","routing","security","hardware"])
        with nc2:
            chg_desc = st.text_area("Description", height=80)
            chg_by = st.text_input("Requested by")
        if st.button("🧠 Submit + AI Risk Score", type="primary"):
            if chg_title and chg_device:
                go_chat(f"Assess risk for this change: '{chg_title}' on {chg_device}. Type: {chg_type}. Description: {chg_desc}. Provide: risk score /100, risk breakdown, blast radius, rollback plan, approval recommendation.", "change")

# ─────────────────────── AUTONOMOUS WORKSPACE ───────────────
elif ws == "autonomous":
    sec_header("🤖 Autonomous Operations Center", "AI actions · Approval workflows · Self-healing · Autonomous remediation")

    # Mode selector
    st.markdown("**Autonomy Level:**")
    mode_cols = st.columns(3)
    modes = [("human","👨‍💼 Human Approval","All AI actions require manual approval","mode-human"),
             ("semi","🤝 Semi-Autonomous","Low-risk actions auto-execute. High-risk need approval.","mode-semi"),
             ("full","⚡ Fully Autonomous","AI executes all actions. Human notified only.","mode-full")]
    for col, (mode_id, label, desc, cls) in zip(mode_cols, modes):
        with col:
            selected = st.session_state.auto_mode == mode_id
            st.markdown(f"""<div class="auto-mode-btn {cls} {'selected' if selected else ''}" onclick="">
              <div style="font-size:14px;font-weight:700;margin-bottom:3px">{label}</div>
              <div style="font-size:11px;color:#64748b;line-height:1.4">{desc}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Set {label.split()[1]}", key=f"mode_{mode_id}", use_container_width=True,
                        type="primary" if selected else "secondary"):
                st.session_state.auto_mode = mode_id; st.rerun()

    st.markdown("---")

    ai_insight("Autonomous Intelligence",
        f"Current mode: <strong>{'Human Approval' if st.session_state.auto_mode=='human' else 'Semi-Autonomous' if st.session_state.auto_mode=='semi' else 'Fully Autonomous'}</strong>. "
        "<strong>3 AI actions logged</strong> — 2 executed successfully, 1 pending your approval. "
        "Auto-remediation success rate this week: <strong>94%</strong>. Time saved: <strong>4.2 hours</strong>.",
        confidence=94)

    # Metrics
    amc = st.columns(4)
    with amc[0]: metric_card("Actions This Week","47","94% success rate","green","up","✅")
    with amc[1]: metric_card("Auto-Healed","12","Issues resolved autonomously","blue",None,"🤖")
    with amc[2]: metric_card("Pending Approval","1","BGP timer change","amber",None,"⏳")
    with amc[3]: metric_card("Time Saved","4.2h","This week","green","up","⚡")

    st.markdown('<div class="sec-hdr"><div class="sec-title">🤖 Autonomous Action Log</div><div class="sec-line"></div></div>', unsafe_allow_html=True)

    auto_actions = get_auto_actions()
    for a in auto_actions:
        status = a.get("status","")
        cls = "aa-exec" if status=="executed" else "aa-pend" if "pending" in status else "aa-fail"
        ico = "✅" if status=="executed" else "⏳" if "pending" in status else "❌"
        conf = a.get("ai_confidence",0)
        conf_cls = "conf-high" if conf>=80 else "conf-med" if conf>=60 else "conf-low"
        st.markdown(f"""<div class="auto-action">
          <div class="aa-status {cls}">{ico}</div>
          <div class="aa-body">
            <div class="aa-title">{a['action']}</div>
            <div class="aa-meta">Device: {a.get('device','')} · Trigger: {a.get('trigger','')}</div>
            <div class="aa-ai">{a.get('result','')}</div>
            <div class="conf-bar {conf_cls}" style="margin-top:5px"><span class="conf-pct">{conf}%</span><div class="conf-track"><div class="conf-fill" style="width:{conf}%"></div></div><span style="font-size:11px;color:#94a3b8">AI Confidence</span></div>
          </div>
        </div>""", unsafe_allow_html=True)
        if "pending" in status:
            pa1, pa2 = st.columns(2)
            with pa1:
                if st.button("✅ Approve Action", key=f"auto_app_{a['id']}", use_container_width=True, type="primary"):
                    con=db(); con.execute(f"UPDATE autonomous_actions SET status='executed' WHERE id={a['id']}"); con.commit(); con.close(); st.rerun()
            with pa2:
                if st.button("❌ Reject", key=f"auto_rej_{a['id']}", use_container_width=True):
                    con=db(); con.execute(f"UPDATE autonomous_actions SET status='rejected' WHERE id={a['id']}"); con.commit(); con.close(); st.rerun()

    # AI operations chat
    st.markdown("---")
    st.markdown("**Ask Autonomous AI:**")
    auto_q = st.text_input("", placeholder="'What autonomous actions have been taken today?' · 'Generate self-healing policy for BGP flaps' · 'Show automation success rate by device'",
                           label_visibility="collapsed", key="auto_q")
    if st.button("🤖 Ask Autonomous AI", type="primary") and auto_q:
        go_chat(auto_q, "autonomous", "Autonomous operations context — AI-driven network management, self-healing, approval workflows")

# ─────────────────────── DESIGN WORKSPACE ───────────────────
elif ws == "design":
    sec_header("🏗 AI Design Studio", "ChatGPT for network architecture · Requirements → Full design → BOM → Roadmap")

    st.markdown("""<div class="design-studio">
      <div class="studio-title">🎯 AI Network Design Studio</div>
      <div class="studio-sub">Describe your requirements in plain English. I generate full architecture, topology, vendor comparison, BOM, and implementation roadmap.</div>
    </div>""", unsafe_allow_html=True)

    # Design templates
    st.markdown("**Design Blueprints — Start from a template:**")
    tmpl_cols = st.columns(3)
    templates = [
        ("🏢","Enterprise Campus","3000 users · 3-tier · SD-Access · Wireless · Zero Trust · HA design",
         "Design enterprise campus network: 3000 users, 3-tier hierarchy (core-distribution-access), Cisco SD-Access, wireless 802.11ax, Zero Trust security, full redundancy HA. Include: topology diagram description, hardware sizing, BOM, vendor comparison, implementation roadmap."),
        ("🛣️","SD-WAN Deployment","50 branches · Dual ISP · Azure · SASE · App-SLA · Cloud breakout",
         "Design SD-WAN for 50 branches: 200 users/branch, dual ISP per branch, Azure cloud integration, SASE (Zscaler ZIA/ZPA), application-aware routing, cloud breakout for SaaS. Include architecture, Cisco Viptela vs Versa comparison, BOM, migration strategy."),
        ("🏭","AI Datacenter","GPU clusters · VXLAN EVPN · RoCE · Leaf-Spine · 400G · InfiniBand",
         "Design AI datacenter fabric: 500 GPU servers, leaf-spine topology, VXLAN EVPN, RoCE for GPU all-reduce, 400G links, Arista EOS, lossless networking (PFC+ECN+DCQCN). Include fabric design, BOM, cabling, performance calculations."),
        ("☁️","Hybrid Cloud","On-prem + AWS + Azure · Direct Connect · ExpressRoute · Multi-cloud HA",
         "Design hybrid cloud network: 2 on-prem datacenters connecting to AWS and Azure, Direct Connect + ExpressRoute, BGP routing, SD-WAN integration, HA across clouds. Include connectivity options comparison, routing design, security architecture, cost analysis."),
        ("🔐","Zero Trust","ZTNA · Micro-segmentation · Identity · Palo Alto · Zscaler · SASE",
         "Design Zero Trust network architecture: ZTNA replacing VPN, micro-segmentation east-west, Palo Alto Prisma + Zscaler ZPA, identity-based access, MFA, continuous verification. Include maturity model, phased implementation, BOM, policy framework."),
        ("📡","5G / SP Transport","SR-MPLS · SRv6 · Slicing · Mobile backhaul · Metro-E · Nokia/Cisco",
         "Design 5G transport network: 500 cell sites, SR-MPLS underlay, SRv6 services, network slicing (eMBB/URLLC/mMTC), mobile backhaul and fronthaul, Nokia SR-OS or Cisco IOS-XR. Include transport architecture, timing sync, BOM, migration from LTE."),
    ]
    for i, (ico, name, desc, prompt) in enumerate(templates):
        with tmpl_cols[i % 3]:
            st.markdown(f"""<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:12px;cursor:pointer">
              <div style="font-size:22px;margin-bottom:8px">{ico}</div>
              <div style="font-size:14px;font-weight:700;color:#0f172a;margin-bottom:4px">{name}</div>
              <div style="font-size:12px;color:#64748b;line-height:1.5;margin-bottom:10px">{desc}</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Design {name}", key=f"design_{name}", use_container_width=True):
                go_chat(prompt, "design")

    st.markdown("---")
    st.markdown("**Custom Design — Describe your requirements:**")

    d1, d2 = st.columns(2)
    with d1:
        req_sites    = st.text_input("Locations / sites", placeholder="e.g. 1 HQ + 20 branches + 2 datacenters")
        req_users    = st.text_input("User count per location", placeholder="e.g. 500 HQ, 100 branch")
        req_cloud    = st.text_input("Cloud requirements", placeholder="e.g. Azure primary, AWS DR, Microsoft 365")
        req_security = st.text_input("Security requirements", placeholder="e.g. Zero Trust, SASE, PCI DSS, HIPAA")
    with d2:
        req_budget   = st.text_input("Budget (optional)", placeholder="e.g. under $500K CAPEX")
        req_vendors  = st.text_input("Vendor preference", placeholder="e.g. Cisco preferred, open to Juniper")
        req_ha       = st.text_input("HA/redundancy", placeholder="e.g. 99.99% uptime, dual ISP, HA pairs")
        req_special  = st.text_area("Special requirements", height=68, placeholder="e.g. HIPAA compliance, AI workloads, video surveillance, IoT")

    if st.button("🧠 Generate Complete Architecture", type="primary", use_container_width=True):
        design_prompt = f"""Design a complete network architecture with these requirements:
- Locations: {req_sites or 'Not specified'}
- Users: {req_users or 'Not specified'}
- Cloud: {req_cloud or 'Not specified'}
- Security: {req_security or 'Not specified'}
- Budget: {req_budget or 'Not specified'}
- Vendors: {req_vendors or 'Best recommendation'}
- HA Requirements: {req_ha or 'Standard HA'}
- Special: {req_special or 'None'}

Provide:
1. Architecture Overview with reasoning
2. Network topology description (core/dist/access/WAN/cloud layers)
3. Vendor selection with comparison table
4. Hardware sizing per layer
5. Bill of Materials (top 10 items with estimated cost)
6. Security architecture
7. 90-day implementation roadmap
8. Key risks and mitigations"""
        go_chat(design_prompt, "design")

    # Show design output if exists
    if st.session_state.chat_msgs and st.session_state.workspace == "design":
        latest = [m for m in st.session_state.chat_msgs if m["role"]=="assistant"]
        if latest:
            st.markdown("---")
            st.markdown("**🏗 Generated Architecture:**")
            st.markdown(latest[-1]["content"])
            st.download_button("⬇ Download Architecture", latest[-1]["content"], "network_design.md", "text/markdown")

# ─────────────────────── LEARN WORKSPACE ────────────────────
elif ws == "learn":
    sec_header("📖 Adaptive Learning Engine", "AI detects your level automatically · CCNA to CCIE · Context-driven")

    p_l = {"fresher":"🌱 Fresher","ccna":"🎓 CCNA","noc":"🖥 NOC","architect":"🏗 Architect","manager":"📊 Manager","security":"🔒 Security"}
    ai_insight("Adaptive NLP Learning",
        f"Current persona: <strong>{p_l[st.session_state.persona]}</strong>. "
        "I detect your level from how you phrase questions. Ask <strong>'what is a VLAN?'</strong> → basics with analogy. "
        "Ask <strong>'explain Q-in-Q double-tagging MTU implications'</strong> → expert level. <strong>No configuration needed.</strong>",
        confidence=None)

    # Learning tracks
    tracks = [
        ("🌐","Routing Fundamentals","OSPF · BGP · EIGRP · IS-IS · Policy · Redistribution · Multicast",65,"blue",
         "Start a routing fundamentals lesson. Detect my level and adapt. Include OSPF, BGP, EIGRP. Give me practical examples."),
        ("🔀","Switching & Fabric","VLANs · STP · EtherChannel · RSTP · MSTP · MACsec · SD-Access",40,"green",
         "Teach me switching and VLANs. Start from my current level. Include STP, EtherChannel, campus design."),
        ("🛣️","WAN & SD-WAN","MPLS · SD-WAN · DMVPN · IPSec · SASE · Cloud WAN · QoS",20,"amber",
         "Explain WAN technologies and SD-WAN. Start from basics, then go to Cisco Viptela and SASE architecture."),
        ("🔒","Network Security","Zero Trust · ZTNA · Firewall · ACL · IPSec · NAC · SASE · IDS/IPS",55,"red",
         "Teach network security from my level. Zero Trust, ZTNA, firewall policies, ACL, segmentation."),
        ("🏢","Datacenter Networking","VXLAN · EVPN · Leaf-Spine · ACI · AI Fabric · RoCE · InfiniBand",10,"purple",
         "Explain datacenter networking. Start with why leaf-spine, then VXLAN EVPN, then AI fabric and RoCE."),
        ("☁️","Cloud & Hybrid","AWS VPC · Azure VNet · GCP · Transit Gateway · Kubernetes · Container",30,"blue",
         "Teach cloud networking. AWS VPC, Azure VNet, hybrid connectivity, Kubernetes networking. Start from my level."),
        ("📡","Service Provider","MPLS L3VPN · L2VPN · SR-MPLS · SRv6 · 5G Transport · BGP-LU",5,"slate",
         "Explain service provider networking. MPLS L3VPN, SR-MPLS, SRv6, 5G transport. Expert level please."),
        ("🤖","AI & Automation","Ansible · Terraform · Python · NETCONF · RESTCONF · gRPC · Intent",15,"green",
         "Teach network automation. Ansible for network, Terraform, Python netmiko, NETCONF/RESTCONF. Practical examples."),
    ]

    tc = st.columns(4)
    for i, (ico, name, desc, pct, color, prompt) in enumerate(tracks):
        with tc[i % 4]:
            pct_color = "#3b82f6" if color=="blue" else "#22c55e" if color=="green" else "#f59e0b" if color=="amber" else "#ef4444" if color=="red" else "#8b5cf6" if color=="purple" else "#64748b"
            st.markdown(f"""<div style="background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:14px;margin-bottom:4px">
              <div style="font-size:20px;margin-bottom:6px">{ico}</div>
              <div style="font-size:13px;font-weight:700;color:#0f172a;margin-bottom:3px">{name}</div>
              <div style="font-size:11px;color:#64748b;margin-bottom:10px;line-height:1.5">{desc}</div>
              <div style="height:4px;background:#f1f5f9;border-radius:4px;overflow:hidden;margin-bottom:4px"><div style="height:100%;width:{pct}%;background:{pct_color};border-radius:4px"></div></div>
              <div style="font-size:10px;color:#94a3b8;font-family:DM Mono,monospace">{pct}% complete</div>
            </div>""", unsafe_allow_html=True)
            if st.button(f"Start", key=f"track_{name}", use_container_width=True):
                go_chat(prompt, "learn")

    st.markdown("---")

    # Free learning
    learn_q = st.text_input("Ask anything to learn", placeholder="'What is BGP?' · 'Explain OSPF DR election with analogy' · 'How does VXLAN work?' · 'Compare SD-WAN vs MPLS'", key="learn_q")
    if st.button("📖 Learn", type="primary") and learn_q:
        go_chat(learn_q, "learn")

    # Show latest learning response
    ai_learns = [m for m in st.session_state.chat_msgs if m["role"]=="assistant"]
    if ai_learns:
        with st.expander("📖 Latest Learning Response", expanded=True):
            render_msg("assistant", ai_learns[-1]["content"], ai_learns[-1].get("meta"))

# ══════════════════════════════════════════════════════════
# FLOATING AI CHAT (always available at bottom)
# ══════════════════════════════════════════════════════════
if ws not in ["troubleshoot","learn"]:
    st.markdown("---")
    with st.expander("💬 AI Copilot — Ask anything (always available)", expanded=False):
        if st.session_state.chat_msgs:
            for msg in st.session_state.chat_msgs[-4:]:
                render_msg(msg["role"], msg["content"], msg.get("meta"))

        chat_cols = st.columns([0.82, 0.1, 0.08])
        with chat_cols[0]:
            chat_inp = st.text_input("", placeholder="Ask anything about your network…", label_visibility="collapsed", key="float_chat")
        with chat_cols[1]:
            if st.button("Send", use_container_width=True, type="primary", key="float_send") and chat_inp:
                go_chat(chat_inp, ws)
        with chat_cols[2]:
            if st.button("🗑", use_container_width=True, key="float_clear"):
                st.session_state.chat_msgs=[]; st.session_state.chat_hist=[]; st.rerun()
