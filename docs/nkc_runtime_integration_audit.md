# Runtime Integration Audit — NKC ↔ Live Troubleshooting Engine

> Status: audit only. No code changed to produce this document. Every
> claim below was verified directly against the repository this session
> (`grep`/`Read`, not memory) — file:line citations throughout. Companion
> documents: [`nkc_architecture_blueprint.md`](nkc_architecture_blueprint.md),
> [`nkc_reasoning_artifact_model.md`](nkc_reasoning_artifact_model.md),
> [`nkc_supply_chain.md`](nkc_supply_chain.md).

## Executive summary

The Network Knowledge Compiler (`core/knowledge/compiler/`) and the live
`TroubleshootingEngine` (`core/troubleshooting/`) are two fully-built,
fully-tested, **completely disconnected** systems today. Verified by
direct grep this session:

```
grep -rln "get_compiled_graph|ReasoningArtifactCompiler|CrossDocumentCompiler|
            SemanticCompiler|failure_signatures|protocol_models|supply_chain|
            compile_facts|FailureSignature" core/troubleshooting/ core/intent_engine.py core/vendor/
→ zero matches
```

Every hypothesis, every planned command, every proposed fix in a live
troubleshooting session is invented fresh by an LLM call, bounded only by
a fixed `0.05–0.4` prior range, with **no access** to the deterministic,
already-compiled, already-tested knowledge sitting one import away. This
audit traces the full pipeline for "why is OSPF stuck in EXSTART?",
enumerates every seam, and rates each one's integration risk — per your
instruction, no code changes follow until this is reviewed.

**One correction to my own framing from two turns ago**: I previously said
the topology-grounding fix should point at `get_compiled_graph()`. Having
now read `core/topology/knowledge_graph_bridge.py` directly, that's
imprecise — that file's `build_knowledge_graph(devices)` builds a
**separate, legitimate, live-CDP/LLDP-discovered graph**, correctly kept
distinct from the NKC's compiled graph under this repo's own "family of
typed graphs" principle (both happen to be instances of the same
`core.knowledge_graph.KnowledgeGraph` class, but hold different content —
physical adjacency vs. compiled interface/protocol/fact objects). The fix
for topology grounding is to call `build_knowledge_graph()`, not
`get_compiled_graph()`. Corrected throughout this document.

---

## Part 1 — Repository audit

| Directory | What's actually there | Relevant to this integration? |
|---|---|---|
| `core/troubleshooting/` | `engine.py` (control loop), `reasoning.py` (all LLM calls), `hypotheses.py` (confidence math, deterministic), `models.py` (Session/Hypothesis/Fix/VerificationPlan), `evidence_graph.py` (session-scoped contradiction tracker, **not** the NKC graph — naming collision noted) | Yes — the consumer side that needs to change |
| `core/intelligence/` | `operational_memory.py`, `learning/` (already bridged in Phase 5), `decision/` (Deliberation Engine — a different, runtime, multi-criteria judgment system, not a target for this integration), `forecasting/`, `outcome_contract.py`, `reasoning.py` (`ReasoningRegistry`/`Conclusion`/`Evidence` — the taxonomy `docs/reasoning_blueprint.md` designed) | Partially — Phase 5 already bridged `OperationalMemory`/`LearningEngine`; `core.intelligence.reasoning`'s registry is a **third** place hypothesis-like `Conclusion`s could flow through, not touched by this audit's scope |
| `core/knowledge/` | `orchestrator.py` (cache→RAG→web→MCP chain, Phase 0), `enterprise/` (`EnterpriseKnowledgeLayer`, authority-ranked hybrid search, Phase 0), `cache/`, `fetchers/`, `parsers/`, `rag/` | Yes — `orchestrator.rag_query()` is what `IntentEngine._ground()` calls; it bypasses `EnterpriseKnowledgeLayer.search()`'s authority weighting entirely (confirmed below) |
| `core/knowledge/compiler/` | Everything built in this session's Phases 1-5: `compiler.py`, `graph_ops.py`, `identity.py`, `ontology.py`, `validation.py`, `facts.py`, `fact_conflicts.py`, `cross_reference.py`, `protocol_models.py`, `cross_document_compiler.py`, `artifacts.py`, `failure_signatures.py`, `reasoning_artifact_compiler.py`, `supply_chain.py` | Yes — the producer side, fully built, zero consumers today |
| `core/vendor/` | `models.py` (`NormalizedObject`), `operations.py` (`Op`, `RemediationIntent`), `sdk.py` (`VendorAdapter`), `gateway.py` (`VendorGateway.collect/remediate`), `adapters/cisco_ios_like.py` | Yes — `gateway.collect()` calls `adapter.build_command()` directly (confirmed, `core/vendor/gateway.py:79`), no NKC seam here either, and this is where the separate MTU-command bug from two turns ago lives |
| `core/topology/` | `knowledge_graph_bridge.py` (`build_knowledge_graph()` — live CDP/LLDP graph, confirmed function name this session), `topology_engine.py`, `l3_topology.py`, `role_classifier.py` | Yes — the CORRECT target for the topology-grounding fix (not the NKC compiled graph — see correction above) |
| `core/governance/` | `contract.py` (`GovernanceContract`), `engine.py` (`GovernanceEngine.govern()`) | Confirmed via grep: **never called** from `core/troubleshooting/engine.py`. This is a deliberate boundary (governance runs at deploy time elsewhere in the platform), not a gap — noted, not flagged as a fix |
| `core/evidence/` | `contract.py` (`EvidenceContract`), `assessor.py` (`EvidenceAssessor`) — per-request evidence-completeness scoring, distinct from Phase 3's `Fact`/`ConflictRecord` evidence model | Not directly wired into troubleshooting either, but out of THIS audit's scope (a request-scoped gate, not a knowledge source) |
| `core/memory/` | **Does not exist.** Only `core/intelligence/memory/` exists (confirmed via `ls` this session) — the mission's directory list has a naming mismatch; noted so nobody goes looking for a directory that isn't there | N/A |

---

## Part 2 — Where NKC outputs are produced, stored, loaded, consumed

| NKC output | Produced by | Stored in | Loaded by | Consumed by troubleshooting engine? |
|---|---|---|---|---|
| Canonical/Semantic Objects | `SemanticCompiler.compile_*()` | `get_compiled_graph()` (in-memory `KnowledgeGraph`) | `graph_ops.export_graph()`, `SemanticCompiler.export_graph()` | **No** |
| Knowledge Graph | Phases 1-5, shared singleton | same as above | `NetworkIntelligenceSupplyChain.export_compiled_knowledge()` | **No** — `_topology_facts()` builds an unrelated empty graph instead |
| Facts | `CrossDocumentCompiler.compile_facts()` | Not persisted as a distinct store — held in memory per call, optionally published as graph nodes (`fact_to_object`) | `resolve_conflicts()`, `merge_evidence()` | **No** |
| Evidence (Fact-level) | Same as Facts — `Fact.citation`/`source_doc_id` | Same | Same | **No** |
| Ontology | `ontology.py`'s static `FAMILY_OF_TYPE` | Module constant, no store | `family_of()` calls in validation/reporting | **No** — not used by `_obs_matches_signals`' token-overlap gate |
| Protocol Models | `protocol_models.PROTOCOL_STATE_MODELS` (OSPF, STP only) | Module constant | `build_protocol_model()` | **No** |
| Failure Signatures | `failure_signatures.compile_failure_signatures()` / `compile_operational_failure_signatures()` | Not persisted independently; published as graph nodes via `ReasoningArtifactCompiler.publish_artifacts()` | `ReasoningArtifactCompiler.compile_root_causes()` | **No** — this is the single highest-value gap: OSPF/ExStart confidence 0.85 sits unused while the live engine guesses 0.20 |
| Verification Templates | `reasoning_artifact_compiler._VERIFICATION_TEMPLATES` | Module constant | `compile_verification()` | **No** |
| Remediation Templates | `reasoning_artifact_compiler._REMEDIATION_INTENTS` | Module constant | `compile_remediation()` | **No** — points at real `IosLikeAdapter` intents, unused |
| Decision Graphs | `compile_decision_graph()` | In-memory per call | — | **No** |
| Risk Annotations | `compile_risk()` | In-memory per call | — | **No** — `TroubleshootReport` has no risk field at all (confirmed: zero "risk" hits anywhere in `core/troubleshooting/*.py`) |
| Operational Intelligence | `OperationalMemory` + `LearningEngine` (pre-existing) | `.ai_net_studio_memory.sqlite` + shared derived-memory store | `NetworkIntelligenceSupplyChain` (Phase 5) | **No**, from the troubleshooting engine's side — Phase 5 built the write/bridge path but nothing reads it back into a live session |

---

## Part 3 — Full runtime trace: "why is OSPF stuck in EXSTART?"

Entry point confirmed this session: `core/copilot_engine.py:781` — "Troubleshoot & Fix" mode constructs a **brand-new** `TroubleshootingEngine` per request (new `cmd_memory`, new `EvidenceGraph`, no `session_store` passed) and calls `tse.run(user_text)` directly. `IntentEngine._classify()`/`_detect_scenario()` (the keyword-based intent/protocol classifier) is **not** on this path at all — it's used by a different Copilot mode. This matters: there is currently no deterministic "which protocol is this about" extraction anywhere in the path that produced the trace you showed me.

```
copilot_engine.py:781  TroubleshootingEngine(ai_call, devices, gateway=gw).run(query)
  │
  ├─ grounding = IntentEngine._ground(query, devices)          [intent_engine.py:1098]
  │    ├─ _rag_context_for()  → KnowledgeOrchestrator.rag_query()
  │    │                         → get_rag_engine().search()      ← bare RAGEngine, NOT
  │    │                           EnterpriseKnowledgeLayer.search() (no authority weighting)
  │    ├─ _vendor_doc_context() → live HTTP fetch per command, no Fact-layer cache/conflict-check
  │    └─ _topology_facts()   → kg = KnowledgeGraph()               ← FRESH, EMPTY, every call
  │                              (confirmed via Read this session, intent_engine.py:1119-1120)
  │
  ├─ objective = Reasoner.phrase_objective(query)     [reasoning.py, LLM]
  ├─ _observe_initial_state() → plan_operations → gateway.collect() → adapter.build_command/parse_output
  ├─ generate_hypotheses(objective, grounding, ...)   [reasoning.py, LLM, prior 0.05–0.4]
  │     ← failure_signatures.compile_failure_signatures("ospf") NEVER CALLED (confidence 0.85 unused)
  │     ← protocol_models.build_protocol_model("ospf") NEVER CALLED
  │
  ├─ loop (max 6 steps, per copilot_engine.py:783's TSConfig(max_steps=6)):
  │    ├─ plan_operations(...)                         [LLM — no VerificationTemplate consulted]
  │    ├─ gateway.collect() → adapter.build_command()  [core/vendor/gateway.py:79]
  │    │     ← IosLikeAdapter maps GET_INTERFACE_DETAILS+ospf → "show ip ospf interface" ONLY
  │    │       (confirmed cisco_ios_like.py:57) — this command's real output has NO MTU field;
  │    │       MTU only appears in `show interface <name>`, never mapped for any operation
  │    ├─ analyze(command, output, active_hypotheses)  [reasoning.py, LLM — free-form extraction,
  │    │                                                 Phase 1's deterministic extractors unused]
  │    ├─ hmgr.reap()                                  [hypotheses.py — deterministic, fine as-is]
  │    ├─ ranker.converged(session)                     [hypotheses.py — deterministic, fine as-is]
  │    └─ widen() if weak → generate_hypotheses again  [same LLM-prior gap, repeated]
  │
  └─ _finish(): propose_intent / generate_fix + plan_verification   [reasoning.py, LLM]
        ← reasoning_artifact_compiler.compile_remediation("ospf") NEVER CALLED
        ← reasoning_artifact_compiler.compile_verification("ospf") NEVER CALLED
        ← compile_risk("ospf") NEVER CALLED — no risk field exists on TroubleshootReport at all
```

---

## Part 4 — Runtime Integration Matrix

Nine columns per your spec, all 18 stages. `Risk` uses Low / Medium / High,
judged by: how many other call sites share the changed function, whether
the change is additive-only vs. behavior-replacing, and whether existing
tests cover the path.

### 1. User Request
- **File/Function**: `core/copilot_engine.py`, inline in the chat-handling block (~line 766-786)
- **Behaviour**: UI mode dispatch; "Troubleshoot & Fix" instantiates a fresh `TroubleshootingEngine` per request
- **NKC component**: None directly — this is dispatch, not reasoning
- **Integrated?**: N/A
- **Minimal safe integration**: None needed at this stage
- **Risk**: N/A

### 2. Intent Resolution
- **File/Function**: Effectively `Reasoner.phrase_objective()` (`reasoning.py`); `IntentEngine._detect_scenario()` exists but is **not on this code path**
- **Behaviour**: One LLM call restates the query as an objective sentence; no structured protocol key is extracted
- **NKC component**: Needed as an INPUT to `protocol_models.build_protocol_model(protocol)` / `failure_signatures.compile_failure_signatures(protocol)` — both require a normalized protocol string
- **Integrated?**: No — nothing extracts one today on this path
- **Why not**: `_detect_scenario()`'s keyword list exists but was never called from `TroubleshootingEngine.run()`
- **Minimal safe integration**: Call the EXISTING `IntentEngine._detect_scenario(query)` (reuse, don't duplicate) alongside `phrase_objective()`, to get a protocol key for the next stage
- **Risk**: Low — purely additive, doesn't change `phrase_objective()`'s existing behavior

### 3. Grounding
- **File/Function**: `IntentEngine._ground()` → `_rag_context_for()` (`intent_engine.py:1040`)
- **Behaviour**: Calls `KnowledgeOrchestrator.rag_query()` → bare `RAGEngine.search()`
- **NKC component**: `EnterpriseKnowledgeLayer.search()` (authority/recency-weighted hybrid RRF)
- **Integrated?**: No
- **Why not**: `orchestrator.rag_query()` predates the Enterprise layer's hybrid search; never swapped
- **Minimal safe integration**: Change `orchestrator.rag_query()`'s backing call from `get_rag_engine().search()` to `get_knowledge_layer().search()` — same underlying ChromaDB collection, so no data migration; output shape differs (`EnterpriseHit` vs `RAGHit`), so the call site needs a small adapter
- **Risk**: Medium — `orchestrator.rag_query()` is a shared utility (used by more than troubleshooting); changing its backing store needs regression coverage across every caller, not just this one

### 4. Topology Lookup
- **File/Function**: `IntentEngine._topology_facts()` (`intent_engine.py:1114`)
- **Behaviour**: `kg = KnowledgeGraph()` — fresh, empty, every call; `get_dependencies()` always returns `[]`
- **NKC component**: **Not** the NKC compiled graph (corrected above) — the right target is `core.topology.knowledge_graph_bridge.build_knowledge_graph(devices)`, a pre-existing, live-CDP/LLDP-populated graph
- **Integrated?**: No — structurally a no-op today
- **Why not**: Looks like leftover code from before the topology bridge existed, or simply never updated
- **Minimal safe integration**: Replace `kg = KnowledgeGraph()` with `kg = build_knowledge_graph(devices)` — one line
- **Risk**: Low — current behavior is a guaranteed no-op, so any real behavior is strictly additive. This likely fixes (or at minimum, is directly implicated in) the currently-failing `tests/test_knowledge_graph_bridge.py::test_topology_facts_now_reports_real_adjacency` — worth confirming by reading that test's actual assertion before claiming the fix closes it.

### 5. Knowledge Retrieval
- **File/Function**: `IntentEngine._vendor_doc_context()`
- **Behaviour**: Live HTTP fetch per command via `vendor_router.get_fetcher()`
- **NKC component**: `CrossDocumentCompiler.compile_facts()` / `resolve_conflicts()` — cached, cross-document-conflict-checked
- **Integrated?**: No
- **Why not**: Built in a later phase than this call site; never wired
- **Minimal safe integration**: Call `compile_facts(query)` first; fall back to the existing live fetch only on a miss (same "compiled-first, live-fallback" shape `orchestrator.lookup()` already uses elsewhere)
- **Risk**: Low-Medium — additive with a fallback, but changes latency characteristics (a Chroma search first, HTTP fetch second) — verify no timeout/UX regression

### 6. Fact Retrieval
- Same as #5 — `Fact`s and vendor-doc grounding are the same seam in this pipeline; not a separate call site today. Listed separately per your stage list, addressed by the same fix.

### 7. Evidence Retrieval
- **File/Function**: `TroubleshootingEngine._observe_initial_state()` / the main loop's evidence collection
- **Behaviour**: Runs live device commands only; no query against already-compiled `NormalizedObject`s for these exact devices (if this config was already compiled by `SemanticCompiler` from a prior config-file ingestion, that compiled truth is never checked before spending a live command)
- **NKC component**: `get_compiled_graph()` — if this device's config was compiled previously, its `interface.mtu` is already sitting there
- **Integrated?**: No
- **Why not**: Never wired
- **Minimal safe integration**: Before planning a live command, check `graph.nodes` for an existing compiled object matching this device+attribute; skip the live call if fresh enough, cite it as evidence instead
- **Risk**: Medium — touches the core collection loop directly; needs careful staleness handling (a compiled object from an old config ingestion could be wrong if the device changed since) — this one needs the most care of any single change

### 8. Hypothesis Generation
- **File/Function**: `Reasoner.generate_hypotheses()` (`reasoning.py`)
- **Behaviour**: LLM proposes up to 4 hypotheses, each with a self-assigned `prior` in `[0.05, 0.4]`
- **NKC component**: `failure_signatures.compile_failure_signatures(protocol)` (0.85 confidence for OSPF/ExStart/MTU)
- **Integrated?**: No — this is Priority 1, the highest-value fix
- **Why not**: Built in Phase 4, never wired into this Phase-0-era function
- **Minimal safe integration**: Before calling the LLM, call `compile_failure_signatures(protocol)`; seed the hypothesis list with any signature matching the CURRENT observed state (e.g., only seed the ExStart/MTU signature if a neighbor is actually observed in ExStart); pass the LLM the seeded set and ask it to **extend, not replace** — same JSON contract, additional context block
- **Risk**: Medium — this function's output directly drives every downstream confidence number; needs the most test coverage of any change here (protocol-specific tests, per your Testing section)

### 9. Confidence Calculation
- **File/Function**: `ConfidenceCalculator.update()` (`hypotheses.py`) — deterministic log-odds, already correct
- **Behaviour**: Confidence changes only via bound `Evidence` (support/contradict), never touches an LLM
- **NKC component**: N/A directly — this stage is fine. The problem upstream (starved evidence, unwired priors) makes THIS stage look worse than it is
- **Integrated?**: Already deterministic and correct as designed
- **Minimal safe integration**: None to this function itself. Confidence quality improves as a SIDE EFFECT of fixing #8 (better priors) and #12 (better evidence) — resist the temptation to add compiled-signature confidence blending directly into `ConfidenceCalculator.update()`, since that would conflate "prior from compiled knowledge" with "log-odds update from observed evidence," two different things this design correctly keeps separate
- **Risk**: N/A (no change recommended here)

### 10. Operation Planning
- **File/Function**: `Reasoner.plan_operations()` (`reasoning.py`)
- **Behaviour**: LLM picks the next operation from `KNOWN_OPERATIONS`, free-form
- **NKC component**: `reasoning_artifact_compiler.compile_verification(protocol)` — curated command list per protocol
- **Integrated?**: No
- **Minimal safe integration**: Pass `compile_verification(protocol).commands` as an explicit "prefer these" block in the prompt, same shape as the existing "PROBE FOR THESE DISCRIMINATING SIGNALS FIRST" block already in this prompt
- **Risk**: Low — additive context in a prompt, existing dedup/safety logic downstream unchanged

### 11. Next Best Command
- **File/Function**: `TroubleshootingEngine._op_signature()` / `cmd_memory.has()`
- **Behaviour**: Dedup keys on `(opname, sorted(params))` string; confirmed bug — `IosLikeAdapter.build_command()` ignores the `interface` param, so `interface=all` and no-interface variants collide into one real command but get DIFFERENT signatures, so neither dedups against the other
- **NKC component**: None directly (this is a framework-level bug, not a missing-knowledge gap) — but `VerificationTemplate`'s curated command list (#10) would reduce the LLM's incentive to invent redundant param variants in the first place
- **Integrated?**: N/A — this is a bug, not a missing integration
- **Minimal safe integration**: Either (a) make `IosLikeAdapter.build_command()` respect `interface` meaningfully (scope the command when a specific interface is given), or (b) normalize known no-op param values (`interface=all` ≡ no interface) before computing the signature. (a) is more correct long-term; (b) is smaller/safer for this pass
- **Risk**: Low for (b), Medium for (a) — (a) changes real command text sent to devices, needs adapter-level tests before anything else

### 12. Evidence Extraction
- **File/Function**: `Reasoner.analyze()` (`reasoning.py`)
- **Behaviour**: Free-form LLM extraction of subject/attribute/value facts from raw command output text
- **NKC component**: Phase 1's deterministic extractors (`interface_extractor`, `protocol_extractor`, etc. in `semantic_analyzer.py`)
- **Integrated?**: No
- **Minimal safe integration**: Run the deterministic extractors on the same output text FIRST; only call `analyze()` (LLM) for whatever the deterministic pass didn't cover (matches your "Priority 6" instruction exactly). Requires converting extractor output (`SemanticFinding`) into the `{"subject","attribute","value"}` shape `_ingest_output()` expects — a small adapter, not new extraction logic
- **Risk**: Medium — this changes what evidence enters the confidence math; needs before/after comparison on the EXSTART scenario specifically to confirm MTU now surfaces correctly (once the adapter command bug from two turns ago is also fixed — the two fixes are linked: this stage can only extract MTU if stage 11's adapter fix makes it reachable at all)

### 13. Hypothesis Ranking
- **File/Function**: `Session.ranked()` (`models.py:195`) — deterministic sort by confidence, already correct
- **Integrated?**: Already fine, no NKC gap — same reasoning as stage 9. Ranking quality is a downstream effect of stages 8/12, not something to change here directly.
- **Risk**: N/A

### 14. Root Cause Selection
- **File/Function**: `RootCauseRanker.converged()` (`hypotheses.py`) — deterministic thresholds (0.80 converge, 0.15 margin), already correct
- **NKC component**: Could additionally check `ProtocolStateModel`/decision-graph consistency (e.g., "is this root cause even reachable from the observed state") but this is a refinement, not a gap fix — **not recommended for this pass**, since the threshold logic works correctly today and this would add complexity without a demonstrated failure mode
- **Risk**: N/A (no change recommended)

### 15. Remediation
- **File/Function**: `Reasoner.propose_intent()` (gateway path) / `Reasoner.generate_fix()` (non-gateway path)
- **Behaviour**: LLM picks an intent name (gateway path) or raw commands (non-gateway path, bypasses adapter entirely)
- **NKC component**: `reasoning_artifact_compiler.compile_remediation(protocol)` — deterministic cause→intent mapping, already pointing at real `IosLikeAdapter` intents
- **Integrated?**: No
- **Minimal safe integration**: In the gateway path, look up the confirmed root cause against `compile_remediation(protocol)`'s mapping first; if a match exists, propose that intent directly (skip the LLM guess); only call `propose_intent()` for causes with no compiled mapping
- **Risk**: Medium — this changes what commands actually get proposed for deployment (human-approved, but still); needs the intent-name cross-check test from two turns ago plus new EXSTART-specific coverage

### 16. Verification
- **File/Function**: `Reasoner.plan_verification()`
- **NKC component**: `compile_verification(protocol).success_criteria`/`.commands`
- **Integrated?**: No
- **Minimal safe integration**: Same pattern as #15 — use the compiled template directly when one exists for the confirmed cause; LLM fills gaps only
- **Risk**: Low-Medium

### 17. Risk Assessment
- **File/Function**: **Does not exist** in `core/troubleshooting/*` — confirmed via grep, zero "risk" references anywhere in this package
- **NKC component**: `compile_risk(protocol)`
- **Integrated?**: No — there is no stage to integrate into; this is a net-new addition, not a rewiring
- **Minimal safe integration**: Add a `risk: Optional[RiskAnnotation]` field to `TroubleshootReport`, populated from `compile_risk()` when `_finish()` proposes a fix
- **Risk**: Low — purely additive field, nothing existing reads or depends on its absence

### 18. Final Response
- **File/Function**: `TroubleshootReport.to_dict()` / `.to_markdown()` (`models.py:210-` — confirmed this session, matches the exact UI output format you pasted two turns ago)
- **Behaviour**: Renders goal/hypotheses/evidence/commands/fix/verification — no evidence sources, no compiled-knowledge citations, no risk (per #17)
- **NKC component**: All of the above, once wired
- **Integrated?**: No
- **Minimal safe integration**: Extend `to_dict()`/`to_markdown()` to render: which failure signature (if any) matched, the risk annotation (#17), and a "knowledge sources" line distinguishing compiled-knowledge-backed claims from LLM-only ones — directly serves your "every recommendation should reference compiled knowledge" success criterion
- **Risk**: Low — additive rendering, no change to the underlying `Session`/`Hypothesis` data model

---

## Part 5 — Priority list, validated against the audit

Your ten priorities map cleanly onto the matrix above. In order of
risk-adjusted value (highest value, lowest risk first — recommended
sequencing, not a claim about what you must do):

1. **Priority 5** (empty graph → `build_knowledge_graph()`) — Low risk, fixes a confirmed structural no-op, may close an existing failing test. **Do this first.**
2. **Priority 1** (seed hypotheses from `compile_failure_signatures`) — Medium risk, highest value (directly fixes the MTU-at-20%/auth-at-30% problem from two turns ago). **Do second**, with dedicated EXSTART regression tests before/after.
3. **Priority 8** (next-best-command dedup) — Low risk if scoped to signature normalization only (not adapter command changes yet).
4. **Priority 2 / Priority 6** (verification templates, deterministic extraction) — Medium risk, depends on #2 producing a confirmed cause to look up against.
5. **Priority 3** (remediation templates) — Medium risk, depends on #2.
6. **Priority 4** (Enterprise layer for grounding) — Medium risk due to shared call sites; do after the troubleshooting-specific wins are validated, so a regression is easier to isolate.
7. **Priority 10** (final response fields) — Low risk, do last, folds in whatever the above produced.
8. **Priority 7** (confidence calculation) — **Recommend declining as specified.** `ConfidenceCalculator.update()` is deterministic and correct; blending compiled confidence directly into it conflates two different things (prior vs. evidence-driven update) this design deliberately separates. The stated goal ("confidence must never be based solely on an LLM prior") is achieved by fixing Priority 1, not by changing this function.
9. **Priority 9** (root cause ranking via decision graphs/relationships) — **Recommend deferring.** `RootCauseRanker`'s threshold logic has no demonstrated failure mode; adding graph-relationship weighting here is speculative complexity without a concrete bug driving it.

---

## Part 6 — Testing strategy for incremental rollout

Per your instruction: baseline first, regression after every step, new
protocol-specific tests (EXSTART, BGP, STP, LACP).

- **Baseline**: capture `tests/test_troubleshooting_engine.py` /
  `tests/test_vendor_framework.py` / `tests/test_mismatch_gateway_bridge.py`
  current pass/fail state before any change (6 pre-existing failures,
  confirmed identically across 6 prior sessions this session — these are
  the baseline, not a target to silently fix as a side effect).
- **BGP/LACP protocol-specific tests**: honest caveat — `protocol_models.py`
  only has verified state models for OSPF and STP (Phase 3's deliberate
  scoping decision, restated in that phase's doc). A "BGP EXSTART-
  equivalent" test can verify the INTEGRATION code path degrades
  gracefully (no seeded signature, falls through to pure LLM exactly as
  today) — it cannot test a compiled BGP signature that doesn't exist.
  Building one is a separate, later decision, not part of this
  integration work.
- Each priority above gets its own before/after test pair using the exact
  EXSTART scenario from this conversation as the running example, plus a
  synthetic "no compiled signature available" case to confirm the LLM
  fallback path still works unmodified.

---

## Waiting for approval, per your instruction

No code has been changed. The sequencing in Part 5 is a recommendation,
not a decision — confirm the order (or reprioritize), confirm the two
declined items (Priority 7, Priority 9), and I'll scope Priority 5 (the
first, lowest-risk fix) as a proper plan the same way every prior phase
in this session was scoped, before touching any code.
