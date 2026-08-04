---
name: engineering_decision_benchmark_changelog
description: "Evolution history of The Standard schema and principles"
metadata:
  type: project
  version: "1.0"
---

# Engineering Decision Benchmark — Evolution History

## v1.0 (2026-08-04)

**Initial schema with 12 dimensions.**

### Dimensions Locked

1. Decision Intent (7 types: Explain, Predict, Decide, Validate, Recover, Optimize, Learn)
2. Evidence Quality (E1-E4: Clear, Incomplete, Conflicting, Misleading)
3. Decision Consequence (Low/Medium/High)
4. Time Pressure (No/Moderate/Severe/Critical)
5. Investigation Pattern (7 types: Parameter mismatch, State machine stall, etc.)
6. Cognitive Trap (8 types: Anchoring, Confirmation bias, etc.)
7. Stable Context (Role, Experience, Domain familiarity, Environment)
8. Dynamic Context (Current belief, Goal, Stress, Risk tolerance, Confidence)
9. Belief Evolution (Timeline of hypothesis changes)
10. Evidence Acquisition Cost (Time, approval, usefulness of each source)
11. Investigation Efficiency (Waste measurement)
12. Safety Checkpoint (When first irreversible recommendation)

### Principles Locked

- Nine core principles (see PRINCIPLES.md)
- The Filter Question (for evaluating schema changes)
- Schema Freeze Rule (no edits during Phase 1)
- The Lucky Guess Rule (never reward guessing over reasoning)

### Key Design Decisions

- **Protocol-agnostic schema:** No mention of OSPF, BGP, Kubernetes, AWS. The incident contains it; the schema doesn't.
- **Human-centric measurement:** Focus on engineer thinking, not AI accuracy.
- **Investigation Efficiency dimension:** Measures waste, not just correctness.
- **Dynamic Context:** Captures how the engineer's state changed during investigation.
- **Belief Evolution timeline:** Shows the path to understanding, not just the destination.

### Rationale

This benchmark measures repeatable engineering thinking under uncertainty.

Success is not "model found root cause."
Success is "engineer abandoned wrong belief faster."

The schema is designed to:
- Survive 5+ years of technology change
- Scale from networking to Kubernetes to cloud to AI clusters
- Measure human cognition, not incident classification
- Compare versions consistently
- Guide product development toward reducing uncertainty

### Status

Ready for Phase 1 population (20 incidents).
Frozen until Phase 1 complete.

---

## Candidate Changes for v1.1

[To be filled after Phase 1 completion]

This section records any gaps or improvements discovered during incident population.

### Examples (placeholder):

- `Candidate: Add "Peer Communication" as investigation pattern`
  - Reason: Some incidents involve two engineers discovering each other doesn't understand the same problem
  - Status: Pending Phase 1 completion

- `Candidate: Split "Risk Tolerance" into "Personal Risk Tolerance" and "Organizational Risk Tolerance"`
  - Reason: Discovered these can conflict
  - Status: Pending Phase 1 completion

---

## Future Versions

[To be filled as schema evolves between phases]

Example evolution (not actual):

### v1.1
Added: Peer Communication Pattern
Reason: Realized many incidents involve discovering teammates have incomplete or conflicting understanding.

### v1.2
Refined: Belief Evolution format
Reason: V1.0 was too verbose. Simplified to enable faster data collection.

### v1.3
Added: Prediction Accuracy
Reason: Product sometimes said "expect FULL in 8s" but it happened in 15s. Need to measure prediction fidelity separately from diagnosis.

---

## Immutable Records

This changelog is immutable. We add to it. We never revise it.

Version history becomes product history.
