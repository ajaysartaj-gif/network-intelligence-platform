# NetBrain AI — Autonomous Network Operating System

> The future AI operating system for enterprise networking.

---

## What This Is

NetBrain AI is **not a dashboard** or monitoring portal.

It is an **AI-Native Autonomous Network Operating System** that combines:

| Platform | Capability |
|----------|-----------|
| Cisco ThousandEyes | Internet path visibility, SaaS monitoring |
| Forward Networks | Network knowledge graph, path analysis |
| Juniper Mist AI | AI-driven operations, anomaly detection |
| Palo Alto AIOps | Security correlation, threat analysis |
| ServiceNow | Incident management, ITSM workflows |
| Dynatrace | Observability, telemetry, anomaly detection |
| ChatGPT | AI reasoning, NLP, config generation |

…unified into **one autonomous platform**.

---

## Architecture

```
netbrain_ai/
├── app.py                          ← Streamlit entry point
│
├── core/
│   ├── ai_engine.py                ← System A: Claude via OpenRouter
│   ├── nlp_engine.py               ← System C: Entity extraction, intent, urgency
│   ├── rag_engine.py               ← System D: ChromaDB/keyword knowledge base
│   ├── mdq_engine.py               ← System B: Parallel SSH multi-device query
│   ├── observability_engine.py     ← Telemetry, anomaly detection, SaaS monitoring
│   ├── digital_twin_engine.py      ← Failure simulation, change validation
│   ├── incident_engine.py          ← Blast radius, correlation, operational memory
│   ├── knowledge_graph.py          ← Network entity relationships
│   ├── compliance_engine.py        ← CIS/NIST/PCI/ZT scoring
│   ├── self_healing_engine.py      ← Autonomous remediation policies
│   └── ...
│
├── database/
│   ├── models.py                   ← SQLAlchemy ORM models
│   └── database.py                 ← DB manager, Fernet encryption, seeding
│
├── security/
│   └── rbac.py                     ← Role-based access control
│
├── ui/
│   └── components.py               ← Enterprise design system
│
├── integrations/
│   └── netmiko_connector.py        ← Production SSH connector
│
└── tests/
    ├── test_nlp.py
    ├── test_mdq.py
    └── test_database.py
```

---

## Workspaces (19 operational workspaces)

| Workspace | Description |
|-----------|-------------|
| ⚡ Operations | Command center, live device status, timeline |
| 🚨 Incidents | War room, AI RCA, blast radius, autonomous remediation |
| 🗺 Topology | Knowledge graph, interactive topology, SPOF detection |
| 📡 Observability | Live telemetry, anomaly detection, SaaS monitoring, syslog |
| 🔧 Diagnose | 4-engine AI troubleshooting pipeline |
| 📋 Changes | AI risk scoring, digital twin pre-validation |
| 🤖 Autonomous | AI action center, human/semi/full autonomy modes |
| 👾 Digital Twin | Failure simulation, change validation, what-if analysis |
| 🔒 Security | Threat analysis, Zero Trust scoring, CVE tracking |
| 🛡 Compliance | CIS/NIST/PCI/ISO/ZT frameworks, config drift |
| 🏗 Design | AI design studio — requirements → full architecture |
| ⚡ Multi-Device | Parallel SSH query across all devices |
| 🧬 NLP | Entity extraction, intent classification, urgency detection |
| 📚 Knowledge | RAG knowledge base, document ingestion |
| 📖 Learn | Adaptive learning hub, CCNA→CCIE tracks |
| 🖧 Devices | Device manager, encrypted credential storage |
| 📈 Executive | Board-ready metrics, SLA, operational risk |
| 💰 FinOps | License optimization, automation ROI, cost analysis |
| 🔐 Audit | Complete audit trail, security events |

---

## Quick Start

### Streamlit Cloud (Recommended)

1. Push code to GitHub
2. Connect repo at [share.streamlit.io](https://share.streamlit.io)
3. Add secrets in App Settings → Secrets:

```toml
OPENROUTER_API_KEY = "sk-or-v1-your-key"
SECRET_KEY = "your-fernet-key"   # optional
```

4. Deploy → live in ~60 seconds

### Local Development

```bash
# Clone and install
git clone https://github.com/your-org/netbrain-ai
cd netbrain-ai
pip install -r requirements.txt

# Configure
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit with your OpenRouter API key

# Run
streamlit run app.py
```

### Docker

```bash
docker build -t netbrain-ai .
docker run -p 8501:8501 \
  -e OPENROUTER_API_KEY=sk-or-v1-... \
  netbrain-ai
```

---

## Security

- **No hardcoded secrets** — all credentials via `st.secrets` or environment
- **Fernet encryption** — all device passwords encrypted at rest
- **RBAC** — 6 roles: Admin, Architect, NOC, Security, ReadOnly, Executive
- **Audit logging** — all user actions tracked in SQLite/PostgreSQL
- **Parameterized SQL** — no SQL injection risk
- **`.gitignore`** — `secrets.toml` never committed

---

## AI Systems

### System A — Claude AI (via OpenRouter)
- Model: `anthropic/claude-sonnet-4-5`
- 6 personas: Fresher, CCNA, NOC, Architect, Manager, Security
- Context injection: RAG + incident memory + workspace context
- Max tokens: 2000 per response

### System B — Multi-Device Query
- ThreadPoolExecutor (max 20 workers)
- Retry with exponential backoff
- Simulation fallback when SSH unavailable
- 11 NL→CLI command categories × 7 vendors

### System C — NLP Engine
- 14 intent classes
- Entity extraction: IP, VLAN, interface, ASN, VRF, hostname, ticket
- Urgency: P1/P2/P3/P4
- Optional: spaCy (falls back to regex)

### System D — RAG Knowledge Base
- Optional: ChromaDB + sentence-transformers
- Fallback: keyword search (always works)
- 7 pre-seeded topics: BGP, OSPF, VLAN, SD-WAN, MPLS, Security, Datacenter

---

## Database

- **Dev**: SQLite (`netbrain.db`)
- **Production**: PostgreSQL (set `DATABASE_URL` secret)
- **ORM**: SQLAlchemy 2.0
- **Tables**: devices, incidents, changes, autonomous_actions, audit_logs, knowledge_docs, users

---

## Environment Variables / Secrets

| Key | Required | Description |
|-----|----------|-------------|
| `OPENROUTER_API_KEY` | ✅ Yes | OpenRouter API key for Claude access |
| `SECRET_KEY` | Optional | Fernet key for credential encryption |
| `DATABASE_URL` | Optional | PostgreSQL URL for production |

---

## Personas

| Persona | Level | Description |
|---------|-------|-------------|
| 🌱 Fresher | Beginner | Analogies, definitions, step-by-step |
| 🎓 CCNA | Foundation | Context, CLI explanation, guided troubleshooting |
| 🖥 NOC | Operational | Concise, root cause first, exact CLI |
| 🏗 Architect | Expert | Trade-offs, RFC references, BOM context |
| 📊 Manager | Business | Impact, revenue risk, decisions needed |
| 🔒 Security | Security | Threats, attack paths, compliance, containment |
