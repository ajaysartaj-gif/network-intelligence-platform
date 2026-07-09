# The Reasoning Artifact Model

> Status: specification of what's implemented (NKC Phase 4), not an
> aspirational design. Companion documents:
> [`nkc_fact_and_conflict_model.md`](nkc_fact_and_conflict_model.md),
> [`nkc_canonical_network_language.md`](nkc_canonical_network_language.md),
> [`nkc_architecture_blueprint.md`](nkc_architecture_blueprint.md).

## Why this phase is mostly reuse, not new reasoning infrastructure

The Phase 4 brief asked for a "Troubleshooting Compiler," "Root Cause
Compiler," "Decision Compiler," and "Risk Compiler." Read literally, that
sounds like new reasoning infrastructure. It would have been a mistake to
build it that way: **the platform already has working, tested systems for
almost every one of these**, predating any NKC work. This section exists
specifically so nobody — human or AI — proposes a fifth hypothesis engine
or a second decision engine later without checking here first.

| Concept | Pre-existing system | What THIS phase adds instead |
|---|---|---|
| Hypothesis / root-cause generation | `core.troubleshooting.hypotheses` (log-odds `ConfidenceCalculator`, `RootCauseRanker`) **and** `core.intelligence.faculties.HypothesisGenerator` (already two systems — see `docs/nkc_gap_analysis.md`) | `FailureSignature` — a STATIC, precompiled, textbook root-cause library keyed by protocol state, not a runtime hypothesis-generation algorithm. Doesn't replace either existing system; could seed them as a faster, deterministic first guess before they run. |
| Decision-making | `core.intelligence.decision` — a full Deliberation Engine (`Option`, `DecisionContext`, `Appraisal`, `OptionVerdict`, `Judgment`, `DecisionFacultyRegistry`) | `DecisionGraph` — a STATIC precompiled flowchart (condition → action → success/failure path) derived from a protocol's known state transitions. Answers "what's the textbook next step from state X," not "which of these live options should we choose" — a fundamentally simpler, different question. |
| Risk modeling | `core.governance.contract.GovernanceContract.risk_score`/`risk_level` **and** 15+ concrete forecasters in `core.intelligence.forecasting` | `RiskAnnotation` — descriptive metadata on a compiled artifact (severity/impact estimated from compiled-knowledge signals: signature confidence, affected-object count). Explicitly NOT an authorization decision; its `mitigation_reference` field points at `GovernanceEngine.govern()` as the real gate. |
| Verification | `core.troubleshooting.models.VerificationPlan` **and** `core.intelligence.outcome_contract.ContractResult`/`PostCondition` | `VerificationTemplate` — a precompiled command/success-criteria template per protocol, reusable across sessions instead of the LLM re-deriving "what commands prove this is fixed" every time. |
| Remediation | `core.vendor.operations.RemediationPlan` + working per-vendor `build_fix`/`build_rollback` (e.g. `core/vendor/adapters/cisco_ios_like.py`) | `RemediationTemplate` — a POINTER to an existing vendor-adapter intent name (`ignore_protocol_mtu`, etc.), plus prerequisites/risk metadata. Never invents new command text; the adapter still generates the actual commands. |

**The genuine, non-duplicative gap** — what this phase actually builds —
is exactly what its own mission statement named: *"Do not generate
reasoning dynamically. Compile reasoning once. Reuse it many times."*
`core/troubleshooting/reasoning.py`'s `Reasoner` calls the LLM fresh every
single session to generate hypotheses, commands, fixes, and verification
plans. There was no durable, precompiled, reusable artifact store before
this phase. Now there is one — built from Phase 3's verified protocol
state models and Phase 1's compiled objects, not from a fresh LLM call.

**Not built in this phase**: wiring these artifacts into
`TroubleshootingEngine`'s live hot path (so it consults a compiled
`FailureSignature` before calling the LLM). That engine has passing tests
that must not be put at risk by a same-session, unreviewed rewire — it's
the obvious next integration point, explicitly deferred, not built
speculatively.

## The Artifact Model (`core/knowledge/compiler/artifacts.py`)

```
FailureSignature(protocol, stuck_state, likely_cause, evidence_fields, confidence)
VerificationTemplate(protocol, commands, success_criteria, failure_indicators, alternative_checks)
RemediationTemplate(applicable_signature, intent_name, prerequisites, risk_level)
DecisionNode(condition, action, expected_result, on_success, on_failure, escalation)
DecisionGraph(protocol, nodes: List[DecisionNode])
RiskAnnotation(severity, probability, impact, affected_object_count, mitigation_reference)
ReasoningArtifact(id, name, description, version, protocol, evidence, confidence,
                 dependencies, inputs, outputs, failure_signatures, verification,
                 remediation, decision_graph, risk, references, compiler_version)
```

`artifact_to_object()` adapts a `ReasoningArtifact` to the EXISTING
`NormalizedObject` (type=`"reasoning_artifact"`), publishing through Phase
2's `graph_ops.merge_into_graph` unchanged — no new storage model.

## The Root Cause / Failure Signature model

Compiled ONLY for protocols with a verified state model in Phase 3's
`protocol_models.py` — today, exactly OSPF and STP. Confidence is honestly
hedged per signature rather than uniform:

| Protocol | Stuck state | Cause | Confidence | Why |
|---|---|---|---|---|
| OSPF | ExStart | MTU mismatch | 0.85 | Textbook, unambiguous |
| OSPF | Init | Hello/dead-interval/area mismatch | 0.75 | Well-known, a few candidate causes |
| OSPF | Down | L1/L2/ACL/not-enabled | 0.55 | Many possible causes, low precision |
| OSPF | 2-Way | Often NORMAL, not a failure | 0.4 | Explicitly noted: DROTHERs stabilize here on broadcast networks |
| STP | Blocking | Superior BPDU (legitimate or root-guard candidate) | 0.6 | Ambiguous without more context |

**One independently-grounded exception**: `compile_acl_deny_signature()`
reads Phase 1's compiled `acl` objects directly — a `deny` rule IS the
signature (confidence 0.9), not an inference from a state machine.

**No signatures for BGP/ISIS/MPLS/VXLAN/EVPN/HSRP/VRRP/RSTP/LACP** — same
protocols Phase 3 declined to seed a state model for, same reason. Adding
a verified model for one of them later automatically extends this
library — zero new code in `failure_signatures.py`.

## The Verification model

One `VerificationTemplate` per protocol with a seeded model, using real,
well-known commands (`show ip ospf neighbor`, `show spanning-tree
interface <interface> detail`) — not invented syntax. `success_criteria`
and `failure_indicators` are plain-language, checkable conditions, not
new command output parsers (that's Phase 1's `semantic_analyzer.py`'s
job, already built).

## The Decision Graph model

One `DecisionNode` per protocol state, built directly from
`ProtocolStateModel.transitions`: `on_success` is the "forward progress"
transition's target state (deliberately skipping regressions back to
`Down`/`Blocking`/`Disabled` when a forward option exists);
`on_failure` names the matching `FailureSignature.likely_cause`. This is
a flowchart a human troubleshooter could follow on paper — deliberately
simpler than `core.intelligence.decision`'s runtime multi-criteria
`Judgment`, which is answering a different question (which of several
live options to choose, weighing multiple faculties) than "what's the
textbook next step from this protocol state" (this artifact's job).

## The Risk model

`compile_risk()` blends the average confidence across a protocol's
failure signatures (as a rough probability) with a caller-supplied
`affected_object_count` (queried from the shared `KnowledgeGraph` in real
usage) into a severity band. This is descriptive metadata attached to a
compiled artifact — **it is not a deployment gate**. Every
`RiskAnnotation` carries a `mitigation_reference` pointing at
`GovernanceEngine.govern()`, which remains the sole authoritative
pre-deployment risk/compliance check.

## Compiler pipeline (`reasoning_artifact_compiler.py`)

```
protocol name
    │
    ▼  compile_root_causes()       -> failure_signatures.compile_failure_signatures()
    ▼  compile_verification()      -> the command/criteria table above
    ▼  compile_remediation()       -> maps failure cause -> EXISTING vendor-adapter intent
    ▼  compile_decision_graph()    -> protocol_models.py's transitions
    │
    ▼  compile_troubleshooting()   composes the four above into one ReasoningArtifact
    ▼  compile_risk()              (separate — attached only by compile_reasoning)
    ▼  compile_reasoning()         = compile_troubleshooting() + risk attached
    │
    ▼  optimize_artifacts()        dedup by (protocol, content_hash)
    ▼  compile_incremental()       hash-gated version bump + in-memory history
    ▼  publish_artifacts()         -> graph_ops.merge_into_graph() [REUSED, Phase 2]
                                      into the SAME KnowledgeGraph
```

## Integration points (present, and explicitly deferred)

- **Present**: artifacts publish into the same `KnowledgeGraph` Phase 1-3
  already populate, so a compiled `reasoning_artifact` node can eventually
  be traversed alongside device objects and reference facts.
- **Deferred, noted for a future phase**: wiring `ReasoningArtifactCompiler`
  output into `TroubleshootingEngine`/`Reasoner` so a compiled
  `FailureSignature` is checked before an LLM call is made — the natural
  next step, not built here to avoid risking regressions in a tested,
  live engine within the same change that introduces the artifacts it
  would consume.
