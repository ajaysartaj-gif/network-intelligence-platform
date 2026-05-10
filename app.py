"""
NetBrain AI — Main Flask Backend
Integrates:
  A) Claude API (all AI reasoning)
  B) Multi-device query engine (netmiko SSH)
  C) NLP entity extractor (spaCy)
  D) RAG knowledge base (ChromaDB + sentence-transformers)
"""

import os, json, time, sqlite3, threading, hashlib
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_sock import Sock

# ── safe imports (graceful fallback if library missing) ──
try:
    import anthropic
    CLAUDE_OK = True
except ImportError:
    CLAUDE_OK = False
    print("[WARN] anthropic not installed. Run: pip install anthropic")

try:
    import spacy
    nlp_model = spacy.load("en_core_web_sm")
    SPACY_OK = True
except Exception:
    SPACY_OK = False
    print("[WARN] spaCy model missing. Run: python -m spacy download en_core_web_sm")

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    chroma_client = chromadb.PersistentClient(path="./chroma_db")
    embedder = SentenceTransformer("all-MiniLM-L6-v2")
    RAG_OK = True
except Exception:
    RAG_OK = False
    print("[WARN] ChromaDB/sentence-transformers not installed.")

try:
    from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException
    NETMIKO_OK = True
except ImportError:
    NETMIKO_OK = False
    print("[WARN] netmiko not installed. Run: pip install netmiko")

# ───────────────────────────────────────────────────────────
app = Flask(__name__, static_folder="static")
sock = Sock(app)

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DB_PATH = "./netbrain.db"

# ══════════════════════════════════════════════════════════
# DATABASE SETUP
# ══════════════════════════════════════════════════════════
def init_db():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL,
            ip TEXT NOT NULL,
            vendor TEXT DEFAULT 'cisco_ios',
            username TEXT,
            password TEXT,
            port INTEGER DEFAULT 22,
            role TEXT,
            site TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            root_cause TEXT,
            resolution TEXT,
            devices TEXT,
            protocols TEXT,
            severity TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            persona TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS knowledge_docs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            vendor TEXT,
            doc_type TEXT,
            content TEXT,
            chunk_id TEXT UNIQUE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS query_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT,
            devices TEXT,
            result TEXT,
            persona TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Seed sample devices
    cur.execute("SELECT COUNT(*) FROM devices")
    if cur.fetchone()[0] == 0:
        sample = [
            ("CORE-RTR-01","10.0.0.1","cisco_ios_xe","admin","admin123",22,"Core Router","HQ"),
            ("PE-MUM-01","10.0.1.1","cisco_ios_xr","admin","admin123",22,"PE Router","Mumbai"),
            ("PE-DEL-01","10.0.2.1","cisco_ios_xr","admin","admin123",22,"PE Router","Delhi"),
            ("DIST-SW-W","10.1.1.1","cisco_ios","admin","admin123",22,"Dist Switch","HQ-West"),
            ("FW-EDGE-01","192.168.1.1","paloalto_panos","admin","admin123",22,"Firewall","DMZ"),
        ]
        cur.executemany(
            "INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site) VALUES(?,?,?,?,?,?,?,?)",
            sample
        )
    # Seed sample incidents
    cur.execute("SELECT COUNT(*) FROM incidents")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO incidents(title,description,root_cause,resolution,devices,protocols,severity) VALUES(?,?,?,?,?,?,?)",
            [
                ("BGP session flapping","PE-MUM-01 BGP to AS65002 flapping 3x/hr",
                 "Upstream ISP BGP prefix withdrawal causing hold-timer expiry",
                 "Increased BGP hold timer to 90s, opened ISP ticket, added BFD",
                 "PE-MUM-01","BGP","critical"),
                ("OSPF adjacency lost","OSPF neighbor down between CORE-RTR-01 and DIST-SW-W",
                 "MTU mismatch on GigabitEthernet interface",
                 "Added ip ospf mtu-ignore on both interfaces",
                 "CORE-RTR-01,DIST-SW-W","OSPF","major"),
                ("VLAN 100 traffic drop","Users in VLAN 100 cannot reach gateway",
                 "VLAN 100 not in allowed list on trunk port Gi0/1",
                 "Added VLAN 100 to trunk allowed list",
                 "DIST-SW-W","VLAN,STP","major"),
            ]
        )
    con.commit()
    con.close()

init_db()

# ══════════════════════════════════════════════════════════
# SYSTEM A — CLAUDE API INTEGRATION
# ══════════════════════════════════════════════════════════

PERSONA_PROMPTS = {
    "ccna": """You are NetBrain AI assisting a CCNA-level network engineer.
- Explain concepts clearly with analogies and real-world examples
- Always include step-by-step guidance
- Define acronyms and technical terms
- Show CLI examples with explanations of what each line does
- Encourage and be supportive""",

    "noc": """You are NetBrain AI assisting a NOC engineer during operations.
- Be concise and action-oriented
- Lead with the most likely root cause
- Give exact CLI commands to verify and fix
- Include rollback steps
- Mention escalation paths when needed""",

    "arch": """You are NetBrain AI assisting a senior network architect.
- Assume deep technical knowledge — skip basics
- Focus on design trade-offs, scalability, and vendor differences
- Include HA/redundancy considerations
- Reference RFC/standards where relevant
- Provide BOM and sizing context when designing"""
}

NETWORK_SYSTEM_PROMPT = """You are NetBrain AI — an autonomous AI brain for enterprise and telecom networking.

You have deep expertise across:
- Routing: OSPF, BGP, EIGRP, IS-IS, MPLS, SRv6, Segment Routing
- Switching: VLANs, STP, EtherChannel, VXLAN, EVPN
- SD-WAN: Cisco Viptela, Versa, VMware VeloCloud, Palo Alto Prisma
- Security: Firewall, ACL, Zero Trust, ZTNA, IPSec, SASE
- Datacenter: Leaf-Spine, ACI, VXLAN EVPN, AI fabric, RoCE
- Cloud: AWS VPC, Azure VNet, GCP, hybrid cloud, Kubernetes networking
- Service Provider: MPLS L3VPN, L2VPN, SR-MPLS, SRv6, 5G transport
- Wireless: CAPWAP, 802.11ax, RF optimization, wireless assurance
- Vendors: Cisco, Juniper, Arista, Palo Alto, Fortinet, Aruba, Nokia, Huawei

When entities like IPs, hostnames, VLANs, or protocols are mentioned, reason about them specifically.
When logs or configs are provided, analyze them deeply.
Always include CLI commands when relevant.
Format responses clearly with headers and code blocks."""


def call_claude(messages, persona="noc", max_tokens=1500):
    """Core Claude API call with persona-aware system prompt."""
    if not CLAUDE_OK or not ANTHROPIC_KEY:
        return "[Claude API not configured. Set ANTHROPIC_API_KEY in Replit Secrets.]"
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
        system = NETWORK_SYSTEM_PROMPT + "\n\n" + PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["noc"])
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system,
            messages=messages
        )
        return resp.content[0].text
    except Exception as e:
        return f"[Claude API error: {str(e)}]"


# ══════════════════════════════════════════════════════════
# SYSTEM B — MULTI-DEVICE QUERY ENGINE
# ══════════════════════════════════════════════════════════

NL_TO_CMD = {
    "bgp summary":      {"cisco_ios": "show bgp all summary", "cisco_ios_xr": "show bgp all summary",
                          "juniper_junos": "show bgp summary", "arista_eos": "show bgp summary"},
    "bgp neighbor":     {"cisco_ios": "show ip bgp neighbors", "cisco_ios_xr": "show bgp neighbors",
                          "juniper_junos": "show bgp neighbor", "arista_eos": "show bgp neighbors"},
    "ospf neighbor":    {"cisco_ios": "show ip ospf neighbor", "cisco_ios_xr": "show ospf neighbor",
                          "juniper_junos": "show ospf neighbor", "arista_eos": "show ip ospf neighbor"},
    "interface status": {"cisco_ios": "show interfaces status", "cisco_ios_xr": "show interfaces brief",
                          "juniper_junos": "show interfaces terse", "arista_eos": "show interfaces status"},
    "cpu":              {"cisco_ios": "show processes cpu sorted", "cisco_ios_xr": "show processes cpu",
                          "juniper_junos": "show chassis routing-engine", "arista_eos": "show processes top"},
    "routing table":    {"cisco_ios": "show ip route", "cisco_ios_xr": "show route ipv4",
                          "juniper_junos": "show route", "arista_eos": "show ip route"},
    "version":          {"cisco_ios": "show version", "cisco_ios_xr": "show version",
                          "juniper_junos": "show version", "arista_eos": "show version"},
    "vlan":             {"cisco_ios": "show vlan brief", "cisco_ios_xr": "show vlan",
                          "juniper_junos": "show vlans", "arista_eos": "show vlan"},
    "log":              {"cisco_ios": "show logging | last 50", "cisco_ios_xr": "show log | last 50",
                          "juniper_junos": "show log messages | last 50", "arista_eos": "show log last 50"},
    "inventory":        {"cisco_ios": "show inventory", "cisco_ios_xr": "show inventory",
                          "juniper_junos": "show chassis hardware", "arista_eos": "show inventory"},
}

def resolve_command(nl_query, vendor):
    """Resolve NL query to vendor-specific CLI command."""
    q = nl_query.lower()
    for keyword, vendor_map in NL_TO_CMD.items():
        if keyword in q:
            return vendor_map.get(vendor, vendor_map.get("cisco_ios", "show version"))
    # Fallback: if it looks like a real command, use it directly
    if q.strip().startswith("show ") or q.strip().startswith("display "):
        return nl_query.strip()
    return None


def ssh_device(device, command, timeout=15):
    """SSH to a single device and run a command."""
    if not NETMIKO_OK:
        # Simulation mode for demo/testing
        return simulate_device_output(device, command)
    try:
        conn_params = {
            "device_type": device["vendor"],
            "host": device["ip"],
            "username": device["username"],
            "password": device["password"],
            "port": device.get("port", 22),
            "timeout": timeout,
            "session_timeout": timeout,
        }
        with ConnectHandler(**conn_params) as conn:
            output = conn.send_command(command, read_timeout=timeout)
        return {"status": "ok", "output": output, "command": command}
    except NetmikoTimeoutException:
        return {"status": "timeout", "output": f"Connection timeout to {device['ip']}", "command": command}
    except NetmikoAuthenticationException:
        return {"status": "auth_error", "output": f"Authentication failed for {device['hostname']}", "command": command}
    except Exception as e:
        return {"status": "error", "output": str(e), "command": command}


def simulate_device_output(device, command):
    """Realistic simulated output for demo mode (when no real devices available)."""
    hostname = device.get("hostname", "DEVICE")
    ip = device.get("ip", "0.0.0.0")
    vendor = device.get("vendor", "cisco_ios")
    
    if "bgp" in command.lower() and "summary" in command.lower():
        return {"status": "ok", "command": command, "output": f"""
BGP router identifier {ip}, local AS number 65001
BGP table state: Active

Neighbor        V    AS  MsgRcvd MsgSent  Up/Down   State/PfxRcd
10.0.0.1        4 65001    14823   14801  5d02h14   Established/142
10.0.1.1        4 65002      341     340  0d00h04   Active
10.0.2.1        4 65003     8912    8890  2d11h22   Established/87
""".strip()}
    elif "ospf" in command.lower() and "neighbor" in command.lower():
        return {"status": "ok", "command": command, "output": f"""
Neighbor ID     Pri   State           Dead Time   Address         Interface
192.168.1.1       1   FULL/DR         00:00:38    10.1.1.1        Gi0/0
192.168.1.2       1   FULL/BDR        00:00:39    10.1.1.2        Gi0/1
192.168.1.3       0   EXSTART/  -     00:00:40    10.1.1.3        Gi0/2
""".strip()}
    elif "interface" in command.lower():
        return {"status": "ok", "command": command, "output": f"""
Interface        Status         Protocol  Description
Gi0/0            up             up        Uplink to CORE
Gi0/1            up             up        Uplink to WAN
Gi0/2            down           down      [UNUSED]
Gi0/3            admin down     down      VLAN-120-ACCESS
""".strip()}
    elif "cpu" in command.lower() or "process" in command.lower():
        return {"status": "ok", "command": command, "output": f"""
CPU utilization for five seconds: 88%/12%; one minute: 75%; five minutes: 62%
PID  Runtime(ms)  Invoked   uSecs  5Sec  1Min  5Min  TTY Process
  42    89234120   1234567     723  45%   38%   34%   0  OSPF-1 Hello
 103    45123456    987654     457  22%   18%   15%   0  BGP Router
""".strip()}
    elif "vlan" in command.lower():
        return {"status": "ok", "command": command, "output": f"""
VLAN Name                             Status    Ports
---- -------------------------------- --------- --------------------
1    default                          active    Gi0/0, Gi0/1
10   MGMT                             active    Gi0/2
100  FINANCE                          active    Gi0/3, Gi0/4
120  BRANCH-HYD                       suspend   
200  SERVERS                          active    Gi1/0, Gi1/1
""".strip()}
    else:
        return {"status": "ok", "command": command, "output": f"""
{hostname}# {command}
Cisco IOS Software, Version 15.7(3)M
Uptime: 127 days, 4 hours, 22 minutes
Last reload reason: Reload Command
""".strip()}


def run_multi_device_query(nl_query, device_ids=None, persona="noc"):
    """
    Core multi-device query engine:
    1. Resolve NL to commands
    2. SSH all devices in parallel
    3. Feed all outputs to Claude
    4. Return unified AI-synthesised answer
    """
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    if device_ids:
        placeholders = ",".join("?" * len(device_ids))
        cur.execute(f"SELECT * FROM devices WHERE id IN ({placeholders})", device_ids)
    else:
        cur.execute("SELECT * FROM devices LIMIT 10")
    
    devices = [dict(r) for r in cur.fetchall()]
    con.close()
    
    if not devices:
        return {"error": "No devices found", "results": []}
    
    results = []
    threads = []
    lock = threading.Lock()
    
    def query_device(device):
        command = resolve_command(nl_query, device["vendor"])
        if not command:
            command = "show version"
        output = ssh_device(device, command)
        with lock:
            results.append({
                "hostname": device["hostname"],
                "ip": device["ip"],
                "vendor": device["vendor"],
                "role": device.get("role", ""),
                "site": device.get("site", ""),
                "command": command,
                "status": output["status"],
                "output": output["output"]
            })
    
    # Run all devices in parallel threads
    for device in devices:
        t = threading.Thread(target=query_device, args=(device,))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=20)
    
    # Build context for Claude
    device_context = "\n\n".join([
        f"=== {r['hostname']} ({r['ip']}) | {r['vendor']} | {r['role']} ===\n"
        f"Command: {r['command']}\nStatus: {r['status']}\n{r['output']}"
        for r in results
    ])
    
    synthesis_prompt = f"""You queried {len(results)} network devices.
Query: "{nl_query}"

Device outputs:
{device_context}

Provide:
1. SUMMARY — direct answer to the query across all devices
2. FINDINGS — specific notable findings per device (focus on anomalies)
3. RISK — any risks or issues detected
4. RECOMMENDED ACTIONS — what the engineer should do next

Be concise. Use device hostnames specifically."""

    ai_answer = call_claude(
        [{"role": "user", "content": synthesis_prompt}],
        persona=persona
    )
    
    # Save to history
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO query_history(query,devices,result,persona) VALUES(?,?,?,?)",
        (nl_query, json.dumps([r["hostname"] for r in results]), ai_answer, persona)
    )
    con.commit()
    con.close()
    
    return {
        "query": nl_query,
        "device_count": len(results),
        "device_results": results,
        "ai_synthesis": ai_answer,
        "timestamp": datetime.utcnow().isoformat()
    }


# ══════════════════════════════════════════════════════════
# SYSTEM C — NLP ENTITY EXTRACTOR
# ══════════════════════════════════════════════════════════

import re

# Networking-specific pattern library
NETWORK_PATTERNS = {
    "ip_address":    r'\b(?:\d{1,3}\.){3}\d{1,3}(?:\/\d{1,2})?\b',
    "ipv6":          r'\b(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b',
    "mac_address":   r'\b(?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2}\b',
    "as_number":     r'\bAS\s*\d+\b|\bASN\s*\d+\b',
    "vlan":          r'\bVLAN\s*\d+\b|\bvlan\s*\d+\b',
    "interface":     r'\b(?:Gi|Fa|Te|Hu|Et|xe|ge|fe|em)\d+(?:[\/\-]\d+){1,3}\b',
    "hostname":      r'\b[A-Z]{2,}[-_][A-Z]{2,}[-_]\d+\b',
    "ospf_area":     r'\barea\s*\d+\b|\bOSPF\s*area\s*\d+\b',
}

PROTOCOL_KEYWORDS = [
    "BGP","OSPF","EIGRP","IS-IS","ISIS","MPLS","VPLS","EVPN","VXLAN",
    "STP","RSTP","MSTP","LACP","LLDP","CDP","BFD","HSRP","VRRP","GLBP",
    "IPSec","GRE","DMVPN","SD-WAN","SDWAN","SASE","ZTNA","QoS","DSCP",
    "SRv6","SR-MPLS","L2VPN","L3VPN","VRF","SNMP","NetFlow","sFlow",
    "CAPWAP","802.11","RADIUS","TACACS","AAA","NAT","PAT","ACL","ZBFW"
]

VENDOR_KEYWORDS = [
    "Cisco","Juniper","Arista","Fortinet","Palo Alto","PAN-OS","Aruba",
    "Versa","VMware","VeloCloud","Viptela","Meraki","Nokia","Huawei",
    "Checkpoint","F5","Citrix","Zscaler","Cato","Netskope","NVIDIA","Mellanox"
]

INTENT_PATTERNS = {
    "troubleshoot": ["not working","down","flapping","unstable","dropping","timeout",
                     "failed","error","issue","problem","debug","diagnose","why","fix"],
    "generate_config": ["generate","create","write","configure","build config",
                        "give me config","make config","produce"],
    "explain": ["explain","what is","what does","how does","describe","tell me about",
                "meaning of","definition","understand"],
    "design": ["design","architect","plan","blueprint","recommend","best practice",
               "how should i","what topology","which vendor"],
    "compare": ["compare","difference","vs","versus","better","pros and cons","which is best"],
    "query_devices": ["show","check","fetch","get","list","find","which devices","all devices",
                      "across all","on all routers","across network"],
    "analyze_log": ["log","syslog","error message","traceback","alert","event","show logging"],
}

def extract_entities(text):
    """
    Full NLP entity extraction from networking text.
    Returns structured entities used to enrich Claude prompts.
    """
    entities = {
        "ip_addresses": [],
        "interfaces": [],
        "vlans": [],
        "as_numbers": [],
        "hostnames": [],
        "protocols": [],
        "vendors": [],
        "ospf_areas": [],
        "mac_addresses": [],
        "intent": "general",
        "urgency": "normal",
        "persona_hint": None,
    }
    
    # Regex extraction
    for entity_type, pattern in NETWORK_PATTERNS.items():
        matches = re.findall(pattern, text, re.IGNORECASE)
        key_map = {
            "ip_address": "ip_addresses",
            "ipv6": "ip_addresses",
            "mac_address": "mac_addresses",
            "as_number": "as_numbers",
            "vlan": "vlans",
            "interface": "interfaces",
            "hostname": "hostnames",
            "ospf_area": "ospf_areas",
        }
        key = key_map.get(entity_type, entity_type)
        entities[key].extend([m.strip() for m in matches if m.strip()])
    
    # Deduplicate
    for k in ["ip_addresses","interfaces","vlans","as_numbers","hostnames","ospf_areas","mac_addresses"]:
        entities[k] = list(dict.fromkeys(entities[k]))
    
    # Protocol detection
    text_upper = text.upper()
    entities["protocols"] = [p for p in PROTOCOL_KEYWORDS if p.upper() in text_upper]
    
    # Vendor detection
    entities["vendors"] = [v for v in VENDOR_KEYWORDS if v.lower() in text.lower()]
    
    # Intent classification
    text_lower = text.lower()
    for intent, keywords in INTENT_PATTERNS.items():
        if any(kw in text_lower for kw in keywords):
            entities["intent"] = intent
            break
    
    # Urgency detection
    urgency_words = ["critical","urgent","down","outage","emergency","production","immediately",
                     "p1","p2","sev1","sev2","bridge call","war room","customers affected"]
    if any(w in text_lower for w in urgency_words):
        entities["urgency"] = "high"
    
    # Persona hint from complexity
    expert_words = ["sr-mpls","srv6","evpn","vxlan","segment routing","rib-failure",
                    "as-path","route-reflector","rpvst","bfd","lsdb","lsp","ted"]
    beginner_words = ["what is","explain","how does","difference between","basics","understand",
                      "i am new","beginner","simple","easy way"]
    if any(w in text_lower for w in expert_words):
        entities["persona_hint"] = "arch"
    elif any(w in text_lower for w in beginner_words):
        entities["persona_hint"] = "ccna"
    
    # spaCy supplemental extraction
    if SPACY_OK:
        try:
            doc = nlp_model(text[:5000])
            for ent in doc.ents:
                if ent.label_ == "ORG" and ent.text not in entities["vendors"]:
                    for vendor in VENDOR_KEYWORDS:
                        if vendor.lower() in ent.text.lower():
                            entities["vendors"].append(vendor)
                if ent.label_ == "PRODUCT":
                    entities["vendors"].append(ent.text)
        except Exception:
            pass
    
    return entities


def enrich_prompt_with_entities(user_query, entities):
    """Add entity context to the message sent to Claude."""
    context_parts = []
    if entities["ip_addresses"]:
        context_parts.append(f"IPs mentioned: {', '.join(entities['ip_addresses'])}")
    if entities["interfaces"]:
        context_parts.append(f"Interfaces: {', '.join(entities['interfaces'])}")
    if entities["vlans"]:
        context_parts.append(f"VLANs: {', '.join(entities['vlans'])}")
    if entities["as_numbers"]:
        context_parts.append(f"AS numbers: {', '.join(entities['as_numbers'])}")
    if entities["protocols"]:
        context_parts.append(f"Protocols detected: {', '.join(entities['protocols'])}")
    if entities["vendors"]:
        context_parts.append(f"Vendors: {', '.join(entities['vendors'])}")
    if entities["ospf_areas"]:
        context_parts.append(f"OSPF areas: {', '.join(entities['ospf_areas'])}")
    if entities["hostnames"]:
        context_parts.append(f"Device hostnames: {', '.join(entities['hostnames'])}")
    
    if context_parts:
        enriched = f"[NLP Context: {' | '.join(context_parts)}]\n\n{user_query}"
    else:
        enriched = user_query
    return enriched


# ══════════════════════════════════════════════════════════
# SYSTEM D — RAG KNOWLEDGE BASE
# ══════════════════════════════════════════════════════════

COLLECTION_NAME = "netbrain_knowledge"
knowledge_collection = None

def get_or_create_collection():
    global knowledge_collection
    if not RAG_OK:
        return None
    if knowledge_collection is None:
        try:
            knowledge_collection = chroma_client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            # Seed with networking knowledge if empty
            if knowledge_collection.count() == 0:
                seed_knowledge_base()
        except Exception as e:
            print(f"[RAG] Collection error: {e}")
    return knowledge_collection


def chunk_text(text, chunk_size=400, overlap=80):
    """Split text into overlapping chunks for better retrieval."""
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


def add_to_knowledge_base(title, content, vendor="general", doc_type="manual"):
    """Add a document to RAG knowledge base."""
    collection = get_or_create_collection()
    if not collection:
        return {"error": "RAG not available"}
    
    chunks = chunk_text(content)
    ids, docs, metas = [], [], []
    
    for i, chunk in enumerate(chunks):
        chunk_id = hashlib.md5(f"{title}_{i}".encode()).hexdigest()
        ids.append(chunk_id)
        docs.append(chunk)
        metas.append({"title": title, "vendor": vendor, "doc_type": doc_type, "chunk": i})
    
    # Generate embeddings and add
    embeddings = embedder.encode(docs).tolist()
    collection.add(ids=ids, documents=docs, embeddings=embeddings, metadatas=metas)
    
    # Save to SQLite
    con = sqlite3.connect(DB_PATH)
    for i, (chunk_id, chunk) in enumerate(zip(ids, docs)):
        try:
            con.execute(
                "INSERT OR IGNORE INTO knowledge_docs(title,vendor,doc_type,content,chunk_id) VALUES(?,?,?,?,?)",
                (title, vendor, doc_type, chunk, chunk_id)
            )
        except Exception:
            pass
    con.commit()
    con.close()
    
    return {"added": len(chunks), "title": title}


def query_knowledge_base(query, n_results=4, vendor_filter=None):
    """Retrieve relevant knowledge chunks for a query."""
    collection = get_or_create_collection()
    if not collection or collection.count() == 0:
        return []
    
    try:
        query_embedding = embedder.encode([query]).tolist()
        where = {"vendor": vendor_filter} if vendor_filter else None
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=min(n_results, collection.count()),
            where=where
        )
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        return [{"content": d, "meta": m} for d, m in zip(docs, metas)]
    except Exception as e:
        print(f"[RAG] Query error: {e}")
        return []


def seed_knowledge_base():
    """Seed the RAG with core networking knowledge."""
    knowledge_items = [
        ("BGP Troubleshooting Guide", "cisco", "runbook", """
BGP Neighbor States: Idle, Connect, Active, OpenSent, OpenConfirm, Established.
Active state means TCP connection not established. Check: ping peer, check ACL blocking TCP 179,
verify remote-as matches, check MD5 auth, verify update-source interface.
BGP Hold Timer default 180 seconds. BFD reduces detection to milliseconds.
Common commands: show bgp all summary, show bgp neighbors <ip>, debug ip bgp <ip> events.
Route not advertised: check network statement, auto-summary, route-map filtering, next-hop reachability.
AS_PATH manipulation: prepend with route-map, set as-path prepend AS AS AS.
BGP attributes preference order: Weight, Local-Preference, Originate, AS_PATH, MED, eBGP/iBGP, IGP metric.
"""),
        ("OSPF Troubleshooting Guide", "cisco", "runbook", """
OSPF neighbor states: Down, Attempt, Init, 2-Way, ExStart, Exchange, Loading, Full.
ExStart stuck: MTU mismatch. Fix: ip ospf mtu-ignore on interface.
Exchange stuck: DBD sequence number issue or duplicate Router-ID.
Full state required for normal operation. DR/BDR elected on broadcast segments.
DR election: highest priority (default 1), then highest Router-ID. Priority 0 = never DR.
OSPF areas: backbone area 0, stub, totally stub, NSSA. ABR connects areas.
LSA types: Type 1 Router, Type 2 Network, Type 3 Summary, Type 4 ASBR Summary, Type 5 External.
Commands: show ip ospf neighbor, show ip ospf interface, show ip ospf database, debug ip ospf adj.
Hello interval default 10s broadcast, 30s NBMA. Dead interval = 4x hello.
Authentication: MD5 or SHA (OSPFv3). Mismatch prevents adjacency.
"""),
        ("VLAN and Trunk Troubleshooting", "cisco", "runbook", """
VLAN not passing on trunk: check show interfaces trunk for allowed VLANs.
Command: switchport trunk allowed vlan add <vlan-id>
Native VLAN mismatch causes broadcast flooding. Must match both sides.
VLAN not in STP: check show spanning-tree vlan <id>. Port may be in BLK state.
STP port states: Blocking, Listening, Learning, Forwarding, Disabled.
RSTP states: Discarding, Learning, Forwarding. Convergence < 1 second.
EtherChannel: all ports must have same speed, duplex, VLAN config.
LACP: active-active or active-passive. PAgP: desirable-desirable or desirable-auto.
Commands: show vlan brief, show interfaces trunk, show spanning-tree vlan <id>, show etherchannel summary.
"""),
        ("BGP SD-WAN Design Guide", "cisco", "design", """
SD-WAN components: vManage (NMS), vBond (orchestrator), vSmart (controller), vEdge/cEdge (data plane).
OMP protocol carries routes between controllers. Similar to BGP for overlay.
Transport: MPLS, Internet, LTE - active/active or active/backup.
Application-aware routing: SLA classes per application. Jitter, loss, latency thresholds.
Cloud breakout: direct internet access at branch for SaaS (O365, Zoom, Salesforce).
Zero Trust integration: identity-based policies, SASE integration.
Coloring: MPLS color for private WAN, Public Internet for internet links.
Centralized vs distributed policies. Data policies for traffic engineering.
"""),
        ("Network Security Zero Trust", "general", "design", """
Zero Trust principles: never trust, always verify. Verify identity, device health, context.
Micro-segmentation: isolate workloads. East-west traffic inspection.
ZTNA replaces VPN: identity-based access to specific applications not full network.
SASE: converges SD-WAN + security (CASB, SWG, ZTNA, FWaaS) in cloud.
Palo Alto Prisma Access: cloud-delivered security for remote users.
Zscaler ZIA/ZPA: internet access proxy + private app access.
Cisco Umbrella: DNS-based security, cloud-delivered.
Identity: integrate with AD, Azure AD, Okta. MFA mandatory for Zero Trust.
Network segmentation: use VRFs, VLANs, firewall zones to isolate traffic.
"""),
        ("MPLS and Service Provider Guide", "general", "reference", """
MPLS labels: 20-bit value, 3-bit EXP (QoS), 1-bit S (bottom of stack), 8-bit TTL.
LDP: Label Distribution Protocol. Distributes labels for IGP prefixes.
RSVP-TE: traffic engineering, explicit paths, bandwidth reservation.
L3VPN: PE-CE routing (BGP, OSPF, EIGRP, static). MP-BGP carries VPN routes with RT.
Route Target: import/export policy for VRF. Route Distinguisher: makes VPN routes unique (64bit).
L2VPN: VPWS (point-to-point), VPLS (multipoint). Pseudowires transport L2 frames.
MPLS QoS: pipe mode, uniform mode, short pipe mode. EXP bits map to DSCP.
Segment Routing: labels assigned per prefix or adjacency. No LDP/RSVP needed.
SRv6: IPv6 addresses as segment IDs. Native IPv6 transport. Simplifies MPLS stack.
Traffic Engineering: RSVP-TE or SR-TE. Explicit paths, bandwidth constraints.
"""),
    ]
    for title, vendor, doc_type, content in knowledge_items:
        try:
            add_to_knowledge_base(title, content.strip(), vendor, doc_type)
        except Exception as e:
            print(f"[RAG] Seed error for {title}: {e}")


def rag_enhanced_query(user_query, persona="noc", session_history=None):
    """
    Full RAG-enhanced query pipeline:
    1. Extract entities via NLP
    2. Retrieve relevant knowledge chunks
    3. Retrieve similar past incidents
    4. Build enriched context for Claude
    5. Return AI response
    """
    # Step 1 — NLP entity extraction
    entities = extract_entities(user_query)
    enriched_query = enrich_prompt_with_entities(user_query, entities)
    
    # Auto-detect persona from entities
    if entities["persona_hint"] and persona == "noc":
        persona = entities["persona_hint"]
    
    # Step 2 — RAG retrieval
    rag_chunks = query_knowledge_base(user_query, n_results=3)
    
    # Step 3 — Past incident retrieval
    similar_incidents = find_similar_incidents(user_query, entities)
    
    # Step 4 — Build messages
    messages = []
    
    # Add knowledge context
    if rag_chunks:
        knowledge_ctx = "\n\n".join([
            f"[Knowledge: {c['meta'].get('title','Doc')}]\n{c['content']}"
            for c in rag_chunks
        ])
        messages.append({
            "role": "user",
            "content": f"RELEVANT KNOWLEDGE BASE CONTEXT:\n{knowledge_ctx}"
        })
        messages.append({
            "role": "assistant",
            "content": "I have reviewed the relevant technical documentation. Ready to help."
        })
    
    # Add past incidents context
    if similar_incidents:
        inc_ctx = "\n".join([
            f"PAST INCIDENT: {inc['title']} | RCA: {inc['root_cause']} | Fix: {inc['resolution']}"
            for inc in similar_incidents[:2]
        ])
        messages.append({
            "role": "user",
            "content": f"SIMILAR PAST INCIDENTS FROM ORG MEMORY:\n{inc_ctx}"
        })
        messages.append({
            "role": "assistant",
            "content": "I have reviewed similar past incidents. This historical context will inform my analysis."
        })
    
    # Add session history
    if session_history:
        for msg in session_history[-6:]:  # last 3 exchanges
            messages.append(msg)
    
    # Add the actual query
    messages.append({"role": "user", "content": enriched_query})
    
    # Step 5 — Claude call
    response = call_claude(messages, persona=persona, max_tokens=2000)
    
    return {
        "response": response,
        "entities": entities,
        "rag_sources": [c["meta"].get("title") for c in rag_chunks],
        "similar_incidents": [i["title"] for i in similar_incidents],
        "persona_used": persona
    }


def find_similar_incidents(query, entities):
    """Find past incidents matching current query by protocol/keyword overlap."""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 20")
    incidents = [dict(r) for r in cur.fetchall()]
    con.close()
    
    query_lower = query.lower()
    scored = []
    for inc in incidents:
        score = 0
        inc_text = f"{inc['title']} {inc['description']} {inc['protocols']}".lower()
        # Protocol match
        for proto in entities.get("protocols", []):
            if proto.lower() in inc_text:
                score += 3
        # Keyword overlap
        for word in query_lower.split():
            if len(word) > 4 and word in inc_text:
                score += 1
        if score > 0:
            scored.append((score, inc))
    
    scored.sort(key=lambda x: x[0], reverse=True)
    return [inc for _, inc in scored[:3]]


# ══════════════════════════════════════════════════════════
# FLASK ROUTES — API ENDPOINTS
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """Main chat endpoint — full RAG + NLP + Claude pipeline."""
    data = request.json or {}
    user_message = data.get("message", "").strip()
    persona = data.get("persona", "noc")
    session_id = data.get("session_id", "default")
    history = data.get("history", [])
    
    if not user_message:
        return jsonify({"error": "No message provided"}), 400
    
    # Save user message
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO chat_sessions(session_id,role,content,persona) VALUES(?,?,?,?)",
        (session_id, "user", user_message, persona)
    )
    con.commit()
    con.close()
    
    # Check if this is a device query
    entities = extract_entities(user_message)
    
    if entities["intent"] == "query_devices":
        # Route to multi-device engine
        result = run_multi_device_query(user_message, persona=persona)
        response_text = result.get("ai_synthesis", "Query completed.")
        meta = {
            "type": "device_query",
            "devices_queried": result.get("device_count", 0),
            "entities": entities,
            "device_results": result.get("device_results", [])
        }
    else:
        # Standard RAG + NLP + Claude pipeline
        result = rag_enhanced_query(user_message, persona=persona, session_history=history)
        response_text = result["response"]
        meta = {
            "type": "rag_chat",
            "entities": result["entities"],
            "rag_sources": result["rag_sources"],
            "similar_incidents": result["similar_incidents"],
            "persona_used": result["persona_used"]
        }
    
    # Save AI response
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "INSERT INTO chat_sessions(session_id,role,content,persona) VALUES(?,?,?,?)",
        (session_id, "assistant", response_text, persona)
    )
    con.commit()
    con.close()
    
    return jsonify({"response": response_text, "meta": meta})


@app.route("/api/multi-device-query", methods=["POST"])
def api_multi_device():
    """Dedicated multi-device query endpoint."""
    data = request.json or {}
    query = data.get("query", "")
    device_ids = data.get("device_ids")
    persona = data.get("persona", "noc")
    
    if not query:
        return jsonify({"error": "No query provided"}), 400
    
    result = run_multi_device_query(query, device_ids, persona)
    return jsonify(result)


@app.route("/api/nlp/extract", methods=["POST"])
def api_nlp_extract():
    """NLP entity extraction endpoint."""
    data = request.json or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text provided"}), 400
    entities = extract_entities(text)
    return jsonify(entities)


@app.route("/api/rag/query", methods=["POST"])
def api_rag_query():
    """Direct RAG knowledge base query."""
    data = request.json or {}
    query = data.get("query", "")
    vendor = data.get("vendor")
    if not query:
        return jsonify({"error": "No query provided"}), 400
    chunks = query_knowledge_base(query, n_results=5, vendor_filter=vendor)
    return jsonify({"results": chunks, "count": len(chunks)})


@app.route("/api/rag/ingest", methods=["POST"])
def api_rag_ingest():
    """Ingest document into RAG knowledge base."""
    data = request.json or {}
    title = data.get("title", "Untitled")
    content = data.get("content", "")
    vendor = data.get("vendor", "general")
    doc_type = data.get("doc_type", "manual")
    if not content:
        return jsonify({"error": "No content provided"}), 400
    result = add_to_knowledge_base(title, content, vendor, doc_type)
    return jsonify(result)


@app.route("/api/devices", methods=["GET"])
def api_devices():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT id,hostname,ip,vendor,role,site FROM devices")
    devices = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(devices)


@app.route("/api/devices", methods=["POST"])
def api_add_device():
    data = request.json or {}
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO devices(hostname,ip,vendor,username,password,port,role,site) VALUES(?,?,?,?,?,?,?,?)",
        (data.get("hostname"), data.get("ip"), data.get("vendor","cisco_ios"),
         data.get("username","admin"), data.get("password",""), data.get("port",22),
         data.get("role",""), data.get("site",""))
    )
    con.commit()
    device_id = cur.lastrowid
    con.close()
    return jsonify({"id": device_id, "message": "Device added"})


@app.route("/api/incidents", methods=["GET"])
def api_incidents():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 50")
    incidents = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(incidents)


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "claude_api": CLAUDE_OK and bool(ANTHROPIC_KEY),
        "netmiko": NETMIKO_OK,
        "spacy_nlp": SPACY_OK,
        "rag_engine": RAG_OK,
        "simulation_mode": not NETMIKO_OK,
        "db": "sqlite",
        "version": "1.0.0"
    })


@app.route("/api/query-history", methods=["GET"])
def api_query_history():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM query_history ORDER BY created_at DESC LIMIT 20")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return jsonify(rows)


# ══════════════════════════════════════════════════════════
# WEBSOCKET — REAL-TIME UPDATES
# ══════════════════════════════════════════════════════════

@sock.route("/ws")
def websocket(ws):
    """WebSocket for live dashboard updates."""
    while True:
        try:
            data = ws.receive(timeout=30)
            if data:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    ws.send(json.dumps({"type": "pong", "ts": time.time()}))
                elif msg.get("type") == "subscribe_alerts":
                    # In production: stream real alerts
                    ws.send(json.dumps({
                        "type": "alert_update",
                        "count": 7,
                        "latest": "BGP flap on PE-MUM-01 — 2 min ago"
                    }))
        except Exception:
            break


# ══════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 55)
    print("  NetBrain AI — Starting up")
    print("=" * 55)
    print(f"  Claude API:  {'✓ Ready' if CLAUDE_OK and ANTHROPIC_KEY else '✗ Set ANTHROPIC_API_KEY'}")
    print(f"  Netmiko:     {'✓ Ready' if NETMIKO_OK else '⚡ Simulation mode'}")
    print(f"  spaCy NLP:   {'✓ Ready' if SPACY_OK else '⚡ Regex-only mode'}")
    print(f"  RAG Engine:  {'✓ Ready' if RAG_OK else '⚡ Disabled'}")
    print("=" * 55)
    
    # Pre-warm RAG
    if RAG_OK:
        threading.Thread(target=get_or_create_collection, daemon=True).start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
