---
name: engineering_decision_benchmark_principles
description: "Immutable principles governing The Standard. Rarely change."
metadata:
  type: project
  status: locked
  version: "1.0"
---

# Engineering Decision Benchmark — Principles

## Purpose

Measure how effectively Network Copilot helps engineers move from uncertainty to safe action.

Success is not "model found root cause."
Success is "engineer abandoned wrong belief faster."

---

## Core Principles

**1. Benchmark engineering decisions, not protocols.**
Organize by decision type, not technology.
OSPF problems, Kubernetes problems, AWS problems all follow the same thinking patterns.

**2. Benchmark human understanding, not model output.**
Measure the engineer's state, not the engine's accuracy.
Did the engineer think clearer? That's the only metric that matters.

**3. Capture belief evolution, not final answers.**
Engineers don't jump to correct beliefs.
They move through wrong beliefs toward right ones.
The speed of that movement is the product.

**4. Record uncertainty explicitly.**
Networking rarely has certainty.
Say "Best Available Explanation" not "Ground Truth."
Acknowledge what we don't know.

**5. Separate observations from interpretation.**
What we saw. What we think it means. Those are different.
Keep them distinct in the record.

**6. Never rewrite historical incidents.**
The Standard only grows. Never revises.
If we learn something was wrong, create a new entry.
History is immutable.

**7. Compare versions using the same Standard.**
Every release, run the same 20 incidents again.
Same questions. Same measurements.
Comparability across time is non-negotiable.

**8. The Standard can become harder over time, but never easier.**
Prevents teaching to the test.
Every year, replace some easy scenarios with harder ones.
Ensures ongoing relevance.

**9. Prioritize signal quality over dataset size.**
20 incidents you fully understand are worth more than 100 you don't.
Start with your own experience.
Expand only when you can maintain fidelity.

---

## The Filter Question

When proposing a new field, dimension, or change to The Standard:

> "Will this help us understand how the engineer's thinking changed?"

If yes → Consider it.
If no → It belongs in telemetry, logs, or performance metrics. Not here.

This discipline keeps The Standard focused on human cognition, not incident classification or AI model evaluation.

It ensures The Standard remains valuable long after today's protocols, vendors, and AI models have changed.

---

## Schema Freeze Rule

**SCHEMA.MD IS FROZEN DURING A BENCHMARK PHASE.**

If an incident exposes a missing field or reveals a flaw in the schema:

**DO NOT** edit the schema.

Instead:

1. Record it in `CHANGELOG.md` under "Candidate changes for v1.1"
2. Complete the incident anyway (best effort)
3. Continue with remaining incidents
4. After Phase complete, review all candidates
5. Only then decide if schema actually needs to evolve

**Why this rule exists:**

Editing schema mid-population causes:
- Inconsistency (early incidents vs late incidents)
- Rework (retrofitting old entries)
- Scope creep (every new incident adds a field)
- Loss of signal (comparing v1 to v1.2 becomes invalid)

A disciplined Standard is more valuable than a perfect one.

---

## The Lucky Guess Rule

The Standard never rewards lucky guesses.

If an engineer reaches the correct answer without sufficient evidence:

```
Guess
↓
Correct answer
↓
Wrong process
```

**Verdict:** Failed reasoning.

Why?

The Standard measures **repeatable engineering thinking**, not coincidence.

A principal engineer who guesses right 9 times out of 10 is lucky.
A principal engineer who reasons through the problem 9 times out of 10 is skilled.

Network Copilot should measure and reinforce repeatable thinking.

Only incidents with sound reasoning count as successes.

---

## What The Standard Measures

- Speed of belief convergence (how fast do wrong hypotheses get abandoned?)
- Safety of recommendations (when does the product recommend irreversible actions?)
- Adaptability to context (does it help CCIEs and junior engineers equally?)
- Evidence quality requirements (what evidence is sufficient for different decisions?)
- Cognitive friction navigation (what thinking patterns slow engineers down?)
- Investigation efficiency (what % of investigation was unnecessary?)

---

## What The Standard Does NOT Measure

- AI model accuracy (internal detail)
- Latency/performance (separate evaluation)
- UI aesthetics (separate evaluation)
- Feature completeness (separate roadmap)
- Protocol coverage (scales naturally from core capability)

Those belong in separate evaluations with separate standards.

---

## Governance

**Principles:** Immutable unless founding team explicitly agrees to change
**Schema:** Versioned. Frozen during phases. Evolves between phases.
**Incidents:** Permanent. Never edited. Only added to.

Changes to principles require board-level discussion.
Changes to schema require completion of current phase + documented reason.
Incidents are sacred—add new ones, never revise old ones.

---

## The Motto

> "A great engineering copilot is not the one that finds the right answer first. It is the one that helps an engineer abandon the wrong answer sooner."

That's what The Standard measures.
That's what we build toward.
That's what we defend.
