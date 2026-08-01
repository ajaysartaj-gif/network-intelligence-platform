# AUTONOMOUS NETWORK INTELLIGENCE OPERATING SYSTEM
## Core Primitives - The Boundary Layer

**Status:** IMPLEMENTATION GATE - ARCHITECTURE REVIEW REQUIRED  
**Scope:** Define OS-level contracts, not implementation details  
**Timeline:** This must be approved before ANY capability implementation  

---

## THE FUNDAMENTAL INSIGHT

**What You've Built So Far:**
```
Capabilities (Investigation, Prediction, Automation, etc.)
Layers (Runtime, Data, Business Context, Trust, etc.)
Architecture (Flows, dependencies, maturity levels)
```

**What's Missing:**
```
Operating System Primitives (Contracts, Events, Lifecycle, Goals, Resources)
```

**The Difference:**
- Without primitives → Tightly coupled, hard to extend, hard to maintain
- With primitives → Loosely coupled, extensible, maintainable for decades

**Example:**
```
Without Primitives:
    Investigation returns Python object
    → Planner reads Investigation object fields
    → Tightly coupled (if Investigation changes, Planner breaks)

With Primitives:
    Investigation publishes InvestigationFinished event
    Planner subscribes to InvestigationFinished event
    Planner reads InvestigationFinished contract
    → Loosely coupled (Investigation and Planner independent)
```

---

## PRIMITIVE #1: CORE CONTRACTS

**Definition:** The canonical data types that flow between components.

These are NOT Python objects. These are language-agnostic, version-stable contracts.

### 1.1 Request Contracts

**Observation** (Input to any capability)
```
{
  id: UUID
  timestamp: ISO8601
  domain: enum[enterprise, sp, telecom, industrial]
  service: string (payment_gateway, vpn, 5g_core, etc)
  type: enum[device_event, telemetry_anomaly, config_change, service_degradation, user_report]
  severity: enum[critical, high, medium, low]
  affected_devices: [Device]
  affected_services: [Service]
  affected_customers: [Customer]
  telemetry_window: {start_time, end_time}
  source: enum[alert, operator, prediction, simulation, user]
  context: {business_context, technical_context}
  trust_score: float[0-1]
}
```

**InvestigationRequest** (What to investigate)
```
{
  observation_id: UUID (reference to Observation)
  protocol: enum[ospf, bgp, isis, eigrp, 5g, lte, diameter, sip, etc]
  issue_type: enum[exstart, flapping, session_down, latency, packet_loss, etc]
  root_device: string
  affected_devices: [string]
  max_cycles: int
  confidence_threshold: float
  time_budget_seconds: int
  evidence_sources: [enum[snmp, cli, netconf, telemetry, logs, simulation]]
  prioritize_speed_over_accuracy: bool
  metadata: dict
}
```

**PredictionRequest** (What to forecast)
```
{
  observation_id: UUID
  metric_name: string (link_utilization, latency, packet_loss, error_rate)
  device_id: string
  interface_id: string
  forecast_horizon_hours: int (1, 6, 24, 48)
  include_confidence_interval: bool
  include_anomaly_detection: bool
  historical_window_days: int
  metadata: dict
}
```

**DecisionRequest** (What to decide)
```
{
  investigation_id: UUID (from InvestigationFinished event)
  root_cause: string
  confidence: float[0-1]
  affected_services: [Service]
  business_impact: {revenue_at_risk, users_affected, sla_breach_time}
  available_options: [Option] where Option = {description, success_probability, risk_level, cost}
  constraints: {change_window, compliance_rules, rollback_capability}
  goal: string (restore_service, prevent_outage, optimize_performance)
  metadata: dict
}
```

**SimulationRequest** (What to simulate)
```
{
  decision_id: UUID
  proposed_change: {type, device, config_diff}
  baseline_metrics: {latency, packet_loss, throughput, etc}
  simulation_duration_seconds: int
  include_rollback_simulation: bool
  measure_blast_radius: bool
  measure_downstream_impact: bool
  metadata: dict
}
```

**AutomationRequest** (What to execute)
```
{
  decision_id: UUID
  proposed_change: {type, device, config_diff}
  approval_status: enum[approved, escalation_required, requires_simulation]
  validation_plan: [Validation]
  rollback_plan: [Rollback]
  time_limit_seconds: int
  require_manual_validation: bool
  abort_on_first_error: bool
  notify_on_status: [email, slack, pagerduty]
  metadata: dict
}
```

### 1.2 Response Contracts

**Evidence** (Output from Evidence Collector)
```
{
  id: UUID
  investigation_id: UUID (reference to InvestigationRequest)
  check_name: string
  command: string
  output: string
  parsed_value: object
  collected_timestamp: ISO8601
  source_device: string
  source_trust: float[0-1] (how reliable is this source?)
  freshness_score: float[0-1] (how recent is this?)
  validation_status: enum[unvalidated, validated_once, validated_multiple]
  conflicting_evidence: [UUID] (references to other Evidence that contradicts)
  metadata: dict
}
```

**Finding** (Output from Evidence Interpreter)
```
{
  id: UUID
  investigation_id: UUID
  evidence_ids: [UUID] (references to Evidence that supports this)
  interpretation: string
  supports_hypothesis: [string]
  eliminates_hypothesis: [string]
  confidence_delta: float[0-1]
  contradictions: [string] (other findings that contradict)
  next_questions: [string]
  requires_external_knowledge: bool
  knowledge_source_needed: enum[protocol, vendor, enterprise, web, mcp]
  metadata: dict
}
```

**Investigation Result** (Output from Investigation capability)
```
{
  id: UUID
  observation_id: UUID
  investigation_request_id: UUID
  root_cause: string
  confidence: float[0-1]
  cycles_taken: int
  total_evidence: int
  top_3_hypotheses: [{name, probability}]
  findings: [Finding] (references)
  knowledge_used: [string]
  knowledge_gaps: [KnowledgeGap]
  investigation_time_seconds: float
  execution_trace: [dict] (for debugging/learning)
  metadata: dict
}
```

**Prediction Result** (Output from Prediction capability)
```
{
  id: UUID
  observation_id: UUID
  prediction_request_id: UUID
  metric_name: string
  forecast_values: [{timestamp, value, confidence_interval}]
  anomaly_detected: bool
  anomaly_probability: float[0-1]
  failure_probability: float[0-1]
  time_to_failure_minutes: int (if failure_probable)
  confidence_score: float[0-1]
  model_accuracy_history: float[0-1]
  metadata: dict
}
```

**Decision** (Output from Decision capability)
```
{
  id: UUID
  investigation_id: UUID
  prediction_id: UUID (optional)
  recommendation: string
  success_probability: float[0-1]
  risk_level: enum[critical, high, medium, low, minimal]
  estimated_mttr_minutes: int
  business_impact: {revenue_restored, users_restored, sla_time}
  blast_radius: {affected_devices, affected_services, affected_customers}
  requires_approval: bool
  approval_required_from: enum[security, compliance, business, cto]
  alternative_options: [{description, success_probability, risk_level}]
  why_best_option: string (explanation)
  metadata: dict
}
```

**SimulationResult** (Output from Digital Twin)
```
{
  id: UUID
  decision_id: UUID
  simulation_request_id: UUID
  proposed_change: {type, device, config_diff}
  predicted_outcome: string
  success_probability: float[0-1]
  metric_changes: {metric_name: {before, after, change_pct}}
  blast_radius_verified: bool
  rollback_feasible: bool
  rollback_time_seconds: int
  estimated_total_time_seconds: int
  safety_score: float[0-1]
  confidence_in_simulation: float[0-1]
  metadata: dict
}
```

**ExecutionPlan** (Generated by Automation capability)
```
{
  id: UUID
  decision_id: UUID
  proposed_change: {type, device, config_diff}
  steps: [{
    step_id: int
    description: string
    device_id: string
    command: string
    estimated_time_seconds: int
    rollback_command: string
    validation: {check_name, expected_result}
    abort_if_fails: bool
  }]
  parallel_steps: [int] (step IDs that can run in parallel)
  conditional_steps: {step_id: {condition, then_step, else_step}}
  rollback_plan: [{reverse_step}]
  estimated_total_time_seconds: int
  estimated_downtime_seconds: int
  metadata: dict
}
```

**LearningEvent** (Output from Learning capability)
```
{
  id: UUID
  observation_id: UUID
  investigation_id: UUID
  decision_id: UUID
  execution_id: UUID
  outcome: enum[success, partial_success, failure]
  actual_mttr_minutes: int
  expected_mttr_minutes: int
  prediction_accuracy: float[0-1]
  decision_quality: float[0-1]
  root_cause_correct: bool
  what_worked: [string]
  what_didnt_work: [string]
  lessons_learned: [string]
  pattern_recognized: string (if this matches known pattern)
  new_rule_proposed: string (if this suggests new rule)
  confidence_adjustment: float (-0.1 to +0.1)
  metadata: dict
}
```

---

## PRIMITIVE #2: EVENT MODEL

**Definition:** How capabilities communicate asynchronously via events.

### 2.1 Event Types (Pub/Sub)

```
OBSERVATION EVENTS:
├─ ObservationCreated
│  └─ When: External alert, telemetry anomaly, user report detected
│  └─ Payload: Observation contract
│
├─ ObservationCorrelated
│  └─ When: Multiple observations linked (same root cause)
│  └─ Payload: {primary_observation_id, correlated_observation_ids}
│
└─ ObservationEscalated
   └─ When: Severity increased (e.g., alert → incident → critical)
   └─ Payload: {observation_id, old_severity, new_severity}

INVESTIGATION EVENTS:
├─ InvestigationStarted
│  └─ When: Investigation capability begins
│  └─ Payload: InvestigationRequest
│
├─ EvidenceCollected
│  └─ When: New evidence gathered
│  └─ Payload: Evidence contract
│
├─ FindingGenerated
│  └─ When: Evidence interpreted
│  └─ Payload: Finding contract
│
├─ KnowledgeGapDetected
│  └─ When: Investigation finds unknown
│  └─ Payload: {investigation_id, gap_description, gap_type}
│
└─ InvestigationFinished
   └─ When: Investigation converges or max cycles reached
   └─ Payload: Investigation Result contract

PREDICTION EVENTS:
├─ PredictionStarted
│  └─ When: Prediction capability begins
│  └─ Payload: PredictionRequest
│
├─ AnomalyDetected
│  └─ When: Anomaly threshold crossed
│  └─ Payload: {metric, device, current_value, expected_range, deviation}
│
├─ FailureForecast
│  └─ When: Failure probability exceeds threshold
│  └─ Payload: {metric, device, failure_probability, time_to_failure}
│
└─ PredictionFinished
   └─ When: Prediction completes
   └─ Payload: Prediction Result contract

DECISION EVENTS:
├─ DecisionStarted
│  └─ When: Decision capability begins
│  └─ Payload: DecisionRequest
│
├─ OptionAnalyzed
│  └─ When: Each option evaluated
│  └─ Payload: {option, success_probability, risk_level, analysis}
│
├─ ConflictDetected
│  └─ When: Recommendations conflict (prediction vs investigation)
│  └─ Payload: {option_a, option_b, conflict_reason}
│
├─ ApprovalRequested
│  └─ When: Decision needs approval
│  └─ Payload: {decision_id, approval_required_from, reason}
│
└─ DecisionFinished
   └─ When: Decision capability completes
   └─ Payload: Decision contract

SIMULATION EVENTS:
├─ SimulationStarted
│  └─ When: Digital Twin simulation begins
│  └─ Payload: SimulationRequest
│
├─ SimulationCheckpoint
│  └─ When: Periodic checkpoint during simulation
│  └─ Payload: {checkpoint_id, simulated_time, metrics_at_checkpoint}
│
└─ SimulationFinished
   └─ When: Digital Twin simulation completes
   └─ Payload: SimulationResult contract

EXECUTION EVENTS:
├─ ExecutionPlanGenerated
│  └─ When: Automation capability generates plan
│  └─ Payload: ExecutionPlan contract
│
├─ ExecutionStarted
│  └─ When: Automation begins executing changes
│  └─ Payload: {execution_id, decision_id, start_time}
│
├─ StepCompleted
│  └─ When: Each automation step completes
│  └─ Payload: {execution_id, step_id, status, actual_time}
│
├─ RollbackTriggered
│  └─ When: Automation detects failure, initiates rollback
│  └─ Payload: {execution_id, trigger_reason, rollback_step}
│
├─ ExecutionValidated
│  └─ When: Post-execution validation passes
│  └─ Payload: {execution_id, validation_results}
│
└─ ExecutionFinished
   └─ When: Automation completes (success or rollback)
   └─ Payload: {execution_id, outcome, actual_mttr, actual_downtime}

LEARNING EVENTS:
├─ OutcomeCaptured
│  └─ When: Actual outcome measured (success/failure)
│  └─ Payload: LearningEvent contract
│
├─ PatternRecognized
│  └─ When: New pattern detected in data
│  └─ Payload: {pattern_name, confidence, frequency, success_rate}
│
├─ RuleProposed
│  └─ When: New rule generated from learning
│  └─ Payload: {rule_name, conditions, actions, confidence}
│
└─ ThresholdAdjusted
   └─ When: Learning updates decision threshold
   └─ Payload: {threshold_name, old_value, new_value, reason}

ERROR EVENTS:
├─ CapabilityFailed
│  └─ When: Capability execution fails
│  └─ Payload: {capability_id, error, stack_trace}
│
├─ TimeoutOccurred
│  └─ When: Capability exceeds time budget
│  └─ Payload: {capability_id, time_budget, time_used}
│
└─ ResourceExhausted
   └─ When: Resource quota exceeded
   └─ Payload: {capability_id, resource_type, quota, usage}
```

### 2.2 Event Bus Architecture

```
Event Bus (Pub/Sub)
│
├─ Publishers (Capabilities that emit events)
│  ├─ Investigation publishes: EvidenceCollected, FindingGenerated, InvestigationFinished
│  ├─ Prediction publishes: AnomalyDetected, FailureForecast, PredictionFinished
│  ├─ Decision publishes: OptionAnalyzed, DecisionFinished
│  ├─ Automation publishes: StepCompleted, ExecutionFinished
│  └─ Learning publishes: PatternRecognized, RuleProposed
│
└─ Subscribers (Capabilities that consume events)
   ├─ Runtime subscribes to: All events (orchestration)
   ├─ Decision subscribes to: InvestigationFinished, PredictionFinished
   ├─ Automation subscribes to: DecisionFinished, SimulationFinished
   ├─ Learning subscribes to: ExecutionFinished, OutcomeCaptured
   └─ Monitoring subscribes to: All events (metrics, alerting)

Event Processing:
├─ Synchronous: Decision waits for Investigation to finish before starting
├─ Asynchronous: Learning processes outcomes in background
├─ Conditional: If AnomalyDetected and confidence > 0.8, trigger Investigation
└─ Speculative: Run multiple Predictions in parallel, use best result
```

---

## PRIMITIVE #3: CAPABILITY LIFECYCLE

**Definition:** States every capability progresses through.

```
┌──────────────┐
│   CREATED    │ (Capability registered in registry)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ INITIALIZING │ (Loading resources, connecting to services)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│    READY     │ (Waiting for invocation)
└──────┬───────┘
       │
       ├─────────────────────────────────────┐
       │                                     │
       ▼                                     ▼
┌──────────────┐                    ┌──────────────┐
│  EXECUTING   │◄───────────────────│  SUSPENDED   │
│              │    (pause/resume)  │              │
└──────┬───────┘                    └──────────────┘
       │
       ├─────────────┬───────────────┐
       │             │               │
       ▼             ▼               ▼
┌───────────┐  ┌──────────┐  ┌─────────────┐
│ COMPLETED │  │ FAILED   │  │ TERMINATED  │
└───────────┘  └─────┬────┘  └─────────────┘
                     │
                     ▼
                ┌──────────┐
                │ RETRYING │
                └─────┬────┘
                      │
                      └──────────────┬─────────┐
                                     │         │
                                     ▼         ▼
                              ┌───────────┐  ┌──────────┐
                              │ COMPLETED │  │ FAILED   │
                              └───────────┘  └──────────┘

STATE TRANSITIONS:

CREATED → INITIALIZING
  Action: Load config, connect to services
  Timeout: 30 seconds
  Error: → FAILED

INITIALIZING → READY
  Action: Health check passes
  Success: Capability ready for requests

READY → EXECUTING
  Action: Request received, start processing
  Precondition: Request validates against input schema

EXECUTING → COMPLETED
  Action: Output generated, response sent
  Postcondition: Response validates against output schema

EXECUTING → FAILED
  Action: Error occurred during execution
  Recovery: Capability logs error, notifies runtime

EXECUTING → SUSPENDED
  Action: Runtime suspends capability (resource constraint, priority change)
  Recovery: Resume when resources available

SUSPENDED → EXECUTING
  Action: Runtime resumes capability
  State: Resume from checkpoint (if supported)

EXECUTING → RETRYING (on failure)
  Action: Runtime initiates retry
  Precondition: Max retries not exceeded, error is retriable
  Backoff: Exponential (1s, 2s, 4s, 8s, 16s)

RETRYING → EXECUTING
  Action: Retry attempt starts

FAILED → TERMINATED
  Action: Max retries exceeded, cleanup resources

EXECUTING/COMPLETED/FAILED → TERMINATED
  Action: Runtime terminates capability (shutdown, replacement, error recovery)

READY → TERMINATED
  Action: Runtime terminates idle capability (resource cleanup)
```

**Lifecycle Events Published:**

```
CapabilityLifecycleEvent
{
  capability_id: UUID
  from_state: enum[...]
  to_state: enum[...]
  timestamp: ISO8601
  reason: string (why transition?)
  metadata: {request_id, resource_used, time_spent}
}
```

---

## PRIMITIVE #4: SCHEDULING MODEL

**Definition:** How runtime decides execution order and parallelization.

### 4.1 Execution Modes

```
SEQUENTIAL
├─ Each capability waits for previous to complete
├─ Example: Investigation → Decision → Automation
├─ Latency: Sum of all capabilities
├─ Use case: When output of one is input to next
└─ Complexity: Low

PARALLEL
├─ Multiple capabilities execute simultaneously
├─ Example: Run Prediction and Investigation in parallel
├─ Latency: Max of all capabilities
├─ Use case: Independent analysis
├─ Complexity: Medium (need to merge results)

CONDITIONAL
├─ Execute capability only if condition true
├─ Example: If Investigation confidence < 60%, run external Knowledge
├─ Latency: Depends on branch taken
├─ Use case: Adaptive investigation
└─ Complexity: Medium (branch management)

SPECULATIVE
├─ Execute multiple capabilities, use best result
├─ Example: Run 3 different Prediction models, select highest confidence
├─ Latency: Max of all branches
├─ Use case: Maximize accuracy
└─ Complexity: High (merge multiple results)

PRIORITY-BASED
├─ High-priority capabilities execute first
├─ Example: P1 Investigation before P3 Prediction
├─ Latency: Depends on priority and resources
├─ Use case: SLA compliance
└─ Complexity: High (priority arbitration)

GOAL-DRIVEN
├─ Execute capabilities needed to achieve goal
├─ Example: Goal="Restore Payment Gateway" → select needed capabilities
├─ Latency: Depends on goal complexity
├─ Use case: Intent-based execution
└─ Complexity: Very high (goal decomposition)
```

### 4.2 Scheduler

```
Scheduler (Runtime component)
├─ Input: Goal or Workflow request
├─ Process:
│  ├─ Determine needed capabilities
│  ├─ Analyze dependencies
│  ├─ Determine execution mode (sequential/parallel/conditional)
│  ├─ Allocate resources
│  ├─ Set time budgets
│  ├─ Assign priorities
│  └─ Generate execution plan
│
└─ Output: Execution schedule with:
   ├─ Capability sequence
   ├─ Parallel groups
   ├─ Conditional branches
   ├─ Time budgets
   ├─ Resource allocations
   └─ Fallback plans

Example Schedule:
1. Parallel Group (t=0-5s):
   ├─ Investigation (budget: 5s)
   └─ Prediction (budget: 5s)
2. Sequential (t=5-10s):
   ├─ Decision (depends: Investigation, Prediction) (budget: 5s)
3. Conditional (t=10-15s):
   ├─ If Decision.success_probability < 80%:
   │  └─ Run Knowledge capability (budget: 5s)
   └─ Else: Skip Knowledge
4. Sequential (t=15+s):
   └─ Simulation (depends: Decision) (budget: varies)
5. Sequential (t=?+s):
   └─ Automation (depends: Simulation) (budget: varies)
```

---

## PRIMITIVE #5: GOAL MODEL

**Definition:** System executes goals, not workflows. Capabilities are tools to achieve goals.

### 5.1 Goal Types

```
GOAL
├─ Goal ID: UUID
├─ Goal Statement: string (natural language)
├─ Goal Type: enum[
│    restore_service,
│    prevent_outage,
│    optimize_performance,
│    reduce_cost,
│    ensure_compliance
│  ]
├─ Priority: enum[critical, high, medium, low]
├─ Business Impact: {revenue_at_risk, users_affected, sla_breach_time}
├─ Time Constraint: int (seconds to achieve goal)
├─ Resource Constraint: {cpu, memory, api_budget, llm_budget}
├─ Constraints: [string] (what we can't do)
│  ├─ Cannot touch production
│  ├─ Must maintain <100ms latency
│  ├─ Cannot exceed change window
│  └─ Must comply with security policy
└─ Success Criteria: [string]
   ├─ Payment gateway latency < 50ms
   ├─ Error rate < 0.1%
   ├─ Customer satisfaction > 90%
   └─ No SLA breach
```

### 5.2 Goal Decomposition

```
Goal: "Restore Payment Gateway"
     ↓
Query Capability Registry: Which capabilities help achieve this goal?
     ↓
Identify Subgoals:
├─ Understand Current State (Investigation)
├─ Predict Impact (Prediction)
├─ Decide Best Action (Decision)
├─ Validate Solution (Simulation)
└─ Execute Safely (Automation)
     ↓
Generate Execution Plan:
├─ Investigation (find root cause)
├─ Prediction (will it get worse?)
├─ Simulation (will proposed fix work?)
├─ Decision (recommend best fix)
├─ Automation (execute with validation)
     ↓
Execute Plan:
└─ Each capability works toward goal
     ↓
Monitor Progress:
└─ Is payment gateway latency improving?
     ↓
Adapt If Needed:
├─ If not improving, select different approach
└─ Replan if constraints violated
     ↓
Goal Achieved:
└─ Payment gateway restored, latency normal
```

### 5.3 Goal vs Workflow

```
WORKFLOW (Old Model):
├─ Runtime: "Run Investigation, then Decision, then Automation"
├─ If Investigation doesn't find root cause:
│  └─ Runtime doesn't know what to do (hardcoded workflow ends)
└─ Problem: Inflexible

GOAL (New Model):
├─ Runtime: "Achieve goal: Restore Payment Gateway"
├─ Runtime queries: "What capabilities help achieve this?"
├─ If Investigation doesn't converge:
│  └─ Runtime adaptively selects: "Run external Knowledge"
├─ If Decision is risky:
│  └─ Runtime adaptively selects: "Run Simulation first"
└─ Advantage: Flexible, adaptive, self-correcting
```

---

## PRIMITIVE #6: RESOURCE MANAGEMENT

**Definition:** Runtime manages shared resources, not individual capabilities.

### 6.1 Resource Types

```
MEMORY
├─ Total budget: X GB
├─ Per-capability quota: Y MB (adjustable based on priority)
├─ Tracking: Memory used by each capability at each step
├─ Limits: Capability terminated if quota exceeded
└─ Allocation: Priority-based (P1 > P3)

COMPUTATION
├─ Total budget: N concurrent investigations
├─ Per-capability: 1-N slots
├─ Tracking: Active capabilities, queue depth
├─ Limits: Queue if all slots full
└─ Allocation: Priority queue

LLM API BUDGET
├─ Total budget: $X/hour
├─ Per-capability quota: $Y
├─ Tracking: $ spent on each LLM call
├─ Limits: Stop LLM calls if quota exceeded
└─ Fallback: Use non-LLM methods if budget limited

EXTERNAL API BUDGET
├─ RAG calls: X/hour
├─ MCP calls: Y/hour
├─ Web search: Z/hour
├─ Device SSH: A/hour (connection slots)
├─ Tracking: Call count per API
├─ Limits: Queue or drop if quota exceeded
└─ Allocation: Priority-based

DATA CACHE
├─ Size: Z MB
├─ Per-item: TTL (time to live)
├─ Tracking: Cache hit/miss rate
├─ Eviction: LRU (least recently used)
└─ Namespace: By device, metric, domain

TIME BUDGET
├─ Per-goal: X seconds
├─ Per-capability: Y seconds (Scheduler allocates from total)
├─ Tracking: Elapsed time vs budget
├─ Overtime: Timeout if exceeded
└─ Early exit: Stop if goal achieved early
```

### 6.2 Resource Manager (Runtime Component)

```
Resource Manager
├─ Monitor: Current resource usage by all capabilities
├─ Allocate: Resources to new requests (priority queue)
├─ Enforce: Limits (terminate, queue, or fail)
├─ Optimize: Reallocate if new request is higher priority
├─ Recover: Cleanup on capability failure
└─ Report: Resource utilization metrics
```

**Example:**

```
Situation: 1000 concurrent observations
├─ Investigation budget: 50 concurrent slots
├─ LLM budget: $100/hour (currently at $80/hour)
└─ Memory: 80% used
     ↓
New P1 Critical observation arrives
├─ Resource Manager checks quota
├─ Finds: Can start Investigation (49/50 slots) but LLM budget tight
├─ Action:
│  ├─ Allocate Investigation slot
│  ├─ Limit LLM calls to 5 per capability (was 10)
│  ├─ Increase Investigation priority (queue other lower-priority tasks)
│  └─ Log: Resource constraint detected
└─ Result: P1 investigation starts, lower-priority P3 predictions queued
```

---

## PRIMITIVE #7: CONFLICT RESOLUTION

**Definition:** When capabilities recommend conflicting actions, runtime arbitrates.

### 7.1 Conflict Types

```
TECHNICAL CONFLICT
├─ Investigation says: "MTU mismatch"
├─ Prediction says: "Interface will fail in 2 hours"
├─ Conflict: Different root causes proposed
├─ Resolution: Merge findings (both true: MTU mismatch will cause failure)

BUSINESS CONFLICT
├─ Decision says: "Fix now (success 95%)"
├─ Business says: "Wait until maintenance window"
├─ Conflict: Technical vs business priority
├─ Resolution: Follow business constraint (business wins)

RISK CONFLICT
├─ Decision A says: "Replace interface (95% success, 5% downtime risk)"
├─ Decision B says: "Reroute traffic (60% success, 0% downtime risk)"
├─ Conflict: High success vs low risk
├─ Resolution: Ask: Is downtime acceptable? If yes, try A first with B as fallback

SAFETY CONFLICT
├─ Automation proposes: "Execute change"
├─ Safety checks say: "Rollback not validated"
├─ Conflict: Can't execute safely
├─ Resolution: Block execution, require simulation first

RESOURCE CONFLICT
├─ Goal A needs: 20 GB memory, 100 LLM calls, 30 seconds
├─ Goal B needs: 30 GB memory, 50 LLM calls, 20 seconds
├─ Available: 40 GB memory, 100 LLM calls/hour budget
├─ Conflict: Can't do both simultaneously
├─ Resolution: Queue Goal B, start Goal A
```

### 7.2 Conflict Arbiter (Runtime Component)

```
Conflict Arbiter
├─ Detect: Identify when capabilities recommend conflicting actions
├─ Analyze:
│  ├─ What's the priority of each conflict?
│  ├─ Can we merge recommendations?
│  ├─ Do business constraints override?
│  ├─ Do safety constraints block?
│  └─ Can we sequence instead of conflict?
│
├─ Resolve using rules:
│  ├─ Safety > Risk > Speed > Cost
│  ├─ Business constraint > Technical constraint
│  ├─ P1 > P3 priority
│  ├─ Proven solution > Experimental
│  └─ Manual approval > Automated for conflicts
│
└─ Execute: Apply resolution, document decision
```

---

## PRIMITIVE #8: STATE MANAGEMENT

**Definition:** Persist and recover capability state.

### 8.1 State Types

```
EXECUTION STATE
├─ What capability is executing?
├─ What step is it on?
├─ What's the progress (% complete)?
├─ How much time spent?
├─ What resources allocated?
└─ Use: Resume on interrupt, monitor, show progress

CAPABILITY STATE
├─ What's the result so far?
├─ What evidence collected?
├─ What hypotheses are current?
├─ What confidence level?
└─ Use: Resume investigation if interrupted

GOAL STATE
├─ What goal are we executing?
├─ What subgoals completed?
├─ What subgoals pending?
├─ Overall progress?
└─ Use: Multi-hour goals, know where we are if interrupted

RESOURCE STATE
├─ Memory used by each capability
├─ API calls made
├─ Cached data
├─ Budget remaining
└─ Use: Resource management, enforce limits

LEARNING STATE
├─ What patterns learned?
├─ What rules generated?
├─ What thresholds adjusted?
├─ What confidence in updates?
└─ Use: Don't repeat learning, persist improvements
```

### 8.2 State Manager (Runtime Component)

```
State Manager
├─ Checkpoint: Save state after each capability completes
│  ├─ Interval: Every 30 seconds or after major event
│  ├─ Storage: Persistent database (not memory)
│  └─ Cleanup: Old checkpoints after 30 days
│
├─ Recover: Resume from checkpoint if failure
│  ├─ Trigger: Capability crash, timeout, resource exhaustion
│  ├─ Action: Restart capability from last checkpoint
│  └─ Retry: Up to 3 times with exponential backoff
│
├─ Compact: Merge sequential states
│  ├─ Example: Investigation step 1, 2, 3 → Investigation result
│  └─ Purpose: Reduce storage
│
└─ Archive: Move old state to cold storage
   ├─ After 90 days of inactivity
   └─ Keep for audit/learning for 1 year
```

---

## PRIMITIVE #9: CAPABILITY REGISTRY

**Definition:** Dynamic discovery of capabilities, not hardcoded.

### 9.1 Registry Structure

```
Capability Registry
│
├─ Capability ID: UUID
├─ Name: string (investigation, prediction, automation, etc)
├─ Version: semantic versioning (1.2.3)
├─ Status: enum[active, deprecated, beta, disabled]
│
├─ Contract (Metadata):
│  ├─ Input Schema: JSON Schema for InvestigationRequest
│  ├─ Output Schema: JSON Schema for Investigation Result
│  ├─ Error Schema: Possible errors and how to handle
│  └─ Events Published: [event types]
│
├─ Capability:
│  ├─ Vendor: string (internal, cisco, juniper, aws, etc)
│  ├─ Domain: enum[enterprise, sp, telecom, industrial]
│  ├─ Supported Technologies: [ospf, bgp, 5g, etc]
│  ├─ Supported Vendors: [cisco, juniper, arista, etc]
│  └─ Confidence: float[0-1] (how reliable is this capability?)
│
├─ Performance:
│  ├─ Average Latency: milliseconds
│  ├─ P95 Latency: milliseconds
│  ├─ Success Rate: float[0-1]
│  ├─ Failure Rate: float[0-1]
│  ├─ Timeout Rate: float[0-1]
│  └─ Avg Cost: $ per invocation
│
├─ Dependencies:
│  ├─ Requires: [other capability IDs]
│  ├─ Must Run After: [other capability IDs]
│  ├─ Conflicts With: [other capability IDs]
│  └─ Optional Dependencies: [other capability IDs]
│
├─ Capabilities:
│  ├─ Supports Parallel Execution: bool
│  ├─ Supports Suspension/Resume: bool
│  ├─ Supports Interruption: bool
│  ├─ Supports Timeouts: bool
│  ├─ Is Idempotent: bool
│  └─ Can Retry: bool
│
├─ Resource Requirements:
│  ├─ Memory: MB
│  ├─ CPU: cores
│  ├─ API Calls: count
│  └─ Time: seconds
│
├─ SLA:
│  ├─ Uptime: float[0-1] (99.9%)
│  ├─ Response Time: milliseconds
│  └─ Availability: timewindows when available
│
└─ Metadata:
   ├─ Documentation URL
   ├─ Source Code URL
   ├─ Owner Contact
   ├─ Support Level
   └─ Custom metadata: dict
```

### 9.2 Registry Usage

```
Runtime starts:
├─ Query Registry: Get all active capabilities
├─ Load Contracts: Know input/output schema for each
├─ Check Dependencies: Validate capability graph
└─ Monitor Health: Track availability
     ↓
User submits goal:
├─ Runtime queries Registry: Which capabilities help achieve this goal?
├─ Example: Goal="Restore Payment Gateway"
│  └─ Registry returns:
│     ├─ Investigation (restore → find root cause)
│     ├─ Prediction (restore → forecast if worsening)
│     ├─ Decision (restore → recommend fix)
│     ├─ Simulation (restore → validate fix)
│     └─ Automation (restore → execute fix)
├─ Runtime selects capabilities based on:
│  ├─ Success rate
│  ├─ Latency
│  ├─ Cost
│  ├─ Dependencies
│  └─ Resource availability
└─ Execute selected plan
     ↓
New capability released:
├─ Register in Registry
├─ Version: 2.0.0
├─ Status: beta
├─ Runtime discovers it
├─ Starts testing it
├─ If good: Promote to active
└─ No code change needed (capabilities are plugins!)
```

---

## PRIMITIVE #10: OPERATING SYSTEM SERVICES

**Definition:** Common services provided by runtime to all capabilities.

### 10.1 Service Catalog

```
LOGGING SERVICE
├─ Structured logging (JSON, not text)
├─ Log levels: DEBUG, INFO, WARN, ERROR, CRITICAL
├─ Automatic fields: timestamp, capability_id, request_id, correlation_id
├─ Retention: Configurable (default 30 days)
├─ Search: Query logs by any field
└─ Usage: All capabilities call logger.info(), logger.error(), etc

CACHING SERVICE
├─ Cache device config (TTL: 1 hour)
├─ Cache topology (TTL: 1 hour)
├─ Cache telemetry (TTL: 5 minutes)
├─ Cache telemetry baseline (TTL: 24 hours)
├─ Manual invalidation: On config change
├─ Hit rate: Monitor and optimize
└─ Usage: Capabilities query cache before device SSH

AUTHENTICATION SERVICE
├─ Device credentials: Encrypted vault
├─ API tokens: Encrypted vault, auto-rotation
├─ Mutual TLS: For secure capabilities
├─ Audit: Log all credential access
└─ Usage: Capabilities request credentials from Runtime

AUTHORIZATION SERVICE
├─ Role-based access: RBAC
├─ Attribute-based access: ABAC
├─ Policies: What can each capability do?
├─ Audit: Log authorization decisions
└─ Usage: Capabilities check if allowed before executing change

SECRETS SERVICE
├─ Store API keys, passwords, certificates
├─ Encryption at rest
├─ Encryption in transit
├─ Auto-rotation
├─ Audit all access
└─ Usage: Capabilities request secrets from Runtime

METRICS SERVICE
├─ Emit metrics: Latency, success rate, error rate
├─ Cardinality: By capability, by device, by domain
├─ Aggregation: 1min, 5min, 1hour, 24hour
├─ Retention: Configurable (default 1 year)
├─ Alerting: On threshold breach
└─ Usage: Capabilities emit metrics to Runtime

TRACING SERVICE
├─ Distributed tracing: Correlation IDs
├─ Span creation: For each step
├─ Timing: Duration of each operation
├─ Causality: Parent-child relationships
├─ Export: To tracing backend (Jaeger, Datadog)
└─ Usage: Capabilities create spans via Runtime

CONFIGURATION SERVICE
├─ Store platform config
├─ Store capability-specific config
├─ Hot reload: Update without restart
├─ Versioning: Track config changes
├─ Rollback: Revert to previous config
└─ Usage: Capabilities read config from Runtime

RETRY SERVICE
├─ Exponential backoff: 1s, 2s, 4s, 8s, 16s
├─ Max retries: Configurable per capability
├─ Retriable errors: Define which errors to retry
├─ Dead letter queue: Persistent storage for permanent failures
└─ Usage: Runtime auto-retries on error (no capability code needed)

TIMEOUT SERVICE
├─ Per-capability timeouts
├─ Escalating timeouts: First timeout = cancel task, second = kill process
├─ Graceful shutdown: Send signal before killing
├─ Cleanup: Release resources
└─ Usage: Runtime enforces timeouts (no capability code needed)

CIRCUIT BREAKER SERVICE
├─ Per-capability circuit breaker
├─ States: Closed (normal) → Open (failing) → Half-Open (testing)
├─ Threshold: N failures in M seconds = Open circuit
├─ Recovery: Try again after cooldown
└─ Usage: Runtime manages circuit breaker (no capability code needed)

STATE STORE SERVICE
├─ Persist capability state
├─ Checkpoint: After each major step
├─ Recovery: On failure, resume from checkpoint
├─ Cleanup: Old state after 30 days
└─ Usage: Capabilities call statestore.save(), statestore.restore()

OBSERVABILITY SERVICE
├─ Health checks: Is each capability healthy?
├─ Dependency health: Can capability reach its dependencies?
├─ Resource health: Memory, CPU, disk usage
├─ Alerts: On health degradation
└─ Usage: Runtime runs health checks periodically

EVENT SERVICE
├─ Publish events: Capabilities publish InvestigationFinished, etc
├─ Subscribe to events: Capabilities subscribe to events
├─ Ordering: Events in order (per capability)
├─ Delivery: At-least-once (may process twice)
└─ Usage: All capabilities use event bus for communication

RATE LIMITING SERVICE
├─ Rate limit by capability
├─ Rate limit by source (device, user)
├─ Rate limit by domain
├─ Backpressure: Queue if limit exceeded
└─ Usage: Runtime enforces rate limits (no capability code needed)

QUOTA SERVICE
├─ Memory quota per capability
├─ LLM API quota (total cost)
├─ External API quota (calls/hour)
├─ Time quota (per goal)
├─ Enforcement: Terminate if exceeded
└─ Usage: Resource Manager enforces quotas
```

### 10.2 System Call Interface

```
All capabilities access OS services via Runtime:

// Logging
logger = runtime.get_logger("capability_name")
logger.info("Starting investigation")
logger.error("Failed to connect to device", extra={error_code: 123})

// Caching
cached_config = runtime.cache.get("device:R1:config")
if not cached_config:
  config = device.get_config()
  runtime.cache.set("device:R1:config", config, ttl_seconds=3600)

// Credentials
creds = runtime.secrets.get_credentials("cisco_device_r1")
ssh_connection = device.connect(host="192.168.1.1", **creds)

// Metrics
runtime.metrics.record_latency("investigation_latency_ms", latency_ms)
runtime.metrics.record_counter("evidence_collected", count=5)

// Tracing
with runtime.tracing.span("collect_evidence") as span:
  span.set_attribute("device", "R1")
  span.set_attribute("count", 5)
  # Do work

// Configuration
config = runtime.config.get("investigation.max_cycles", default=5)

// State Store
checkpoint = {
  "cycle": 3,
  "findings": [...],
  "confidence": 0.75
}
runtime.statestore.save("investigation_123", checkpoint)

// Events
runtime.events.publish("InvestigationFinished", {
  investigation_id: "inv_123",
  root_cause: "MTU mismatch",
  confidence: 0.94
})

// Subscribe to events
runtime.events.subscribe("EvidenceCollected", on_evidence_collected_handler)

def on_evidence_collected_handler(event):
  # Handle new evidence

// Raise alert
runtime.alerts.raise("investigation_slow", 
  severity="warning",
  message="Investigation taking longer than expected",
  context={"investigation_id": "inv_123"}
)
```

---

## THE COMPLETE OPERATING SYSTEM ARCHITECTURE

```
┌────────────────────────────────────────────────────────────────┐
│ APPLICATIONS / USERS                                           │
│ (Operators, APIs, Integrations)                               │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│ GOAL INTERFACE                                                 │
│ (User specifies intent, not workflow)                         │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│ AUTONOMOUS INTELLIGENCE RUNTIME (OS KERNEL)                   │
│                                                                │
│ ┌────────────────────────────────────────────────────────┐    │
│ │ Core Services                                          │    │
│ │ ├─ Intent Parser → Capability Planner                │    │
│ │ ├─ Scheduler (sequential, parallel, conditional)     │    │
│ │ ├─ Execution Engine (invoke capabilities)            │    │
│ │ ├─ Result Synthesizer (merge outputs)                │    │
│ │ ├─ Conflict Arbiter (resolve contradictions)         │    │
│ │ ├─ Resource Manager (memory, API, compute quotas)   │    │
│ │ └─ Learning Coordinator (capture outcomes)           │    │
│ └────────────────────────────────────────────────────────┘    │
│                                                                │
│ ┌────────────────────────────────────────────────────────┐    │
│ │ Operating System Services (Available to all)          │    │
│ │ ├─ Logging, Caching, Auth, Secrets                   │    │
│ │ ├─ Metrics, Tracing, Configuration                  │    │
│ │ ├─ Retry, Timeout, Circuit Breaker                  │    │
│ │ ├─ State Store, Events, Rate Limiting               │    │
│ │ └─ Health, Observability, Quota                     │    │
│ └────────────────────────────────────────────────────────┘    │
│                                                                │
│ ┌────────────────────────────────────────────────────────┐    │
│ │ System Registries                                      │    │
│ │ ├─ Capability Registry (discovery)                   │    │
│ │ ├─ Contract Registry (input/output schemas)          │    │
│ │ └─ Event Registry (event types)                      │    │
│ └────────────────────────────────────────────────────────┘    │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│ CAPABILITY LAYER (All exchange contracts, not objects)        │
│                                                                │
│ ├─ Investigation Capability                                  │
│ │  ├─ Input: InvestigationRequest                          │
│ │  └─ Output: Investigation Result                         │
│ │     └─ Publishes: EvidenceCollected, FindingGenerated... │
│ │                                                            │
│ ├─ Prediction Capability                                    │
│ │  ├─ Input: PredictionRequest                             │
│ │  └─ Output: Prediction Result                            │
│ │     └─ Publishes: AnomalyDetected, FailureForecast...   │
│ │                                                            │
│ ├─ Decision Capability                                      │
│ │  ├─ Input: DecisionRequest                               │
│ │  └─ Output: Decision                                      │
│ │     └─ Publishes: DecisionFinished                       │
│ │                                                            │
│ ├─ Simulation Capability                                    │
│ │  ├─ Input: SimulationRequest                             │
│ │  └─ Output: SimulationResult                             │
│ │     └─ Publishes: SimulationFinished                    │
│ │                                                            │
│ ├─ Automation Capability                                    │
│ │  ├─ Input: AutomationRequest                             │
│ │  └─ Output: ExecutionResult                              │
│ │     └─ Publishes: StepCompleted, ExecutionFinished...   │
│ │                                                            │
│ ├─ Learning Capability                                      │
│ │  ├─ Input: LearningEvent                                 │
│ │  └─ Output: LearningResult                               │
│ │     └─ Publishes: PatternRecognized, RuleProposed...    │
│ │                                                            │
│ └─ [More capabilities via plugins, same interface]         │
│                                                                │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│ UNIFIED DATA PLATFORM (Single source of truth)               │
│                                                                │
│ ├─ Configuration Data       ├─ Knowledge Data               │
│ ├─ State Data              ├─ Business Data                │
│ ├─ Telemetry Data          ├─ Trust Data                   │
│ ├─ Event Data              ├─ Experience Data              │
│ ├─ Inventory Data          └─ Plugin Metadata              │
│ └─ Topology Data                                            │
│    Dependency Data                                           │
│                                                                │
└────────────────────────────────┬───────────────────────────────┘
                                 │
┌────────────────────────────────▼───────────────────────────────┐
│ CONNECTORS (To external systems)                             │
│                                                                │
│ ├─ Device Connectors         ├─ Cloud Connectors            │
│ │  ├─ SSH/CLI                │  ├─ AWS API                 │
│ │  ├─ SNMP                   │  ├─ Azure API               │
│ │  ├─ Netconf                │  └─ GCP API                 │
│ │  └─ APIs                   │                              │
│ │                             ├─ Telecom Connectors        │
│ ├─ Vendor Connectors          │  ├─ 5G APIs               │
│ │  ├─ Cisco                  │  └─ Telecom OSS APIs       │
│ │  ├─ Juniper                │                              │
│ │  ├─ Arista                 ├─ Knowledge Connectors      │
│ │  ├─ Nokia                  │  ├─ RAG Engine             │
│ │  └─ Others                 │  ├─ MCP Server             │
│ │                             │  └─ Web Search             │
│ ├─ Telemetry Connectors       │                              │
│ │  ├─ SNMP                   ├─ Business Connectors       │
│ │  ├─ Streaming Telemetry    │  ├─ CMDB (asset database)  │
│ │  ├─ Logs/Syslog            │  ├─ Billing System         │
│ │  ├─ Metrics Feeds          │  ├─ SLA System             │
│ │  └─ Flow Data              │  └─ Ticketing System       │
│ │                                                            │
│ └─ [Extensible via plugins]                                │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## THE 10 OPERATING SYSTEM PRIMITIVES

```
1. CONTRACTS
   ├─ Define data flowing between capabilities
   ├─ Request contracts (InvestigationRequest, PredictionRequest)
   ├─ Response contracts (Finding, Investigation Result)
   └─ Never exchange objects, always contracts

2. EVENTS
   ├─ Publish-subscribe event bus
   ├─ Capabilities publish events (InvestigationFinished)
   ├─ Capabilities subscribe to events
   └─ Runtime coordinates via events

3. CAPABILITY LIFECYCLE
   ├─ States: Created → Initializing → Ready → Executing → Completed/Failed/Suspended
   ├─ Transitions: Define state machine
   └─ Runtime manages transitions

4. SCHEDULING
   ├─ Execution modes: Sequential, Parallel, Conditional, Speculative, Priority, Goal-driven
   ├─ Scheduler decides order and parallelization
   └─ Capabilities don't call each other

5. GOALS
   ├─ System executes goals, not workflows
   ├─ Goal decomposition into subgoals
   ├─ Adaptive execution based on progress
   └─ Capabilities are tools to achieve goals

6. RESOURCE MANAGEMENT
   ├─ Memory, computation, LLM, API, time quotas
   ├─ Resource Manager allocates and enforces
   ├─ Priority-based allocation
   └─ Capabilities don't manage resources

7. CONFLICT RESOLUTION
   ├─ Detect contradicting recommendations
   ├─ Arbiter resolves conflicts
   ├─ Rules: Safety > Risk > Speed > Cost
   └─ Business constraints override technical

8. STATE MANAGEMENT
   ├─ Checkpoint execution state
   ├─ Recover from failures
   ├─ Persist capability state
   └─ Runtime manages state lifecycle

9. CAPABILITY REGISTRY
   ├─ Dynamic discovery of capabilities
   ├─ Metadata: Input/output contracts, dependencies, performance
   ├─ Not hardcoded
   └─ Plugins register at startup

10. OPERATING SYSTEM SERVICES
    ├─ Logging, Caching, Auth, Secrets
    ├─ Metrics, Tracing, Configuration
    ├─ Retry, Timeout, Circuit Breaker
    ├─ State Store, Events, Rate Limiting
    └─ All provided by Runtime (no capability code needed)
```

---

## WHAT THIS ENABLES

**Before (Collection of Services):**
```
Investigation calls Knowledge
Knowledge calls LLM
Planner calls Investigation
No contracts → tight coupling
No registry → hardcoded
No events → polling
No resource management → resource contention
No conflict resolution → undefined behavior
```

**After (True Operating System):**
```
Investigation publishes InvestigationFinished
Planner subscribes to InvestigationFinished
Planner requests Decision capability from Registry
Decision receives DecisionRequest contract
Decision publishes DecisionFinished
Automation subscribes to DecisionFinished
No coupling → replaceable components
Registry-based → plugin architecture
Event-driven → reactive
Resource managed → fair allocation
Conflicts arbitrated → deterministic
```

---

## IMPLEMENTATION GATES

**Do NOT implement any capability until these primitives are defined and approved:**

### Gate 1: Contract Design ✅ Required
- [ ] All request contracts defined (JSON Schema)
- [ ] All response contracts defined (JSON Schema)
- [ ] Version compatibility strategy
- [ ] Schema evolution rules

### Gate 2: Event Model ✅ Required
- [ ] All event types defined
- [ ] Event ordering guarantees
- [ ] Retry semantics (at-least-once vs at-most-once)
- [ ] Dead letter queue behavior

### Gate 3: Runtime Services ✅ Required
- [ ] Logging interface specification
- [ ] Caching interface specification
- [ ] State store interface specification
- [ ] Event bus interface specification
- [ ] All 10 OS services specified

### Gate 4: Capability Interface ✅ Required
- [ ] Standard interface all capabilities implement
- [ ] Lifecycle hooks
- [ ] Metadata requirements
- [ ] Error handling

### Gate 5: Registry Format ✅ Required
- [ ] Capability metadata structure
- [ ] Schema versioning
- [ ] Dependency resolution
- [ ] Query API

---

## RECOMMENDATION

**CTO Decision:**

✅ **APPROVE** the 10 operating system primitives as the foundational layer.

These primitives are:
- **Stable:** Will not change for years
- **General:** Apply to any capability (Investigation, Prediction, Automation, etc.)
- **Extensible:** Support plugins without core changes
- **Durable:** Can add domains without architecture change

**DO NOT** build any capability (Investigation, Prediction, Automation) until these primitives are:
1. Formally specified (JSON schemas, interfaces)
2. Reviewed and approved
3. Implemented in runtime
4. Tested with mock capabilities

**Timeline:**
- Week 1-2: Specify and review all 10 primitives
- Week 3: Implement runtime with OS services
- Week 4: Build mock capabilities to validate primitives
- Week 5+: Build real capabilities knowing primitives are solid

This is the difference between building a platform for 5 years vs building one for 20 years.

