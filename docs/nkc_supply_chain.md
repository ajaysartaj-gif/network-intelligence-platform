# The Network Intelligence Supply Chain

> Status: specification of what's implemented (NKC Phase 5), not an
> aspirational design. Companion documents:
> [`nkc_architecture_blueprint.md`](nkc_architecture_blueprint.md),
> [`nkc_reasoning_artifact_model.md`](nkc_reasoning_artifact_model.md),
> [`nkc_fact_and_conflict_model.md`](nkc_fact_and_conflict_model.md),
> [`nkc_gap_analysis.md`](nkc_gap_analysis.md).

## Why this phase is a reframing, not a rebuild

This phase asked for a "three-layer supply chain" (Raw → Compiled →
Operational Intelligence). Read against the actual repository, **the
first two layers already existed in full** (Phases 0-4), and **the third
layer already existed too — predating any NKC work** in
`core.intelligence.operational_memory.OperationalMemory` and
`core.intelligence.learning.LearningEngine`. The only genuine gap was that
nothing connected operational learning back into the compiled-knowledge
layers. This phase is one thin facade (`core/knowledge/compiler/
supply_chain.py`) plus exactly two new pieces of logic that close that
loop — everything else is delegation to code that was already there.

## The three layers, mapped to real code

```
┌──────────────────────────────────────────────────────────────────────┐
│ LEVEL 1 — RAW KNOWLEDGE                                               │
│ core/knowledge/enterprise/ + fetchers/ + parsers/ + cache/ (Phase 0)  │
│                                                                        │
│  register_source/ingest_document → pipelines.ingest_file/directory   │
│  fetch_vendor_updates            → pipelines.fetch_and_ingest_       │
│                                     vendor_doc()              [NEW]  │
│  detect_changes/version_source   → EnterpriseKnowledgeLayer.ingest()'s│
│                                     content-hash dedup + versioning   │
│  archive_source                  → pipelines.archive_source() [NEW]  │
│  search_raw_sources               → EnterpriseKnowledgeLayer.search() │
└──────────────────────────────────────┬─────────────────────────────────┘
                                        │ compile_document/directory/incremental
                                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ LEVEL 2 — COMPILED KNOWLEDGE                                          │
│ SemanticCompiler + CrossDocumentCompiler + ReasoningArtifactCompiler  │
│ (Phases 1-4), sharing ONE KnowledgeGraph                              │
│                                                                        │
│  compile_document/directory/incremental/graph → SemanticCompiler     │
│  compile_facts                    → CrossDocumentCompiler             │
│  compile_reasoning                 → ReasoningArtifactCompiler        │
│  validate/optimize/export_knowledge → composes the above's existing   │
│                                       validate_graph/optimize_graph/  │
│                                       export_graph                    │
└──────────────────────────────────────┬─────────────────────────────────┘
                                        │ artifact_to_object + graph_ops.merge_into_graph
                                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ LEVEL 3 — OPERATIONAL INTELLIGENCE                                    │
│ core.intelligence.operational_memory.OperationalMemory +              │
│ core.intelligence.learning.LearningEngine (PRE-EXISTING, predates NKC)│
│                                                                        │
│  record_incident/resolution/failed_resolution → OperationalMemory.   │
│                                     record()/record_from_contract()   │
│  learn_from_incident               → LearningEngine.learn_from()      │
│  compile_operational_patterns/     → LearningEngine.retrospect()'s    │
│  generate_lessons_learned            per-learner output / digest()   │
│  update_confidence                  → ConfidenceLearner (via retrospect)│
│  build_failure_signatures           → NEW: recurring_failures() ->    │
│                                        FailureSignature               │
│  publish_operational_intelligence   → NEW: writes BOTH back into      │
│                                        Level 1 (EnterpriseKnowledge   │
│                                        Layer) and Level 2 (KnowledgeGraph)│
└────────────────────────────────────────────────────────────────────────┘
        ▲                                                    │
        └──────────── publish_operational_intelligence ──────┘
             (the loop this phase closes: operational learning
              flows back UP into searchable/traversable knowledge)
```

## Data flow: an incident becomes searchable knowledge

```
1. Engineer fixes an OSPF adjacency stuck in ExStart on R1, R2, R3
   (three separate incidents, same root cause, over time)
        │
2. sc.record_failed_resolution("configure_ospf_interface", device, ...)
   → OperationalMemory.record_from_contract() writes deployment +
     verification (+ recurring-failure, from the 2nd occurrence) events,
     all sharing one stable signature (protocol + normalized intent +
     failed conditions)
        │
3. sc.build_failure_signatures(min_count=2)
   → OperationalMemory.recurring_failures() surfaces the signature
     (count=3, e.g.) → failure_signatures.
     compile_operational_failure_signatures() converts it into a REAL
     FailureSignature (same shape as the textbook OSPF/STP ones),
     confidence scaled by recurrence count
        │
4. sc.publish_operational_intelligence(signature)
   → (a) pipelines.ingest_incident_report() writes it into the
         EnterpriseKnowledgeLayer as SourceType.INCIDENT — now
         `sc.search_raw_sources("ospf stuck")` finds it alongside vendor
         docs and RFCs
   → (b) ReasoningArtifactCompiler.compile_reasoning("ospf") + Phase 2's
         graph_ops.merge_into_graph publish a reasoning_artifact node
         into the KnowledgeGraph — now traversable alongside every
         device object Phase 1 compiled from real configs
        │
5. The next engineer investigating a 4th OSPF ExStart incident finds
   THIS organization's own experience — not just vendor documentation —
   the moment they search or compile reasoning for "ospf"
```

## Sequence diagram: `publish_operational_intelligence`

```
Caller          SupplyChain        OperationalMemory   ReasoningArtifactCompiler   EnterpriseKnowledgeLayer   KnowledgeGraph
  │                  │                    │                       │                        │                     │
  │ record_failed_   │                    │                       │                        │                     │
  │ resolution() x N │───────────────────>│ record_from_contract  │                        │                     │
  │                  │                    │ (writes MemoryEvents) │                        │                     │
  │                  │<───────────────────│                       │                        │                     │
  │ build_failure_   │                    │                       │                        │                     │
  │ signatures()     │───────────────────>│ recurring_failures()  │                        │                     │
  │                  │<───────────────────│ [{signature,count,..}]│                        │                     │
  │                  │ compile_operational_failure_signatures()   │                        │                     │
  │                  │ -> List[FailureSignature]                  │                        │                     │
  │ publish_          │                    │                       │                        │                     │
  │ operational_      │                    │                       │                        │                     │
  │ intelligence(sig) │                    │                       │  ingest_incident_report│                     │
  │                  │─────────────────────────────────────────────────────────────────────>│                     │
  │                  │                    │                       │  (SourceType.INCIDENT)│                     │
  │                  │                    │                       │                        │                     │
  │                  │───────────────────────────────────────────>│ compile_reasoning()   │                     │
  │                  │                    │                       │ publish_artifacts()   │                     │
  │                  │                    │                       │────────────────────────────────────────────>│
  │                  │<─────────────────────────────────────────────────────────────────────────────────────────│
  │<─────────────────│ {knowledge_layer, graph_node_ids}           │                        │                     │
```

## Compiler lifecycle (source → operational feedback → republish)

```
1. SOURCE     a document/config is ingested (Level 1) or an incident is
              recorded (Level 3) — both immutable, versioned, never
              overwritten
2. VERSION    content-hash decides: new version, or skip (unchanged)
3. COMPILE    Level 2 turns new/changed Level 1 content into
              NormalizedObjects/Facts/ReasoningArtifacts (Phases 1-4)
4. VALIDATE   graph/fact validation flags conflicts, never silently
              resolves them
5. PUBLISH    compiled knowledge lands in the shared KnowledgeGraph
6. LEARN      operational outcomes (Level 3) accumulate independently,
              via the same record_from_contract/learn_from path every
              other platform workflow already uses
7. BRIDGE     build_failure_signatures() + publish_operational_
              intelligence() (THIS phase's new contribution) convert
              accumulated operational patterns into the SAME compiled
              shapes as steps 3-5, and republish them into Level 1/2 —
              closing the loop so step 3 next time has more to compile
              from, not just what OEMs published
```

## Gap report for the next evolution phase

Honest, in order of how load-bearing each gap is:

1. **`LearningEngine`'s `Corpus`/learners hardcode the global
   `OperationalMemory`/derived-memory singletons** (confirmed by reading
   `core/intelligence/learning/base.py::Corpus._opmem()` and
   `core/intelligence/memory/store.py`'s `_SHARED_BE` this session) — no
   dependency injection, unlike `OperationalMemory` itself (which cleanly
   accepts `db_path`/`dsn`). This is why this phase's tests use a stub
   learning engine for `learn_from_incident`/`compile_operational_
   patterns`/`update_confidence`/`generate_lessons_learned` rather than a
   real isolated instance. Not fixed here — it predates NKC and reworking
   it is a distinct, larger change to a subsystem with its own existing
   tests, not something to fold into a documentation/facade phase.
2. **Provenance is one level deep, not fully chained.** A published
   `reasoning_artifact` node's `evidence` list names the operational
   signature it came from, but doesn't yet carry a structured pointer
   back to the exact `MemoryEvent.id`(s) that fed `recurring_failures()`
   — the mission's "no object may lose provenance" is satisfied at the
   signature level (searchable text, human-traceable) but not yet at the
   level of "click through from the graph node to the exact incident
   records." A small addition, not built here to keep this phase's scope
   to the bridge itself.
3. **`mistakes()`/`strategies()`/other `LessonStore` output is not yet
   bridged** the way `recurring_failures()` is — only the failure-
   signature path was built, since it's the one with a direct, obvious
   mapping onto Phase 4's `FailureSignature`. Bridging validated
   "strategy" lessons into `RemediationTemplate`, for instance, is a
   natural next increment once there's real accumulated lesson data to
   justify it.
4. **Everything deferred in Phases 0-4 remains deferred**: RBAC on
   `SourceType`/tags, distributed/parallel compilation, additional
   verified protocol state models, real graph persistence beyond JSON
   snapshots — all still gated on real scale/multi-tenant need, not
   built speculatively.
