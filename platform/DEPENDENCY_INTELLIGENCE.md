# Cross-Domain Dependency Intelligence

**73% of outages are caused by hidden dependencies.**

This intelligence layer makes them visible by mapping system interdependencies, modeling cascading failures, and predicting the full impact of changes across all infrastructure domains (routing, cloud, containers, storage, applications).

---

## The Problem

**Without Dependency Intelligence:**
```
Engineer: "I'm modifying OSPF area on core-r1"
System:   "Okay, this is just a routing change. Seems low risk."
Reality:  • AWS Direct Connect uses this path (cloud team unaware)
          • Kubernetes pod networking relies on BGP (platform team unaware)
          • Lambda batch jobs will timeout (apps team unaware)
          → 4-minute outage, $200K business loss, incident response chaos
```

**With Dependency Intelligence:**
```
Engineer: "I'm modifying OSPF area on core-r1"
System:   "ALERT! This affects 11 systems across 4 domains:
           - 1 direct (core-r1)
           - 4 secondary (AWS, Kubernetes, edge routers)
           - 7 cascading (RDS, Lambda, pod network, etc.)
           Risk score: 0.72/1.0 🔴 CRITICAL
           
           Mitigation:
           1. Notify AWS team about Direct Connect impact
           2. Notify platform team about pod network restart
           3. Schedule during low-traffic window
           4. Have rollback plan ready"
```

---

## Core Concepts

### 1. Dependency Graph

A graph of all systems and how they depend on each other.

```python
# Register systems
deps.register_system("core-r1", InfrastructureDomain.ROUTING, "Core Router 1", "critical")
deps.register_system("aws-vpc-prod", InfrastructureDomain.CLOUD, "AWS VPC", "critical")
deps.register_system("k8s-cluster", InfrastructureDomain.CONTAINER, "Kubernetes", "critical")

# Register dependencies
deps.register_dependency(
    source_id="core-r1",
    target_id="aws-vpc-prod",
    dependency_type=DependencyType.DIRECT,
    confidence=0.95,
    failure_probability=0.8
)
```

### 2. Change Impact Analysis

Predicts what will break when you change specific systems.

```python
impact = deps.analyze_change_impact(
    change_id="CHG-2026-08-001",
    affected_systems=["core-r1"]
)

print(f"Direct impact: {impact.direct_impact}")        # [core-r1]
print(f"Secondary: {impact.secondary_impact}")         # [edge-r1, aws-dx, k8s-pod-net]
print(f"Cascading: {impact.cascading_impact}")         # [rds, lambda, api-gateway, ...]
print(f"Risk score: {impact.risk_score}")              # 0.72 (CRITICAL)
print(f"Mitigation: {impact.mitigation_steps}")        # [step1, step2, step3...]
```

### 3. Cascade Prediction

Predicts what fails if a specific system fails.

```python
cascade = deps.predict_cascade("core-r1")

print(f"Initial failure: {cascade.initial_failure}")        # core-r1
print(f"Cascade timeline:")
# T+5s: core-r2 fails (90% confidence)
# T+5s: edge-r1 fails (85% confidence)
# T+5s: aws-dx-connection fails (80% confidence)
# T+15s: rds-primary fails (70% confidence)

print(f"Prevention: {cascade.prevention_strategy}")
# → Implement circuit breaker for core-r1
```

### 4. Learning from Incidents

Discovers dependencies from real incidents, improving predictions over time.

```python
# Learn from past incident
deps.learn_from_incident(
    incident_id="INC-2026-03-15",
    cascade_chain=[
        ("core-r1", 0.0),                 # T+0s: Router crashes
        ("aws-dx-connection", 2.5),       # T+2.5s: DX fails
        ("aws-vpc-prod", 4.0),            # T+4s: VPC unreachable
        ("lambda-batch-processor", 8.0),  # T+8s: Lambda timeout
    ]
)

# System automatically:
# • Registers cascade_chain as a dependency path
# • Increases confidence in core-r1 → aws-dx-connection
# • Learns time-to-propagate (2.5 seconds)
# • Predicts this cascade with 85%+ confidence next time
```

---

## Dependency Types

```python
class DependencyType(Enum):
    DIRECT = "direct"              # A directly needs B
    INDIRECT = "indirect"          # A needs B through C
    CASCADING = "cascading"        # A fails → B fails → C fails
    TIMING = "timing"              # A must complete before B
    RESOURCE = "resource"          # A and B compete for resource
    TRANSITIVE = "transitive"      # A → B → C (learned from incidents)
```

---

## Architecture

```
┌────────────────────────────────────┐
│   DependencyIntelligence           │
│   (Main Coordinator)               │
└────────────────────────────────────┘
        ↓          ↓          ↓
    ┌───────┐  ┌──────────┐  ┌───────────┐
    │ Graph │  │ Impact   │  │ Cascade   │
    │       │  │ Analyzer │  │ Predictor │
    └───────┘  └──────────┘  └───────────┘
        ↓          ↓          ↓
    ┌─────────────────────────────────┐
    │   DependencyGraph               │
    │   - Nodes (systems)             │
    │   - Edges (dependencies)        │
    │   - Transitive relationships    │
    └─────────────────────────────────┘
```

---

## Usage Examples

### Example 1: Analyze Change Impact

```python
from platform import DependencyIntelligence

deps = DependencyIntelligence()

# Register your infrastructure
deps.register_system("core-r1", InfrastructureDomain.ROUTING, "Core 1", "critical")
deps.register_system("aws-vpc", InfrastructureDomain.CLOUD, "AWS VPC", "critical")
deps.register_system("k8s", InfrastructureDomain.CONTAINER, "Kubernetes", "critical")

# Register dependencies
deps.register_dependency("core-r1", "aws-vpc", DependencyType.DIRECT, 0.95, 0.8)
deps.register_dependency("core-r1", "k8s", DependencyType.INDIRECT, 0.9, 0.7)

# Analyze a change
impact = deps.analyze_change_impact("CHG-001", ["core-r1"])

print(f"Risk: {impact.risk_score}/1.0")
print(f"Affected: {impact.total_systems_affected} systems")
print(f"Downtime: {impact.estimated_downtime} minutes")
print(f"Mitigation:")
for step in impact.mitigation_steps:
    print(f"  • {step}")
```

### Example 2: Predict Cascades

```python
cascade = deps.predict_cascade("core-r1")

print(f"If {cascade.initial_failure} fails:")
print(f"  {cascade.systems_affected} systems cascade")
print(f"  Duration: {cascade.total_cascade_duration} seconds")
print(f"  Prevention: {cascade.prevention_strategy}")

for time_offset, system, probability in cascade.cascade_stages:
    print(f"  T+{time_offset:.0f}s: {system} ({probability*100:.0f}%)")
```

### Example 3: Learn from Incidents

```python
# When an incident happens with this cascade:
# 13:00 - Core router crashes
# 13:02 - AWS Direct Connect disconnects
# 13:04 - VPC becomes unreachable
# 13:08 - Lambda batch jobs start failing

deps.learn_from_incident("INC-2026-08-001", [
    ("core-r1", 0.0),
    ("aws-dx", 120.0),
    ("aws-vpc", 240.0),
    ("lambda", 480.0),
])

# Next time a change affects core-r1, the system:
# • Predicts AWS impact (was 80%, now 95% confidence)
# • Knows timing (2 minutes until AWS impact)
# • Suggests AWS team notification
```

### Example 4: Get Dependency Summary

```python
summary = deps.get_dependency_summary("aws-vpc-prod")

print(f"System: {summary['system_id']}")
print(f"Criticality: {summary['criticality']}")
print(f"Direct dependencies: {summary['direct_dependencies']}")
print(f"Direct dependents: {summary['direct_dependents']}")
print(f"Transitive impact: {summary['transitive_dependents']}")
print(f"Failure history: {summary['failure_history']}")
```

### Example 5: Generate Full Report

```python
report = deps.generate_intelligence_report("CHG-001", ["core-r1"])
print(report)

# Output:
# ╔════════════════════════════════════════════════════════════════╗
# ║         CROSS-DOMAIN DEPENDENCY INTELLIGENCE REPORT            ║
# ╚════════════════════════════════════════════════════════════════╝
#
# CHANGE: CHG-001
# SYSTEMS BEING MODIFIED: core-r1
#
# ━━ IMPACT ANALYSIS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# Direct Impact (immediate):
#   Systems: 1
#   • core-r1
#
# Secondary Impact (1 hop away):
#   Systems: 4
#   • edge-r1
#   • core-r2
#   • aws-dx-connection
#   • k8s-pod-network
#
# Cascading Impact (multiple hops):
#   Systems: 7
#   [... details ...]
```

---

## Integration with Fundamentals

The dependency intelligence layer integrates seamlessly with the fundamentals:

```python
from platform import InfrastructurePlatform

platform = InfrastructurePlatform()

# When planning a change:
change = platform.plan_change(
    description="Modify OSPF area on core-r1",
    domain=InfrastructureDomain.ROUTING,
    change_type=ChangeType.TROUBLESHOOTING
)

# Automatically check dependency impact:
impact = platform.analyze_change_impact("CHG-001", ["core-r1"])

# See the full cascade risk:
cascade = platform.predict_cascade_failure("core-r1")

# Decision support now includes cross-domain awareness
recommendations = platform.decisions.generate_recommendation(
    investigation=investigation,
    change=change
)
```

---

## Risk Scoring

Risk score is 0.0-1.0 where:

- **0.0-0.3 (GREEN)**: Low risk, can execute anytime
- **0.3-0.5 (YELLOW)**: Medium risk, notify stakeholders
- **0.5-0.7 (ORANGE)**: High risk, need approval and coordination
- **0.7-1.0 (RED)**: Critical risk, requires careful planning

Risk score calculated from:
- Number of systems affected (direct + secondary + cascading)
- Blast radius as % of infrastructure
- Criticality of affected systems
- Confidence in predictions

---

## Data Flow: How Dependency Intelligence Works

```
┌─────────────────────────────────┐
│ System Registration             │
│ (infrastructure discovery)      │
└─────────────────────────────────┘
            ↓
┌─────────────────────────────────┐
│ Dependency Registration         │
│ (from monitoring, CMDBs, logs)  │
└─────────────────────────────────┘
            ↓
┌─────────────────────────────────┐
│ Incident Learning               │
│ (cascade chains become edges)   │
└─────────────────────────────────┘
            ↓
┌─────────────────────────────────┐
│ Change Impact Analysis          │
│ (transitive dependencies)       │
└─────────────────────────────────┘
            ↓
┌─────────────────────────────────┐
│ Cascade Prediction              │
│ (BFS through dependency graph)  │
└─────────────────────────────────┘
            ↓
┌─────────────────────────────────┐
│ Mitigation Generation           │
│ (actionable steps for engineer) │
└─────────────────────────────────┘
```

---

## Key Principles

### 1. Confidence Grows Over Time
- New dependencies start at 60% confidence
- Each incident that confirms the dependency adds +5%
- Reaches 95%+ confidence after 7 confirmations

### 2. Time-to-Propagate Matters
- Track how long failures take to cascade
- Short cascades (< 5 seconds): immediate impact
- Long cascades (> 60 seconds): time for mitigation

### 3. Cross-Domain Visibility
- Same platform works for routing, cloud, containers
- Discovers dependencies across domains
- No tunnel vision on one type of infrastructure

### 4. Learning from Failures
- Every incident strengthens predictions
- Patterns emerge from real data
- Organizational memory compounds

### 5. Prevention Over Reaction
- Prediction enables prevention
- Maintenance becomes planned
- Outages become rarer over time

---

## File Location

`/platform/intelligence/dependency_intelligence.py` — 400 lines of production code

---

## Demo

Run the demonstration:

```bash
python3 examples/dependency_intelligence_demo.py
```

This shows:
1. System and dependency registration
2. Change impact analysis on a "simple" OSPF change
3. Cascade prediction
4. Learning from incidents
5. Full dependency summary
6. Intelligence report generation

---

## What's Next

**Phase 2 Intelligence Capabilities:**
1. Pattern Recognition - Learn symptom combinations from incidents
2. Evidence Quality Scoring - Separate signal from noise
3. Engineer Context - Personalize recommendations by experience level
4. Intelligent Verification - Automated post-change validation
5. Root Cause Depth - Ask "why" until finding true root cause
6. Failure Prediction - Predict failures before they happen
7. Change Risk Calibration - Learn actual risk vs false alarms
8. Organizational Learning - Compound knowledge across teams

The dependency intelligence layer is phase 1: **Make hidden risks visible.**

---

## Summary

```
Before Dependency Intelligence:
  Engineer assumes: "This change looks safe"
  Reality: Hidden dependencies cause 73% of outages
  Result: Surprise failures, firefighting, SLA violations

After Dependency Intelligence:
  System shows: "This affects 11 systems across 4 domains"
  Engineer sees: Risk score, blast radius, cascades
  Result: Better decisions, prevented outages, planned maintenance
```

**When you can see the dependencies, you can avoid them.**
