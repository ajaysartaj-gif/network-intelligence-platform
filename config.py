"""NetBrain AI Configuration."""

import os
from typing import Dict

# API Configuration
OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "anthropic/claude-sonnet-4-5"
OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://netbrain-ai.streamlit.app",
    "X-Title": "NetBrain AI",
}

# Database
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///netbrain.db")

# Security
SECRET_KEY = os.environ.get("SECRET_KEY", None)

# Session State Limits
MAX_CHAT_HISTORY = 20
MAX_RESULTS_STORED = 5
TTL_SIMULATION_MINUTES = 30
TTL_RESULTS_MINUTES = 60
TTL_DEVICES_SECONDS = 60
TTL_INCIDENTS_SECONDS = 30
TTL_CHANGES_SECONDS = 60

# Network Knowledge Base
KNOWLEDGE_BASE: Dict = {
    "BGP": {
        "vendor": "general",
        "protocols": ["BGP"],
        "content": """
BGP (Border Gateway Protocol) — Path vector protocol for inter-AS routing.

NEIGHBOR STATES: Idle → Connect → Active → OpenSent → OpenConfirm → Established
Active state = TCP session NOT established. Never ignore Active state in production.

TROUBLESHOOTING ACTIVE STATE:
1. TCP 179 reachability: telnet <peer-ip> 179
2. Remote-as mismatch
3. MD5 authentication mismatch
4. Update-source unreachable
5. ACL blocking TCP 179

BEST PATH SELECTION ORDER:
Weight → Local-Preference → Originate → AS_PATH length → Origin → MED → eBGP > iBGP

KEY TIMERS:
Hold-timer default: 180s. Keepalive: 60s. BFD: 300ms-1s detection.
"""
    },
    "OSPF": {
        "vendor": "general",
        "protocols": ["OSPF"],
        "content": """
OSPF — Link State IGP, Dijkstra SPF algorithm, hierarchical areas.

NEIGHBOR STATES: Down → Attempt → Init → 2-Way → ExStart → Exchange → Loading → Full
FULL = healthy. Any other state = investigate.

EXSTART STUCK — MOST COMMON CAUSE:
MTU mismatch between peers. Fix: ip ospf mtu-ignore OR match MTU both sides.

DR/BDR ELECTION:
Highest priority wins. Default 1. Priority 0 = never become DR.
Non-preemptive (new DR elected only on current DR failure).

LSA TYPES:
Type 1: Router LSA | Type 2: Network LSA | Type 3: Summary LSA
Type 4: ASBR Summary | Type 5: AS External | Type 7: NSSA External

TIMERS: Hello=10s, Dead=40s (must match both ends).
"""
    },
    "VLAN": {
        "vendor": "general",
        "protocols": ["VLAN", "STP"],
        "content": """
VLAN TROUBLESHOOTING:

VLAN NOT PASSING ON TRUNK:
show interfaces trunk → check allowed VLAN list
Fix: switchport trunk allowed vlan add <vlan-id>

NATIVE VLAN MISMATCH:
Causes broadcast flooding and security risks.
Both ends must have same native VLAN.
Best practice: change native VLAN to unused VLAN ID.

STP STATES:
Blocking → Listening → Learning → Forwarding → Disabled
RSTP: Discarding → Learning → Forwarding (faster convergence)

ETHERCHANNEL REQUIREMENTS:
Both sides must match: speed, duplex, mode, VLANs, native VLAN
LACP modes: active-active or active-passive
"""
    },
}

# Workspaces
WORKSPACES = [
    ("operations", "⚡", "Operations"),
    ("incident", "🚨", "Incidents"),
    ("topology", "🗺", "Topology"),
    ("observe", "📡", "Observability"),
    ("troubleshoot", "🔧", "Diagnose"),
    ("change", "📋", "Changes"),
    ("autonomous", "🤖", "Autonomous"),
    ("twin", "👾", "Digital Twin"),
    ("security", "🔒", "Security"),
    ("compliance", "🛡", "Compliance"),
    ("design", "🏗", "Design"),
    ("mdq", "⚡", "Multi-Device"),
    ("nlp", "🧬", "NLP"),
    ("rag", "📚", "Knowledge"),
    ("learn", "📖", "Learn"),
    ("devices", "🖧", "Devices"),
    ("executive", "📈", "Executive"),
    ("finops", "💰", "FinOps"),
    ("audit", "🔐", "Audit"),
]

# Personas
PERSONAS = {
    "fresher": "Persona: BEGINNER STUDENT. Explain everything with analogies. Define every acronym.",
    "ccna": "Persona: CCNA ENGINEER. Explain with context. Show CLI with explanation.",
    "noc": "Persona: NOC ENGINEER. BE CONCISE. Lead with probable root cause. Give exact CLI.",
    "architect": "Persona: SENIOR ARCHITECT. Skip basics. Focus on design trade-offs, scalability.",
    "manager": "Persona: OPERATIONS MANAGER. Business language only. Focus on user impact.",
    "security": "Persona: SECURITY ENGINEER. Threat context first. Zero Trust alignment.",
}

# Roles & Permissions
PERMISSIONS = {
    "admin": {
        "view_all", "manage_devices", "push_config", "manage_users",
        "approve_changes", "run_automation", "view_credentials",
        "manage_integrations", "view_audit", "delete_records",
        "manage_rbac", "view_security", "run_mdq", "view_incidents",
    },
    "architect": {
        "view_all", "manage_devices", "view_credentials",
        "approve_changes", "run_digital_twin", "view_security",
        "run_mdq", "view_incidents", "create_incidents",
    },
    "noc": {
        "view_all", "run_mdq", "view_incidents", "create_incidents",
        "resolve_incidents", "approve_changes", "run_automation",
    },
    "security": {
        "view_all", "view_security", "view_incidents", "create_incidents",
        "resolve_incidents", "view_credentials", "run_mdq",
    },
    "readonly": {"view_all", "view_incidents"},
    "executive": {"view_all", "view_incidents"},
}
