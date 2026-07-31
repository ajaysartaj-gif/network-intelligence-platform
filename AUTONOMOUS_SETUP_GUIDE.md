# Autonomous Troubleshooting Setup Guide

Complete guide to integrating all 5 phases and enabling the 3 execution paths.

---

## Quick Start (5 minutes)

### 1. Install Dependencies

```bash
# Add to requirements.txt:
sentence-transformers>=2.2.0  # For semantic similarity search
sqlite3  # Usually included with Python
```

### 2. Initialize in Your App (e.g., `app.py`)

```python
from core.autonomous_troubleshooting import create_autonomous_troubleshooter
from core.ai_engine import ask_ai
from core.troubleshooting import TroubleshootingEngine  # existing engine

# Initialize troubleshooter with all 5 phases
troubleshooter = create_autonomous_troubleshooter(
    ai_call=ask_ai,
    troubleshoot_engine=ts_engine,  # Your existing engine
    ssh_collector=lambda dev, cmds: intent_engine._ssh_collect(dev, cmds),
    command_validator=lambda cmd: intent_engine.is_read_only(cmd),
    approved_devices=approved_devices,
    topology=topology_graph,
)
```

### 3. Wire Into Streamlit UI

```python
# In your Streamlit workspace where user asks questions:
import streamlit as st
from core.autonomous_troubleshooting import ExecutionPath

# User selects troubleshooting mode
mode = st.radio(
    "Troubleshooting mode:",
    options=["on_demand", "learning", "autonomous"],
    captions=[
        "Diagnose & approve fixes manually",
        "Diagnose & store patterns for learning",
        "Predict issues + auto-fix when confident",
    ]
)

# User enters problem
problem = st.text_area("Describe your network problem:")

if st.button("Troubleshoot"):
    # Run troubleshooting
    def approval_fn(plan):
        st.info(f"**Fix:** {plan.fix_explanation}")
        st.code("\n".join(plan.fix_commands), language="bash")
        return st.button("✅ Approve & Apply")
    
    session = troubleshooter.troubleshoot(
        user_query=problem,
        operation_mode=mode,
        approval_callback=approval_fn if mode == "on_demand" else None,
        telemetry_metrics=orchestrator.telemetry.current_metrics if mode == "autonomous" else None,
    )
    
    # Display results
    st.subheader("Diagnosis")
    st.write(f"**Root Cause:** {session.root_cause}")
    if session.predictions:
        st.warning(f"**Predicted Issues:** {len(session.predictions)} potential issues detected")
    if session.execution_result:
        st.success(f"**Outcome:** {session.execution_result.outcome}")
```

---

## Understanding the 3 Paths

### Path A: Fully Autonomous (Prod-Ready after 2+ weeks of learning)

```
User describes problem
    ↓
[PHASE 1] Semantic Intake → structured problem classification
    ↓
[PHASE 4] Pattern Predictor → forecast issues before they break
    ↓
[PHASE 2] Troubleshoot Engine → diagnose root cause
    ↓
[PHASE 4] Autonomous Decision → "Should I auto-apply?"
    │
    ├─ If high confidence + good track record → Auto-apply
    │   ↓
    │   [PHASE 2] Remediation Executor → execute with pre/post checks
    │   ↓
    │   [PHASE 3] Pattern DB → record outcome + update confidence
    │   ↓
    │   Outcome: FIXED (or rolled back if verification fails)
    │
    └─ If uncertain → Queue for approval
        ↓
        Wait for human approval
        ↓
        [PHASE 2] Remediation Executor → execute
        ↓
        [PHASE 3] Pattern DB → record outcome
```

**When to use:** After collecting 20-30 incident patterns and >80% success rate on similar issues.

**Risk level:** LOW (unknown fixes still require approval)

**Benefits:**
- ✅ Known issues fixed automatically in <2 minutes
- ✅ Predicted issues prevented before they break
- ✅ Learns from every incident

---

### Path B: On-Demand Troubleshooting (Start here)

```
User asks: "Network is slow"
    ↓
[PHASE 1] Semantic Intake → "link", "performance", affected devices
    ↓
[PHASE 2] Troubleshoot Engine → diagnose root cause
    ↓
"Fix ready: set interface MTU 1500"
    ↓
User clicks "Approve" (or declines)
    ↓
[PHASE 2] Remediation Executor
    • Pre-check: Syntax valid? Device reachable? Command safe?
    • Execute: SSH to devices, run commands
    • Post-check: Verify fix worked
    • Rollback: Auto-roll if verification fails
    ↓
[PHASE 3] Pattern DB → record for learning (optional)
    ↓
"✅ Fixed: OSPF neighbor now FULL" or "❌ Rollback triggered"
```

**When to use:** Week 1 - Start here for immediate value

**Risk level:** VERY LOW (all changes need human approval)

**Benefits:**
- ✅ Immediate diagnosis (2-5 min vs hours of manual troubleshooting)
- ✅ Safe execution (pre-checks + post-checks + automatic rollback)
- ✅ Builds pattern DB automatically

---

### Path C: Learning-First (Parallel to Path B, Week 1-2)

```
User: "Network slow"
    ↓
[PHASE 3] Pattern DB → "We've seen this 3 times before!"
    • Success rate: 67% (2 fixed, 1 degraded)
    • Suggested fix: "set interface mtu 1500" (from past incident)
    ↓
[PHASE 2] Troubleshoot Engine → confirm diagnosis
    ↓
"✨ Similar issue: success rate 67%, precedent: 3 times"
    ↓
User applies fix
    ↓
[PHASE 3] Pattern DB → record outcome
    ↓
"Pattern updated: success rate now 75% (3 fixed, 1 degraded)"
```

**When to use:** Week 1-2, parallel to Path B

**Risk level:** VERY LOW (no automation)

**Benefits:**
- ✅ Speeds up diagnosis: "We've seen this" → instant context
- ✅ Shows success rate: "This fix works 80% of the time"
- ✅ Learns patterns naturally without needing explicit rule-writing

---

## Architecture Diagram

```
User Query (natural language)
    ↓
┌──────────────────────────────────────────────────────────┐
│ PHASE 1: SEMANTIC INTAKE (core/semantic_intake.py)       │
│ "Network slow" → {scope:link, symptom:performance, ...}  │
└──────────────────────────────────────────────────────────┘
    ↓
    ├─→ Decide Path: A (autonomous) | B (on-demand) | C (learning)
    ↓
┌──────────────────────────────────────────────────────────┐
│ PHASE 2: TROUBLESHOOTING (existing engine + new executor) │
│ • Diagnose: evidence-first hypothesis ranking             │
│ • Generate fix: safe, minimal, vendor-aware               │
│ • Execute: pre-check → run → post-check → rollback        │
│   (core/remediation_executor.py)                          │
└──────────────────────────────────────────────────────────┘
    ↓
┌──────────────────────────────────────────────────────────┐
│ PHASE 3: PATTERN DB (core/pattern_db.py)                 │
│ • Record: every incident + outcome                        │
│ • Query: semantic similarity search ("Have we seen this?")│
│ • Learn: update confidence based on feedback              │
└──────────────────────────────────────────────────────────┘
    ↓
    └─→ Path A Only:
        ┌──────────────────────────────────────────────────────────┐
        │ PHASE 4: PREDICTION & AUTONOMY (core/prediction_*.py)    │
        │ • Predict: match telemetry to failure patterns            │
        │ • Decide: "Auto-apply this fix? (confidence 92%)"         │
        │ • Learn: grade predictions over time                      │
        └──────────────────────────────────────────────────────────┘
            ↓
        Outcome: FIXED | DEGRADED | ERROR
            ↓
        Loop back to Pattern DB → update confidence
```

---

## Data Files Created

```
./network_pattern_db.sqlite     # SQLite database of all incidents
                                # Tables: incidents, failure_patterns, predictions
```

Backup strategy:
```bash
# Backup patterns (important!)
cp network_pattern_db.sqlite network_pattern_db.backup.$(date +%Y%m%d).sqlite

# Restore
cp network_pattern_db.backup.20240731.sqlite network_pattern_db.sqlite
```

---

## Configuration & Tuning

### Semantic Intake (Phase 1)

```python
from core.semantic_intake import SemanticIntake

intake = SemanticIntake(ai_call=ask_ai)

# Optional: Provide topology context for better classification
problem = intake.parse(
    user_query="Network is slow",
    discovered_devices=approved_devices,
    topology_context="NYC site, 50 devices, 3 core routers, 20 access switches"
)
```

### Remediation Executor (Phase 2)

```python
from core.remediation_executor import RemediationExecutor

executor = RemediationExecutor(
    ssh_collector=collector,
    command_validator=validator,
    approval_required=True,  # Set False only for Path A + known fixes
    auto_rollback_on_failure=True,  # Always True
)
```

### Pattern Database (Phase 3)

```python
from core.pattern_db import PatternDatabase

db = PatternDatabase(db_path="./network_pattern_db.sqlite")

# Get stats to monitor learning progress
stats = db.get_stats()
print(f"Total patterns: {stats['total_incidents']}")
print(f"Avg success confidence: {stats['avg_success_confidence']:.0%}")
```

### Prediction (Phase 4, Path A only)

```python
from core.prediction_forecaster import PatternPredictor, AutonomousDecisionMaker

predictor = PatternPredictor(pattern_db)
predictions = predictor.predict_degradation(
    topology=topology_graph,
    current_metrics=telemetry.current_metrics,
    recent_events=event_engine.recent_events
)

decision_maker = AutonomousDecisionMaker(
    pattern_db,
    confidence_threshold=0.85,  # Min diagnosis confidence
    success_rate_threshold=0.80  # Min fix success rate
)

should_auto_apply = decision_maker.should_auto_apply(
    root_cause="MTU mismatch",
    suggested_fix="set mtu 1500",
    confidence=0.92
)
```

---

## Testing

### Run All Tests

```bash
pytest tests/test_autonomous_troubleshooting.py -v
```

### Test Individual Phases

```bash
# Phase 1: Semantic Intake
pytest tests/test_autonomous_troubleshooting.py::TestSemanticIntake -v

# Phase 2: Remediation
pytest tests/test_autonomous_troubleshooting.py::TestRemediationExecutor -v

# Phase 3: Pattern DB
pytest tests/test_autonomous_troubleshooting.py::TestPatternDatabase -v

# Phase 4: Prediction
pytest tests/test_autonomous_troubleshooting.py::TestPrediction -v

# Phase 5: Integration
pytest tests/test_autonomous_troubleshooting.py::TestAutonomousTroubleshooter -v
```

---

## Deployment Timeline

### Week 1: Path B (On-Demand)
- Deploy Phase 1 + 2 + 3
- Users can troubleshoot manually
- Start collecting patterns
- **Risk:** Very low (all fixes need approval)

### Week 2: Path C (Learning)
- Keep Phase 1-3 as-is
- UI shows "We've seen this before" when patterns match
- Pattern confidence starts building
- Users grade outcomes
- **Risk:** Very low (no automation)

### Week 3: Phase 4 (Prediction)
- Add Phase 4 (prediction engine)
- System starts forecasting issues
- AI learns failure patterns
- **Risk:** Low (forecasts are informational only)

### Week 4: Path A (Autonomous)
- Enable auto-fix for:
  - High confidence diagnosis (>85%)
  - Fix with >80% success rate
  - Known issues from pattern DB (3+ precedents)
- Unknown fixes still require approval
- **Risk:** Low (approval gate on unknowns)

---

## Monitoring & Observability

### Key Metrics to Track

```python
stats = troubleshooter.get_stats()

# Pattern DB health
print(f"Total incidents learned: {stats['pattern_db']['total_incidents']}")
print(f"Success rate (avg): {stats['pattern_db']['avg_success_confidence']:.0%}")

# Prediction accuracy
accuracy = db.get_prediction_accuracy()
print(f"Forecast accuracy: {accuracy:.0%}")

# Auto-apply rate (Path A only)
auto_applied = executor.history.count(lambda r: r.status == COMPLETE and not r.rolled_back)
print(f"Auto-fixed this month: {auto_applied}")
```

### Logging

All phases log to standard Python logger:

```python
import logging
logging.basicConfig(level=logging.INFO)

# Per-module logging
logging.getLogger("core.semantic_intake").setLevel(logging.DEBUG)
logging.getLogger("core.remediation_executor").setLevel(logging.INFO)
logging.getLogger("core.pattern_db").setLevel(logging.INFO)
logging.getLogger("core.prediction_forecaster").setLevel(logging.INFO)
```

---

## Troubleshooting

### "Semantic classification returns 'unknown' for every query"

**Issue:** AI not responding with proper JSON

**Fix:**
```python
intake = SemanticIntake(ai_call=ask_ai)
# Test AI response
response = ask_ai("Classify this: network is slow")
print(response)  # Should be valid JSON
```

### "Patterns not persisting between runs"

**Issue:** Pattern DB not initialized properly

**Fix:**
```python
from core.pattern_db import PatternDatabase
db = PatternDatabase(db_path="./network_pattern_db.sqlite")
db._init_db()  # Force re-init
```

### "Auto-apply never triggers even with high confidence"

**Issue:** Thresholds too high or not enough patterns

**Fix:**
```python
# Lower thresholds for testing
decision_maker = AutonomousDecisionMaker(
    pattern_db,
    confidence_threshold=0.75,  # Down from 0.85
    success_rate_threshold=0.70  # Down from 0.80
)

# Check if patterns exist
stats = pattern_db.get_stats()
print(f"Patterns: {stats['total_incidents']}")
```

---

## Next Steps

1. **Start with Path B** (on-demand) → Week 1
2. **Enable Path C** (learning) → Week 1, parallel
3. **Monitor pattern collection** → Week 2
4. **Enable Path A** (autonomous) → Week 4+, once patterns mature

See `IMPLEMENTATION_PLAN.md` for detailed weekly checklist.
