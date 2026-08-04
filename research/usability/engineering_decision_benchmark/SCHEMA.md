---
name: engineering_decision_benchmark_schema
description: "Engineering Decision Benchmark Schema v1.0 - frozen during Phase 1"
metadata:
  type: project
  version: "1.0"
  status: frozen
  locked_date: "2026-08-04"
---

# Engineering Decision Benchmark Schema

**Version:** 1.0
**Date:** 2026-08-04
**Status:** FROZEN during Phase 1
**Locked by:** CTO decision

---

## CRITICAL NOTE

Do not edit this schema during incident population.
See PRINCIPLES.md for Schema Freeze Rule.

If an incident exposes a missing field, record it in CHANGELOG.md as "Candidate v1.1" and continue.
Complete all 20 incidents before reconsidering schema changes.

---

## The 12 Dimensions

### 1. Decision Intent
What is the engineer trying to accomplish?

**Options:** 
- Explain (Why did this happen?)
- Predict (What will happen if...?)
- Decide (Which option should I choose?)
- Validate (Is this safe?)
- Recover (What's the fastest safe recovery?)
- Optimize (Can this be improved?)
- Learn (Why did this work/fail?)

### 2. Evidence Quality
How trustworthy and complete is the evidence available?

- **E1:** Clear, direct evidence
- **E2:** Incomplete evidence (gaps need filling)
- **E3:** Conflicting evidence (sources disagree)
- **E4:** Misleading evidence (misdirects investigation)

### 3. Decision Consequence
What is the cost of being wrong?

- **Low:** 5 minutes wasted, easy rollback, no impact
- **Medium:** Service degraded, customer impact, moderate downtime
- **High:** Global outage, data loss, millions in impact

### 4. Time Pressure
How much time is available to investigate and decide?

- **No pressure:** Routine maintenance, hours or days available
- **Moderate:** Standard change window, 30-60 minutes available
- **Severe:** Production degradation, 15-30 minutes to fix
- **Critical:** Sev-1 outage, seconds matter

### 5. Investigation Pattern
What reasoning pattern is involved?

**Options:**
- Parameter mismatch (values on two sides don't align)
- State machine stall (protocol stuck in non-terminal state)
- Asymmetric state (two sides disagree on state)
- Multi-factor interaction (multiple conditions combined)
- Hidden assumption (unstated precondition violated)
- Resource exhaustion (capacity or performance limit)
- Timing dependency (order or delay matters)

### 6. Cognitive Trap
What thinking error is most likely to occur?

**Options:**
- Anchoring (fixated on first hypothesis)
- Confirmation bias (seeking only confirming evidence)
- Availability bias (recent incidents bias judgment)
- Escalation bias ("I've spent an hour, must be complex")
- Authority bias ("TAC said X, so we stop thinking")
- Tunnel vision (missed obvious alternatives)
- Overconfidence (confident in wrong answer)
- Incomplete comparison (didn't compare both sides)

### 7. Stable Context
Properties of the engineer and environment that don't change during investigation.

- **Role:** Individual contributor | Team lead | Principal engineer
- **Experience:** Junior | Mid-level | Senior | Principal
- **Domain familiarity:** Strong (expert) | Moderate | Weak | New to domain
- **Environment:** Data center | Campus network | Branch | Cloud | Hybrid | Other

### 8. Dynamic Context
Properties that evolve as investigation progresses.

Record how these changed:

- **Current belief:** What did they think was wrong? (changes with new evidence)
- **Goal:** Restore service | Find root cause | Prepare CAB | Design solution | Prepare rollback
- **Stress level:** Low | Moderate | Severe | Critical
- **Risk tolerance:** "Quick and dirty" vs "absolutely certain"
- **Confidence:** Timeline of confidence changes (e.g., 30% → 60% → 92% → 99%)

### 9. Belief Evolution
Timeline of how the engineer moved through hypotheses.

**Format:**
```
HH:MM  Hypothesis (Confidence %)
       Reason: Why this belief
       Trigger: What caused the shift

HH:MM  Next hypothesis (Confidence %)
       Reason: Why this belief
       Trigger: What caused the shift
```

**Measures:** How quickly does the engineer converge toward reality?
**Example:**
```
00:00  Parameter mismatch (70%)
       Reason: Two sides have different configurations
       Trigger: Initial observation from syslog alert

03:00  Configuration error (55%)
       Reason: One side might not be running updated version
       Trigger: Checked version numbers

08:00  Cascading state (92%)
       Reason: One side failed to notify the other
       Trigger: Looked at state on both sides simultaneously

11:00  Cascading state (99%)
       Reason: Applied synchronization fix, problem resolved
       Trigger: Verification successful
```

### 10. Evidence Acquisition Cost
What information was collected and how much did it cost to get?

For each piece of evidence collected, record:

- **Information source type:** State information | Configuration | Topology | Telemetry | Historical data | Log analysis | Packet capture | Other
- **Time to collect:** Seconds / minutes / hours
- **Approval required:** None | Change window approval | Maintenance window | Business hours restriction
- **Useful?:** Yes / No / Partially
- **What it revealed:** One-sentence description of what this evidence showed

**Example:**
```
| Information | Type | Time | Approval | Useful? | Revealed |
| Neighbor state | State info | 5s | None | Yes | Neighbor stuck in EXSTART |
| Interface config | Configuration | 10s | None | Yes | Both sides in same area |
| Change history | Historical | 2 min | None | No | No recent changes |
| Packet capture | Packet capture | 25 min | Maintenance | No | Not collected (too late) |
```

### 11. Investigation Efficiency
Measure: Did we over-investigate?

After the incident is complete, record:

- **Total information sources accessed:** [number]
- **Information sources actually required to reach confidence:** [number]
- **Unnecessary investigation:** [% = (total - required) / total]
- **Critical path:** List the minimal sufficient set of evidence
- **Dead ends explored:** List information sources that didn't help

**Example:**
```
Total sources accessed: 12
Sources required for decision: 3
Unnecessary investigation: 75%

Critical path:
  1. Neighbor state (detected stuck state)
  2. Configuration comparison (found mismatch)
  3. Apply fix verification (confirmed working)

Dead ends:
  - MTU investigation (3 sources, 12 min wasted)
  - Authentication review (2 sources, 8 min wasted)
  - Interface detail analysis (3 sources, 5 min wasted)
```

**Measures:** How much investigation could have been skipped?

### 12. Safety Checkpoint
When did the product first recommend an irreversible action?

For each recommendation made during the incident:

- **Timestamp:** HH:MM
- **Recommendation:** What was suggested?
- **Evidence available:** What supported it at that moment?
- **Reversibility:** Can this be undone? How easily?
- **Outcome:** Was it correct? Safe?

**Example:**
```
Minute 2
Recommendation: Collect these four show commands
Evidence: Initial observation of stuck state
Reversibility: N/A (data collection only)
Outcome: ✅ Safe, prepared ground for next step

Minute 8
Recommendation: Apply configuration alignment fix
Evidence: Clear mismatch in configuration comparison
Reversibility: Yes, one command rollback
Outcome: ✅ Safe, correct, problem resolved
```

---

## How to Fill This Schema

### For each incident, you will record:

1. What was the engineer trying to accomplish? (Intent)
2. How good was the available evidence? (E1-E4)
3. What was at stake if they got it wrong? (Consequence)
4. How much time did they have? (Pressure)
5. What reasoning pattern applied? (Pattern)
6. What cognitive trap was likely? (Trap)
7. Who was making the decision? (Stable context)
8. How did their state change? (Dynamic context)
9. How did their beliefs evolve? (Belief evolution timeline)
10. What did it cost to gather information? (Acquisition cost)
11. Did they waste time investigating? (Efficiency)
12. When was it first safe to act? (Safety checkpoint)

---

## What You CAN Change Between Phases

- Add new evidence types (when new domains emerge)
- Refine option lists (when patterns become clearer)
- Improve field definitions (for clarity, not substance)

## What You CANNOT Change During Phase 1

- Add/remove dimensions
- Rename dimensions
- Change the fundamental structure

---

## Example: Full Incident Entry

```markdown
## Incident 001: Stuck BGP Session

### 1. Decision Intent
Explain

### 2. Evidence Quality
E2 (Incomplete - logs were sparse)

### 3. Decision Consequence
Medium (Session down, routes not propagating)

### 4. Time Pressure
Moderate (30-minute change window)

### 5. Investigation Pattern
Asymmetric state

### 6. Cognitive Trap
Anchoring

### 7. Stable Context
- Role: Senior engineer
- Experience: Senior
- Domain familiarity: Strong
- Environment: Data center

### 8. Dynamic Context
- Current belief evolution
- Goal: Restore connectivity
- Stress: Moderate
- Risk tolerance: Absolutely certain before changing
- Confidence: 40% → 65% → 88% → 96%

### 9. Belief Evolution
00:00  Configuration error (40%)
       Reason: BGP down is often config
       Trigger: Alert arrived

03:00  Timer mismatch (65%)
       Reason: Hold timer behavior suggests timeout
       Trigger: Checked keepalive intervals

08:00  Asymmetric state (88%)
       Reason: One side upgraded, other didn't
       Trigger: Checked version on both sides

12:00  Asymmetric state (96%)
       Reason: Applied version sync, session came up
       Trigger: Session now established

### 10. Evidence Acquisition Cost
| Information | Type | Time | Approval | Useful? | Revealed |
| BGP state | State | 5s | None | Yes | Session down |
| Configuration | Config | 8s | None | Partial | Timers matched |
| Version check | State | 10s | None | Yes | Version mismatch found |
| Syslog | Logs | 2min | None | Yes | Version incompatibility message |

### 11. Investigation Efficiency
Total sources: 8
Required: 3
Waste: 62%

Critical path:
  1. BGP state check
  2. Version comparison
  3. Verification post-fix

Dead ends:
  - Configuration timer review (not the issue)
  - Access list investigation (not the issue)

### 12. Safety Checkpoint
Minute 3: "Check versions" (safe, informational)
Minute 8: "Upgrade remote BGP version" (safe, reversible)
Outcome: ✅ Correct and successful
```

---

## Final Notes

This schema is intentionally general. It applies to:
- Network incidents
- Cloud incidents
- Kubernetes incidents
- Storage incidents
- Any engineering decision under uncertainty

The protocol is incidental. The human thinking is the benchmark.
