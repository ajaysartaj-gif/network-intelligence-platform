# The Cognitive Memory System Blueprint
### Canonical architecture for the long-term memory of an Autonomous Network Intelligence Platform

> Status: foundational design document. Third in the trilogy with the Reasoning Blueprint (*how the platform thinks*) and the Knowledge Blueprint (*what it thinks with*). This defines *how the platform remembers having thought and acted* — and how that memory becomes expertise over a 15-year operational lifetime.

---

## Part 0 — First principles

**Axiom 1 — Memory is not what you store; it is what survives.**
This is the founding inversion. A flat log that retains every event with equal weight is not memory — it is a tape recorder, and it drowns. Human expertise is built by the *opposite* of total recall: by forgetting the irrelevant, strengthening the consequential, and consolidating the repeated into instinct. The architecture of memory is therefore primarily the architecture of **selective retention** — forgetting, decay, reinforcement, and consolidation. The memory *types* are the easy part; the *lifecycles that act on them* are the design.

**Axiom 2 — A mind has multiple memory SYSTEMS, not one store.**
Cognitive science distinguishes episodic memory (specific events: "the OSPF outage at Site-2 last March"), semantic memory (generalized facts: "MTU mismatch causes ExStart hangs"), procedural memory (how to act: the reflex of checking MTU first), and working memory (the active context of the current task). These are *different systems* with different persistence, retrieval, and decay. An autonomous platform needs all four, plus forms a human lacks. Collapsing them into one table is the equivalent of a person with only a diary and no instincts.

**Axiom 3 — Every memory is weighted by OUTCOME and AGE.**
A 30-year engineer does not weight all memories equally. A fix that worked ten times is near-certain; one that worked once is a hypothesis. A lesson from last week is sharp; one from 2011 may be obsolete (the hardware is gone). Therefore every memory carries **confidence** (how reliable, updated by outcomes) and is subject to **aging** (relevance decays unless reinforced). Memory without these two dimensions cannot distinguish wisdom from a rumor it heard once.

**Axiom 4 — Memory consolidates: episodes become patterns become instinct.**
The defining process of expertise. A single incident is an *episode*. The same incident signature recurring becomes a recognized *pattern* (semantic memory). A pattern with a reliably successful response becomes *procedural* — the platform stops "reasoning it out" and simply *acts*, the way a senior engineer diagnoses MTU in seconds. This upward consolidation (episodic → semantic → procedural) is how memory turns experience into speed and certainty. It is the memory-side twin of the Knowledge Blueprint's value gradient and the Reasoning Blueprint's Learning Reasoner — **one mechanism, three views.**

**Axiom 5 — Forgetting is a feature, and it is deliberate.**
The hardest and most-neglected design problem. The platform must forget — but *correctly*. It must never forget a verified critical lesson, may compress a thousand routine successes into one statistic, should expire knowledge tied to decommissioned hardware, and must purge superseded facts while retaining their *history*. Forgetting is not deletion-by-neglect; it is a *governed policy* per memory type. A platform that cannot forget becomes slower and less wise every year — the opposite of an expert.

**Axiom 6 — Memory is relational; experiences connect.**
An expert's memories are a web, not a list. "This outage reminds me of that one." "This engineer always handles BGP." "This site has a history." Memories link to each other, to devices, to causes, to outcomes. Retrieval follows these links (spreading activation), not just keyword match. The memory substrate is therefore a **graph of episodes**, not a flat table — even though individual episodes are records.

**Axiom 7 — Extensibility: new memory KINDS without redesign.**
In 15 years there will be memory types we cannot name (AI-model-behavior memory, quantum-path memory, intent-drift memory). Each new kind must register with its own retention, decay, and consolidation policy — without touching existing memory. The deliverable is a **Memory Registry of typed memory systems**, the same plug-in pattern as the Capability, Reasoning, and Knowledge registries.

---

## Part 1 — The memory taxonomy

Organized by the **cognitive system** each belongs to (Axiom 2), because that — not the topic — determines its lifecycle. The domain memory types you listed are *episodic* by nature; the deeper architecture is the four systems they live within and consolidate through.

### 1A — The four cognitive memory systems (the deep axis)

| System | Holds | Persistence | Retrieval | Decay |
|---|---|---|---|---|
| **Episodic** | Specific events, timestamped | Long, then consolidated/compressed | Similarity, temporal, relational | Ages unless reinforced |
| **Semantic** | Generalized patterns & facts | Very long; strengthens with recurrence | Pattern/signature match | Slow; updated by new evidence |
| **Procedural** | Validated action policies (reflexes) | Longest; the platform's instincts | Triggered by situation match | Only on repeated failure |
| **Working** | Active task context | Seconds–hours; ephemeral by design | Direct (it's the current focus) | Cleared on task completion |

> Architectural consequence: the platform needs **four memory subsystems with different storage and lifecycle**, and a consolidation pipeline that moves content *upward* (episodic → semantic → procedural). Your current Operational Memory is a strong **episodic** system. The semantic, procedural, and working systems — and the consolidation between them — are the unbuilt depth.

### 1B — The episodic memory domains (what is remembered)

These are the types you enumerated, plus discovered ones, each a category of episode. All share the episodic lifecycle but differ in retention priority and decay rate.

#### Operational episodes *(the core operational record)*
- **Incident Memory** — what broke, when, symptoms, severity. *High retention; critical incidents never forgotten.*
- **Deployment Memory** — every change, its intent, config, outcome. *The platform's action history.*
- **Failure Memory** — failure events and their signatures. *Includes the precious negative memory: "this failed."*
- **Verification Memory** — what was checked, the proof, pass/fail. *The evidence layer; ages faster (point-in-time).*
- **Remediation Memory** — fixes attempted and their results. *Highest consolidation value — becomes procedural.*
- **Rollback Memory** — what was undone and why.
- **Decision Memory** — choices made, alternatives rejected, rationale. *The most-neglected, highest-value: decision-rationale as memory.*

#### Entity-anchored episodes *(memory indexed by the thing it's about)*
- **Topology Memory** — how the network looked over time. *Versioned snapshots — "what was connected when."*
- **Configuration Memory** — config state and its history per device. *Enables "what changed since it last worked."*
- **Device/Vendor Memory** — per-device and per-vendor behavior, quirks, bug history. *"This platform does X under load."*
- **Site Memory** — a site's operational history, recurring issues, character. *Sites have personalities; experts know them.*
- **Protocol Memory** — accumulated experience per protocol (OSPF/BGP/...). *Where protocol instinct lives.*
- **Operator Memory** — what each engineer did, their patterns, strengths, decisions. *Institutional memory of people.*

#### Contextual episodes *(memory of the surrounding world)*
- **Business Memory** — service criticality history, SLA events, business impact of past incidents.
- **Application Memory** — application behavior, dependencies, sensitivity to network change.
- **Security Memory** — past threats, incidents, exploited paths, posture changes. *Adversarial; long retention.*
- **Optimization Memory** — what tuning helped, what trade-offs were made.
- **Temporal Memory** — *when* things happen ("Site-2 degrades at month-end"). Cross-cuts all others; a first-class temporal index.

#### Meta-episodes *(memory about the platform's own experience)*
- **Learning Memory** — what the platform learned, when, and from which outcome. *The audit trail of its own growth.*
- **Historical Memory** — the long-arc institutional record; the consolidated "career" of the platform.

---

## Part 2 — Memory types the field tends to forget

Honoring "do not stop there":

- **Negative Memory** — failures, dead-ends, "we tried this and it didn't work." Organizations relearn mistakes because negative memory is never deliberately kept. First-class here.
- **Counterfactual Memory** — "what we almost did" and "what would have happened." Pairs with the Reasoning Blueprint's counterfactual reasoner; remembers roads not taken.
- **Confidence/Provenance Memory** — memory *about* memories: how reliable has this remembered fix actually proven? Meta-memory that weights all retrieval.
- **Surprise Memory** — events that violated expectation. Humans remember the anomalous vividly because it carries the most learning signal; the platform should preferentially retain what surprised it (high prediction-error episodes).
- **Sensory/Signal Memory** — raw telemetry baselines as memory ("what normal felt like here"). Ephemeral-but-foundational; mostly consolidated into semantic baselines, raw form decays fast.
- **Relational/Associative Memory** — the *links themselves* as memory ("these two incidents are related"), distinct from the episodes they connect.
- **Emotional-Analog / Salience Memory** — a salience weight on memories (criticality, cost, blast radius) that governs retention priority — the platform's analog of why humans never forget the outage that took down the business.

---

## Part 3 — The memory lifecycle (the real design)

This is the heart. Memory types are nouns; the lifecycle is the verbs that turn events into expertise.

### 3.1 The lifecycle stages
```
   ENCODE ──▶ STORE ──▶ REINFORCE ──▶ CONSOLIDATE ──▶ AGE ──▶ FORGET / ARCHIVE
      │          │           │              │            │            │
   capture    episodic    outcome-      episodic→     relevance   governed
   with       record +    weighted      semantic→     decay       compression
   salience   provenance  strengthen    procedural    over time   or expiry
```

### 3.2 Encoding — what enters memory, and how strongly
Not all events deserve equal encoding. Encoding strength is set at capture by **salience**: criticality, surprise (prediction error), business impact, and novelty. A routine successful ping is encoded weakly (and will compress); a business-critical outage is encoded strongly (and will persist). This is the platform's analog of why you remember the disaster, not the Tuesday.

### 3.3 Reinforcement — outcome-weighted strengthening
Every time a memory proves useful or is corroborated (a remembered fix works again), its confidence and retention strength increase. Every time it proves wrong, its confidence drops. This is the mechanism by which a fix that worked ten times becomes near-certain and a one-off stays a hypothesis. (Your `by_signature` recurrence detection is the seed; reinforcement makes it a confidence model.)

### 3.4 Consolidation — the expertise engine (Axiom 4)
The pipeline that creates wisdom:
- **Episodic → Semantic:** when N episodes share a signature, the platform forms a *pattern* ("MTU mismatch → ExStart" learned from many incidents). The individual episodes can then be *compressed* — their lesson retained, their bulk discarded.
- **Semantic → Procedural:** when a pattern has a reliably successful response, it becomes an *action policy* — the platform stops deliberating and acts (gated by safety/confidence). This is instinct.
- **Periodic consolidation runs** (the platform's "sleep") sweep episodic memory, detect emergent patterns, promote, compress, and re-index.

### 3.5 Aging — relevance decay
Memory relevance decays over time *unless reinforced* — modeled on the forgetting curve. But decay rate is **per-type**: a critical security lesson decays slowly; a telemetry baseline decays fast (last month's "normal" may be stale); a config fact tied to live hardware decays only when the hardware changes. Aging reduces *retrieval priority*, not necessarily existence — an aged memory still surfaces if strongly matched, just ranked lower.

### 3.6 Forgetting — the governed policy (Axiom 5)
Forgetting is deliberate and per-type, with hard rules:
- **Never forget:** verified critical lessons, major incidents, security events, decision rationale.
- **Compress, don't delete:** thousands of routine successes → one reinforced statistic + exemplars.
- **Expire:** knowledge tied to decommissioned entities (device gone → its quirk memory archived, not live).
- **Supersede with history:** when a fact changes, the old version is archived (queryable as history), not destroyed — enabling "what was true when?" (Your enterprise layer's supersede-not-delete pattern, applied to memory.)
- **Purge only:** genuinely transient working memory, and legally-required deletions.

Forgetting is a *registered policy* each memory type declares — never an accident of storage limits.

### 3.7 Memory confidence
Every memory carries a calibrated confidence that is *born* from encoding salience, *updated* by reinforcement, *decayed* by aging, and *checked* against outcomes. Confidence is what lets retrieval rank "near-certain wisdom" above "heard it once," and what the Reasoning layer consumes to know how much to trust a recalled experience.

---

## Part 4 — The architecture: a Memory Registry of typed memory systems

### 4.1 The layered architecture
```
┌──────────────────────────────────────────────────────────────┐
│  L5  MEMORY GOVERNANCE                                        │
│      forgetting policy · confidence calibration · aging ·     │
│      consolidation scheduler · provenance · salience          │
├──────────────────────────────────────────────────────────────┤
│  L4  UNIFIED RECALL INTERFACE                                 │
│      cross-system retrieval · spreading activation ·          │
│      relevance ranking (match × confidence × recency × salience)│
├──────────────────────────────────────────────────────────────┤
│  L3  MEMORY REGISTRY                                          │
│      typed memory-system plug-ins; each declares its          │
│      lifecycle, decay, consolidation, retrieval contract      │
├──────────────────────────────────────────────────────────────┤
│  L2  THE FOUR MEMORY SYSTEMS                                  │
│      Episodic · Semantic · Procedural · Working               │
│      + the consolidation pipeline between them                │
├──────────────────────────────────────────────────────────────┤
│  L1  ENCODING & INDEXING                                      │
│      salience-weighted capture · multi-index (similarity,     │
│      temporal, entity, signature, relational graph)           │
├──────────────────────────────────────────────────────────────┤
│  L0  SUBSTRATE                                                │
│      durable store (your Supabase memory) · vector index ·    │
│      episode graph · time-series                              │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 The MemorySystem contract (what every plug-in declares)
The 15-year extensibility guarantee:
```
MemorySystemSpec:
  key                 unique id (e.g. "episodic_incident", "procedural_remediation")
  system              episodic | semantic | procedural | working
  domain              what it remembers
  encode(event)       salience-weighted capture → typed memory object
  index_by            [similarity | temporal | entity | signature | relational]
  reinforce(outcome)  how corroboration/contradiction updates confidence
  decay_model         per-type aging function
  consolidate_policy  when/how it promotes upward or compresses
  forget_policy       never-forget | compress | expire | supersede | purge
  confidence(obj)     calibrated reliability
  recall(cue)         native retrieval in its modality
  health()/metrics()  live readiness
```

### 4.3 Memory indexing (multi-index, not one key)
A single episode is indexed many ways simultaneously, because experts recall by many cues:
- **Similarity** (semantic embedding) — "like this situation." *(You have this.)*
- **Temporal** — "around that time," "at month-end." *(You have this.)*
- **Entity** — by device/site/protocol/operator/vendor. *(You have this — four lenses.)*
- **Signature** — by normalized failure fingerprint. *(You have this.)*
- **Relational** — by links to other memories (the episode graph). *(The unbuilt index — spreading-activation recall.)*

### 4.4 The Unified Recall Interface (L4) — how an expert remembers
A cue activates memory across all systems and indices at once, then ranks by **match × confidence × recency × salience**, following relational links (spreading activation) to pull in associated memories. "OSPF stuck at Site-2" recalls: the specific past episodes (episodic), the learned MTU pattern (semantic), the reflex to check MTU first (procedural), the fact that Site-2 has a history (entity+relational), and that this tends to happen post-change (temporal). That *composite* recall — not a single lookup — is what expertise feels like. (Your six lenses are the episodic-tier prototype; this generalizes recall across all four systems.)

### 4.5 Consolidation scheduler (the platform's "sleep")
A background process — the single most important *active* component — periodically: detects emergent patterns in episodic memory, promotes episodic→semantic→procedural, compresses routine episodes, recalibrates confidence from accumulated outcomes, applies aging, and enforces forgetting policy. Without this, memory only grows; with it, memory *matures*.

### 4.6 Relationship to the trilogy
```
        KNOWLEDGE (what is true)
              ▲
              │ memory consolidates into knowledge
   MEMORY (what happened) ──recalled by──▶ REASONING (what to do)
              ▲                                    │
              └────── outcomes encoded as memory ◀─┘
```
Memory is the bridge: Reasoning acts → outcomes become Memory → Memory consolidates into Knowledge → Knowledge feeds Reasoning. The Learning Reasoner (Reasoning 7.3), the Value-Gradient Promoter (Knowledge L5), and the Consolidation Scheduler (Memory L5) are **three faces of one mechanism** — the platform getting wiser. Built once, registered in all three.

### 4.7 Mapping to what already exists (canonical for THIS platform)
| Blueprint element | Current state |
|---|---|
| Episodic memory system | **Built** — Operational Memory (events, signatures, Supabase) |
| Multi-index: similarity, temporal, entity, signature | **Built** — six retrieval lenses |
| Recurrence → pattern (seed of consolidation) | **Partial** — `recurring_failures`, `by_signature` |
| Supersede-with-history (forgetting primitive) | **Partial** — pattern exists in the knowledge layer |
| Semantic memory system (learned patterns as objects) | **Not started** |
| Procedural memory (action reflexes) | **Not started** |
| Working memory (task context) | **Not started** |
| Consolidation scheduler ("sleep") | **Not started** — the highest-leverage unbuilt piece |
| Confidence (reinforcement + decay + salience) | **Partial** — outcomes recorded, not yet a confidence model |
| Forgetting policies (per-type, governed) | **Not started** |
| Relational/associative index (episode graph) | **Not started** |
| Memory Registry + MemorySystem contract | **Not started** — the enabling architecture |

### 4.8 Maturity-ordered build sequence
1. **Formalize the Memory Registry + MemorySystem contract** (makes all memory pluggable; aligns with the other two registries).
2. **Promote existing Operational Memory to the episodic plug-in** under the registry.
3. **Add the confidence model** — reinforcement (corroboration↑, contradiction↓) + salience at encoding.
4. **Build the consolidation scheduler** — recurrence→semantic patterns; the first real "maturing."
5. **Add semantic memory** as a first-class system (patterns as durable objects, not just queries).
6. **Add the relational index** (episode graph) → spreading-activation recall.
7. **Add forgetting policies** per type — compression, expiry, supersession.
8. **Add procedural memory** — validated reflexes (gated by safety/confidence) — and working memory for task context.
9. **Salience/surprise & negative/counterfactual memory** — the highest-value "forgotten" types.

---

## Part 5 — The single most important architectural commitment

> **Memory is what survives, not what is stored. Every memory is weighted by outcome and decayed by time; experience consolidates upward from episode to pattern to instinct; forgetting is a deliberate, governed policy — never an accident; and recall is a composite activation across episodic, semantic, and procedural systems, ranked by confidence and salience. The consolidation that turns experience into expertise — the platform's "sleep" — is the single component that makes memory a mind rather than a log.**

A database remembers everything and learns nothing. A 30-year engineer remembers selectively, weights by how it turned out, and has compressed a career of incidents into instinct. The difference is not capacity — it is *consolidation and forgetting*. That is the entire design, and it is what no event log, however large, can do on its own.
