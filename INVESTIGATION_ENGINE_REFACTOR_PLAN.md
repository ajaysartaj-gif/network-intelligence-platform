# Investigation Engine Refactoring Plan
## Phase 1: Core Architecture Fix (2-3 weeks)

**Goal:** Transform investigation engine from generic to protocol-aware, knowledge-first system.

**Status:** Starting Phase 1.1

---

## Phase 1.1: Separate Concerns (Planner / Interpreter / Confidence Manager)

### What we're building:

```
Current (Monolithic):
┌─────────────────────────────┐
│    Generic LLM              │
│  - Plans investigation      │
│  - Interprets evidence      │
│  - Updates confidence       │
└─────────────────────────────┘
              ↓
           Coupled errors


New (Separated):
┌──────────────────┐
│ Protocol Planner │  (OSPF/BGP/IS-IS aware)
└──────────────────┘
         ↓
┌──────────────────────────┐
│ Evidence Interpreter     │  (Domain expert)
└──────────────────────────┘
         ↓
┌──────────────────────────┐
│ Bayesian Confidence Mgr  │  (Probabilistic)
└──────────────────────────┘
         ↓
      Lower error coupling
```

### Files to create:

1. **core/protocol_planner.py** (200+ lines)
   - Load protocol knowledge (OSPF, BGP, IS-IS, etc.)
   - Generate protocol-specific investigation plan
   - Rank candidate checks by priority
   - Handle protocol state machines

2. **core/evidence_interpreter.py** (250+ lines)
   - Apply protocol logic to interpret evidence
   - Determine what evidence means in protocol context
   - Identify contradictions vs confirmations
   - Output structured interpretation

3. **core/bayesian_confidence_manager.py** (200+ lines)
   - Bayesian probability updating
   - Track hypothesis likelihoods
   - Calculate confidence mathematically (not LLM opinion)
   - Explicit confidence increase/decrease rules

---

## Phase 1.2: Integrate Knowledge Upfront

### What we're building:

```
Current (Knowledge as fallback):
Investigate → Converged? → No → External Knowledge

New (Knowledge first):
Load Protocol Knowledge
    ↓
Load Enterprise History (RAG)
    ↓
Plan investigation WITH knowledge
    ↓
Investigate
    ↓
Gaps detected? → Query MCP / Web
    ↓
Update investigation with gap knowledge
```

### Files to create:

1. **core/protocol_knowledge_loader.py** (150+ lines)
   - Load protocol-specific knowledge packages
   - OSPF state machine, prerequisites, common issues
   - BGP state machine, common misconfigs
   - IS-IS, EIGRP, etc.

2. **core/knowledge_first_investigator.py** (300+ lines)
   - Refactored investigation workflow
   - Load knowledge FIRST
   - Plan WITH knowledge
   - Execute investigation
   - Detect gaps → retrieve knowledge

---

## Phase 1.3: Knowledge Gap Detection

### What we're building:

```
After each investigation cycle:
├─ Findings analyzed
├─ Hypotheses evaluated
├─ Gaps detected: "What DON'T we know?"
│  ├─ "What is OSPF state machine for this device?"
│  ├─ "What are common OSPF EXSTART issues here?"
│  └─ "What MTU values does vendor support?"
├─ Knowledge retrieved for gaps
└─ Investigation updated with gap knowledge
```

### Files to create:

1. **core/knowledge_gap_detector.py** (150+ lines)
   - Analyze findings and hypotheses
   - Detect gaps: what knowledge would help?
   - Categorize gaps: protocol? enterprise? vendor?
   - Trigger targeted knowledge retrieval

---

## Phase 1.4: Information-Gain-Aware Planning

### What we're building:

```
Current: "What should we check?" (random)
         → Collects low-value evidence

New: For each hypothesis:
     ├─ Candidate check A: info_gain=0.8, time=2s
     ├─ Candidate check B: info_gain=0.3, time=1s
     └─ Candidate check C: info_gain=0.6, time=5s
     
     Sort by info_gain/time ratio
     → Check A, then C, then B
     → High-value checks first
     → Converge faster
```

### Files to create:

1. **core/information_gain_calculator.py** (200+ lines)
   - Calculate information gain for each candidate check
   - Score checks by value per unit time
   - Rank candidate checks
   - Provide prioritized collection plan

---

## Phase 1.5: Hypothesis Refinement

### What we're building:

```
Initial hypotheses (LLM-generated)
    ↓
Investigate cycle 1
    ↓
Score hypotheses based on evidence
    ↓
Are top 2 > 90% of probability mass?
    ├─ YES: Focus investigation on top 2
    └─ NO: Generate NEW hypotheses based on evidence
    ↓
Continue investigating
```

### Files to create:

1. **core/hypothesis_refinement_engine.py** (200+ lines)
   - Track hypothesis probability distribution
   - Detect when initial hypotheses are poor
   - Generate new hypotheses from evidence
   - Prune low-probability hypotheses

---

## Implementation Order

### Week 1: Separate Concerns

1. **Day 1-2:** Create `protocol_planner.py`
   - Load protocol packages
   - Generate protocol-aware plans
   - Test with OSPF

2. **Day 2-3:** Create `evidence_interpreter.py`
   - Apply protocol logic to evidence
   - Test interpretation accuracy

3. **Day 3-4:** Create `bayesian_confidence_manager.py`
   - Implement Bayesian updating
   - Test confidence calculations

4. **Day 5:** Integrate & test
   - Wire together all 3 components
   - Verify they work together
   - Test on sample investigation

---

### Week 2: Knowledge Integration

1. **Day 1-2:** Create `protocol_knowledge_loader.py`
   - Load OSPF, BGP knowledge
   - Test knowledge retrieval

2. **Day 2-3:** Create `knowledge_first_investigator.py`
   - Refactor investigation workflow
   - Load knowledge upfront
   - Test integration

3. **Day 3-4:** Create `knowledge_gap_detector.py`
   - Detect gaps after cycles
   - Trigger knowledge retrieval

4. **Day 5:** Test knowledge-first flow
   - OSPF investigation with knowledge-first approach
   - Verify external knowledge is used early

---

### Week 2-3: Info Gain & Hypothesis Refinement

1. **Day 1-2:** Create `information_gain_calculator.py`
   - Calculate info gain
   - Test prioritization

2. **Day 2-3:** Create `hypothesis_refinement_engine.py`
   - Implement refinement loop
   - Test hypothesis generation

3. **Day 3-4:** Integrate both
   - Info-gain-aware planning + hypothesis refinement
   - Test together

4. **Day 5:** Comprehensive testing
   - Full workflow test
   - Performance validation

---

## Testing Strategy

### Unit Tests (Per Component)
- Protocol planner generates correct plan for OSPF
- Interpreter correctly evaluates evidence
- Confidence manager updates probabilities correctly
- Gap detector identifies missing knowledge
- Info gain calculator prioritizes correctly
- Hypothesis engine refines hypotheses

### Integration Tests
- Full investigation workflow with OSPF EXSTART
- Knowledge-first flow (load → plan → investigate → gaps)
- Hypothesis refinement (initial → evidence-based → final)
- Multi-cycle convergence

### Validation Tests
- OSPF EXSTART: converges in ≤3 cycles (vs 10+ now)
- BGP flapping: identifies root cause correctly
- Unknown issues: uses external knowledge effectively
- Accuracy: root cause matches historical solution

---

## Success Criteria (Phase 1 Complete)

- [x] All 6 components implemented and tested
- [x] OSPF EXSTART converges in ≤3 cycles
- [x] External knowledge used in 50%+ of investigations
- [x] Diagnosis accuracy ≥80% on test cases
- [x] No regression on existing functionality

---

## Files to Modify

1. **core/autonomous_troubleshooting.py**
   - Remove monolithic LLM calls
   - Wire in new components
   - Refactor troubleshoot() workflow

2. **core/external_knowledge_layer.py**
   - Move from fallback to integrated
   - Add upfront knowledge retrieval

3. **tests/test_core_enhancements.py**
   - Add tests for new components

---

## Expected Outcome

**Before:** System investigates for 10+ cycles without converging  
**After:** System investigates for 2-3 cycles with high confidence

**Why?**
- Protocol-aware planning → right checks
- Knowledge-first approach → external knowledge integrated early
- Info-gain prioritization → high-value evidence first
- Hypothesis refinement → doesn't get stuck with bad hypotheses

---

**Next:** Start Week 1, Day 1: Protocol Planner
