# The Fact, Evidence, Conflict, Confidence & Protocol-State Model

> Status: specification of what's implemented (NKC Phase 3), not an
> aspirational design. Companion documents:
> [`nkc_canonical_network_language.md`](nkc_canonical_network_language.md)
> (Phase 1-2's device-scoped `NormalizedObject`/`KnowledgeGraph` model),
> [`nkc_architecture_blueprint.md`](nkc_architecture_blueprint.md).

## Why this is a separate model from the CNL

The CNL (`NormalizedObject`) is **device-scoped**: an id like
`R1:interface:GigabitEthernet0/1` only means something in the context of
one device's compiled config/CLI. Phase 3 works one layer up, on
**reference knowledge** — what RFCs, vendor docs, release notes, and KB
articles *assert in general*, independent of any one device. A `Fact` has
no device; it has a `subject` ("ospf hello interval"), not a device+
interface pair. This is a deliberate, load-bearing distinction: conflating
the two would mean either device facts losing their device scope, or
reference facts gaining a meaningless one.

## The Fact model (`core/knowledge/compiler/facts.py`)

```python
Fact(subject, predicate, object, context, source_doc_id, vendor,
    source_type, confidence, timestamp, compiler_version, citation)
```

Extraction is scoped to ONE deterministic pattern: **default-value
assertions** — "the default value of X is Y," "X defaults to Y," "by
default, X is Y," "default X is Y." This is a genuine engineering choice,
not a shortcut: vendor docs and RFCs phrase default-value statements
consistently enough that regex extraction is reliable; general semantic
fact extraction from arbitrary prose is not deterministic no matter how
much regex is thrown at it, and asserting otherwise would make "trusted
enterprise knowledge" untrustworthy. `predicate` is always
`"default_value"` today — the shape supports other predicates (the field
exists), but none are extracted yet without an equally well-defined
pattern behind them.

## The Evidence model

There's no separate "Evidence" class — a `Fact`'s evidence IS its
`citation`/`source_doc_id`/`source_type`/`vendor`/`confidence` fields,
which trace directly back to the `EnterpriseHit` that
`EnterpriseKnowledgeLayer.search()` (built in an earlier session) already
returns, which in turn traces back to the ingested document's `Citation`
(`core/knowledge/base.py`). Evidence is never discarded: every `Fact`
that ever gets extracted is retained in `ConflictRecord.items` even when
it conflicts with others (see below) — nothing is silently dropped or
overwritten in favor of a "winner."

## The Conflict model (`core/knowledge/compiler/fact_conflicts.py`)

**One shape, two producers:**

```python
ConflictRecord(subject, predicate, items, kind, resolved, preferred_index)
```

- `kind="fact"`, from `detect_fact_conflicts()`: two documents disagree on
  a `(subject, predicate)`'s value. `items` is the full list of competing
  `Fact`s (never trimmed); `preferred_index` names the highest-confidence
  one, but resolution is a SUGGESTION, not an overwrite — `resolved`
  stays `False` unless a caller explicitly marks it.
- `kind="cross_device_object"`, from `detect_cross_device_conflicts()`:
  two DIFFERENT devices' already-compiled objects (Phase 1/2, living in
  the shared `KnowledgeGraph`) for the same named entity (VRF/VLAN/QoS
  policy — see below for why ACLs are excluded) disagree on an attribute.
  `items` is a list of `{device, node_id, attributes}` dicts.

**Why ACLs are excluded from cross-device comparison**: an ACL is
compiled as one object PER RULE (Phase 1's `acl_extractor`), so grouping
by `acl_name` alone would flag every distinct permit/deny line — even
within one device's own multi-line ACL — as a false "conflict." VRF/VLAN/
QoS-policy names genuinely identify one entity enterprise-wide, so
cross-device comparison is meaningful for those specifically.

## The Confidence model

`fact_confidence(fact, group)` blends four factors, same blend STYLE as
`EnterpriseKnowledgeLayer.confidence()` (0.60·semantic + 0.25·authority +
0.15·recency) but reweighted for facts, which have no semantic-similarity
score of their own:

```
0.35 · authority (SOURCE_RANK[source_type], reused as-is — config_standard
                  and RFC outrank incident/runbook, exactly as they already
                  do for document chunks)
+ 0.25 · cross-source agreement (fraction of the group asserting the SAME value)
+ 0.20 · recency (same decay shape as _recency_factor: 1.0 fresh -> ~0.5 over a year)
+ 0.20 · evidence count (more independent sources -> higher, saturating at 5)
```

## The Protocol / State-Machine model (`core/knowledge/compiler/protocol_models.py`)

`ProtocolStateModel(protocol, states, transitions)` is a generic,
registry-based state machine (`PROTOCOL_STATE_MODELS: Dict[str,
ProtocolStateModel]`). Seeded with exactly two, verified models:

- **OSPF neighbor** (RFC 2328): Down → Attempt/Init → 2-Way → ExStart →
  Exchange → Loading → Full, plus the regression edges back to Down.
- **STP port** (802.1D): Disabled → Blocking → Listening → Learning →
  Forwarding, plus the "superior BPDU" regressions back to Blocking.

**Deliberately NOT seeded**: BGP, EIGRP, ISIS, MPLS, VXLAN, EVPN, VRRP,
HSRP, LACP. Several of these have real vendor- or RFC-revision-specific
nuance (HSRP and VRRP have different state names AND different default
timers; LACP spans multiple 802.3ad/802.1AX revisions) that would need
verification against an authoritative spec per protocol to assert
correctly — a wrong transition table would be worse than none, undermining
the "trusted" part of "trusted enterprise knowledge." `build_protocol_model()`
returns `None` for anything not in the registry rather than guessing.
Adding a verified model for another protocol is a new
`PROTOCOL_STATE_MODELS` entry — the registry mechanism doesn't change.

## Cross-document compiler pipeline (`cross_document_compiler.py`)

```
subject query
    │
    ▼  EnterpriseKnowledgeLayer.search()      [REUSED, Phase 0]
    │  (hybrid RRF over the ingested corpus)
    ▼  extract_facts_from_text() per hit       [facts.py]
    │
    ▼  validate_facts() / resolve_conflicts()  [fact_conflicts.py]
    │  / merge_evidence()
    ▼  optimize_knowledge() (dedup)
    │
    ▼  publish_facts() -> fact_to_object()     [REUSES graph_ops.merge_into_graph, Phase 2]
    │                                           into the SAME KnowledgeGraph
    ▼  compare_versions()                      (in-memory history per compiler instance)
```

`detect_cross_device_conflicts()` runs directly against the shared
`KnowledgeGraph`, independent of the fact pipeline above — it doesn't need
any document search, only what Phase 1/2 already compiled.

## Deliberately deferred (same discipline as every prior phase)

- **Distributed execution / millions-of-facts infrastructure** — gated on
  real scale need that doesn't exist yet.
- **More protocol state models** — gated on being able to verify each one
  against an authoritative source; not built to "cover more ground."
- **Deeper NLU-based fact extraction** (beyond default-value assertions)
  — would require accepting non-deterministic extraction, which this phase
  deliberately avoids in favor of narrower-but-trustworthy coverage.
- **A durable fact-history store** — the in-memory, per-compiler-instance
  history is enough for `compare_versions()` at this phase's scope; real
  document versioning already exists one layer down
  (`EnterpriseKnowledgeLayer`'s content-hash versioning).
- **Fact ↔ device-object cross-linking** via `RelationType.VALIDATED_BY`/
  `RESOLVED_BY` (defined in Phase 2, unused until now) — a natural future
  integration (e.g. flagging a device's compiled timer object against a
  reference default-value Fact), noted here as the obvious next step, not
  built speculatively ahead of a concrete need.
