"""
NetBrain AI — Autonomous Network Intelligence Platform
Single-file Streamlit app — Streamlit Cloud compatible
No submodule imports. All 4 engines inline.
"""

import streamlit as st
st.set_page_config(
    page_title="NetBrain AI",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "NetBrain AI v1.0"}
)

import os, re, json, sqlite3, threading, hashlib
from datetime import datetime
import pandas as pd

# ── Safe optional imports ──────────────────────────────────
try:
    import anthropic
    CLAUDE_OK = True
except ImportError:
    CLAUDE_OK = False

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException
    NETMIKO_OK = True
except Exception:
    NETMIKO_OK = False

try:
    import spacy
    _spacy_nlp = spacy.load("en_core_web_sm")
    SPACY_OK = True
except Exception:
    SPACY_OK = False
    _spacy_nlp = None

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    _chroma_client  = chromadb.PersistentClient(path="./chroma_db")
    _embedder       = SentenceTransformer("all-MiniLM-L6-v2")
    _rag_collection = None
    RAG_OK = True
except Exception:
    RAG_OK = False
    _chroma_client  = None
    _embedder       = None
    _rag_collection = None

# ══ DATABASE ══════════════════════════════════════════════
DB_PATH = "netbrain.db"

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    con = _db()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT, ip TEXT, vendor TEXT DEFAULT 'cisco_ios',
            username TEXT, password TEXT, port INTEGER DEFAULT 22,
            role TEXT, site TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, description TEXT, root_cause TEXT,
            resolution TEXT, devices TEXT, protocols TEXT, severity TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT, device_count INTEGER, ai_result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    if con.execute("SELECT COUNT(*) FROM devices").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site) VALUES(?,?,?,?,?,?,?,?)",
            [("CORE-RTR-01","10.0.0.1","cisco_ios_xr","admin","admin123",22,"Core Router","HQ"),
             ("PE-MUM-01","10.0.1.1","cisco_ios_xr","admin","admin123",22,"PE Router","Mumbai"),
             ("PE-DEL-01","10.0.2.1","cisco_ios_xr","admin","admin123",22,"PE Router","Delhi"),
             ("DIST-SW-W","10.1.1.1","cisco_ios","admin","admin123",22,"Dist Switch","HQ-West"),
             ("FW-EDGE-01","192.168.1.1","paloalto_panos","admin","admin123",22,"Firewall","DMZ")])
    if con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0:
        con.executemany(
            "INSERT INTO incidents(title,description,root_cause,resolution,devices,protocols,severity) VALUES(?,?,?,?,?,?,?)",
            [("BGP session flapping","PE-MUM-01 BGP to AS65002 flapping",
              "ISP BGP prefix withdrawal","Increased hold timer, ISP ticket","PE-MUM-01","BGP","critical"),
             ("OSPF adjacency lost","CORE-RTR-01 OSPF down with DIST-SW-W",
              "MTU mismatch","Added ip ospf mtu-ignore","CORE-RTR-01","OSPF","major"),
             ("VLAN 100 drop","VLAN 100 users cannot reach gateway",
              "VLAN not in trunk allowed list","Added VLAN 100 to trunk","DIST-SW-W","VLAN","major")])
    con.commit(); con.close()

def db_get_devices():
    con = _db(); rows = con.execute("SELECT * FROM devices").fetchall(); con.close()
    return [dict(r) for r in rows]

def db_add_device(hostname,ip,vendor,username,password,port,role,site):
    con = _db()
    con.execute("INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site) VALUES(?,?,?,?,?,?,?,?)",
                (hostname,ip,vendor,username,password,port,role,site))
    con.commit(); con.close()

def db_get_incidents():
    con = _db(); rows = con.execute("SELECT * FROM incidents ORDER BY created_at DESC").fetchall(); con.close()
    return [dict(r) for r in rows]

init_db()

# ══ SYSTEM A — CLAUDE API ════════════════════════════════
NETWORK_SYSTEM = """You are NetBrain AI — autonomous AI brain for enterprise and telecom networking.
Deep expertise: OSPF BGP EIGRP IS-IS MPLS SRv6 VLANs STP EtherChannel VXLAN EVPN
SD-WAN SASE Zero-Trust ZTNA Firewall ACL IPSec Datacenter(Leaf-Spine RoCE)
Cloud(AWS Azure GCP) Kubernetes SP(L3VPN L2VPN SR-MPLS 5G) Wireless.
Vendors: Cisco Juniper Arista PaloAlto Fortinet Aruba Nokia Versa Zscaler.
Always include CLI commands. Use headers and code blocks."""

PERSONAS = {
    "ccna": "Helping a CCNA engineer. Explain with analogies. Define acronyms. Show CLI with line-by-line explanation.",
    "noc":  "Helping NOC engineer. Be concise. Lead with root cause. Give exact CLI to verify and fix. Include rollback.",
    "arch": "Helping senior architect. Skip basics. Focus on design trade-offs scalability HA. Reference RFCs."
}

def call_claude(messages, persona="noc", max_tokens=2000):
    api_key = ""
    try:    api_key = st.secrets.get("ANTHROPIC_API_KEY","")
    except: api_key = os.environ.get("ANTHROPIC_API_KEY","")
    if not api_key:
     return ("⚠️ **Claude API key missing.**\n\nAdd to Streamlit Cloud secrets:\n"
                "Go to **App menu → Settings → Secrets** and add:\n```\nANTHROPIC_API_KEY = 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"
                 OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1")
    if not CLAUDE_OK:
        return "⚠️ `anthropic` package not installed. Check requirements.txt."
    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-20250514", max_tokens=max_tokens,
            system=NETWORK_SYSTEM + "\n\n" + PERSONAS.get(persona, PERSONAS["noc"]),
            messages=messages)
        return resp.content[0].text
    except Exception as e:
        return f"❌ Claude API error: `{e}`"

# ══ SYSTEM B — MULTI-DEVICE QUERY ════════════════════════
NL_CMD = {
    "bgp summary":   {"cisco_ios":"show ip bgp summary","cisco_ios_xr":"show bgp all summary","juniper_junos":"show bgp summary","arista_eos":"show bgp summary"},
    "bgp neighbor":  {"cisco_ios":"show ip bgp neighbors","cisco_ios_xr":"show bgp neighbors","juniper_junos":"show bgp neighbor","arista_eos":"show bgp neighbors"},
    "ospf neighbor": {"cisco_ios":"show ip ospf neighbor","cisco_ios_xr":"show ospf neighbor","juniper_junos":"show ospf neighbor","arista_eos":"show ip ospf neighbor"},
    "interface":     {"cisco_ios":"show interfaces status","cisco_ios_xr":"show interfaces brief","juniper_junos":"show interfaces terse","arista_eos":"show interfaces status"},
    "cpu":           {"cisco_ios":"show processes cpu sorted","cisco_ios_xr":"show processes cpu","juniper_junos":"show chassis routing-engine","arista_eos":"show processes top once"},
    "routing table": {"cisco_ios":"show ip route","cisco_ios_xr":"show route ipv4","juniper_junos":"show route","arista_eos":"show ip route"},
    "vlan":          {"cisco_ios":"show vlan brief","cisco_ios_xr":"show vlan","juniper_junos":"show vlans","arista_eos":"show vlan"},
    "version":       {"cisco_ios":"show version","cisco_ios_xr":"show version","juniper_junos":"show version","arista_eos":"show version"},
    "log":           {"cisco_ios":"show logging | last 50","cisco_ios_xr":"show log | last 50","juniper_junos":"show log messages | last 50","arista_eos":"show log last 50"},
}

def _resolve(query, vendor):
    q = query.lower()
    for kw, vm in NL_CMD.items():
        if kw in q: return vm.get(vendor, vm.get("cisco_ios","show version"))
    if any(q.startswith(p) for p in ["show","ping","trace","debug","display"]): return query.strip()
    return "show version"

def _sim(device, command):
    ip = device.get("ip","0.0.0.0")
    if "bgp" in command and "summary" in command:
        out = f"BGP router identifier {ip}, local AS 65001\nNeighbor    AS    Up/Down  State\n10.0.0.1  65001  5d02h14  Established/142\n10.0.1.1  65002  0d00h04  Active\n10.0.2.1  65003  2d11h22  Established/87"
    elif "ospf" in command:
        out = "Neighbor ID  Pri  State     Interface\n192.168.1.1    1  FULL/DR   Gi0/0\n192.168.1.2    1  FULL/BDR  Gi0/1\n192.168.1.3    0  EXSTART   Gi0/2"
    elif "cpu" in command:
        out = "CPU 5sec 88%, 1min 75%, 5min 62%\n42  45%  OSPF Hello\n103  22%  BGP"
    elif "vlan" in command:
        out = "VLAN  Name         Status\n1     default      active\n100   FINANCE      active\n120   BRANCH-HYD   suspend"
    elif "interface" in command:
        out = "Interface  Status  Protocol\nGi0/0      up      up\nGi0/1      up      up\nGi0/2      down    down\nGi0/3      adm dn  down"
    else:
        out = f"Hostname: {device.get('hostname','DEV')}\nUptime: 127 days 4 hours"
    return {"status":"ok","output":out,"command":command,"simulated":True}

def _ssh(device, command):
    if not NETMIKO_OK: return _sim(device, command)
    try:
        with ConnectHandler(device_type=device.get("vendor","cisco_ios"), host=device.get("ip"),
                            username=device.get("username","admin"), password=device.get("password",""),
                            port=device.get("port",22), timeout=12) as c:
            return {"status":"ok","output":c.send_command(command,read_timeout=12),"command":command,"simulated":False}
    except Exception:
        return _sim(device, command)

def run_mdq(query, persona="noc"):
    devices = db_get_devices()
    if not devices: return {"error":"No devices","device_results":[],"ai_synthesis":"","device_count":0}
    results, lock = [], threading.Lock()
    def qone(dev):
        cmd = _resolve(query, dev.get("vendor","cisco_ios"))
        out = _ssh(dev, cmd)
        with lock: results.append({**{k:dev.get(k,"") for k in ["hostname","ip","vendor","role","site"]}, **out})
    threads = [threading.Thread(target=qone, args=(d,)) for d in devices]
    for t in threads: t.start()
    for t in threads: t.join(timeout=18)
    ctx = "\n\n".join(f"=== {r['hostname']} ({r['ip']}) | {r['vendor']} ===\nCMD: {r['command']}\n{r['output']}" for r in results)
    synth = call_claude([{"role":"user","content":f'Query:"{query}"\n{len(results)} devices:\n{ctx}\n\n1)SUMMARY 2)FINDINGS 3)RISKS 4)ACTIONS. Use hostnames.'}], persona)
    return {"query":query,"device_count":len(results),"device_results":results,"ai_synthesis":synth}

# ══ SYSTEM C — NLP ═══════════════════════════════════════
_RE = {
    "ip_addresses": r'\b(?:\d{1,3}\.){3}\d{1,3}(?:\/\d{1,2})?\b',
    "interfaces":   r'\b(?:Gi|Fa|Te|Hu|Et|xe|ge|fe|Lo|Tu)\d+(?:[\/\-]\d+){0,3}\b',
    "vlans":        r'\b[Vv][Ll][Aa][Nn]\s*\d+\b',
    "as_numbers":   r'\b[Aa][Ss]\s*\d+\b',
    "ospf_areas":   r'\barea\s*\d+\b',
    "hostnames":    r'\b[A-Z]{2,}[-_][A-Z0-9]{2,}[-_][A-Z0-9]+\b',
}
_PROTO   = ["BGP","OSPF","EIGRP","IS-IS","MPLS","EVPN","VXLAN","STP","RSTP","LACP","BFD","HSRP","VRRP","IPSec","GRE","SD-WAN","SASE","ZTNA","QoS","SRv6","VRF","SNMP","ACL"]
_VENDORS = ["Cisco","Juniper","Arista","Fortinet","Palo Alto","Aruba","Versa","Nokia","Huawei","Zscaler","Cato","Viptela"]
_INTENTS = {
    "troubleshoot":   ["not working","down","flapping","unstable","dropping","timeout","failed","error","issue","problem","diagnose","why","fix","broken"],
    "generate_config":["generate","create","write","configure","build config","give me config"],
    "explain":        ["explain","what is","what does","how does","describe","understand"],
    "design":         ["design","architect","plan","blueprint","recommend","topology"],
    "query_devices":  ["show","check","fetch","across all","all devices","all routers","on all"],
}

def extract_entities(text):
    ents = {k: list(dict.fromkeys(re.findall(pat, text, re.IGNORECASE))) for k,pat in _RE.items()}
    tu = text.upper()
    ents["protocols"] = [p for p in _PROTO if p.upper() in tu]
    ents["vendors"]   = [v for v in _VENDORS if v.lower() in text.lower()]
    tl = text.lower()
    ents["intent"] = next((i for i,kws in _INTENTS.items() if any(k in tl for k in kws)), "general")
    ents["urgency"] = "high" if any(w in tl for w in ["critical","urgent","down","outage","p1","production"]) else "normal"
    ents["persona_hint"] = ("arch" if any(w in tl for w in ["sr-mpls","srv6","evpn","vxlan","bfd","lsdb"])
                            else "ccna" if any(w in tl for w in ["what is","explain","how does","beginner"]) else None)
    return ents

def enrich(query, ents):
    parts = []
    for k,label in [("ip_addresses","IPs"),("interfaces","Ifaces"),("vlans","VLANs"),
                    ("as_numbers","AS"),("protocols","Proto"),("vendors","Vendor"),("hostnames","Devs")]:
        if ents.get(k): parts.append(f"{label}:{','.join(ents[k])}")
    return f"[NLP:{' | '.join(parts)}]\n\n{query}" if parts else query

# ══ SYSTEM D — RAG ═══════════════════════════════════════
KB = {
    "BGP": "BGP states: Idle Connect Active OpenSent OpenConfirm Established. Active=TCP not established. Check: ping peer, ACL blocking TCP179, remote-as mismatch, MD5 auth, update-source. Hold-timer 180s. BFD sub-second. Commands: show bgp all summary, show bgp neighbors <ip>. AS_PATH prepend: set as-path prepend. Best path: Weight>Local-Pref>Originate>AS_PATH>MED>eBGP>IGP.",
    "OSPF": "OSPF states: Down Attempt Init 2-Way ExStart Exchange Loading Full. ExStart stuck=MTU mismatch, fix: ip ospf mtu-ignore. DR/BDR: highest priority then RID. Priority 0=never DR. LSA types: 1=Router 2=Network 3=Summary 5=External 7=NSSA. Hello 10s broadcast. Dead=4x hello. Commands: show ip ospf neighbor, show ip ospf interface, show ip ospf database.",
    "VLAN": "VLAN not on trunk: show interfaces trunk. Fix: switchport trunk allowed vlan add <id>. Native VLAN mismatch=storms. STP states: Blocking Listening Learning Forwarding. RSTP <1s convergence. EtherChannel: match speed duplex VLAN. LACP active/passive. Commands: show vlan brief, show interfaces trunk, show spanning-tree vlan <id>.",
    "SDWAN": "SD-WAN: vManage(NMS) vBond(orch) vSmart(ctrl) vEdge/cEdge(data). OMP=overlay routing. Colors: mpls biz-internet lte. App-aware routing: SLA per app class. Direct cloud access: breakout at branch for SaaS. TLOC=system-IP+color+encap.",
    "MPLS": "MPLS: 20-bit label, 3-bit TC, 1-bit S, 8-bit TTL. LDP for IGP prefixes. L3VPN: MP-BGP, VRF per customer, RT import/export. RD 64-bit. L2VPN: VPWS point-to-point, VPLS multipoint. Segment Routing: prefix-SID adj-SID, no LDP/RSVP. SRv6: IPv6 as segment IDs.",
    "SECURITY": "Zero Trust: never trust always verify. ZTNA=app-specific access replaces VPN. SASE=SD-WAN+security-service-edge. Palo Alto: App-ID user-ID content-ID. Microsegmentation: east-west inspection. MFA mandatory. NAC: posture before access. 802.1X enforcement.",
    "DATACENTER": "Leaf-spine: every leaf connects every spine. No STP. ECMP. VXLAN UDP4789 VNI 24-bit. EVPN BGP: type-2 MAC/IP type-3 multicast type-5 prefix. Symmetric IRB: distributed anycast gateway. RoCE: RDMA over Ethernet, needs PFC ECN DCQCN lossless for GPU clusters.",
}

def rag_search(query, n=3):
    global _rag_collection
    if RAG_OK and _chroma_client and _embedder:
        try:
            if _rag_collection is None:
                _rag_collection = _chroma_client.get_or_create_collection("netbrain_v1",metadata={"hnsw:space":"cosine"})
                if _rag_collection.count() == 0:
                    for topic, content in KB.items():
                        words = content.split(); chunks = [" ".join(words[i:i+200]) for i in range(0,len(words),160) if words[i:i+200]]
                        ids   = [hashlib.md5(f"{topic}_{i}".encode()).hexdigest() for i in range(len(chunks))]
                        embs  = _embedder.encode(chunks).tolist()
                        metas = [{"title":f"{topic} Reference","vendor":"general","doc_type":"knowledge","chunk":i} for i in range(len(chunks))]
                        _rag_collection.add(ids=ids,documents=chunks,embeddings=embs,metadatas=metas)
            emb = _embedder.encode([query]).tolist()
            res = _rag_collection.query(query_embeddings=emb,n_results=min(n,_rag_collection.count()))
            return [{"content":d,"meta":m} for d,m in zip(res["documents"][0],res["metadatas"][0])]
        except Exception:
            pass
    # Keyword fallback
    q = query.lower(); scored = []
    for topic, content in KB.items():
        score = sum(1 for w in q.split() if len(w)>3 and w in content.lower())
        if topic.lower() in q: score += 5
        if score > 0: scored.append((score, topic, content))
    scored.sort(reverse=True)
    return [{"content":c[:400],"meta":{"title":f"{t} Reference","vendor":"general","doc_type":"knowledge","chunk":0}} for _,t,c in scored[:n]]

def ingest_doc(title, content, vendor="general", dtype="manual"):
    global _rag_collection
    if not RAG_OK or not _embedder: return 0
    try:
        if _rag_collection is None: _rag_collection = _chroma_client.get_or_create_collection("netbrain_v1")
        words = content.split(); chunks = [" ".join(words[i:i+200]) for i in range(0,len(words),160) if words[i:i+200]]
        ids   = [hashlib.md5(f"{title}_{i}".encode()).hexdigest() for i in range(len(chunks))]
        embs  = _embedder.encode(chunks).tolist()
        metas = [{"title":title,"vendor":vendor,"doc_type":dtype,"chunk":i} for i in range(len(chunks))]
        _rag_collection.add(ids=ids,documents=chunks,embeddings=embs,metadatas=metas)
        return len(chunks)
    except Exception: return 0

# ══ MASTER PIPELINE ══════════════════════════════════════
def pipeline(query, persona="noc", history=None):
    ents = extract_entities(query)
    ep   = ents.get("persona_hint") or persona
    enriched = enrich(query, ents)
    chunks   = rag_search(query, n=3)
    incs     = [i for i in db_get_incidents() if any(p.lower() in f"{i['title']} {i.get('protocols','')}".lower() for p in ents.get("protocols",[]))][:2]
    msgs = []
    if chunks:
        kb = "\n\n".join(f"[{c['meta'].get('title','Doc')}]\n{c['content']}" for c in chunks)
        msgs += [{"role":"user","content":f"KNOWLEDGE:\n{kb}"},{"role":"assistant","content":"Reviewed."}]
    if incs:
        ic = "\n".join(f"PAST: {i['title']} | RCA: {i['root_cause']} | Fix: {i['resolution']}" for i in incs)
        msgs += [{"role":"user","content":f"INCIDENTS:\n{ic}"},{"role":"assistant","content":"Historical context reviewed."}]
    if history: msgs += history[-8:]
    msgs.append({"role":"user","content":enriched})
    response = call_claude(msgs, ep, 2000)
    return {"response":response,"entities":ents,"persona_used":ep,
            "rag_sources":[c["meta"].get("title","") for c in chunks],
            "similar_incidents":[i["title"] for i in incs]}

def sys_status():
    api_key = ""
    try:    api_key = st.secrets.get("ANTHROPIC_API_KEY","")
    except: api_key = os.environ.get("ANTHROPIC_API_KEY","")
    return {"claude":CLAUDE_OK and bool(api_key),"netmiko":NETMIKO_OK,
            "spacy":SPACY_OK,"rag":RAG_OK,"rag_mode":"ChromaDB" if RAG_OK else "Keyword"}

# ══ CSS ══════════════════════════════════════════════════
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&family=Fraunces:wght@700&display=swap');
html,body,[class*="css"]{font-family:'DM Sans',sans-serif!important}
[data-testid="stSidebar"]{background:#fff!important;border-right:1px solid #d9dde6}
.bh{background:linear-gradient(135deg,#0a1628,#0f2042);border-radius:12px;padding:14px 18px;margin-bottom:14px;display:flex;align-items:center;gap:12px}
.bn{font-family:'Fraunces',serif;font-size:20px;font-weight:700;color:#fff}
.bs{font-size:10px;color:rgba(255,255,255,.4);letter-spacing:.8px;text-transform:uppercase;font-family:'DM Mono',monospace}
.pill{font-size:11px;padding:3px 9px;border-radius:20px;font-family:'DM Mono',monospace;font-weight:500;display:inline-block;margin:2px}
.pon{background:#d4f0e1;color:#14613a;border:1px solid #a0dfc0}
.poff{background:#fad5d2;color:#8b1a1a;border:1px solid #f0a0a0}
.psim{background:#fde8b8;color:#7a4a00;border:1px solid #f0c070}
.aib{background:linear-gradient(135deg,#f0f5fd,#fff);border:1px solid #c8d9f5;border-radius:12px;padding:13px 15px;margin-bottom:14px;display:flex;gap:12px;align-items:flex-start}
.aii{width:34px;height:34px;border-radius:8px;flex-shrink:0;background:linear-gradient(135deg,#3b74d0,#0077cc);display:flex;align-items:center;justify-content:center;font-size:16px}
.ail{font-size:10px;font-weight:600;color:#0077cc;letter-spacing:1px;text-transform:uppercase;font-family:'DM Mono',monospace;margin-bottom:3px}
.ait{font-size:13px;color:#0f1b2d;line-height:1.6}
.mc{background:#fff;border:1px solid #d9dde6;border-radius:12px;padding:16px;box-shadow:0 1px 4px rgba(15,27,45,.06)}
.mcg{border-bottom:3px solid #1e8f55}.mcr{border-bottom:3px solid #c0392b}.mcb{border-bottom:3px solid #0077cc}.mca{border-bottom:3px solid #b06a00}
.mcl{font-size:10px;font-weight:600;color:#7a8799;letter-spacing:.5px;text-transform:uppercase;font-family:'DM Mono',monospace}
.mcv{font-family:'Fraunces',serif;font-size:28px;font-weight:700;margin:4px 0 2px;line-height:1}
.mcm{font-size:12px;color:#7a8799}
.vg{color:#14613a}.vr{color:#8b1a1a}.vb{color:#1e4080}.va{color:#7a4a00}
.cu{background:#0077cc;color:#fff;border-radius:12px 12px 2px 12px;padding:10px 14px;margin:3px 0;display:inline-block;max-width:85%;font-size:13px}
.ca{background:#fff;border:1px solid #d9dde6;border-radius:12px 12px 12px 2px;padding:10px 14px;margin:3px 0;display:inline-block;max-width:92%;font-size:13px;box-shadow:0 1px 4px rgba(15,27,45,.06)}
.mm{font-size:10px;color:#7a8799;font-family:'DM Mono',monospace;margin-top:3px}
.mp{padding:1px 6px;border-radius:10px;background:#e4edfc;color:#1e4080;margin:1px;display:inline-block}
.mpg{background:#d4f0e1;color:#14613a}.mpp{background:#e8d9fa;color:#4a2080}.mpt{background:#d0f0f5;color:#0e5460}
.dc{background:#fff;border:1px solid #d9dde6;border-radius:10px;padding:12px;margin-bottom:8px}
.dok{border-left:4px solid #1e8f55}.derr{border-left:4px solid #c0392b}
.dhn{font-family:'DM Mono',monospace;font-size:13px;font-weight:600;color:#0f1b2d}
.dout{font-family:'DM Mono',monospace;font-size:11px;background:#0a1628;color:#7dd3a8;padding:8px;border-radius:6px;margin-top:6px;white-space:pre-wrap;max-height:120px;overflow-y:auto}
.et{font-size:11px;padding:2px 7px;border-radius:10px;border:1px solid #d9dde6;color:#4a5568;font-family:'DM Mono',monospace;display:inline-block;margin:2px}
.rc{background:#fff;border:1px solid #d9dde6;border-radius:10px;padding:12px;margin-bottom:8px}
.rs{font-size:10px;font-weight:600;color:#0e5460;font-family:'DM Mono',monospace;margin-bottom:4px}
.rb{font-size:12px;color:#4a5568;line-height:1.7}
.sh{font-family:'Fraunces',serif;font-size:20px;font-weight:700;color:#0f1b2d;margin-bottom:3px}
.ss{font-size:13px;color:#4a5568;margin-bottom:14px}
div[data-testid="stButton"] button{border-radius:8px!important;font-weight:500!important}
</style>""", unsafe_allow_html=True)

# ══ SESSION STATE ════════════════════════════════════════
for k,v in [("chat_msgs",[]),("chat_hist",[]),("persona","noc"),("page","Overview"),
             ("mdq_res",None),("nlp_res",None),("rag_res",[])]:
    if k not in st.session_state: st.session_state[k] = v

# ══ SIDEBAR ══════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="bh"><div style="font-size:28px">🧠</div><div><div class="bn">NetBrain AI</div><div class="bs">Network Intelligence</div></div></div>', unsafe_allow_html=True)

    stat = sys_status()
    def pill(lbl,ok,sim=False):
        return f'<span class="pill {"pon" if ok else "psim" if sim else "poff"}">{lbl}</span>'
    st.markdown(
        pill(f"Claude {'✓' if stat['claude'] else '✗'}", stat["claude"]) +
        pill(f"SSH {'✓' if stat['netmiko'] else '⚡sim'}", stat["netmiko"], not stat["netmiko"]) +
        pill(f"NLP {'✓' if stat['spacy'] else '~reg'}", stat["spacy"], not stat["spacy"]) +
        pill(f"RAG {stat['rag_mode'][:6]}", True, not stat["rag"]),
        unsafe_allow_html=True)

    st.markdown("---")
    p_map = {"🎓 CCNA":"ccna","🖥 NOC":"noc","🏗 Architect":"arch"}
    st.session_state.persona = p_map[st.radio("**AI Persona**", list(p_map.keys()), index=1)]

    st.markdown("---")
    def nb(lbl,pg):
        if st.button(lbl,key=f"n_{pg}",use_container_width=True): st.session_state.page=pg

    st.markdown("**Operations**")
    for l,p in [("📊 Overview","Overview"),("🗺 Topology","Topology"),("🚨 Alerts","Alerts"),
                ("🔧 Troubleshooting","Troubleshoot"),("⚙ Automation","Automation"),
                ("🛡 Compliance","Compliance"),("🔒 Security","Security")]: nb(l,p)

    st.markdown("**AI Intelligence**")
    for l,p in [("🤖 AI Assistant","Chat"),("⚡ Multi-Device Query","MDQ"),
                ("🧬 NLP Engine","NLP"),("📚 RAG Knowledge","RAG"),
                ("💻 CLI Assistant","CLI"),("🏗 Network Design","Design"),("👾 Digital Twin","Twin")]: nb(l,p)

    st.markdown("**Learning & Mgmt**")
    for l,p in [("📖 Learning Hub","Learn"),("🖧 Device Manager","Devices"),
                ("📈 Executive","Exec"),("💰 FinOps","FinOps")]: nb(l,p)

    st.markdown("---")
    st.progress(0.97); st.caption("Platform health: 97%")

# ══ HELPERS ══════════════════════════════════════════════
def ai_bar(lbl, txt):
    st.markdown(f'<div class="aib"><div class="aii">🧠</div><div><div class="ail">{lbl}</div><div class="ait">{txt}</div></div></div>', unsafe_allow_html=True)

def mrow(items):
    for col,(l,v,m,cc,vc) in zip(st.columns(len(items)),items):
        with col: st.markdown(f'<div class="mc {cc}"><div class="mcl">{l}</div><div class="mcv {vc}">{v}</div><div class="mcm">{m}</div></div>',unsafe_allow_html=True)

def render_msg(role,content,meta=None):
    if role=="user":
        st.markdown(f'<div style="text-align:right"><span class="cu">{content}</span></div>',unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="ca">{content}</div>',unsafe_allow_html=True)
        if meta:
            pills=""
            if meta.get("persona_used"):       pills+=f'<span class="mp mpg">Persona:{meta["persona_used"]}</span>'
            if meta.get("rag_sources"):        pills+=f'<span class="mp mpt">📚{",".join(meta["rag_sources"][:2])}</span>'
            if meta.get("similar_incidents"):  pills+=f'<span class="mp">💡{meta["similar_incidents"][0]}</span>'
            if meta.get("entities",{}).get("protocols"): pills+=f'<span class="mp mpp">🧬{",".join(meta["entities"]["protocols"][:3])}</span>'
            if pills: st.markdown(f'<div class="mm">{pills}</div>',unsafe_allow_html=True)

def go(prompt, target="Chat"):
    st.session_state.chat_msgs.append({"role":"user","content":prompt,"meta":None})
    with st.spinner("🧠 NLP → RAG → Claude…"):
        r = pipeline(prompt, st.session_state.persona, st.session_state.chat_hist)
    st.session_state.chat_msgs.append({"role":"assistant","content":r["response"],"meta":r})
    st.session_state.chat_hist += [{"role":"user","content":prompt},{"role":"assistant","content":r["response"]}]
    st.session_state.page = target; st.rerun()

# ══ PAGES ════════════════════════════════════════════════
pg = st.session_state.page

if pg == "Overview":
    st.markdown('<div class="sh">Network Overview</div>',unsafe_allow_html=True)
    st.markdown('<div class="ss">847 devices · 4-engine AI · Last sync 12s</div>',unsafe_allow_html=True)
    ai_bar("AI Insight · NLP+RAG+Memory","<strong>BGP flapping</strong> on <code>PE-MUM-01→AS65002</code> — 3 flaps/hr. RAG matched Nov 2024: ISP withdrawal. <strong>Action:</strong> 10 min monitor then ISP ticket.")
    mrow([("Devices Online","831","of 847 · 16 degraded","mcg","vg"),("Active Alerts","7","3 critical · 4 warning","mcr","vr"),("BGP Sessions","248","247 up · 1 active","mcb","vb"),("Avg Latency","14ms","↑ +2ms","mca","va")])

    c1,c2 = st.columns(2)
    with c1:
        st.markdown("**🗺 Topology**")
        st.markdown("""<div style="background:#f7f8fa;border:1px solid #d9dde6;border-radius:10px;overflow:hidden"><svg viewBox="0 0 480 200" width="100%" xmlns="http://www.w3.org/2000/svg"><rect width="480" height="200" fill="#f7f8fa"/>
        <line x1="240" y1="45" x2="110" y2="105" stroke="#b8bfcc" stroke-width="1.5"/><line x1="240" y1="45" x2="240" y2="108" stroke="#f59e0b" stroke-width="2" stroke-dasharray="4 3"/><line x1="240" y1="45" x2="370" y2="105" stroke="#b8bfcc" stroke-width="1.5"/>
        <line x1="110" y1="118" x2="65" y2="168" stroke="#d9dde6" stroke-width="1"/><line x1="110" y1="118" x2="155" y2="168" stroke="#d9dde6" stroke-width="1"/><line x1="240" y1="121" x2="240" y2="168" stroke="#d9dde6" stroke-width="1"/><line x1="370" y1="118" x2="325" y2="168" stroke="#d9dde6" stroke-width="1"/><line x1="370" y1="118" x2="415" y2="168" stroke="#d9dde6" stroke-width="1"/>
        <circle cx="240" cy="33" r="18" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/><text x="240" y="29" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">CORE</text><text x="240" y="40" text-anchor="middle" fill="#2356a8" font-size="7" font-family="DM Mono">RTR-01</text>
        <rect x="84" y="105" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/><text x="110" y="119" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-W</text>
        <rect x="214" y="108" width="52" height="22" rx="5" fill="#fff8ea" stroke="#b06a00" stroke-width="1.5"/><text x="240" y="122" text-anchor="middle" fill="#7a4a00" font-size="9" font-family="DM Mono">DIST-C⚠</text>
        <rect x="344" y="105" width="52" height="22" rx="5" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/><text x="370" y="119" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-E</text>
        <circle cx="65" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/><circle cx="155" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/><circle cx="240" cy="175" r="9" fill="#fef5f5" stroke="#c0392b" stroke-width="1.5"/><circle cx="325" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/><circle cx="415" cy="175" r="9" fill="#edfaf4" stroke="#1e8f55" stroke-width="1"/>
        <text x="240" y="192" text-anchor="middle" fill="#c0392b" font-size="7" font-family="DM Mono">DOWN</text></svg></div>""",unsafe_allow_html=True)
    with c2:
        st.markdown("**🚨 Alerts**")
        for s,t,m,tm in [("🔴","BGP flapping — PE-MUM-01","Routing · 142 prefixes","2m"),("🔴","Interface Down — SW-ACC-14","Access · VLAN 120","8m"),("🟡","High CPU CORE-RTR-01 88%","OSPF SPF recalc","14m"),("🟡","VPN Tunnel Down Branch-HYD","IPSec DPD timeout","45m")]:
            a,b,c=st.columns([.08,.74,.18]); a.write(s); b.markdown(f"**{t}**\n*{m}*"); c.caption(f"`{tm}`"); st.divider()

    devs = db_get_devices()
    if devs: st.dataframe(pd.DataFrame(devs)[["hostname","ip","vendor","role","site"]],use_container_width=True,hide_index=True)

    st.markdown("**⚡ Quick Actions**")
    qc=st.columns(4)
    with qc[0]:
        if st.button("🔧 Diagnose BGP",use_container_width=True): go("BGP flapping on PE-MUM-01 AS65002. Root cause and fix.")
    with qc[1]:
        if st.button("⚡ All devices BGP",use_container_width=True): go("Show BGP summary all devices","MDQ")
    with qc[2]:
        if st.button("📋 Compliance",use_container_width=True): go("Compliance gap analysis top 5 fixes")
    with qc[3]:
        if st.button("🏗 SD-WAN design",use_container_width=True): go("Design SD-WAN 50 branches dual ISP Azure SASE")

elif pg == "Chat":
    p_l = {"ccna":"CCNA","noc":"NOC Engineer","arch":"Architect"}
    st.markdown('<div class="sh">🤖 AI Network Assistant</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="ss">NLP · RAG · Incident Memory · Claude · Persona: <strong>{p_l[st.session_state.persona]}</strong></div>',unsafe_allow_html=True)
    qc=st.columns(5)
    for col,(l,p) in zip(qc,[("BGP not forming","Why is BGP not establishing with ISP?"),("BGP all devs","Show BGP summary all devices"),("OSPF DR","Explain OSPF DR election"),("Gen OSPF cfg","Generate Cisco IOS-XR OSPF area 0 Gi0/0/0 MD5 config"),("SD-WAN design","Design SD-WAN 50 branches dual ISP SASE Azure")]):
        with col:
            if st.button(l,use_container_width=True,key=f"qk{l}"): go(p)
    st.divider()
    if not st.session_state.chat_msgs:
        st.info("👋 **NetBrain AI** — NLP + RAG + Multi-Device + Claude. Ask anything about networking.")
    for m in st.session_state.chat_msgs: render_msg(m["role"],m["content"],m.get("meta"))
    st.divider()
    ci,cb=st.columns([.87,.13])
    with ci: ui=st.text_area("",placeholder="Ask anything — configs, logs, design, troubleshoot…",height=80,label_visibility="collapsed",key="ci")
    with cb:
        st.markdown("<br>",unsafe_allow_html=True)
        if st.button("Send ➤",use_container_width=True,type="primary") and ui.strip(): go(ui.strip(),"Chat")
    if st.button("🗑 Clear",key="clr"):
        st.session_state.chat_msgs=[]; st.session_state.chat_hist=[]; st.rerun()

elif pg == "MDQ":
    st.markdown('<div class="sh">⚡ Multi-Device Query</div>',unsafe_allow_html=True)
    st.markdown('<div class="ss">System B — One query → all devices parallel SSH → AI synthesises</div>',unsafe_allow_html=True)
    ai_bar("Netmiko SSH — System B","Ask: <strong>'Show OSPF neighbors all routers'</strong> — I SSH all devices simultaneously and give one unified answer.")
    qc=st.columns(5)
    for col,(l,q) in zip(qc,[("BGP summary","Show BGP summary all routers"),("OSPF neighbors","Show OSPF neighbors all devices"),("CPU","Show CPU all devices"),("Interfaces","Show interface status"),("VLANs","Show VLAN brief all switches")]):
        with col:
            if st.button(l,key=f"mdqq{l}",use_container_width=True): st.session_state["_mdqf"]=q
    mq=st.text_input("Query",value=st.session_state.pop("_mdqf",""),placeholder='"Which routers have BGP Active state?" · "Show OSPF neighbors"')
    if st.button("⚡ Query All Devices",type="primary") and mq.strip():
        with st.spinner("⚡ Querying all devices…"):
            st.session_state.mdq_res = run_mdq(mq.strip(), st.session_state.persona)
    if st.session_state.mdq_res:
        res=st.session_state.mdq_res
        st.success(f"✓ {res['device_count']} devices queried")
        devrs=res.get("device_results",[])
        if devrs:
            cols=st.columns(min(len(devrs),3))
            for i,d in enumerate(devrs):
                with cols[i%3]:
                    cls="dok" if d["status"]=="ok" else "derr"
                    s=" · sim" if d.get("simulated") else ""
                    st.markdown(f'<div class="dc {cls}"><div class="dhn">{d["hostname"]} ({d["ip"]})</div><div style="font-size:11px;color:#7a8799;font-family:DM Mono,monospace">{d.get("vendor","")} · {d.get("role","")}{s}</div><div style="font-size:11px;color:#4a5568;font-family:DM Mono,monospace">CMD:{d["command"]}</div><div class="dout">{d["output"][:280]}</div></div>',unsafe_allow_html=True)
        st.markdown("---"); st.markdown("**🧠 AI Synthesis**"); st.markdown(res.get("ai_synthesis",""))

elif pg == "NLP":
    st.markdown('<div class="sh">🧬 NLP Entity Extractor</div>',unsafe_allow_html=True)
    st.markdown('<div class="ss">System C — Extracts IPs VLANs protocols hostnames intent from any text</div>',unsafe_allow_html=True)
    ai_bar("spaCy + Regex — System C","Paste any log config or query — entities extracted automatically and injected into every Claude call.")
    sc=st.columns(3)
    samples={"BGP log":"BGP neighbor 10.0.1.1 AS65002 stuck Active on GigabitEthernet0/0/0 PE-MUM-01 area 0 VLAN 100","OSPF":"OSPF adjacency lost CORE-RTR-01 DIST-SW-W 192.168.1.0/30 area 0 Cisco IOS-XR","Design":"Design VXLAN EVPN leaf-spine Arista EOS BGP EVPN RoCE GPU cluster"}
    for col,(n,t) in zip(sc,samples.items()):
        with col:
            if st.button(n,key=f"ns{n}",use_container_width=True): st.session_state["_nlpf"]=t
    nt=st.text_area("Paste text",value=st.session_state.pop("_nlpf",""),placeholder="BGP neighbor 10.0.1.1 AS65002…",height=90)
    if st.button("🧬 Extract",type="primary") and nt: st.session_state.nlp_res=extract_entities(nt)
    if st.session_state.nlp_res:
        e=st.session_state.nlp_res
        m1,m2,m3=st.columns(3)
        m1.metric("Intent",e.get("intent","general").replace("_"," ").title())
        m2.metric("Urgency",e.get("urgency","normal").title())
        m3.metric("Persona Hint",e.get("persona_hint") or "Auto")
        st.divider()
        cats=[("IPs","ip_addresses"),("Protocols","protocols"),("Interfaces","interfaces"),("VLANs","vlans"),("AS#","as_numbers"),("Vendors","vendors"),("Devices","hostnames"),("OSPF Areas","ospf_areas")]
        cols=st.columns(4)
        for i,(lbl,key) in enumerate(cats):
            with cols[i%4]:
                st.markdown(f"**{lbl}**")
                items=e.get(key,[])
                st.markdown(" ".join(f'<span class="et">{x}</span>' for x in items) if items else "*none*",unsafe_allow_html=True)

elif pg == "RAG":
    st.markdown('<div class="sh">📚 RAG Knowledge Base</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="ss">System D — Mode: <strong>{"ChromaDB" if RAG_OK else "Keyword fallback"}</strong> · 7 topics pre-loaded</div>',unsafe_allow_html=True)
    ai_bar("RAG — System D","Search the knowledge base or add your own vendor docs runbooks and SOPs.")
    t1,t2=st.tabs(["🔍 Search","➕ Ingest"])
    with t1:
        rq=st.text_input("Search",placeholder="BGP troubleshooting · OSPF states · SD-WAN · MPLS…")
        if st.button("📚 Search",type="primary") and rq:
            with st.spinner("Searching…"): st.session_state.rag_res=rag_search(rq,5)
        if st.session_state.rag_res:
            for r in st.session_state.rag_res:
                m=r.get("meta",{})
                st.markdown(f'<div class="rc"><div class="rs">📚 {m.get("title","Doc")} · chunk {m.get("chunk",0)}</div><div class="rb">{r.get("content","")[:400]}</div></div>',unsafe_allow_html=True)
        else:
            st.markdown("**Pre-loaded topics:**")
            tc=st.columns(4)
            for i,t in enumerate(KB.keys()):
                with tc[i%4]: st.markdown(f'<div class="rc"><div class="rs">📚 knowledge</div><div style="font-size:13px;font-weight:600">{t}</div></div>',unsafe_allow_html=True)
    with t2:
        it=st.text_input("Title",placeholder="Juniper BGP Guide")
        ic1,ic2=st.columns(2)
        iv=ic1.selectbox("Vendor",["cisco","juniper","arista","paloalto","fortinet","general"])
        idt=ic2.selectbox("Type",["manual","runbook","design","reference","sop"])
        ico=st.text_area("Content",placeholder="Paste full document…",height=180)
        if st.button("➕ Ingest",type="primary") and ico and it:
            with st.spinner("Indexing…"):
                n=ingest_doc(it,ico,iv,idt)
            st.success(f"✅ {n} chunks ingested" if n else "✅ Stored in keyword base")

elif pg == "CLI":
    st.markdown('<div class="sh">💻 CLI Assistant</div>',unsafe_allow_html=True)
    st.markdown('<div class="ss">NL → CLI · Multi-vendor · AI-explained</div>',unsafe_allow_html=True)
    ai_bar("NL→CLI Engine","Type plain English → exact CLI. Or paste a command → I explain it.")
    cv,ct=st.columns(2)
    ven=cv.selectbox("Vendor",["Cisco IOS","Cisco IOS-XR","Cisco NX-OS","Juniper JunOS","Arista EOS","Palo Alto","Fortinet"])
    tsk=ct.selectbox("Task",["NL to CLI","Explain command","Review config","Generate config block"])
    ci2=st.text_area("Request",placeholder="'Configure eBGP neighbor 10.0.1.1 AS65002 MD5 auth BFD'",height=100)
    if st.button("🧠 Generate",type="primary") and ci2:
        with st.spinner("🧠 Generating…"):
            resp=call_claude([{"role":"user","content":f"Vendor:{ven}. Task:{tsk}.\n\n{ci2}\n\nExact CLI with explanation of each line."}],st.session_state.persona)
        st.markdown(resp)

elif pg == "Troubleshoot":
    st.markdown('<div class="sh">🔧 AI Troubleshooting</div>',unsafe_allow_html=True)
    ai_bar("4-Engine Pipeline","<strong>NLP</strong>→<strong>RAG</strong>→<strong>Memory</strong>→<strong>Claude</strong>. Root cause + fix commands.")
    c1,c2=st.columns(2)
    with c1:
        prob=st.text_area("Problem",placeholder="'BGP flapping to ISP 2 hours, CPU 88%, no config changes'",height=110)
        v,s=st.columns(2)
        ven2=v.selectbox("Vendor",["Any","Cisco IOS/IOS-XR","Juniper","Arista","Palo Alto","Fortinet"])
        sev=s.selectbox("Severity",["Unknown","🔴 Critical","🟡 Major","🟢 Minor"])
        if st.button("🧠 Analyze — 4 Engines",type="primary") and prob: go(f"Problem:{prob}\nVendor:{ven2}\nSeverity:{sev}")
    with c2:
        st.markdown("**Common issues:**")
        for l,p in [("BGP stuck Active","BGP neighbor stuck Active state Cisco IOS-XR troubleshoot"),
                    ("OSPF EXSTART","OSPF stuck EXSTART MTU mismatch diagnose fix"),
                    ("VLAN trunk issue","VLAN not passing trunk links STP or allowed VLAN"),
                    ("SD-WAN failover","SD-WAN failover not switching to backup ISP"),
                    ("MPLS packet loss","High packet loss MPLS backbone LSP ping trace"),
                    ("IPSec flapping","IPSec VPN flapping DPD timeout stabilize"),
                    ("STP loop","Spanning tree loop find blocking port immediately")]:
            if st.button(l,key=f"ts{l}",use_container_width=True): go(p)

elif pg == "Design":
    st.markdown('<div class="sh">🏗 Network Design</div>',unsafe_allow_html=True)
    ai_bar("Design AI","Requirements → Architecture → BOM → Roadmap. Plain English input.")
    des=[("🏢 Campus","Design enterprise campus 3000 users 3-tier SD-Access wireless Zero Trust"),("🛣️ SD-WAN","Design SD-WAN 50 branches dual ISP Azure SASE app-SLA"),("🏭 Datacenter","Design leaf-spine VXLAN EVPN 10000 servers AI GPU RoCE"),("☁️ Hybrid Cloud","Design hybrid cloud on-prem AWS Azure Direct Connect ExpressRoute"),("🔐 Zero Trust","Design Zero Trust ZTNA micro-segmentation Palo Alto Zscaler"),("📡 5G SP","Design 5G transport SR-MPLS SRv6 slicing mobile backhaul")]
    cols_d=st.columns(3)
    for i,(l,p) in enumerate(des):
        with cols_d[i%3]:
            if st.button(l,key=f"ds{l}",use_container_width=True): go(p)
    st.divider()
    cust=st.text_area("Custom requirements",placeholder="Describe your specific design needs…",height=100)
    if st.button("🏗 Generate Architecture",type="primary") and cust: go(cust)

elif pg == "Learn":
    st.markdown('<div class="sh">📖 Learning Hub</div>',unsafe_allow_html=True)
    ai_bar("Adaptive NLP Learning","Ask <strong>'what is a VLAN?'</strong> → teach from scratch. Ask <strong>'explain Q-in-Q'</strong> → expert level. Automatic.")
    tracks=[("🌐","Routing","OSPF BGP EIGRP IS-IS Policy",65,"Start routing lesson detect my level"),("🔀","Switching","STP EtherChannel VTP RSTP",40,"Teach switching VLANs STP EtherChannel"),("🛣️","SD-WAN","Viptela Versa Cato Zscaler",20,"Explain SD-WAN concepts Cisco Viptela SASE"),("🔒","Security","Zero Trust ZTNA Firewall ACL",55,"Teach network security Zero Trust ZTNA"),("🏢","Datacenter","VXLAN EVPN Leaf-Spine RoCE",10,"Explain VXLAN EVPN leaf-spine CCNA level"),("☁️","Cloud","AWS Azure GCP Kubernetes",30,"Teach cloud networking AWS VPC Azure VNet")]
    tc=st.columns(3)
    for i,(ico,n,d,pct,p) in enumerate(tracks):
        with tc[i%3]:
            st.markdown(f"**{ico} {n}**\n\n*{d}*"); st.progress(pct/100); st.caption(f"{pct}% complete")
            if st.button(f"Start {n}",key=f"tk{n}",use_container_width=True): go(p)

elif pg == "Devices":
    st.markdown('<div class="sh">🖧 Device Manager</div>',unsafe_allow_html=True)
    t1,t2=st.tabs(["📋 Devices","➕ Add"])
    with t1:
        devs=db_get_devices()
        if devs: st.dataframe(pd.DataFrame(devs)[["hostname","ip","vendor","role","site","port"]],use_container_width=True,hide_index=True)
        st.caption(f"{'Live SSH' if NETMIKO_OK else '⚡ Simulation mode'}")
    with t2:
        c1,c2,c3=st.columns(3)
        hn=c1.text_input("Hostname",placeholder="CORE-RTR-01"); ip=c1.text_input("IP",placeholder="10.0.0.1")
        ven=c2.selectbox("Vendor",["cisco_ios","cisco_ios_xe","cisco_ios_xr","cisco_nxos","juniper_junos","arista_eos","paloalto_panos","fortinet"])
        role=c2.text_input("Role",placeholder="Core Router")
        usr=c3.text_input("Username",placeholder="admin"); pwd=c3.text_input("Password",type="password")
        site=c3.text_input("Site",placeholder="HQ"); port=c3.number_input("Port",value=22,min_value=1)
        if st.button("➕ Add Device",type="primary"):
            if hn and ip: db_add_device(hn,ip,ven,usr,pwd,int(port),role,site); st.success(f"✅ Added {hn}"); st.rerun()
            else: st.error("Hostname and IP required.")

elif pg == "Compliance":
    st.markdown('<div class="sh">🛡 Compliance</div>',unsafe_allow_html=True)
    mrow([("CIS","91%","23 violations","mcg","vg"),("NIST CSF","78%","Identity gap","mca","va"),("PCI DSS","96%","Compliant","mcg","vg"),("Zero Trust","62%","Partial","mca","va")])
    if st.button("🧠 AI Gap Analysis",type="primary"): go("Full compliance gap analysis CIS NIST PCI Zero Trust. Top 5 gaps remediation steps.")

elif pg == "Alerts":
    st.markdown('<div class="sh">🚨 Alerts & Outages</div>',unsafe_allow_html=True)
    ai_bar("AI Correlation","<strong>7 alerts → 2 root causes.</strong> Primary: ISP→BGP flap→OSPF recalc→high CPU. Secondary: physical failure SW-ACC-14. Fix roots not symptoms.")
    for s,t,m,tm,p in [("🔴","BGP flapping PE-MUM-01→AS65002","Routing · 3 flaps/hr · 142 prefixes","2m","BGP flapping PE-MUM-01 AS65002 root cause fix"),("🔴","Interface Down Gi0/0/3 SW-ACC-14","Access · VLAN 120 · 47 users","8m","Interface Gi0/0/3 down SW-ACC-14 troubleshoot"),("🔴","Lateral Movement 10.2.14.0/24","Security · Port scan","22m","Lateral movement 10.2.14.0/24 immediate action"),("🟡","High CPU CORE-RTR-01 88%","OSPF SPF recalc","14m","High CPU 88% CORE-RTR-01 OSPF SPF"),("🟡","OSPF Neighbor Timeout Area 0","DR/BDR election","31m","OSPF timeout area 0 diagnose"),("🟡","VPN Down Branch-HYD","IPSec DPD","45m","IPSec VPN down Branch-HYD DPD fix"),("🟡","14 Unpatched CVEs Edge","3 critical","2h","14 CVEs edge devices prioritize patch")]:
        with st.expander(f"{s} {t}",expanded=s=="🔴"):
            ca,cb=st.columns([.8,.2]); ca.markdown(f"**{m}** · *{tm} ago*")
            if cb.button("🧠 Diagnose",key=f"al{t[:12]}",use_container_width=True): go(p)

elif pg == "Security":
    st.markdown('<div class="sh">🔒 Security Ops</div>',unsafe_allow_html=True)
    mrow([("Threats","2","Lateral movement","mcr","vr"),("CVEs","14","3 critical","mca","va"),("FW Rules","98%","Optimized","mcg","vg"),("Zero Trust","62%","Improving","mcb","vb")])
    if st.button("🧠 Security Audit",type="primary"): go("Full security posture: lateral movement CVEs firewall gaps Zero Trust readiness. Prioritize.")

elif pg == "Automation":
    st.markdown('<div class="sh">⚙ Automation</div>',unsafe_allow_html=True)
    mrow([("Jobs/Week","342","99.7% success","mcg","vg"),("Running","3","Config push","mcb","vb"),("Self-Healed","12","Auto-fixed","mca","va"),("Failed","1","Review needed","mcr","vr")])
    ac=st.columns(2)
    for col,(l,p) in zip(ac*2,[("Ansible OSPF","Generate Ansible playbook OSPF area 0 10 Cisco IOS-XR routers MD5 BFD"),("Ansible BGP","Generate Ansible playbook eBGP neighbor 10.0.1.1 AS65002 route-map prefix-list"),("Python backup","Generate Python netmiko script backup running configs all devices"),("Terraform VPC","Generate Terraform AWS VPC Transit Gateway BGP SD-WAN integration")]):
        with col:
            if st.button(f"🧠 {l}",key=f"auto{l}",use_container_width=True): go(p)

elif pg == "Twin":
    st.markdown('<div class="sh">👾 Digital Twin</div>',unsafe_allow_html=True)
    ai_bar("Digital Twin","Ask <strong>'What if PE-MUM-01 fails?'</strong> → simulate failure show services failover time mitigation.")
    mrow([("Cloned","847","Devices","mcb","vb"),("Accuracy","99.2%","Config sync","mcg","vg"),("Simulations","3","Active","mca","va"),("Tested","47","This month","mcg","vg")])
    sc=st.columns(2)
    for col,(l,p) in zip(sc*2,[("CORE-RTR-01 failure","Simulate CORE-RTR-01 complete failure services failover recommendations"),("ISP link failure","Blast radius ISP link PE-MUM-01 completely down"),("Add OSPF area 10","Validate adding OSPF area 10 before production"),("Firmware upgrade","Simulate firmware upgrade PE-MUM-01 7.5 to 7.7 predict risk")]):
        with col:
            if st.button(f"▶ {l}",key=f"tw{l}",use_container_width=True): go(p)

elif pg == "Topology":
    st.markdown('<div class="sh">🗺 Topology</div>',unsafe_allow_html=True)
    st.markdown("""<div style="background:#f7f8fa;border:1px solid #d9dde6;border-radius:12px;overflow:hidden;padding:10px"><svg viewBox="0 0 700 340" width="100%" xmlns="http://www.w3.org/2000/svg"><rect width="700" height="340" fill="#f7f8fa"/>
    <ellipse cx="350" cy="25" rx="65" ry="18" fill="#f5f0fd" stroke="#6b35b5" stroke-width="1" stroke-dasharray="4 3"/><text x="350" y="29" text-anchor="middle" fill="#6b35b5" font-size="10" font-family="DM Mono">INTERNET/ISP</text>
    <line x1="350" y1="43" x2="350" y2="72" stroke="#6b35b5" stroke-width="1.5"/>
    <rect x="315" y="72" width="70" height="22" rx="5" fill="#f5f0fd" stroke="#6b35b5" stroke-width="1"/><text x="350" y="86" text-anchor="middle" fill="#4a2080" font-size="9" font-family="DM Mono">FW-EDGE-01</text>
    <line x1="350" y1="94" x2="180" y2="138" stroke="#b8bfcc" stroke-width="1.5"/><line x1="350" y1="94" x2="350" y2="138" stroke="#b8bfcc" stroke-width="2"/><line x1="350" y1="94" x2="520" y2="138" stroke="#b8bfcc" stroke-width="1.5"/>
    <circle cx="180" cy="155" r="20" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/><text x="180" y="152" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">CORE</text><text x="180" y="163" text-anchor="middle" fill="#2356a8" font-size="7" font-family="DM Mono">RTR-01</text>
    <circle cx="350" cy="155" r="20" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/><text x="350" y="152" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">PE-MUM</text><text x="350" y="163" text-anchor="middle" fill="#2356a8" font-size="7" font-family="DM Mono">01</text>
    <circle cx="520" cy="155" r="20" fill="#e4edfc" stroke="#2356a8" stroke-width="1.5"/><text x="520" y="152" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">PE-DEL</text><text x="520" y="163" text-anchor="middle" fill="#2356a8" font-size="7" font-family="DM Mono">01</text>
    <line x1="180" y1="175" x2="120" y2="220" stroke="#d9dde6" stroke-width="1"/><line x1="180" y1="175" x2="240" y2="220" stroke="#d9dde6" stroke-width="1"/><line x1="350" y1="175" x2="350" y2="220" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="4 3"/><line x1="520" y1="175" x2="460" y2="220" stroke="#d9dde6" stroke-width="1"/><line x1="520" y1="175" x2="580" y2="220" stroke="#d9dde6" stroke-width="1"/>
    <rect x="94" y="220" width="52" height="20" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/><text x="120" y="233" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-W</text>
    <rect x="214" y="220" width="52" height="20" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/><text x="240" y="233" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-E</text>
    <rect x="324" y="220" width="52" height="20" rx="4" fill="#fff8ea" stroke="#b06a00" stroke-width="1.5"/><text x="350" y="233" text-anchor="middle" fill="#7a4a00" font-size="9" font-family="DM Mono">DIST-C⚠</text>
    <rect x="434" y="220" width="52" height="20" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/><text x="460" y="233" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-N</text>
    <rect x="554" y="220" width="52" height="20" rx="4" fill="#e4edfc" stroke="#2356a8" stroke-width="1"/><text x="580" y="233" text-anchor="middle" fill="#1e4080" font-size="9" font-family="DM Mono">DIST-S</text>
    <line x1="120" y1="240" x2="80" y2="285" stroke="#eef0f4" stroke-width="1"/><line x1="120" y1="240" x2="160" y2="285" stroke="#eef0f4" stroke-width="1"/>
    <rect x="64" y="285" width="32" height="15" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="80" y="296" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-1</text>
    <rect x="144" y="285" width="32" height="15" rx="3" fill="#edfaf4" stroke="#1e8f55" stroke-width=".8"/><text x="160" y="296" text-anchor="middle" fill="#14613a" font-size="7" font-family="DM Mono">ACC-2</text>
    <rect x="184" y="285" width="32" height="15" rx="3" fill="#fef5f5" stroke="#c0392b" stroke-width="1.2"/><text x="200" y="294" text-anchor="middle" fill="#8b1a1a" font-size="7" font-family="DM Mono">ACC-14↓</text>
    </svg></div>""",unsafe_allow_html=True)
    tq=st.text_input("Ask about topology",placeholder="'Single points of failure' · 'OSPF area 0 devices' · 'Path Branch to HQ'")
    if st.button("🧠 Analyze",type="primary") and tq: go(tq)

elif pg == "Exec":
    st.markdown('<div class="sh">📈 Executive Dashboard</div>',unsafe_allow_html=True)
    mrow([("Uptime","99.94%","SLA 99.9% ✅","mcg","vg"),("MTTR","18m","↓ 40% vs last qtr","mcb","vb"),("Risk","Medium","14 CVEs · 2 threats","mca","va"),("Automation","78%","↑ 12% this qtr","mcg","vg")])
    if st.button("🧠 Board Report",type="primary"): go("Executive board report: uptime MTTR risks automation ROI recommended investments 90-day outlook.","arch")

elif pg == "FinOps":
    st.markdown('<div class="sh">💰 FinOps & Cost</div>',unsafe_allow_html=True)
    mrow([("Annual Spend","$4.2M","Within budget","mcb","vb"),("Savings","$380K","Identified","mcg","vg"),("EoL Devices","34","Need replacement","mca","va"),("Wasted Lic.","18%","Unused","mcr","vr")])
    if st.button("🧠 Cost Analysis",type="primary"): go("Network cost analysis. Top 5 optimization: license consolidation hardware rightsizing cloud cost automation ROI vendor negotiation.")
