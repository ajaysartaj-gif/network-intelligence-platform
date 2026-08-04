# Engineering Decision Benchmark

## What This Is

A permanent measurement system for Network Copilot.

Answers: **How much faster do engineers reach confident, safe action?**

Not: "How accurate is the AI?"
But: "How much does this product reduce uncertainty?"

## Why This Matters

- Guides product development for years
- Measures what customers actually care about
- Compares versions consistently
- Records why decisions were made
- Scales across protocols, vendors, and domains

## How to Use It

### For Product Development
1. Run the 20 standard incidents on each release
2. Compare INSIGHTS_v2 to INSIGHTS_v1
3. Track improvement on these metrics:
   - Time to understanding
   - Speed of belief convergence
   - Recommendation acceptance rate
   - Engineer confidence delta
   - Investigation efficiency (waste reduction)

### For Adding New Incidents
1. Choose an incident type not well-covered
2. Fill all 12 dimensions
3. Record Belief Evolution honestly (include wrong turns)
4. Document Safety Checkpoints
5. Add to incidents/ folder (never edit existing ones)

### For Evolving The Standard
1. If schema needs evolution, first complete all 20 incidents
2. Update SCHEMA.md with version number
3. Document reason in CHANGELOG.md
4. Don't rewrite old incidents to match new schema
5. Run old and new versions in parallel until confident

## Files in This Standard

- **PRINCIPLES.md** — Immutable values (rarely change)
- **SCHEMA.md** — Current structure (versioned, frozen during phases)
- **CHANGELOG.md** — Why the schema changed over time
- **incidents/** — Historical incidents (permanent, never edited)
- **analysis/** — Pattern extraction and cross-version comparisons
- **README.md** — This file

## The Standard Matures In Phases

**Phase 1:** 20 incidents from my own experience (highest signal)
**Phase 2:** 50-100 from team investigations (different thinking patterns)
**Phase 3:** 100-500 from customers (different environments)
**Phase 4:** 500+ from public postmortems (industry stress-testing)

Each phase keeps historical incidents. Only adds new ones.

## Core Principle

Every feature must survive this test:

> "Which incident in The Standard becomes measurably better because of this?"

If the answer is "none," the feature doesn't get built.

## Governance

The Standard is locked during a Phase.
Schema changes only happen between Phases.
Incidents are permanent and never rewritten.
Principles are immutable unless founding team agrees.
