# The Network Knowledge Compiler (NKC) — Architecture Blueprint
### Canonical architecture for compiling heterogeneous networking knowledge into the platform's existing canonical models

> Status: foundational design document, companion to
> [`nkc_gap_analysis.md`](nkc_gap_analysis.md) and
> [`reasoning_blueprint.md`](reasoning_blueprint.md). No implementation code
> in this document by design — it defines contracts, data shapes, and
> sequencing so implementation can proceed incrementally, the way
> `core/knowledge/parsers` and `core/knowledge/enterprise/` were added in a
> prior increment.
>
> **Framing, stated once so it isn't repeated in every section:** this repo
> already has a canonical object model (`NormalizedObject`), a knowledge
> graph (`KnowledgeGraph`), a vendor adapter framework (`VendorAdapter`), and
> a reasoning registry (`ReasoningRegistry`). The NKC is the **front-end
> compiler** that turns unstructured documents into instances of those
> existing shapes — it is not a second back-end.

---

## Part 0 — The compiler analogy, made precise

A traditional compiler is: `source text → tokens → AST → semantic model →
IR → optimized IR → target code`. Networking knowledge compilation is the
same shape, with networking-specific stages:

```
Vendor doc / RFC / config / CLI output / telemetry     (source text)
        │
        ▼  Lexical Analysis           "what are the tokens/sections?"
        │
        ▼  Syntax Analysis            "what's the document's structure?"
        │
        ▼  AST Generation             "structured tree, still vendor-specific"
        │
        ▼  Semantic Analysis          "what does this MEAN?" (protocol, ACL, VRF...)
        │
        ▼  Canonicalization           "vendor-neutral form" → NormalizedObject
        │
        ▼  Graph Compilation          "how does this relate to everything else?"
        │
        ▼  Validation                 "is this true, fresh, non-contradictory?"
        │
        ▼  Publishing                 KnowledgeGraph / EnterpriseKnowledgeLayer /
                                       OperationalMemory (existing stores)
```

The crucial engineering decision this blueprint makes: **stop treating "the
compiler" as one monolithic new system**, and instead treat it as a small
number of new stages (Lexical→Semantic→Canonicalization→Validation) sitting
in front of several already-working back ends (Graph, Store, Memory,
Reasoning). This is what keeps the design additive rather than a rewrite.

---

## Part 1 — Layered architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│ L9  API / SDK LAYER            compile() parse() validate() search()│
│                                 explain() diff() export() — thin     │
│                                 wrapper; network_compiler.py is the  │
│                                 seed CLI form of this today.         │
├─────────────────────────────────────────────────────────────────────┤
│ L8  PUBLISHING LAYER            writes compiled objects into the    │
│                                 THREE existing stores below — never │
│                                 a new store of its own              │
├───────────────────┬───────────────────┬─────────────────────────────┤
│ KnowledgeGraph     │ EnterpriseKnowledge│ OperationalMemory          │
│ (core/knowledge_   │ Layer (chunks,     │ (events, remediations,     │
│  graph.py)         │  ChromaDB)         │  embeddings)               │
├───────────────────┴───────────────────┴─────────────────────────────┤
│ L7  VALIDATION LAYER            NEW: duplicate/conflict detection,  │
│                                 confidence scoring, staleness check  │
│                                 (reuses EvidenceItem shape)          │
├─────────────────────────────────────────────────────────────────────┤
│ L6  GRAPH COMPILATION LAYER     NEW: canonical objects → graph nodes│
│                                 /edges, extends KnowledgeGraph       │
├─────────────────────────────────────────────────────────────────────┤
│ L5  CANONICALIZATION LAYER      NEW: vendor syntax → NormalizedObject│
│                                 (reuses ObjectType, extends its enum)│
├─────────────────────────────────────────────────────────────────────┤
│ L4  SEMANTIC ANALYSIS LAYER     NEW: deterministic entity/relation/  │
│                                 intent extractors (protocol/ACL/VRF/│
│                                 VLAN/timer/metric recognizers)       │
├─────────────────────────────────────────────────────────────────────┤
│ L3  SYNTAX / AST LAYER          NEW (lightweight): structure the     │
│                                 parsed text into sections/tables/    │
│                                 config stanzas before semantic pass  │
├─────────────────────────────────────────────────────────────────────┤
│ L2  PARSING / LEXICAL LAYER     REUSE: core/knowledge/parsers/       │
│                                 (PDF/DOCX/JSON/YAML/XML/CSV/HTML)    │
├─────────────────────────────────────────────────────────────────────┤
│ L1  ACQUISITION / CONNECTOR     REUSE: core/knowledge/fetchers/ +    │
│     LAYER                       enterprise/pipelines.py + ttl_policy│
├─────────────────────────────────────────────────────────────────────┤
│ L0  KNOWLEDGE SOURCE LAYER      RFCs, vendor docs, configs, CLI      │
│                                 output, telemetry, TAC cases, ...    │
└─────────────────────────────────────────────────────────────────────┘

Cross-cutting (not a stage, present at every layer):
  Governance/Policy gate (core/governance, core/policy) — reused as-is
  Observability (metrics/health already on EnterpriseKnowledgeLayer)
  Security (see Part 9 — currently the thinnest layer, flagged honestly)
```

L0–L2 are done (last session). L3–L7 are the real scope of "building the
NKC." L8 is glue code, not new architecture. L9 already has a seed (the
`network_compiler.py` CLI).

---

## Part 2 — Canonical object model (extends `NormalizedObject`, doesn't replace it)

`core/vendor/models.py` already defines:

```
ObjectType: DEVICE | INTERFACE | VRF | ROUTE | NEIGHBOR | PROTOCOL | POLICY
          | ACL | TUNNEL | TOPOLOGY | SERVICE | APPLICATION | FLOW
          | TELEMETRY | ALARM | EVENT | INVENTORY | CONFIGURATION
          (explicitly "illustrative, not exhaustive")

NormalizedObject: { type: ObjectType, id: str, device: str,
                    attributes: Dict[str, Any] }
```

This is the Canonical Network Language (CNL) the original prompt asks for —
it is vendor-neutral by construction (an OSPF neighbor from Cisco IOS and one
from Junos both become `NormalizedObject(type=NEIGHBOR, attributes={...})`).
What's missing is not the *shape*, it's:

1. **More `ObjectType` members** for document-derived concepts the live-adapter
   path doesn't currently need: `QOS_POLICY`, `SECURITY_RULE`,
   `YANG_LEAF`, `DESIGN_PATTERN`, `FAILURE_SIGNATURE`, `BEST_PRACTICE_RULE`.
   Additive enum members — zero breaking change to existing adapters.
2. **A bidirectional mapping registry** (vendor syntax ⇄ canonical): today
   `VendorAdapter.build_command`/`parse_output` do this one-way, per-adapter,
   for *live* device interaction. The NKC needs the same mapping driven from
   *document* text (a config guide's example block → `NormalizedObject`),
   which is a new producer of the same consumer shape, not a new shape.
3. **Confidence + provenance on the object itself**, not just on the
   citation — extend `NormalizedObject.attributes` with reserved keys
   (`_confidence`, `_source_doc_id`, `_extracted_by`) rather than adding a
   parallel wrapper class. Reserved-key convention keeps `NormalizedObject`
   unchanged for the live-adapter callers that never set them.

**Extension mechanism for new protocols:** add `Op` constants
(`core/vendor/operations.py`) and `ObjectType` members
(`core/vendor/models.py`). No engine, no gateway, no reasoning code changes —
this is already proven by how OSPF-specific reasoning was added to
`TroubleshootingEngine` without protocol conditionals in the engine itself.

---

## Part 3 — Semantic Analysis Layer (the real new engineering)

This is the one layer with no existing equivalent (see gap analysis). Design
principle from the prompt, worth repeating because it's the right call:
**prefer deterministic extraction; use an LLM only for genuine ambiguity
resolution.**

```
Parsed text (from L2)
    │
    ▼
┌───────────────────────────────────────────────────────────┐
│ Section classifier (deterministic, rule/regex-based)        │
│  — same pattern as core/topology/role_classifier.py:        │
│    ordered rules, first match wins, falls to UNKNOWN         │
│  — classifies: config-stanza / show-output / prose / table   │
├───────────────────────────────────────────────────────────┤
│ Per-section extractors (one deterministic extractor per      │
│ concept, registered — same plugin pattern as                 │
│ core.intelligence.reasoning.ReasoningRegistry):               │
│   - CommandExtractor      (CLI syntax blocks)                │
│   - ProtocolExtractor     (OSPF/BGP/EIGRP/... keyword+context)│
│   - InterfaceExtractor    (interface names, IPs, MTU, VLANs)  │
│   - ACLExtractor          (permit/deny rules, object-groups)  │
│   - VRFExtractor          (VRF names, RDs, route-targets)     │
│   - TimerMetricExtractor  (hello/dead timers, thresholds)     │
│   - StateExtractor        (up/down/established/EXSTART, ...)  │
│   - DependencyExtractor   (references between sections/docs)  │
├───────────────────────────────────────────────────────────┤
│ LLM fallback (ONLY when a section fails every deterministic   │
│ extractor with confidence above a floor) — reuses the same    │
│ ai_call plumbing TroubleshootingEngine.reasoner already uses,  │
│ produces the same NormalizedObject shape, tagged                │
│ `_extracted_by="llm"` so Validation can weight it lower         │
└───────────────────────────────────────────────────────────┘
    │
    ▼  list[NormalizedObject] + list[(subject, relation, object)] triples
```

Each extractor is deterministic regex/state-machine code, same spirit as
`core/topology/l3_discovery.py`'s TextFSM-with-regex-fallback approach — this
repo already has the pattern for "parse messy CLI text deterministically,"
it's just scoped to live `show` output today. Extending it to prose vendor
docs is the same technique against different input.

**Extension mechanism for new document types:** register a new extractor
against the classifier's section-type enum, same shape as registering a new
parser in `core/knowledge/parsers/__init__.py`'s `_EXT_MAP`. No changes to
other extractors.

---

## Part 4 — Knowledge Graph Compilation (extends `core/knowledge_graph.py`)

Current `KnowledgeGraph`:

```
GraphNode(node_id, label, attributes: Dict)
GraphRelationship(source, target, relationship_type: str, weight=1.0, metadata: Dict)
KnowledgeGraph: nodes, relationships, adjacency (in-memory)
  .add_node / .add_relationship / .get_dependencies / .find_path (BFS) /
  .trace_impact_chain (bounded BFS) / .dependency_summary
```

Extend, in order of necessity:

1. **Typed edges.** Replace the free-string `relationship_type` with a
   closed vocabulary (`DEPENDS_ON`, `USES`, `IMPLEMENTS`, `CONTAINS`,
   `CONNECTED_TO`, `NEIGHBOR_OF`, `ROUTES_THROUGH`, `ADVERTISES`,
   `LEARNS_FROM`, `CAUSES`, `AFFECTED_BY`, `CONFLICTS_WITH`, `OVERRIDES`,
   `SUPPORTS`, `DEPRECATED_BY`, `INTRODUCED_IN`, `VALIDATED_BY`,
   `VERIFIED_BY`, `RESOLVED_BY` — the exact list from the prompt). Backward
   compatible: existing free-string callers keep working since Python
   strings satisfy a `str`-backed enum; new compiled edges use the enum.
2. **Provenance + confidence per edge**, in `GraphRelationship.metadata`
   (already a free dict — no schema change needed, just a convention:
   `metadata={"source_doc_id":..., "confidence":..., "extracted_by":...}`).
3. **A `compile_object(obj: NormalizedObject) -> GraphNode` mapping function**
   — the one genuinely new function this layer needs. Maps `ObjectType` →
   node `label`, `attributes` → node `attributes`, and any cross-references
   inside `attributes` (e.g. an ACL referencing an object-group by name)
   into `GraphRelationship`s.
4. **Persistence.** In-memory adjacency lists don't survive a process
   restart or scale past one process. Roadmap-gated (Part 11), not needed
   for MVP: swap the in-memory dict for a real graph store (Neo4j,
   or a Postgres edge table) behind the *same* `KnowledgeGraph` method
   signatures, so nothing above this layer notices the change.

`TopologyGraph` stays a **separate, purpose-built graph** (per
`reasoning_blueprint.md`'s Axiom 4 — "a family of typed graphs, not one
graph"). Document-derived topology facts (e.g. a design guide's intended
topology diagram) compile into `KnowledgeGraph` nodes/edges that *reference*
`TopologyGraph` node IDs (device IPs) rather than merging the two schemas.

---

## Part 5 — Ontology

A shallow, extensible taxonomy — deliberately not a deep formal ontology
(OWL/RDF), because nothing downstream (the graph, the reasoning registry)
needs formal inference; it needs consistent categorization for filtering and
authority ranking, which `SourceType`/`ObjectType` already do at the
document/object level. The ontology is the classification of `ObjectType`
values into families, so a new object type has a documented home:

```
Protocol            (OSPF, BGP, EIGRP, IS-IS, MPLS, ...)
Feature             (QoS, NAT, HSRP/VRRP, DMVPN, VXLAN-EVPN, ...)
Object               (Interface, VRF, VLAN, ACL, Route, Neighbor, ...)
Configuration        (stanza, template, golden config, standard)
Operational State    (up/down, established, degraded, flapping)
Intent               (remediation intent, design intent, business rule)
Security             (policy, rule, advisory, vulnerability)
Cloud/Infrastructure (VPC, cloud gateway, NSX segment — future vendor scope)
Application          (service, dependency, SLA)
Event/Incident       (alarm, incident, root cause, remediation record)
Dependency           (cross-object, cross-document reference)
```

Extension rule: adding a family is a new top-level key in this taxonomy plus
new `ObjectType` members under it — never a change to an existing family's
members.

---

## Part 6 — Validation Layer (net-new, but small)

Operates on `EnterpriseKnowledgeLayer` search results and compiled
`NormalizedObject`/`GraphNode` instances — no new store.

```
Duplicate detection    → content-hash, ALREADY DONE at the document level
                          (EnterpriseKnowledgeLayer.ingest()'s _content_hash);
                          extend to the object level: two NormalizedObjects
                          with equal (type, device, key attributes) hash
Conflict detection      → NEW: two objects with equal (type, device, id) but
                          differing attribute values → flagged, not silently
                          overwritten; surfaced with both sources' Citation
Staleness               → ALREADY DONE (ttl_policy.py + KnowledgeEntry.is_stale()
                          + EnterpriseKnowledgeLayer._recency_factor())
Confidence scoring      → ALREADY DONE (EnterpriseKnowledgeLayer.confidence():
                          0.60·semantic + 0.25·source_authority + 0.15·recency);
                          extend the same formula to object-level confidence
                          by substituting semantic score with extractor
                          agreement (how many extractors/sources concur)
Broken references       → NEW: a GraphRelationship whose target node_id
                          doesn't resolve — flag at publish time, don't
                          silently drop the edge
```

Three of five validation concerns are already solved at the document level;
the genuinely new work is conflict detection and broken-reference checking
at the object/graph level — both small, well-bounded functions.

---

## Part 7 — Metadata & Storage architecture

No new storage tier is needed for MVP scope. Map artifact types to what
exists:

| Artifact | Storage today | Gap |
|---|---|---|
| Raw source documents | Not persisted (read, parsed, discarded) | Add optional raw-blob retention (local disk or object store) if audit requires the original PDF/DOCX on hand — currently only the extracted text + `extra={"path": ...}` metadata survives |
| Parsed text / chunks | ChromaDB via `EnterpriseKnowledgeLayer` | None — this is the right store |
| Document metadata | Chroma metadata dict (`doc_id`, `version`, `content_hash`, `ingested_at`, `source_type`, `vendor`, `platform`, `tags`) | Add `license` field (the original prompt's "Licensing Metadata" — genuinely absent today) and `trust_score` (distinct from `confidence`: trust is about the *source*, confidence is about the *retrieval match*) |
| Canonical objects | None yet (L5 doesn't exist) | New: lives in `KnowledgeGraph` nodes once L4-L6 are built — no separate object store needed |
| Graph | In-memory (`core.knowledge_graph.KnowledgeGraph`) | Roadmap-gated persistence (Part 4.4) |
| Command/vendor-doc cache | SQLite (`core.knowledge.cache.cache_db`) | None |
| Operational memory / embeddings | `core.intelligence.operational_memory.OperationalMemory` | None |
| Audit log | `GovernanceContract.ts` + status, per governed action | Not a durable audit *store* today — GovernanceContract instances aren't persisted anywhere visible; if compliance requires a queryable audit trail, that's a genuine gap worth a dedicated append-only log, separate from this compiler effort |

Full metadata record (extending `Citation` + `KnowledgeRecord.extra`,
not a new class):

```
source_name, source_type, source_url, source_title, vendor, platform,
confidence, fetched_at, ingested_at, version, content_hash, superseded,
tags, license (NEW), trust_score (NEW), extraction_method (NEW: "deterministic"|"llm"),
compiler_version (NEW: which NKC pipeline version produced this — for lineage)
```

---

## Part 8 — API / SDK Layer

`network_compiler.py` is the MVP CLI form of this layer today
(`ingest`, `standard`, `rfc`, `vendor-doc`, `search`, `stats`). The full API
surface, as thin wrappers over the layers above (no new business logic in
the API layer itself — same principle `core/vendor/gateway.py` follows: the
facade orchestrates, it doesn't decide):

```
compile(source, options)        → runs L1-L8 for one source, returns a
                                   CompilationReport (files in, objects out,
                                   edges out, validation warnings)
parse(path)                      → L2 only (== core.knowledge.parsers.extract_text)
normalize(objects)                → L5 only, exposed standalone for testing
                                    extractors against known input
validate(doc_id | object_id)      → L7 only, re-run validation without recompiling
search(query, filters)            → == EnterpriseKnowledgeLayer.search() today
explain(object_id)                → walk provenance: object → source doc(s) →
                                     citation(s) → confidence breakdown
                                     (composes existing CitationTracker +
                                     EnterpriseHit.metadata, no new storage)
reason(question, context)         → == KnowledgeOrchestrator.rag_query() +
                                     ReasoningRegistry composition (existing)
diff(doc_id, v1, v2)               → NEW, small: two Chroma-stored versions of
                                     the same doc_id already exist (versioning
                                     is done); diff is a text/object comparison
                                     over them
export(format, filter)            → NEW, small: serialize KnowledgeGraph subset
                                     or EnterpriseKnowledgeLayer hits to JSON/CSV
import(source)                    → == ingest_file/ingest_directory today
graph_query(pattern)              → == KnowledgeGraph.find_path/trace_impact_chain
                                     today, exposed over the API layer
```

Roughly half of this API already exists as Python functions; the "API layer"
work is consolidation and a stable interface (REST/CLI/SDK), not new logic.

---

## Part 9 — Security architecture (honest gap)

This is the thinnest part of the existing platform relative to the original
prompt's ask, and it would be dishonest to paper over it:

- **Authentication**: none in `core/knowledge/*` today — it's a library
  called from within an already-authenticated Streamlit session context
  (`config/workspaces.py` governs workspace-level access elsewhere in the
  platform, not knowledge-layer access specifically).
- **Authorization / RBAC**: `core.policy.contract.PolicyContract.role_validation`
  is presence-of-an-operator-string, not a real permission check (confirmed
  in the gap analysis). A production NKC handling TAC cases, internal wikis,
  and customer docs with different sensitivity levels needs real RBAC on
  `SourceType`/`tags` at minimum (e.g., "customer_doc tagged
  customer=acme is only searchable by operators scoped to that account") —
  this does not exist and is a real build item, not an extension of
  something partial.
- **Secrets management**: out of scope for NKC specifically — device
  credentials are handled elsewhere (`core/topology/credentials.py`,
  `.env`/`core/.env`); NKC never touches device credentials, only documents.
- **Encryption at rest**: ChromaDB/SQLite files are unencrypted on local
  disk today — acceptable for a single-operator local deployment, a real
  gap for multi-tenant.
- **Provenance as a security property**: this one *is* strong today —
  every `KnowledgeEntry`/`EnterpriseHit` carries `Citation`, so "where did
  this fact come from" is always answerable. Keep this invariant as NKC
  grows; every new extractor output must carry it too.

Recommendation: don't build RBAC speculatively ahead of a real multi-tenant
requirement (this platform is currently single-operator-oriented per prior
session context) — but track it explicitly as a blocking gap the moment
multi-tenant or customer-data ingestion becomes real, rather than assuming
`role_validation`'s string check is a security control.

---

## Part 10 — Observability, scalability, fault tolerance

**Observability — mostly already exists:**
`EnterpriseKnowledgeLayer.health()/.metrics()/.source_statistics()/.retrieval_latency()`
already report chunk counts, per-source breakdowns, and p50/p95 latency.
Extend with: per-extractor success/failure counts (L4), validation-flag
counts (L7), and compiler-version lineage (Part 7) — all additive fields on
existing report dicts, not new subsystems. Tracing: none exists today
end-to-end; adding OpenTelemetry spans around the L1-L8 pipeline stages is
real but mechanical work, deferred to the scale-out roadmap phase.

**Scalability — today's real ceiling:** single-process, in-memory
`KnowledgeGraph`, local ChromaDB file, synchronous ingestion
(`ingest_directory` walks files serially; `orchestrator.lookup_batch` already
parallelizes *remote fetches* with a `ThreadPoolExecutor`, so the pattern for
introducing concurrency elsewhere is established). This comfortably handles
thousands of documents; "millions of documents" from the original prompt
needs, in order of when they'd actually bind:
1. Parallelize `ingest_directory` (thread pool, same pattern as
   `lookup_batch`) — small change, first bottleneck to hit.
2. Move `KnowledgeGraph` off in-memory adjacency lists (Part 4.4) — second
   bottleneck, once the graph exceeds single-process memory.
3. Queue-based ingestion (a real message queue in front of L1) — only
   needed once ingestion volume exceeds what a scheduled batch job handles;
   don't build this ahead of that need.

**Fault tolerance — already partially present:** every fetcher and parser
degrades gracefully today (`extract_text` catches `ImportError`/generic
exceptions per-file and logs rather than aborting the batch;
`ingest_directory`'s per-file try/except does the same). What's missing:
retry-with-backoff for transient fetch failures (currently one attempt), and
a dead-letter list for files that fail every extractor (currently just
logged, not tracked for re-processing). Both are small, additive changes to
existing loops — not new architecture.

---

## Part 11 — Continuous learning / incremental compilation

**Already solved at the document level**, and this is worth stating plainly
because it's the part of the original prompt most likely to be
over-engineered if built from scratch: `EnterpriseKnowledgeLayer.ingest()`
already does content-hash dedup (skip unchanged), versioning (new content →
version+1, old marked `superseded`), and `run_standard_pipelines`/
`ingest_directory` are naturally idempotent (re-running only changes what
changed). That *is* incremental compilation for the document/chunk layer.

**What extends it, once L4-L6 exist:** re-running semantic extraction only
for documents whose `content_hash` changed since their last-compiled
version (a single new field on the version metadata: `last_compiled_hash`),
and re-running graph compilation only for the `NormalizedObject`s that came
from those documents (traceable via the `_source_doc_id` reserved attribute
key from Part 2). No new incremental-build system — a hash comparison gate
in front of the existing per-document ingest loop.

---

## Part 12 — Extension mechanisms (summary)

| Extension | Mechanism | Already proven by |
|---|---|---|
| New vendor (doc fetcher) | Subclass `VendorFetcher`, register in `vendor_router._FETCHERS` | Huawei/Dell/Extreme, added last session |
| New vendor (live adapter) | Subclass `VendorAdapter`, `@register` decorator | `IosLikeAdapter`/`JuniperJunosLikeAdapter`/`GenericCliAdapter` |
| New document format | Add extractor fn + entry in `parsers._EXT_MAP` | PDF/DOCX/JSON/YAML/XML/CSV/HTML, added last session |
| New protocol/object type | Add `Op` constant + `ObjectType` member | Additive enum members, zero engine changes (Part 2) |
| New semantic extractor | Register against L4's section-classifier taxonomy | Same registry pattern as `ReasoningRegistry` |
| New graph edge type | Add to the typed-edge vocabulary (Part 4.1) | Backward compatible (str-backed enum) |
| New source type (taxonomy) | Add `SourceType` member + `SOURCE_RANK` weight | 8 types added last session |

---

## Part 13 — Phased roadmap

```
Phase 0  MVP (SHIPPED)     Acquisition + Parsing + typed Publishing
                           core/knowledge/parsers, enterprise/pipelines,
                           8 new SourceTypes, 3 new vendor fetchers,
                           network_compiler.py CLI

Phase 1  Semantic core     SHIPPED — core/knowledge/compiler/: tokens.py
    (SHIPPED)              (lexer/tokenizer), ast_builder.py (parser/AST,
                           indentation + `!`-stanza nesting), semantic_
                           analyzer.py (10 deterministic extractors:
                           interface/protocol+neighbor+timer/acl/vrf/vlan/
                           qos/nat/security_rule/state+error+warning/
                           dependency, plus analyze_structured() for
                           JSON/YAML/XML), canonicalizer.py (SemanticFinding
                           -> NormalizedObject with provenance stamping),
                           relationships.py (6 deterministic rules ->
                           GraphRelationship, using the new RelationType
                           vocabulary added to core/knowledge_graph.py),
                           validation.py (missing-field/duplicate/conflict/
                           broken-reference checks), compiler.py
                           (SemanticCompiler: compile_cli/configuration/
                           document/protocol/directory/incremental,
                           publishes into KnowledgeGraph). ObjectType
                           extended with VLAN/QOS/NAT/SECURITY_RULE/
                           CLOUD_RESOURCE. 30 tests in
                           tests/test_semantic_compiler.py, all passing;
                           full suite shows the same pre-existing 6
                           failures as before (torch/sentence-transformers
                           environment issue, unrelated). Phase 2 (below)
                           is the next increment.

Phase 2  Graph compilation SHIPPED — core/knowledge/compiler/identity.py
    (SHIPPED)              (Cisco interface/protocol alias normalization,
                           merge_attributes, merge_duplicate_objects — both
                           within-batch and cross-batch via graph_ops.
                           merge_into_graph, replacing blind overwrite),
                           ontology.py (FAMILY_OF_TYPE, operationalizing
                           Part 5 as code), graph_ops.py (export_graph/
                           import_graph JSON snapshots, optimize_graph
                           edge-dedup, diff_graph, merge_two_graphs),
                           validation.py extended with validate_graph
                           (orphan nodes, cycle detection, duplicate-
                           relationship audit, broken-reference audit).
                           Found and fixed a real latent bug along the way:
                           KnowledgeGraph.add_relationship
                           (core/knowledge_graph.py) appended a duplicate
                           edge on every repeated call for the same
                           (source, target, relationship_type) — now
                           idempotent (updates weight/metadata in place),
                           confirmed backward compatible with the topology
                           bridge's usage. SemanticCompiler gained a
                           coherent Graph API: compile_graph/validate_graph/
                           optimize_graph/diff_graph/export_graph/
                           import_graph/merge_graph. compile_incremental now
                           reports an entity-level stats["delta"] (added/
                           removed/changed objects and relationships), not
                           just a file-level skip/recompile signal. See
                           docs/nkc_canonical_network_language.md for the
                           CNL spec this phase formalized. 25 tests in
                           tests/test_knowledge_graph_compiler.py, all
                           passing; full suite unchanged from Phase 1's
                           6 pre-existing failures. Phase 3 (below) is the
                           next increment.

Phase 3  Cross-document     SHIPPED — core/knowledge/compiler/facts.py
    (SHIPPED)              (Fact model: subject/predicate/object/context/
                           confidence/provenance, default-value-assertion
                           extraction from EnterpriseKnowledgeLayer-ingested
                           reference text), fact_conflicts.py (ConflictRecord
                           shared by fact-level and cross-device-object
                           conflicts; fact_confidence() blending SOURCE_RANK/
                           agreement/recency/evidence-count), cross_
                           reference.py (deterministic RFC/CVE/bug-ID/field-
                           notice detection), protocol_models.py (generic
                           state-machine registry, seeded with verified OSPF-
                           neighbor and STP-port models only — see
                           docs/nkc_fact_and_conflict_model.md for why not
                           more), cross_document_compiler.py
                           (CrossDocumentCompiler: compile_facts/
                           validate_facts/resolve_conflicts/
                           correlate_documents/merge_evidence/
                           build_protocol_model/optimize_knowledge/
                           publish_facts/compare_versions/
                           detect_cross_device_conflicts — every method a
                           thin composition of an existing module, no
                           parallel logic). Facts publish into the SAME
                           KnowledgeGraph Phase 1/2 already builds via the
                           unchanged graph_ops.merge_into_graph. Tests in
                           tests/test_cross_document_compiler.py, all
                           passing; full suite unchanged from Phase 1-2's
                           6 pre-existing failures. Phase 4 (below) is the
                           next increment.

Phase 4  Reasoning          SHIPPED — core/knowledge/compiler/artifacts.py
    Artifacts (SHIPPED)    (ReasoningArtifact/FailureSignature/
                           VerificationTemplate/RemediationTemplate/
                           DecisionGraph/RiskAnnotation data model, all
                           publishing into the SAME KnowledgeGraph via
                           the unchanged graph_ops.merge_into_graph),
                           failure_signatures.py (textbook root-cause
                           library for OSPF/STP — the only two protocols
                           with a verified state model from Phase 3 —
                           plus an independently-grounded ACL-deny
                           signature read directly from Phase 1's
                           compiled objects), reasoning_artifact_
                           compiler.py (ReasoningArtifactCompiler:
                           compile_root_causes/verification/remediation/
                           decision_graph/risk/troubleshooting/reasoning,
                           optimize_artifacts, compile_incremental with
                           version/history tracking, publish_artifacts).
                           The load-bearing decision this phase made:
                           almost everything its own brief asked for
                           already existed (core.troubleshooting.
                           hypotheses, core.intelligence.decision,
                           core.governance risk scoring, core.vendor.
                           operations remediation) — see
                           docs/nkc_reasoning_artifact_model.md's
                           side-by-side table. What was actually built is
                           narrow: STATIC, precompiled, reusable artifacts
                           (compile once, reuse many times) derived from
                           verified protocol models and existing vendor-
                           adapter intents — not a second hypothesis/
                           decision/risk engine. Tests in
                           tests/test_reasoning_artifact_compiler.py, all
                           passing; full suite unchanged from prior
                           phases' 6 pre-existing failures. Wiring these
                           artifacts into TroubleshootingEngine's live
                           hot path is the natural next step, explicitly
                           deferred (see the doc). Phase 5 (below) is the
                           next increment.

Phase 5  Supply Chain       SHIPPED — core/knowledge/compiler/
    facade (SHIPPED)       supply_chain.py: NetworkIntelligenceSupplyChain,
                           a thin delegating facade unifying Level 1 (Raw
                           Knowledge, Phase 0), Level 2 (Compiled
                           Knowledge, Phases 1-4), and Level 3 (Operational
                           Intelligence — core.intelligence.
                           operational_memory.OperationalMemory +
                           core.intelligence.learning.LearningEngine,
                           BOTH pre-existing, predating NKC) under one
                           stable API surface, satisfying this phase's
                           original "API consolidation" goal plus more.
                           Extended enterprise/pipelines.py with
                           fetch_and_ingest_vendor_doc() (extracted from
                           network_compiler.py's cmd_vendor_doc, now
                           shared instead of duplicated) and
                           archive_source(). Extended failure_
                           signatures.py with compile_operational_
                           failure_signatures() — the one genuinely new
                           algorithm, converting OperationalMemory.
                           recurring_failures()'s raw operational history
                           into the SAME FailureSignature shape Phase 4's
                           textbook OSPF/STP signatures use. Added
                           publish_operational_intelligence(), which
                           closes the "continuously learning supply
                           chain" loop: a learned operational pattern
                           publishes into BOTH the EnterpriseKnowledgeLayer
                           (searchable) and the KnowledgeGraph
                           (traversable), via the unchanged
                           ingest_incident_report()/graph_ops.
                           merge_into_graph(). 14 tests in
                           tests/test_supply_chain.py, all passing; full
                           suite unchanged from prior phases' 6 pre-
                           existing failures. See
                           docs/nkc_supply_chain.md for the full data-flow/
                           sequence diagrams and an honest gap report
                           (LearningEngine's Corpus hardcodes global
                           memory singletons with no DI — a pre-existing
                           constraint, not fixed here).

Phase 6  Scale-out          Parallelize ingestion, graph persistence,
                           tracing — only once volume actually demands it
                           (don't build ahead of real document counts)

Phase 7  Security hardening RBAC on SourceType/tags, encryption at rest —
                           gated on multi-tenant/customer-data becoming real
                           requirements, not built speculatively
```

Each phase is independently shippable and testable against the existing
test suite pattern (`tests/test_knowledge_parsers.py` established the
`FakeEmbedder` + temp-ChromaDB-dir pattern for testing without a real model
download — reuse it for Phase 1-3 tests).

**Recommendation:** the next concrete build increment, if you want one, is
**wiring Phase 4's artifacts (now reachable via the Phase 5 facade) into
`TroubleshootingEngine`** (the natural completion of "compile once, reuse
many times" — right now the artifacts are compiled and published but
nothing in the live troubleshooting hot path consults them yet), **richer
provenance chaining** (Phase 5's gap report item #2 — linking a published
artifact back to the exact `MemoryEvent` ids, not just the signature
text), or **Phase 7** (security hardening, if multi-tenant/customer-data
ingestion is becoming a real near-term requirement). Say the word and
I'll scope whichever one the same way we scoped Phases 0-4: a short plan,
sign-off, then build against the existing test pattern.
