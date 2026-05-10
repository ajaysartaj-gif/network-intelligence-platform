"""
engines/core.py
All 4 AI systems — Claude, Multi-Device, NLP, RAG
Streamlit-compatible: uses st.session_state for persistence
"""

import os, re, json, threading, hashlib, sqlite3
from datetime import datetime

import streamlit as st

# ── Safe imports ──────────────────────────────────────────
try:
    import anthropic
    CLAUDE_OK = True
except ImportError:
    CLAUDE_OK = False

try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    SPACY_OK = True
except Exception:
    SPACY_OK = False
    _nlp = None

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    RAG_OK = True
except Exception:
    RAG_OK = False

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_OK = True
except ImportError:
    NETMIKO_OK = False

DB_PATH = "netbrain.db"


# ══════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL, ip TEXT NOT NULL,
            vendor TEXT DEFAULT 'cisco_ios', username TEXT, password TEXT,
            port INTEGER DEFAULT 22, role TEXT, site TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, description TEXT, root_cause TEXT,
            resolution TEXT, devices TEXT, protocols TEXT, severity TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT, content TEXT, persona TEXT, meta TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT, device_count INTEGER, ai_result TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Seed devices
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM devices")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site) VALUES(?,?,?,?,?,?,?,?)",
            [
                ("CORE-RTR-01","10.0.0.1","cisco_ios_xr","admin","admin123",22,"Core Router","HQ"),
                ("PE-MUM-01","10.0.1.1","cisco_ios_xr","admin","admin123",22,"PE Router","Mumbai"),
                ("PE-DEL-01","10.0.2.1","cisco_ios_xr","admin","admin123",22,"PE Router","Delhi"),
                ("DIST-SW-W","10.1.1.1","cisco_ios","admin","admin123",22,"Dist Switch","HQ-West"),
                ("FW-EDGE-01","192.168.1.1","paloalto_panos","admin","admin123",22,"Firewall","DMZ"),
            ]
        )
    cur.execute("SELECT COUNT(*) FROM incidents")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO incidents(title,description,root_cause,resolution,devices,protocols,severity) VALUES(?,?,?,?,?,?,?)",
            [
                ("BGP session flapping","PE-MUM-01 BGP to AS65002 flapping 3x/hr",
                 "Upstream ISP BGP prefix withdrawal","Increased hold timer to 90s, opened ISP ticket",
                 "PE-MUM-01","BGP","critical"),
                ("OSPF adjacency lost","CORE-RTR-01 OSPF neighbor down with DIST-SW-W",
                 "MTU mismatch on GigabitEthernet interface","Added ip ospf mtu-ignore",
                 "CORE-RTR-01,DIST-SW-W","OSPF","major"),
                ("VLAN 100 traffic drop","Users in VLAN 100 cannot reach gateway",
                 "VLAN 100 not in allowed trunk list","Added VLAN 100 to trunk allowed list",
                 "DIST-SW-W","VLAN,STP","major"),
            ]
        )
    con.commit()
    con.close()


def get_devices():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM devices").fetchall()
    con.close()
    return [dict(r) for r in rows]


def add_device(hostname, ip, vendor, username, password, port, role, site):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site) VALUES(?,?,?,?,?,?,?,?)",
        (hostname, ip, vendor, username, password, port, role, site)
    )
    con.commit()
    con.close()


def get_incidents():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 30").fetchall()
    con.close()
    return [dict(r) for r in rows]


def save_chat(role, content, persona="noc", meta=None):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO chat_history(role,content,persona,meta) VALUES(?,?,?,?)",
        (role, content, persona, json.dumps(meta or {}))
    )
    con.commit()
    con.close()


# ══════════════════════════════════════════════════════════
# SYSTEM A — CLAUDE API
# ══════════════════════════════════════════════════════════

NETWORK_SYSTEM = """You are NetBrain AI — an autonomous AI brain for enterprise and telecom networking.

Deep expertise across: OSPF, BGP, EIGRP, IS-IS, MPLS, SRv6, Segment Routing, VLANs, STP,
EtherChannel, VXLAN, EVPN, SD-WAN (Viptela/Versa/VeloCloud), SASE, Zero Trust, ZTNA,
Firewall, ACL, IPSec, Datacenter (Leaf-Spine, ACI, RoCE), Cloud (AWS VPC, Azure VNet, GCP),
Kubernetes networking, Service Provider (L3VPN, L2VPN, SR-MPLS, SRv6, 5G transport), Wireless.

Vendors: Cisco, Juniper, Arista, Palo Alto, Fortinet, Aruba, Nokia, Huawei, Versa, Zscaler.

When entities like IPs, hostnames, VLANs, protocols are mentioned — reason about them specifically.
Always include CLI commands. Format with headers and code blocks."""

PERSONA = {
    "ccna": "You are helping a CCNA-level engineer. Explain everything with analogies and step-by-step guidance. Define every acronym. Show CLI with explanation of what each line does. Be encouraging.",
    "noc":  "You are helping a NOC engineer during operations. Be concise and action-oriented. Lead with probable root cause. Give exact CLI to verify and fix. Include rollback steps.",
    "arch": "You are helping a senior network architect. Skip basics. Focus on design trade-offs, scalability, HA, vendor differences. Reference RFCs. Provide BOM context when designing."
}


def call_claude(messages: list, persona: str = "noc", max_tokens: int = 2000) -> str:
    """Core Claude API call — returns response text."""
    api_key = st.secrets.get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
    if not CLAUDE_OK or not api_key:
        return "⚠️ Claude API not configured. Add ANTHROPIC_API_KEY to `.streamlit/secrets.toml`."
    try:
        client = anthropic.Anthropic(api_key=api_key)
        system = NETWORK_SYSTEM + "\n\n" + PERSONA.get(persona, PERSONA["noc"])
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system,
            messages=messages
        )
        return resp.content[0].text
    except Exception as e:
        return f"❌ Claude API error: {e}"


# ══════════════════════════════════════════════════════════
# SYSTEM B — MULTI-DEVICE QUERY ENGINE
# ══════════════════════════════════════════════════════════

NL_CMD_MAP = {
    "bgp summary":      {"cisco_ios":"show ip bgp summary","cisco_ios_xr":"show bgp all summary","cisco_ios_xe":"show ip bgp summary","juniper_junos":"show bgp summary","arista_eos":"show bgp summary","cisco_nxos":"show bgp all summary"},
    "bgp neighbor":     {"cisco_ios":"show ip bgp neighbors","cisco_ios_xr":"show bgp neighbors","cisco_ios_xe":"show ip bgp neighbors","juniper_junos":"show bgp neighbor","arista_eos":"show bgp neighbors","cisco_nxos":"show bgp neighbors"},
    "ospf neighbor":    {"cisco_ios":"show ip ospf neighbor","cisco_ios_xr":"show ospf neighbor","cisco_ios_xe":"show ip ospf neighbor","juniper_junos":"show ospf neighbor","arista_eos":"show ip ospf neighbor","cisco_nxos":"show ip ospf neighbors"},
    "interface status": {"cisco_ios":"show interfaces status","cisco_ios_xr":"show interfaces brief","cisco_ios_xe":"show interfaces status","juniper_junos":"show interfaces terse","arista_eos":"show interfaces status","cisco_nxos":"show interface status"},
    "cpu":              {"cisco_ios":"show processes cpu sorted","cisco_ios_xr":"show processes cpu","cisco_ios_xe":"show processes cpu sorted","juniper_junos":"show chassis routing-engine","arista_eos":"show processes top once","cisco_nxos":"show processes cpu sort"},
    "routing table":    {"cisco_ios":"show ip route","cisco_ios_xr":"show route ipv4","cisco_ios_xe":"show ip route","juniper_junos":"show route","arista_eos":"show ip route","cisco_nxos":"show ip route"},
    "vlan":             {"cisco_ios":"show vlan brief","cisco_ios_xr":"show vlan","cisco_ios_xe":"show vlan brief","juniper_junos":"show vlans","arista_eos":"show vlan","cisco_nxos":"show vlan"},
    "version":          {"cisco_ios":"show version","cisco_ios_xr":"show version","cisco_ios_xe":"show version","juniper_junos":"show version","arista_eos":"show version","cisco_nxos":"show version"},
    "log":              {"cisco_ios":"show logging | last 50","cisco_ios_xr":"show log | last 50","cisco_ios_xe":"show logging | last 50","juniper_junos":"show log messages | last 50","arista_eos":"show log last 50","cisco_nxos":"show log last 50"},
    "inventory":        {"cisco_ios":"show inventory","cisco_ios_xr":"show inventory","cisco_ios_xe":"show inventory","juniper_junos":"show chassis hardware","arista_eos":"show inventory","cisco_nxos":"show inventory"},
    "memory":           {"cisco_ios":"show memory statistics","cisco_ios_xr":"show memory summary","cisco_ios_xe":"show memory statistics","juniper_junos":"show system memory","arista_eos":"show version | grep Mem","cisco_nxos":"show system resources"},
}


def resolve_cmd(query: str, vendor: str) -> str:
    q = query.lower()
    for keyword, vmap in NL_CMD_MAP.items():
        if keyword in q:
            return vmap.get(vendor, vmap.get("cisco_ios", "show version"))
    if any(q.strip().startswith(p) for p in ["show","display","get","ping","trace","debug"]):
        return query.strip()
    return "show version"


def _sim_output(device: dict, command: str) -> dict:
    """Realistic simulated output when no real devices available."""
    h, ip = device.get("hostname","DEV"), device.get("ip","0.0.0.0")
    if "bgp" in command and "summary" in command:
        out = f"BGP router identifier {ip}, local AS 65001\nNeighbor     AS      Up/Down    State/PfxRcd\n10.0.0.1   65001   5d02h14   Established/142\n10.0.1.1   65002   0d00h04   Active\n10.0.2.1   65003   2d11h22   Established/87"
    elif "ospf" in command and "neighbor" in command:
        out = f"Neighbor ID   Pri  State         Dead Time  Address    Interface\n192.168.1.1    1  FULL/DR       00:00:38   10.1.1.1   Gi0/0\n192.168.1.2    1  FULL/BDR      00:00:39   10.1.1.2   Gi0/1\n192.168.1.3    0  EXSTART/-     00:00:40   10.1.1.3   Gi0/2"
    elif "cpu" in command or "process" in command:
        out = f"CPU utilization: 5sec 88%, 1min 75%, 5min 62%\nPID  5Sec  Process\n42   45%   OSPF-1 Hello\n103  22%   BGP Router\n201  12%   IP Input"
    elif "vlan" in command:
        out = f"VLAN  Name            Status   Ports\n1     default         active   Gi0/0,Gi0/1\n100   FINANCE         active   Gi0/3,Gi0/4\n120   BRANCH-HYD      suspend\n200   SERVERS         active   Gi1/0,Gi1/1"
    elif "interface" in command:
        out = f"Interface  Status    Protocol  Descr\nGi0/0      up        up        WAN-Uplink\nGi0/1      up        up        LAN-Core\nGi0/2      down      down      UNUSED\nGi0/3      admin dn  down      VLAN-120"
    else:
        out = f"Cisco IOS-XR Software, Version 7.5.2\nUptime: 127 days 4 hours\nProcessor: 88% CPU"
    return {"status": "ok", "output": out, "command": command, "simulated": True}


def _ssh_device(device: dict, command: str) -> dict:
    if not NETMIKO_OK:
        return _sim_output(device, command)
    try:
        params = {"device_type": device["vendor"], "host": device["ip"],
                  "username": device.get("username","admin"),
                  "password": device.get("password",""), "port": device.get("port",22),
                  "timeout": 15, "session_timeout": 15}
        with ConnectHandler(**params) as conn:
            out = conn.send_command(command, read_timeout=15)
        return {"status": "ok", "output": out, "command": command, "simulated": False}
    except NetmikoTimeoutException:
        return _sim_output(device, command)  # fall back to sim on timeout
    except NetmikoAuthenticationException:
        return {"status": "auth_err", "output": f"Auth failed for {device['hostname']}", "command": command, "simulated": False}
    except Exception as e:
        return _sim_output(device, command)


def run_multi_device_query(query: str, persona: str = "noc") -> dict:
    """
    System B — query all devices in parallel, synthesise with Claude.
    Returns: device_results list + ai_synthesis string
    """
    devices = get_devices()
    if not devices:
        return {"error": "No devices in database", "device_results": [], "ai_synthesis": ""}

    results, lock = [], threading.Lock()

    def query_one(dev):
        cmd = resolve_cmd(query, dev.get("vendor","cisco_ios"))
        out = _ssh_device(dev, cmd)
        with lock:
            results.append({
                "hostname": dev["hostname"], "ip": dev["ip"],
                "vendor": dev.get("vendor",""), "role": dev.get("role",""),
                "site": dev.get("site",""), "command": cmd,
                "status": out["status"], "output": out["output"],
                "simulated": out.get("simulated", True)
            })

    threads = [threading.Thread(target=query_one, args=(d,)) for d in devices]
    for t in threads: t.start()
    for t in threads: t.join(timeout=20)

    device_ctx = "\n\n".join(
        f"=== {r['hostname']} ({r['ip']}) | {r['vendor']} | {r['role']} ===\n"
        f"CMD: {r['command']}\n{r['output']}" for r in results
    )
    synthesis = call_claude([{"role":"user","content":
        f'Query: "{query}"\n\nDevice outputs ({len(results)} devices):\n{device_ctx}\n\n'
        f'Provide: 1) SUMMARY — direct answer  2) FINDINGS — anomalies per device  '
        f'3) RISKS  4) RECOMMENDED ACTIONS. Use device hostnames specifically.'}], persona=persona)

    con = sqlite3.connect(DB_PATH)
    con.execute("INSERT INTO query_log(query,device_count,ai_result) VALUES(?,?,?)",
                (query, len(results), synthesis))
    con.commit()
    con.close()

    return {"query": query, "device_count": len(results),
            "device_results": results, "ai_synthesis": synthesis}


# ══════════════════════════════════════════════════════════
# SYSTEM C — NLP ENTITY EXTRACTOR
# ══════════════════════════════════════════════════════════

_NET_REGEX = {
    "ip_addresses":  r'\b(?:\d{1,3}\.){3}\d{1,3}(?:\/\d{1,2})?\b',
    "interfaces":    r'\b(?:Gi|Fa|Te|Hu|Et|xe|ge|fe|em|Mg|Lo|Tu)\d+(?:[\/\-]\d+){0,3}\b',
    "vlans":         r'\bVLAN\s*\d+\b|\bvlan\s*\d+\b',
    "as_numbers":    r'\bAS\s*\d+\b|\bASN\s*\d+\b',
    "ospf_areas":    r'\barea\s*\d+\b',
    "hostnames":     r'\b[A-Z]{2,}[-_][A-Z0-9]{2,}[-_][A-Z0-9]+\b',
    "mac_addresses": r'\b(?:[0-9a-fA-F]{2}[:\-.]){5}[0-9a-fA-F]{2}\b',
}

PROTOCOLS = ["BGP","OSPF","EIGRP","IS-IS","ISIS","MPLS","EVPN","VXLAN","STP","RSTP","MSTP",
             "LACP","LLDP","CDP","BFD","HSRP","VRRP","GLBP","IPSec","GRE","DMVPN",
             "SD-WAN","SDWAN","SASE","ZTNA","QoS","DSCP","SRv6","SR-MPLS","VRF",
             "SNMP","NetFlow","CAPWAP","RADIUS","TACACS","AAA","NAT","ACL"]

VENDORS = ["Cisco","Juniper","Arista","Fortinet","Palo Alto","Aruba","Versa",
           "VMware","Meraki","Nokia","Huawei","Checkpoint","F5","Zscaler","Cato",
           "Netskope","Viptela","VeloCloud","NVIDIA","Mellanox"]

INTENTS = {
    "troubleshoot": ["not working","down","flapping","unstable","dropping","timeout","failed",
                     "error","issue","problem","debug","diagnose","why","fix","broken"],
    "generate_config": ["generate","create","write","configure","build config","give me config","produce"],
    "explain":      ["explain","what is","what does","how does","describe","tell me about","understand"],
    "design":       ["design","architect","plan","blueprint","recommend","best practice","topology"],
    "compare":      ["compare","difference","vs","versus","better","pros and cons","which is"],
    "query_devices":["show","check","fetch","across all","all devices","all routers","on all"],
    "analyze_log":  ["log","syslog","error message","show logging","alert","event"],
}


def extract_entities(text: str) -> dict:
    ents = {k: [] for k in _NET_REGEX}
    ents.update({"protocols":[],"vendors":[],"intent":"general","urgency":"normal","persona_hint":None})

    for key, pat in _NET_REGEX.items():
        ents[key] = list(dict.fromkeys(re.findall(pat, text, re.IGNORECASE)))

    tu = text.upper()
    ents["protocols"] = [p for p in PROTOCOLS if p.upper() in tu]
    ents["vendors"]   = [v for v in VENDORS if v.lower() in text.lower()]

    tl = text.lower()
    for intent, kws in INTENTS.items():
        if any(k in tl for k in kws):
            ents["intent"] = intent; break

    urgency_words = ["critical","urgent","down","outage","p1","p2","sev1","production","war room"]
    if any(w in tl for w in urgency_words):
        ents["urgency"] = "high"

    expert_words = ["sr-mpls","srv6","evpn","vxlan","route-reflector","bfd","lsdb","ted","rpvst"]
    beginner_words = ["what is","explain","how does","difference between","beginner","simple"]
    if any(w in tl for w in expert_words):   ents["persona_hint"] = "arch"
    elif any(w in tl for w in beginner_words): ents["persona_hint"] = "ccna"

    if SPACY_OK and _nlp:
        try:
            doc = _nlp(text[:4000])
            for ent in doc.ents:
                if ent.label_ in ("ORG","PRODUCT"):
                    for v in VENDORS:
                        if v.lower() in ent.text.lower() and v not in ents["vendors"]:
                            ents["vendors"].append(v)
        except Exception:
            pass

    return ents


def enrich_query(query: str, ents: dict) -> str:
    parts = []
    if ents["ip_addresses"]: parts.append(f"IPs: {', '.join(ents['ip_addresses'])}")
    if ents["interfaces"]:   parts.append(f"Interfaces: {', '.join(ents['interfaces'])}")
    if ents["vlans"]:        parts.append(f"VLANs: {', '.join(ents['vlans'])}")
    if ents["as_numbers"]:   parts.append(f"AS: {', '.join(ents['as_numbers'])}")
    if ents["protocols"]:    parts.append(f"Protocols: {', '.join(ents['protocols'])}")
    if ents["vendors"]:      parts.append(f"Vendors: {', '.join(ents['vendors'])}")
    if ents["hostnames"]:    parts.append(f"Devices: {', '.join(ents['hostnames'])}")
    if ents["ospf_areas"]:   parts.append(f"OSPF areas: {', '.join(ents['ospf_areas'])}")
    ctx = " | ".join(parts)
    return f"[NLP: {ctx}]\n\n{query}" if ctx else query


# ══════════════════════════════════════════════════════════
# SYSTEM D — RAG KNOWLEDGE BASE
# ══════════════════════════════════════════════════════════

_chroma_client = None
_embedder      = None
_collection    = None

KNOWLEDGE_SEED = [
    ("BGP Troubleshooting Guide", "cisco", "runbook", """
BGP neighbor states: Idle Connect Active OpenSent OpenConfirm Established.
Active state = TCP session not established. Check: ping peer IP, verify TCP 179 not blocked by ACL,
confirm remote-as matches, check MD5 auth password, verify update-source interface matches.
BGP Hold timer default 180s. BFD reduces detection to sub-second.
Commands: show bgp all summary, show bgp neighbors <ip>, debug ip bgp <ip> events.
Route not advertised: check network statement, route-map filter, next-hop reachability, auto-summary.
AS_PATH prepend: route-map SET_PREPEND permit 10 / set as-path prepend 65001 65001 65001.
Best path selection: Weight > Local-Pref > Originate > AS_PATH > MED > eBGP/iBGP > IGP metric.
BGP communities: no-export 65535:65281, no-advertise 65535:65282, internet 0:0.
Route reflector: clients do not need full mesh. RR reflects iBGP routes to clients.
EBGP multihop needed when peering via loopbacks across multiple hops."""),

    ("OSPF Troubleshooting Guide", "cisco", "runbook", """
OSPF states: Down Attempt Init 2-Way ExStart Exchange Loading Full.
ExStart stuck: MTU mismatch. Fix: ip ospf mtu-ignore or match MTU both sides.
Exchange stuck: duplicate Router-ID or DBD sequence issue.
Full = healthy. DR/BDR elected on broadcast segments by priority then Router-ID.
DR priority 0 = never become DR. Default priority 1.
LSA types: 1=Router 2=Network 3=Summary 4=ASBR-Summary 5=External 7=NSSA-External.
Area types: backbone(0) stub totally-stub NSSA. ABR connects areas. ASBR redistributes.
Hello interval 10s broadcast/P2P, 30s NBMA. Dead = 4x hello. Must match both sides.
Authentication: MD5 or SHA (OSPFv3). Mismatch prevents adjacency.
Commands: show ip ospf neighbor, show ip ospf interface, show ip ospf database, debug ip ospf adj."""),

    ("VLAN and STP Troubleshooting", "cisco", "runbook", """
VLAN not on trunk: show interfaces trunk. Add: switchport trunk allowed vlan add <id>.
Native VLAN mismatch: causes broadcast storms and CDP warnings. Must match both ends.
VLAN not created: show vlan brief. Create: vlan <id> / name <name>.
STP port states: Blocking Listening Learning Forwarding Disabled.
RSTP port roles: Root Designated Alternate Backup. Convergence <1 second.
STP BPDUs every 2 seconds. Max-age 20s. Forward-delay 15s (per state).
EtherChannel: all ports must match speed duplex mode VLAN config. 
LACP modes: active-active or active-passive. PAgP: desirable-desirable or desirable-auto.
Commands: show vlan brief, show interfaces trunk, show spanning-tree vlan <id>, show etherchannel summary.
PortFast: enable on access ports only. BPDU Guard: disable port if BPDU received."""),

    ("SD-WAN Architecture", "cisco", "design", """
Components: vManage(NMS) vBond(orchestrator) vSmart(controller) vEdge/cEdge(data-plane).
OMP overlay management protocol carries routes between controllers like BGP for overlay.
Transport colors: mpls biz-internet lte public-internet. Each gets its own tunnel.
Application-aware routing: SLA policy per app class. Jitter loss latency thresholds per class.
Direct cloud access: breakout at branch for SaaS. Avoids backhauling to HQ for O365/Zoom/SFDC.
Centralized policy: applied at vSmart, affects all edges. Data policy for traffic engineering.
Localized policy: applied at edge device. Access lists QoS route policy.
Security: onbox UTD, umbrella DNS, NGFW. Or cloud security via Zscaler/Netskope SASE.
TLOC: transport location. Combination of system-IP, color, encapsulation(IPSEC/GRE)."""),

    ("MPLS and Service Provider", "general", "reference", """
MPLS label: 20-bit value, 3-bit TC(QoS), 1-bit S(bottom of stack), 8-bit TTL.
LDP: label distribution protocol for IGP prefixes. Auto-discovery via hello.
RSVP-TE: traffic engineering, explicit paths, bandwidth reservation per LSP.
L3VPN: MP-BGP carries VPN routes. VRF per customer. RT import/export controls reachability.
Route Distinguisher 64-bit makes duplicate prefixes unique in BGP table.
L2VPN: VPWS point-to-point pseudowire, VPLS multipoint bridging over MPLS.
Segment Routing: prefix-SID per loopback, adj-SID per link. No LDP/RSVP needed.
SRv6: IPv6 addresses as segment IDs. SRH header carries segment list. IPv6 native.
Traffic Engineering: SR-TE policy with explicit segment list. Color community selects policy.
QoS: MPLS EXP/TC bits map to DSCP. Pipe/uniform/short-pipe mode per PE configuration."""),

    ("Zero Trust and Security", "general", "design", """
Zero Trust: never trust always verify. Identity device health context all required.
Micro-segmentation: east-west inspection. Workload isolation. Policy per flow not per zone.
ZTNA replaces VPN: identity-based access to specific apps not full network layer access.
SASE: converges SD-WAN security-service-edge. Cloud-delivered. Zscaler Cato Netskope Prisma.
Palo Alto Prisma Access: cloud NGFW for remote users. GlobalProtect agent.
Zscaler ZIA: proxy-based internet access. ZPA: private app access without VPN.
Identity integration: AD Azure-AD Okta MFA mandatory for Zero Trust maturity.
Firewall policy: application-based not port-based. App-ID user-ID content-ID.
NAC: posture assessment before network access. ISE for Cisco 802.1X enforcement.
Segmentation: VRF VLAN firewall zone microsegment. Defense in depth layered approach."""),

    ("Datacenter Networking VXLAN EVPN", "general", "reference", """
Leaf-spine: every leaf connects to every spine. No STP. ECMP load balancing.
VXLAN: UDP encapsulation port 4789. VNI 24-bit. Extends L2 over L3 underlay.
EVPN: BGP address family for VXLAN control plane. Route types 2(MAC/IP) 3(multicast) 5(prefix).
Symmetric IRB: distributed anycast gateway. Same IP/MAC gateway on every leaf.
Asymmetric IRB: routing on ingress leaf only. Simpler but requires all VNIs everywhere.
BGP underlay: eBGP between leaf and spine. Different ASN per leaf. Spine as route reflector.
OSPF underlay alternative: simpler but less scalable than BGP for large fabrics.
BFD: sub-second failure detection between leaf and spine. Default 300ms.
RoCE: RDMA over Converged Ethernet. Requires lossless: PFC ECN DCQCN.
AI fabric: 400G/800G links. InfiniBand alternative. Low latency critical for GPU all-reduce."""),
]


def get_rag_collection():
    global _chroma_client, _embedder, _collection
    if not RAG_OK:
        return None
    if _collection is None:
        try:
            _chroma_client = chromadb.PersistentClient(path="./chroma_db")
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
            _collection = _chroma_client.get_or_create_collection(
                "netbrain_v1", metadata={"hnsw:space":"cosine"}
            )
            if _collection.count() == 0:
                _seed_rag()
        except Exception as e:
            st.warning(f"RAG init error: {e}")
    return _collection


def _seed_rag():
    for title, vendor, dtype, content in KNOWLEDGE_SEED:
        _ingest(title, content.strip(), vendor, dtype)


def _ingest(title, content, vendor="general", dtype="manual"):
    col = get_rag_collection()
    if not col or not _embedder: return 0
    words = content.split()
    chunks, size, overlap = [], 400, 80
    for i in range(0, len(words), size - overlap):
        c = " ".join(words[i:i+size])
        if c: chunks.append(c)
    ids   = [hashlib.md5(f"{title}_{i}".encode()).hexdigest() for i in range(len(chunks))]
    embs  = _embedder.encode(chunks).tolist()
    metas = [{"title":title,"vendor":vendor,"doc_type":dtype,"chunk":i} for i in range(len(chunks))]
    col.add(ids=ids, documents=chunks, embeddings=embs, metadatas=metas)
    return len(chunks)


def ingest_document(title, content, vendor="general", dtype="manual"):
    return _ingest(title, content, vendor, dtype)


def rag_search(query: str, n: int = 4, vendor_filter: str = None) -> list:
    col = get_rag_collection()
    if not col or not _embedder or col.count() == 0:
        return []
    try:
        emb = _embedder.encode([query]).tolist()
        where = {"vendor": vendor_filter} if vendor_filter else None
        res = col.query(query_embeddings=emb, n_results=min(n, col.count()), where=where)
        docs  = res.get("documents",[[]])[0]
        metas = res.get("metadatas",[[]])[0]
        return [{"content":d,"meta":m} for d,m in zip(docs,metas)]
    except Exception:
        return []


def _similar_incidents(query, ents):
    incidents = get_incidents()
    scored = []
    ql = query.lower()
    for inc in incidents:
        score = 0
        txt = f"{inc['title']} {inc['description']} {inc.get('protocols','')}".lower()
        for p in ents.get("protocols",[]):
            if p.lower() in txt: score += 3
        for w in ql.split():
            if len(w)>4 and w in txt: score += 1
        if score > 0: scored.append((score, inc))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [i for _,i in scored[:2]]


# ══════════════════════════════════════════════════════════
# MASTER PIPELINE — All 4 systems together
# ══════════════════════════════════════════════════════════

def full_pipeline(query: str, persona: str = "noc", history: list = None) -> dict:
    """
    Combined pipeline:
    1. NLP entity extraction
    2. RAG retrieval
    3. Incident memory recall
    4. Claude reasoning
    Returns response text + metadata
    """
    # 1 — NLP
    ents = extract_entities(query)
    effective_persona = ents.get("persona_hint") or persona
    enriched = enrich_query(query, ents)

    # 2 — RAG
    rag_chunks = rag_search(query, n=3)

    # 3 — Incidents
    similar = _similar_incidents(query, ents)

    # 4 — Build messages
    messages = []

    if rag_chunks:
        kb_ctx = "\n\n".join(
            f"[Knowledge: {c['meta'].get('title','Doc')}]\n{c['content']}"
            for c in rag_chunks
        )
        messages += [
            {"role":"user","content":f"KNOWLEDGE BASE CONTEXT:\n{kb_ctx}"},
            {"role":"assistant","content":"Knowledge reviewed. Ready to assist."}
        ]

    if similar:
        inc_ctx = "\n".join(
            f"PAST INCIDENT: {i['title']} | RCA: {i['root_cause']} | Fix: {i['resolution']}"
            for i in similar
        )
        messages += [
            {"role":"user","content":f"SIMILAR PAST INCIDENTS:\n{inc_ctx}"},
            {"role":"assistant","content":"Historical context reviewed."}
        ]

    if history:
        messages += history[-8:]

    messages.append({"role":"user","content":enriched})

    response = call_claude(messages, persona=effective_persona, max_tokens=2000)

    return {
        "response": response,
        "entities": ents,
        "persona_used": effective_persona,
        "rag_sources": [c["meta"].get("title","") for c in rag_chunks],
        "similar_incidents": [i["title"] for i in similar],
    }


def system_status() -> dict:
    api_key = st.secrets.get("ANTHROPIC_API_KEY","") or os.environ.get("ANTHROPIC_API_KEY","")
    return {
        "claude": CLAUDE_OK and bool(api_key),
        "netmiko": NETMIKO_OK,
        "spacy": SPACY_OK,
        "rag": RAG_OK,
        "simulation_mode": not NETMIKO_OK,
    }
