# NRIE — Address Bounded Context (Phase 1: Enterprise Knowledge Foundation)

The **Network Resource Intelligence Engine (NRIE)** address context is the single
place responsible for **enterprise network resource knowledge**. This PR delivers
the *foundation only* — Memory, Resource, Business Context, Organizational Memory
and a Knowledge layer. **No allocation, planning, prediction, optimization, or AI.**

## Layering (DDD)

```
domain/          pure model — no persistence, no allocation
  value_objects  Identifier, EnterpriseLevel, ResourceType/Status, Lifecycle, Tags, Metadata, …
  entities       EnterpriseEntity, NetworkResource, BusinessContext, OrganizationalKnowledge
  aggregates     EnterpriseHierarchy, ResourceInventory, OrganizationalMemory (consistency + events)
  policies       ParentMustExist, HierarchyLevelOrder, BusinessContextAttachment (invariants)
  specifications composable read predicates (by_level, by_resource_type, by_purpose, …)
  events         domain facts (records only)

knowledge/       declarative domain knowledge (no AI)
  ontology       resource relationships      taxonomy   resource classification
  relationships  dependency kinds            glossary   canonical term definitions
  standards      organizational standard kinds
  memory         descriptor of WHAT is remembered + which store backs each layer
  reasoning      descriptor of reasoning questions posed to the EXISTING Reasoning Engine (IMPLEMENTS_AI = False)

contracts/       the ONLY orchestrator touchpoint
  commands  queries  events  dto  interfaces

infrastructure/  persistence + repositories (no business logic)
  persistence    MemoryStore subclasses — REUSES core.intelligence.memory (dual SQLite/Postgres)
  repositories   map domain ↔ stored payloads; persist/retrieve only

api/             thin facade (commands in, DTOs out) + read-only Streamlit panel
  service        NRIEFoundationService / get_nrie_service()
  ui             render_nrie_panel()  (wired next to the Network Topology workspace)

tests/           domain + knowledge + service round-trip (9 tests, all passing)
```

## Reuse (no duplication)

| Need | Reused platform asset |
|------|----------------------|
| Persistence / Memory Platform | `core.intelligence.memory.store.MemoryStore` (dual-backend, consolidation, decay) |
| Knowledge Graph | `core.knowledge_graph` (referenced by `knowledge/reasoning.py`; resolution in later PRs) |
| Reasoning Engine | `core.reasoning_layer` (reasoning surface declared, not reimplemented) |
| Navigation / UI | existing Streamlit workspace registry (`config/workspaces.py`) |
| Logging/telemetry | standard `logging` (`NetBrain.*` loggers) |

## Integration

`Intent → Knowledge Graph → Memory Platform → Reasoning → Orchestrator → Database → Logging → Telemetry`
— NRIE plugs in as the resource-knowledge authority; it introduces **no replacement components**
and exposes **read-only** APIs (`enterprise_hierarchy`, `resource_hierarchy`, `business_context`,
`knowledge`). The UI panel appears in the top navigation immediately after **Network Topology**.

## Out of scope (later PRs)
IP allocation · address/resource planning · prediction · capacity · optimization · route
summarization · explainability · recommendation · validation · deployment · config generation ·
DHCP/DNS automation · vendor/cloud integrations · AI decision-making.

---

## PR-001.1 — Foundation Hardening (refinement)

Extends PR-001 in place (no rewrites, no file moves, existing tests still pass):

1. **Richer Business Context** — `entities.BusinessContext` now also carries
   *why a resource exists*: business_capability, business_service, business_owner,
   availability (target/RTO/RPO), growth_expectation, operational_model,
   architecture_pattern, risk_classification (criticality & compliance retained).
2. **Context Builder** (`context/`) — `models.py` (EnterpriseContext, ResourceContext,
   BusinessContextModel, OrganizationalContext, merged **ResourceContextBundle**),
   `interfaces.py` (ContextBuilder protocol), `builder.py` (DefaultContextBuilder:
   build each context + merge into one). Reusable by future Planning / Prediction /
   Optimization / Explainability. **No allocation/planning logic.**
3. **Pool is the Address Aggregate Root** (`aggregates.Pool`) — owns Subnets,
   Reservations, Capacity, Utilization, Fragmentation and Growth. Future allocation
   must work through this aggregate (none implemented here — ownership/structure only).
4. **Strengthened Ontology** (`knowledge/ontology.py`) — adds a reusable,
   DOMAIN-NEUTRAL relationship vocabulary: belongs_to, contains, supports,
   depends_on, connected_to, protected_by, owned_by, uses, allocated_from,
   managed_by. Existing edges preserved; `relationships.py` maps dependency kinds
   onto these reusable types.
5. **Extensibility** — `ResourceDomain` enum + `domain` tag on Pool/ResourceContextBundle
   ensure nothing assumes Address is the only Resource Domain. Device/Cloud/
   Connectivity/Identity are **not** implemented (future PRs).

Additionally touched (necessary, additive, backward-compatible): `value_objects.py`
(new enums/VOs for the above) and `events.py` (Pool events). Tests: `tests/test_hardening.py`
(6 tests). Out of scope unchanged: allocation, planning, prediction, optimization,
explainability, lifecycle, vendor/cloud, deployment, config generation.

---

## PR-002 — Intelligence & Reasoning Foundation (Phase 2)

Turns the knowledge foundation into an intelligence platform. **Binding rule:
every intelligence module consumes the `ResourceContextBundle` from the Context
Builder — none reconstructs Enterprise/Business/Organizational/Resource context.
The Context Builder is the single source of contextual truth.**

```
memory/
  decision_memory.py      Layer 4 — engineering decisions (queryable)        [MemoryStore reuse]
  operational_memory.py   Layer 5 — resource operational timeline            [MemoryStore reuse]
  predictive_memory.py    Layer 6 — predictions + realized accuracy/variance [MemoryStore reuse]
cognition/
  classification.py       resource classification + criticality (from bundle)
  relationship_engine.py  relationship discovery via reusable ontology
  context_builder.py      Layer 9 — ResourceCognition: CONSUMES the bundle, adds understanding
policy/
  policy_engine.py        Layer 10 — policy registry (report-only rules)
  policy_evaluator.py     evaluate bundle → pass/violations/recommendations/standards
dependency/
  dependency_graph.py     Layer 11 — wraps the platform Knowledge Graph (reuse, no new graph)
  dependency_engine.py    discover upstream/downstream/business/routing/security/cloud deps
events/
  domain_events.py        DecisionRecorded / OperationalHistoryUpdated / PredictionGenerated /
                          CognitionCompleted / PolicyEvaluated / DependencyDiscovered
                          (published through the existing EventEngine; locally recorded too)
api/
  intelligence_api.py     read-only: decision/operational/prediction history, resource context,
                          policy evaluation, dependency graph
tests/test_intelligence.py  7 tests, all bundle-driven
```

### Reuse (no duplication)
- **Memory Platform** — Decision/Operational/Predictive memory subclass `MemoryStore`
  (dual-backend, consolidation); NRIE operational memory is a distinct *resource* history,
  not a copy of the platform autonomy memory.
- **Knowledge Graph** — Dependency Intelligence registers/queries the existing
  `KnowledgeGraph` (`add_node`/`add_relationship`/`get_dependencies`/`trace_impact_chain`);
  no second graph.
- **Event Framework** — events emitted via the existing `EventEngine.emit_event`.
- **Reasoning** — Decision Memory stores reasoning summaries/confidence; it does not
  re-implement the platform reasoning engine.
- **Context** — all layers consume the PR-001.1 Context Builder bundle.

### Out of scope (PR-003)
IP allocation · pool selection · reservation · route summarization · capacity optimization ·
lifecycle state machine · recommendation/explainability engines · config generation ·
deployment · vendor/cloud provisioning.

---

## PR-003 — Autonomous Resource Planning & Execution (Phase 3)

Completes NRIE: it now plans, allocates, validates, recommends, optimizes,
explains and learns. **Planning is separated from deployment; allocation is
separated from configuration generation. NRIE never generates config or deploys**
— existing deployment components own execution. Every capability consumes the
`ResourceContextBundle`.

```
allocation/
  conflict_detector.py   overlap/duplicate detection (ipaddress)
  reservation.py         soft reservations (reuses domain Reservation/Pool)
  allocator.py           intelligent best-fit allocation (growth + criticality headroom,
                         NOT first-available); references business context/standards/utilisation
planning/
  planner.py             Layer: Enterprise Resource Plan (pools/subnets/VLANs/VRFs/DHCP/DNS/
                         headroom/hierarchy/business mapping) — no config generation
  planning_service.py    orchestrates plan → validate → recommend → explain
lifecycle/
  state_machine.py       Planned→Reserved→Allocated→Configured→Verified→Production→
                         Expanding→Retiring→Archived
  lifecycle_manager.py   Layer 12 — audited transitions (timestamp/trigger/actor/reason/
                         deployment/change/prev/new); audit via reused Operational Memory
optimization/
  fragmentation.py       fragmentation analysis (ipaddress)
  summarization.py       route-aggregation opportunities (collapse_addresses)
  optimizer.py           Layer 13 — recommendations only (no automatic changes)
explainability/
  explanation_engine.py  Layer 14 — why/evidence/policies/business/alternatives/confidence/
                         benefits/risks/future impact for every recommendation
validation/
  policy_validator.py    reuses the PR-002 Policy Evaluator (no duplicate policy logic)
  validator.py           Validation Engine — duplicate/overlap/capacity/policy/naming/lifecycle
recommendation/
  recommendation_engine.py  ranked alternatives (never one answer): confidence/risk/cost/
                            complexity/growth/business-impact/explanation
learning/
  outcome_tracker.py     structured execution outcomes
  feedback.py            feeds outcomes back into reused Decision/Operational/Predictive memory
api/
  planning_api.py        plan/allocate/validate/recommend/optimize/lifecycle/explain/learn
tests/test_planning.py   7 tests (real CIDR math), all bundle-driven
```

### Reuse (no duplication)
Pool aggregate (PR-001.1) for ownership · Context Builder bundle for context ·
PR-002 Decision/Operational/Predictive memory for learning + lifecycle audit ·
PR-002 Policy Evaluator for validation · existing Event framework for all PR-003
events · `ipaddress` stdlib for CIDR math. No new orchestration/memory/graph/
reasoning/deployment components.

### UI
The Admin → **🧮 IP Intelligence** panel now has a third tab, **🤖 Autonomous
Planning**: pick a resource, enter intent + demands, and NRIE returns the
Enterprise Resource Plan (real CIDRs/VLANs/VRFs/DHCP/DNS), validation, ranked
recommendations, a full explanation, and optimization opportunities — with a
clear note that NRIE plans/allocates only and deployment remains the platform's.

### Out of scope (unchanged)
vendor config/CLI/Terraform/Ansible generation · device deployment · cloud
provisioning · DHCP/DNS server implementation.

---

## AI-Native Autonomy — Intent → Hierarchy → Plan → Live IP Discovery

Makes IP Intelligence truly autonomous and AI-native. Reuses the platform Groq
client (`core.ai_engine.ask_ai`) and the device discovery engine
(`core.device_discovery`); introduces no new LLM or scanner.

```
ai/assistant.py            reuses Groq (ask_ai); strict-JSON parse, per-IP descriptions,
                           graceful deterministic fallback when offline
intent/intent_parser.py    NL → SiteIntent ("deploy a 20 users site in Mumbai" →
                           users=20, location=Mumbai, site_type) + per-profile demand derivation
location/location_map.py   place → Region>Country>State>City (map + AI fallback)
location/hierarchy_builder.py  builds Region>Country>State>City>Campus>Site>Building>Floor
                               (reuses the foundation service; idempotent-ish)
discovery/ip_scanner.py    active-IP scan — REUSES DeviceDiscoveryEngine (ICMP/GNS3/range)
discovery/ip_inventory.py  Subnet>IP leaf — per-IP status + AI description + "engaged as"
                           (MemoryStore-backed)
autonomy/site_designer.py  orchestrator: intent → location → hierarchy → derive demands →
                           plan/allocate (reused PR-003) → record subnets under Floor →
                           optional scan → inventory IPs with descriptions
api/autonomy_api.py        design_site() · scan_subnet() · ip_inventory()
tests/test_autonomy.py     4 tests (intent, location, full-chain design, profile differences)
```

### What it does
1. **Intent → decision** — "deploy a 20 users site in Mumbai" is parsed (AI + fallback);
   NRIE derives the site profile and decides subnets/VLANs/VRFs automatically.
2. **Active-IP scan + descriptions** — scans a subnet (reusing the platform engine),
   identifies active IPs, infers where each is engaged (router/CCTV/server/managed host…)
   and writes a description against every IP.
3. **Full hierarchy** — Region > Country > State > City > Campus > Site > Building > Floor >
   Subnet > IP details, built automatically from the intent's location.
4. **Real AI** — wired to Groq; the UI shows 🟢/🟡 AI status and degrades gracefully.

### UI
Admin → **🧮 IP Intelligence** → **🌐 Intent & Autonomy**: type an intent, click
*Design site autonomously*, and see the parsed intent, the auto-built hierarchy,
the planned subnets, and the discovered active IPs with descriptions. NRIE
plans/allocates/inventories only — deployment stays with the platform.
