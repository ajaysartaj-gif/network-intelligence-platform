# Network Knowledge Compiler — Phase 1 Gap Analysis

> Status: analysis document, grounded in direct inspection of the repository
> (not a generic template). Every classification below cites the actual
> class/file it's based on. Companion document:
> [`nkc_architecture_blueprint.md`](nkc_architecture_blueprint.md).

## Method

This repository already has five mature subsystems that a "Network Knowledge
Compiler" (NKC) would naturally touch. Rather than assume they're missing,
each was read directly this session (or in a prior session for
`core/knowledge/`) and classified as:

- **Reuse** — already does the job; NKC calls it, doesn't change it.
- **Extend** — does part of the job; NKC adds capability alongside the
  existing shape, doesn't rewrite it.
- **Refactor** — works, but has accumulated duplication that should be
  consolidated before NKC adds a third/fourth version of the same concept.
- **Replace** — no existing equivalent, or the existing thing is a stub with
  no real behavior. Rare — used twice below.

## Headline finding

**The repository does not need a new canonical object model, a new
knowledge-graph schema, or a new vendor-adapter framework.** All three
already exist, are actively used by the troubleshooting engine, and are
reasonably designed:

| Concept NKC prompt asks for | Already exists as |
|---|---|
| Vendor-neutral operation/object model | `core.vendor.models.NormalizedObject` / `ObjectType` / `core.vendor.operations.Operation` |
| Vendor adapter extension point ("add a vendor with zero engine changes") | `core.vendor.sdk.VendorAdapter` + `core.vendor.registry` (decorator-based auto-discovery) |
| Knowledge graph (nodes/edges/traversal) | `core.knowledge_graph.KnowledgeGraph` (`GraphNode`, `GraphRelationship`, BFS path/impact-chain) |
| Physical/L2-L3 topology graph | `core.topology.topology_models.TopologyGraph` |
| Evidence/confidence contract | `core.evidence.contract.EvidenceContract` + `EvidenceAssessor` |
| Governance/approval gate | `core.governance.contract.GovernanceContract` + `GovernanceEngine` |
| Hypothesis generation + confidence scoring | `core.troubleshooting.hypotheses` (log-odds) **and** `core.intelligence.faculties.HypothesisGenerator`/`ConfidenceCalibrator` — **two independent implementations** (see Refactor candidate below) |
| Reasoning taxonomy / epistemic typing / graph substrate philosophy | Already fully designed in [`docs/reasoning_blueprint.md`](reasoning_blueprint.md) — don't re-derive it |
| Typed, authority-ranked, versioned knowledge store | `core.knowledge.enterprise.knowledge_layer.EnterpriseKnowledgeLayer` (built last session on top of the pre-existing `RAGEngine`) |
| Multi-format document ingestion | `core.knowledge.parsers` + `core.knowledge.enterprise.pipelines` (built last session) |

**What's genuinely missing** is narrower than the original prompt implies: a
**deterministic semantic-extraction stage** that turns parsed document text
into instances of the object model that already exists (`NormalizedObject`,
`GraphNode`/`GraphRelationship`, `EvidenceItem`), plus the **publishing glue**
that writes those instances into the existing graph/evidence/memory stores.
That is a real, scoped engineering project — see the architecture blueprint's
phased roadmap. It is not a reason to invent a second graph schema or a
second vendor framework.

---

## Module-by-module classification

### `core/knowledge/` — document knowledge (extended last session)

| Module | Classification | Rationale |
|---|---|---|
| `base.py` (`KnowledgeEntry`, `Citation`, `ConfidenceLevel`) | **Reuse** | Solid provenance/confidence model; NKC's metadata architecture builds directly on `Citation`. |
| `orchestrator.py` (cache → RAG → web fetch → MCP → stale → unverified) | **Reuse** | Already the production lookup chain, wired into `IntentEngine._ground()` and thus every troubleshooting round. |
| `fetchers/*` (9 vendors + RFC) | **Extend** (done) | Search-first DDG+BS4 pattern is sound and cheap to replicate; added Huawei/Dell/Extreme/RFC last session. Remaining gap: Nokia, MikroTik, cloud (AWS/Azure/GCP/NSX) fetchers — same pattern, not yet built. |
| `enterprise/knowledge_layer.py` (`SourceType`, versioning, hybrid RRF search) | **Extend** (done) | Added 8 source types + ranks last session. This is the closest existing thing to a "canonical knowledge store" — NKC's Publishing layer should write here, not around it. |
| `enterprise/pipelines.py` | **Extend** (done) | Now format-agnostic (`ingest_file`/`ingest_directory` route through `core.knowledge.parsers`). |
| `parsers/` | **New, built last session** | Did not exist before; genuinely net-new (PDF/DOCX/JSON/YAML/XML/CSV/HTML → text). This is only the **lexical/parsing** stage — it stops at plain text, not semantic objects. NKC's Semantic Analysis stage is the next layer up, still to be built. |
| `cache/cache_db.py`, `cache/ttl_policy.py` | **Reuse** | SQLite TTL cache with per-vendor freshness policy is a working, sufficient freshness/incremental-recompilation signal at the document level. |
| `citation_tracker.py` | **Reuse** | Per-session citation rollup; NKC's explainability requirement is already served by this for the command-lookup path. |
| `rag/rag_engine.py`, `rag/embedder.py` (incl. `FakeEmbedder`) | **Reuse** | Chunking, ChromaDB persistence, pluggable embedder (already swappable without touching call sites) — no reason to replace. |
| `vendor_router.py`, `mcp/*` | **Reuse** | Plugin-style vendor routing and MCP fallback sources are already the right shape. |

### `core/vendor/` — Universal Vendor Adapter Framework

| Module | Classification | Rationale |
|---|---|---|
| `models.py` (`NormalizedObject`, `ObjectType`, `VendorProfile`, `NormalizedError`) | **Reuse, Extend the enum** | This *is* the canonical object model the NKC prompt asks for. `ObjectType` is explicitly documented as "illustrative, not exhaustive" — extending it (ACL detail objects, QoS objects, security-policy objects) is additive, not a rewrite. |
| `operations.py` (`Op`, `Operation`, `RemediationIntent`, `RemediationPlan`) | **Reuse, Extend the verb set** | Vendor-neutral verbs already exist; new protocols/features add new `Op` constants, never new engine branching. |
| `sdk.py` (`VendorAdapter` ABC, `DeviceProbe`, `Transport`) | **Reuse** | This is the extension mechanism the NKC prompt calls "extension mechanism for adding new vendors" — it already exists and already supports zero-engine-change vendor addition (proven by the existing Cisco/Juniper/generic-fallback adapters). |
| `registry.py` (decorator auto-discovery, confidence-based `detect_adapter`) | **Reuse** | Plugin registry pattern is exactly right; don't add a second registry. |
| `gateway.py` (`VendorGateway` facade) | **Reuse** | Zero vendor conditionals, already the single call point for the troubleshooting engine. |
| `adapters/{cisco_ios_like,juniper_junos_like,generic_cli}.py` | **Reuse, Extend by adding adapters** | `IosLikeAdapter` is a complete, working reference implementation (detect/build_command/parse_output/build_fix/rollback/verification/validate) — the template for Huawei/Dell/Extreme *adapters* (distinct from the *doc fetchers* added last session — adapters execute live commands, fetchers retrieve documentation; both are needed, neither replaces the other). |

### `core/knowledge_graph.py` + `core/topology/` — graph substrate

| Module | Classification | Rationale |
|---|---|---|
| `core/knowledge_graph.py` (`GraphNode`, `GraphRelationship`, `KnowledgeGraph`) | **Extend** | Working generic node/edge/adjacency-list model with BFS path and impact-chain tracing. Gaps vs. the NKC ask: no persistence (in-memory only), no typed edge taxonomy (`relationship_type` is a free string), no confidence/provenance on edges. Extend, don't replace — the traversal API is sound. |
| `core/topology/topology_models.py` (`TopologyGraph`, `TopologyNode`, `TopologyLink`, `DeviceRole`) | **Reuse** | Purpose-built physical/L2-L3 graph (geo/layout-aware) is a *different, legitimate* graph from the generic `KnowledgeGraph` — the NKC architecture should keep them distinct (see blueprint's "family of typed graphhs" section, which mirrors `reasoning_blueprint.md`'s Axiom 4) and federate queries across both rather than merge them. |
| `core/topology/topology_engine.py` (`build_topology_for_site`) | **Reuse** | Full working topology builder (parallel CDP/LLDP discovery, reconciliation, role classification, L3 subnet pass, caching). This already *is* the "topology analysis" pipeline stage for live devices; NKC's document-derived topology facts (e.g., a design guide describing an intended topology) should feed into `KnowledgeGraph`, not duplicate this engine. |
| `core/topology/role_classifier.py`, `l3_topology.py`, `l3_discovery.py`, `topology_cache.py` | **Reuse** | Each does one clear job (role rules, L3 mismatch detection, subnet discovery, TTL+schema-versioned cache) with no overlap to consolidate. |

### `core/intelligence/`, `core/reasoning_layer/`, `core/troubleshooting/` — reasoning

| Module | Classification | Rationale |
|---|---|---|
| `core/intelligence/reasoning.py` (`ReasoningRegistry`, `Evidence`, `Conclusion`, `ReasonerSpec`, epistemic typing) | **Reuse** | This is the reasoning taxonomy/registry `docs/reasoning_blueprint.md` designed and it's implemented, not just documented. NKC's "Reasoning Dataset Generation" stage should emit `Evidence`/`Conclusion`-shaped artifacts so they slot into this registry, rather than inventing a parallel artifact schema. |
| `core/intelligence/faculties.py` (`HypothesisGenerator`, `SelfCritic`, `ConfidenceCalibrator`) | **Refactor candidate** | Real, working abductive reasoning — but see duplication flag below. |
| `core/troubleshooting/hypotheses.py`, `models.py` (log-odds `ConfidenceCalculator`, `RootCauseRanker`) | **Refactor candidate** | Also real and working (this is what powers `TroubleshootingEngine`, verified against live tests). **Duplication flag**: this is a second, independent hypothesis+confidence system parallel to `faculties.py`. Not a blocker for NKC — NKC should feed *both* via a shared canonical `Evidence` shape — but it's worth a dedicated consolidation effort before adding a third. |
| `core/reasoning_layer/contract.py` (`DecisionContract`) vs. `core/intelligence/outcome_contract.py` (`ContractResult`) vs. `core/intelligence/decision/` (`Judgment`) | **Refactor candidate** | Three distinct "contract/decision" concepts already exist (pre-execution gate, post-execution proof, multi-criteria judgment). They're not redundant — they answer different questions — but a future engineer proposing a fourth "compiler decision contract" should map onto one of these three, not add a fourth. Flagged, not touched, in this analysis. |
| `core/intelligence/config_synthesis/synthesizer.py::parse_intent` | **Extend** | Closest existing thing to "intent extraction" from the NKC prompt — but scoped narrowly to config-change intents (raw_text → `ConfigIntent` features/params/constraints), not general document semantic extraction. NKC's semantic-analysis stage extends this pattern (rule-based, deterministic slot extraction) to document-derived facts, rather than introducing an LLM-first NLU layer. |
| `core/intelligence/operational_memory.py` (`OperationalMemory`, `MemoryEvent`, embedding `similar()`, `recurring_failures()`) | **Reuse** | This is the durable experience store; NKC's "Continuous Learning" phase should write compiled remediation/incident knowledge here (it already has the embedding-similarity retrieval NKC would otherwise reinvent). |
| `core/intelligence/forecasting/`, `learning/`, `autonomy/`, `capability_model.py` | **Reuse, out of scope for NKC** | Fully separate concerns (prediction, lessons-learned, MAPE-K autonomy gating, capability health). NKC doesn't need to touch these; they're downstream consumers of compiled knowledge at most. |

### `core/evidence/`, `core/governance/`, `core/policy/`, `core/verification/`

| Module | Classification | Rationale |
|---|---|---|
| `core/evidence/contract.py` + `assessor.py` (`EvidenceContract`, `EvidenceAssessor`) | **Extend** | Real evidence-completeness scoring — but scoped to "is there enough evidence for *this one change request*," not cross-document conflict/duplicate detection across the knowledge base. NKC's Validation layer (Phase 9 of the original prompt: duplicate facts, conflicting facts, stale docs) is a genuinely new capability layered *alongside* this, reusing `EvidenceItem`'s shape rather than inventing a new one. |
| `core/governance/contract.py` + `engine.py` (`GovernanceContract`, `GovernanceEngine`) | **Reuse** | Deterministic approval-gate orchestration (compliance + risk + rollback readiness + simulation) is already solid and is the natural home for any future "should this compiled knowledge auto-publish or need review" gate — extend its inputs, don't replace the engine. |
| `core/policy/contract.py` + `engine.py` (`PolicyContract`, `EnterprisePolicyEngine`) | **Reuse** | Change-freeze/business-criticality checks. Note: `role_validation` is presence-of-operator-string, not real RBAC — flagged as an honest gap in the architecture blueprint's Security section, not something to silently paper over. |
| `core/verification/command_validator.py`, `version_parser.py` | **Reuse** | Pre-deploy safety validation and version parsing are unrelated-but-adjacent; NKC's compiled "verification workflows" (Phase 11 of the original prompt) should call `CommandValidator`, not reimplement command-safety rules. |

### Net-new (Replace/build fresh — nothing to reuse)

| Concept | Classification | Rationale |
|---|---|---|
| Deterministic semantic extractors (protocol/interface/ACL/VRF/VLAN/timer/metric recognizers over parsed document text) | **Replace/build fresh** | Nothing in the repo does deterministic entity extraction from *unstructured prose* today — `config_synthesis/synthesizer.py::parse_intent` is the nearest analog but works on operator intent text, not vendor documentation. This is real, scoped, net-new work — the first concrete phase in the roadmap. |
| Cross-document knowledge validation (duplicate/conflicting-fact detection across the whole knowledge base) | **Replace/build fresh** | `EvidenceAssessor` checks completeness for one request; nothing today compares two ingested documents against each other for contradiction. Net-new, but small in surface area (operates on `EnterpriseKnowledgeLayer` hits, doesn't need a new store). |

---

## Bottom line for scoping the next increment

Of the 15 "compiler phases" in the original prompt, roughly two-thirds are
**already implemented** somewhere in this repository under different names.
The other third — deterministic semantic extraction into the existing
canonical model, cross-document validation, and the publishing glue that
writes compiled objects into `KnowledgeGraph`/`OperationalMemory` — is real,
bounded, additive work. See the phased roadmap in
[`nkc_architecture_blueprint.md`](nkc_architecture_blueprint.md) for how to
sequence it; it is not a rewrite of anything above.
