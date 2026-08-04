# Infrastructure Engineering Platform: Fundamentals

1200 lines of production-ready code that handles **network design, troubleshooting, and configuration**—and scales to any infrastructure domain.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│           Platform Orchestrator (Unified API)               │
└─────────────────────────────────────────────────────────────┘
           ↓              ↓              ↓              ↓
    Investigation    Design Engine   Configuration   Decision
      Engine                           Engine          Support
           ↓              ↓              ↓              ↓
    ┌─────────────────────────────────────────────────────────┐
    │              Safety Framework & Learning                 │
    └─────────────────────────────────────────────────────────┘
           ↓              ↓              ↓              ↓
    OSPFAdapter    AWSAdapter    K8sAdapter    FirewallAdapter
           ↓              ↓              ↓              ↓
    [Routing]      [Cloud]      [Containers]   [Security]
```

---

## 7 Core Engines

### 1. Investigation Engine (Troubleshooting)

**Purpose:** Systematic problem diagnosis for any infrastructure domain.

**Workflow:**
```python
# Start investigating
investigation = platform.troubleshoot(
    problem_statement="OSPF neighbor stuck in EXSTART",
    domain=InfrastructureDomain.ROUTING,
    category=ProblemCategory.CONNECTIVITY,
    severity="high"
)

# Add evidence
platform.investigation.add_evidence(
    investigation=investigation,
    description="Neighbor in EXSTART state",
    source="show ip ospf neighbor",
    confidence=0.99
)

# Generate theories
theories = platform.investigation.generate_hypotheses(
    investigation,
    domain_handler=ospf_adapter
)

# Theories ranked by confidence
# - Area mismatch: 85%
# - Network type mismatch: 60%
# - Authentication: 40%
```

**Key Concept:** Hypothesis elimination, not confirmation.
- Record observations without bias
- Generate all plausible theories
- Update confidence as new evidence arrives
- Let data speak

---

### 2. Design Engine (Planning)

**Purpose:** Infrastructure design and architecture review.

**Workflow:**
```python
# Create design option
design = platform.design.create_design(
    description="Redundant BGP with two upstream ISPs",
    domain=InfrastructureDomain.ROUTING
)

# Define trade-offs
design.advantages = ["Carrier diversity", "Active-active load sharing"]
design.disadvantages = ["Higher cost", "More complex routing policies"]
design.scalability = "high"
design.complexity = "medium"

# Score design
score = design.score()  # 0.0-1.0

# Compare multiple options
best_designs = platform.design.compare_designs([design1, design2, design3])
```

**Key Concept:** Design as a scored choice, not a binary decision.
- Multiple options
- Explicit trade-offs
- Quantified scoring
- Engineer decides

---

### 3. Configuration Engine (Change Management)

**Purpose:** Safe, verifiable infrastructure changes.

**Workflow:**
```python
# Propose change
change = platform.plan_change(
    description="Change OSPF area to align both sides",
    domain=InfrastructureDomain.ROUTING,
    change_type=ChangeType.TROUBLESHOOTING
)

# Define verification
platform.configuration.define_verification(
    change=change,
    verification_steps=[
        "show ip ospf neighbor (expect FULL)",
        "show ip route (expect all routes present)",
        "ping across adjacency (expect no loss)"
    ]
)

# Define rollback
platform.configuration.define_rollback(
    change=change,
    rollback_steps=[
        "no ip ospf area 0",
        "write memory"
    ]
)

# Record result
platform.configuration.record_verification(
    change_id=change.id,
    expected={"neighbor_state": "FULL", "packet_loss": 0},
    actual={"neighbor_state": "FULL", "packet_loss": 0}
)
```

**Key Concept:** Every change must be verifiable and reversible.
- Prediction before action
- Verification after action
- Rollback always available
- Safety first

---

### 4. Decision Support Engine

**Purpose:** Provide guidance, not make decisions.

**Workflow:**
```python
# Generate recommendation
recommendation = platform.decisions.generate_recommendation(
    investigation=investigation,
    change=change
)

# Present options
options = platform.decisions.present_options(investigation)
# {
#   "option_a": {
#     "description": "Change area on Router A",
#     "pros": ["Quick fix", "Low risk"],
#     "cons": ["Requires coordination"],
#     "effort": "5 minutes",
#   },
#   "option_b": {
#     "description": "Debug with packet capture first",
#     "pros": ["More certainty"],
#     "cons": ["Slower resolution"],
#     "effort": "30 minutes",
#   }
# }
```

**Key Concept:** Support human judgment, don't replace it.
- Multiple options presented
- Trade-offs explicit
- Engineer chooses
- Tool explains why

---

### 5. Safety Framework

**Purpose:** Ensure changes are safe and reversible.

**Workflow:**
```python
# Pre-change checklist
checklist = SafetyFramework.pre_change_checklist(change)
# {
#   "can_see_what_changes": True,
#   "can_predict_outcome": True,
#   "can_verify_worked": True,
#   "can_rollback": True,
#   "have_escape_route": True,
# }

# Verify change safety
safe, issues = SafetyFramework.verify_change_safety(change)
# Issues found:
# - "No verification steps defined"
# - "High blast radius changes require approval"
```

**Key Concept:** Safety is non-negotiable.
- Pre-change verification
- Risk assessment
- Approval gating for high-risk changes
- Blast radius calculation

---

### 6. Learning System

**Purpose:** Build organizational knowledge from decisions.

**Workflow:**
```python
# Record decision and outcome
decision = platform.document_decision(
    investigation=investigation,
    decision="Changed area from 0 to 1",
    outcome="success",
    lessons=[
        "Area mismatch is the most common EXSTART cause",
        "Always verify both sides before applying",
        "Convergence time is predictable (8-15 sec)"
    ]
)

# Find similar past decisions
similar = platform.learning.find_similar_cases(investigation)
# Returns all past connectivity issues with ROUTING domain
```

**Key Concept:** Every decision is a learning opportunity.
- Decisions recorded with outcome
- Lessons extracted
- Similar cases found
- Organizational memory grows

---

### 7. Platform Orchestrator (Unified API)

**Purpose:** Single interface for all infrastructure work.

**Workflow:**
```python
# 1. TROUBLESHOOT
investigation = platform.troubleshoot(
    problem_statement="...",
    domain=...,
    category=...
)

# 2. PLAN CHANGE
change = platform.plan_change(
    description="...",
    domain=...,
    change_type=...
)

# 3. ASSESS DESIGN
design = platform.assess_design(
    description="...",
    domain=...
)

# 4. DOCUMENT DECISION
decision = platform.document_decision(
    investigation=investigation,
    decision="...",
    outcome="...",
    lessons=[...]
)
```

---

## Domain Model

### Universal Concepts

Every infrastructure domain has:
1. **Observations** - Facts about state
2. **Theories** - Hypotheses about what's wrong
3. **Changes** - Proposed modifications
4. **Designs** - Architectural options
5. **Decisions** - What was done and why

### Supported Domains

- **Routing** - OSPF, BGP, ISIS, static routes
- **Switching** - VLAN, STP, LACP, port-channel
- **Security** - Firewalls, ACLs, NAT, policies
- **Cloud** - AWS, Azure, GCP VNets and routing
- **Container** - Kubernetes services, network policies
- **Storage** - SAN, NAS, object storage
- **Compute** - VM placement, instance configuration
- **Application** - Service deployment, dependencies
- **Observability** - Monitoring, logging, tracing

---

## Key Principles

### 1. Show Reasoning, Not Confidence

**Instead of:**
```
Recommendation: Change area to 0
Confidence: 85%
```

**Provide:**
```
Supporting evidence:
  ✓ Neighbor in EXSTART (99% sure)
  ✓ Areas don't match (100% sure)

Contradicting evidence:
  ✗ None

Unknown factors:
  ? Packet capture shows what?
  ? Is peer aware of change?
```

### 2. Assume Everything Could Be Wrong

Every theory includes:
- What supports it
- What contradicts it
- What we don't know
- How we'd know if wrong

### 3. Give Runbooks, Not Recommendations

Before applying any change:
1. **BEFORE** - Verify prerequisites
2. **THE CHANGE** - Exact steps
3. **IMMEDIATE** - Verify next 30 seconds
4. **SHORT-TERM** - Verify next 5 minutes
5. **IF FAILS** - Rollback steps
6. **IF PASSES** - Success criteria

### 4. Safety Is Non-Negotiable

Every change requires:
- Verification plan
- Rollback plan
- Risk assessment
- Approval (if high-risk)
- Escape route

### 5. Decision Support, Not Decisions

Tool provides:
- Options
- Trade-offs
- Reasoning
- Recommendations

Engineer decides.

---

## Extensibility: Adding Domains

To support a new domain (e.g., Firewall policies):

```python
class FirewallAdapter(DomainAdapter):
    """Handle firewall policy changes."""
    
    def __init__(self):
        super().__init__(InfrastructureDomain.SECURITY)
    
    def hypothesize(self, observations):
        """Generate theories about firewall issues."""
        # Firewall-specific logic
        return [
            Theory(description="ACL blocking traffic", ...),
            Theory(description="NAT misconfigured", ...),
            Theory(description="Policy rule order wrong", ...),
        ]
    
    def verify_theory(self, theory):
        """Verify firewall hypothesis."""
        # Check theory against firewall state
        pass
    
    def predict_change(self, change):
        """Predict impact of firewall policy change."""
        # Firewall-specific predictions
        pass
    
    def evaluate_design(self, design):
        """Evaluate firewall design."""
        # Check design feasibility
        pass

# Use it
platform = InfrastructurePlatform()
firewall_adapter = FirewallAdapter()

investigation = platform.troubleshoot(
    problem_statement="Traffic blocked",
    domain=InfrastructureDomain.SECURITY,
    category=ProblemCategory.CONNECTIVITY
)
```

---

## Real-World Workflows

### Workflow 1: Troubleshoot + Fix

```
1. platform.troubleshoot()
   ↓ Add evidence
2. Generate hypotheses
   ↓ Eliminate theories
3. platform.plan_change()
   ↓ Define verification/rollback
4. Execute change safely
   ↓ Verify
5. platform.document_decision()
   ↓ Record lessons
```

### Workflow 2: Design + Build

```
1. platform.assess_design()
   ↓ Define options
2. platform.design.compare_designs()
   ↓ Evaluate each
3. Select design
   ↓
4. platform.plan_change() for each component
   ↓ Verify each step
5. Build incrementally
   ↓
6. Document architecture
```

### Workflow 3: Plan Maintenance

```
1. platform.plan_change()
   ↓ Define scope
2. Safety verification
   ↓ Approval gating
3. Coordinate with stakeholders
   ↓
4. Execute during maintenance window
   ↓ Verify each step
5. Post-change validation
   ↓
6. Document lessons
```

---

## Success Metrics

### Investigation Success
- Theory confidence >80%
- Rare contradictions
- Quick resolution (minutes, not hours)

### Design Success
- Trade-offs understood
- Scalability clear
- Risk accepted explicitly

### Change Success
- Verification 100% passed
- No unexpected side effects
- Rollback never needed

### Organization Success
- Decision patterns emerge
- Similar problems solved faster
- Knowledge compounds over time

---

## Implementation Status

✅ **Complete:**
- Investigation engine
- Design engine
- Configuration engine
- Decision support
- Safety framework
- Learning system
- Platform orchestrator
- Domain adapter interface

🔄 **Next Steps:**
- OSPF adapter implementation
- AWS adapter implementation
- Kubernetes adapter implementation
- Firewall adapter implementation
- Storage adapter implementation

---

## File Location

`/platform/fundamentals.py` - 1200 lines of production code

---

## Usage Example

See end of fundamentals.py for working examples:
- Troubleshoot OSPF issue
- Plan configuration change
- Document decision with lessons

