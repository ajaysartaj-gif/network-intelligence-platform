# Platform Specification: The Executable Architecture

**Status:** CTO Approved - Architecture Foundation  
**Contract Version:** 1.0  
**Last Updated:** August 1, 2026

---

## What This Is

This is NOT a document describing the architecture.

**This IS the architecture.**

Every file in this directory is executable specification that defines:
- The canonical platform language (objects, relationships, contracts)
- The canonical platform grammar (how intents are expressed)
- The canonical conformance tests (what every capability must pass)

---

## Architecture in Code (Not Documents)

### `platform_spec.go`

Defines the permanent platform language:

```go
// Canonical Network Objects
type ObjectType string  // Device, Interface, Network, Service, Application, Customer, Circuit
type PlatformObject interface { ... }

// Canonical Relationships
type ObjectReference struct { ... }  // depends_on, impacts, hosts, connects_to

// Canonical Grammar (How user intents are expressed)
type IntentRequest struct {
    Intent              IntentType
    Subject             ObjectReference
    Scope               []ObjectReference
    Constraints         []Constraint
    SuccessCriteria     []SuccessCriterion
    Policy              []PolicyRequirement
}

// Canonical Contracts
type IntelligenceResult struct { ... }  // What the platform returns
type EvidenceItem struct { ... }        // What evidence looks like
type RecommendedOption struct { ... }   // What recommendations look like

// Capability Interface (How capabilities integrate)
type Capability interface {
    Name() string
    Version() string
    Execute(ctx context.Context, request IntentRequest, objects []PlatformObject) (IntelligenceResult, error)
    ...
}

// Adapter Interface (How external systems connect)
type Adapter interface {
    Type() AdapterType
    Execute() Command
    GetTelemetry() Metrics
    ...
}

// Runtime Interface (The platform kernel)
type Runtime interface {
    ExecuteIntent(ctx context.Context, intent IntentRequest) (IntelligenceResult, error)
    RegisterCapability(ctx context.Context, cap Capability) error
    ...
}
```

**This code IS the contract.**

If a capability doesn't implement these interfaces, it won't even compile. That's the point.

### `conformance_test.go`

Defines the tests every capability must pass:

```go
BuildConformanceSuite() // 20+ tests including:
- Capability metadata (name, version, intent support)
- Contract compliance (accepts IntentRequest, returns IntelligenceResult)
- Platform language compliance (uses correct object types, references, evidence)
- State management (tracks and persists state)
- Multi-tenancy (respects tenant boundaries)
- Health & reliability (health checks, timeouts, context cancellation)
```

Every new capability must pass this suite before being accepted into the platform.

---

## The Permanent Language (What Freezes)

```
✅ FROZEN:
├─ Canonical Objects: Device, Interface, Network, Service, Application, Customer, Circuit
├─ Relationships: depends_on, impacts, hosts, routes_traffic_for, connects_to
├─ Contracts: IntentRequest, IntelligenceResult, EvidenceItem, RecommendedOption
├─ Grammar: How intents are expressed and understood
├─ Adapter Types: CLI, NETCONF, gNMI, REST, SNMP, Telemetry, Cloud
├─ Lifecycle States: Unknown → Discovered → Managed → Healthy → Degraded → Failed → Recovered → Retired
└─ Conformance Requirements: The 20+ tests that all capabilities must pass
```

These interfaces and contracts will remain stable for years.

---

## What Evolves (What Changes)

```
❌ DON'T FREEZE:
├─ Capabilities: Investigation, Prediction, Automation, Change Intelligence, Compliance, etc.
├─ Reasoning: Bayesian, neural networks, symbolic reasoning
├─ Prediction: Time-series models, anomaly detection, pattern recognition
├─ Automation: Execution strategies, validation approaches
├─ Learning: ML models, rule generation, threshold tuning
└─ Vendor Support: New adapters for new protocols as needed
```

Capabilities are pluggable. They come and go. The platform language stays stable.

---

## How Capabilities Integrate

### Step 1: Implement the Capability Interface

```go
type MyCapability struct { ... }

func (c *MyCapability) Name() string { return "my-capability" }
func (c *MyCapability) Version() string { return "1.0.0" }
func (c *MyCapability) CanHandle(intent IntentType) bool { ... }

func (c *MyCapability) Execute(ctx context.Context, request IntentRequest, objects []PlatformObject) (IntelligenceResult, error) {
    // 1. Accept IntentRequest (the grammar)
    // 2. Process platform objects
    // 3. Return IntelligenceResult (the contract)
    // 4. Include evidence, confidence, affected objects
}
```

### Step 2: Pass Conformance Tests

```go
suite := BuildConformanceSuite()
violations := suite.VerifyCapability(ctx, myCapability)

if len(violations) > 0 {
    // Fix violations
    // Retry conformance tests
}
```

### Step 3: Register with Platform

```go
runtime.RegisterCapability(ctx, myCapability)
// Now it's available for user intents
```

---

## Example: Requesting an Investigation

### User Intent (The Grammar)

```go
request := IntentRequest{
    Intent: IntentDiagnose,
    Subject: ObjectReference{
        ID:   "app-sap",
        Type: TypeApplication,
    },
    Scope: []ObjectReference{
        {ID: "svc-payment", Type: TypeService},
        {ID: "net-vrf100", Type: TypeNetwork},
        {ID: "dev-lb01", Type: TypeDevice},
    },
    Constraints: []Constraint{
        {Type: "time_window", Value: "business_hours"},
        {Type: "no_packet_loss", Value: true},
    },
    SuccessCriteria: []SuccessCriterion{
        {Metric: "latency", Target: 50, Unit: "ms"},
        {Metric: "error_rate", Target: 0.1, Unit: "%"},
    },
}
```

### Platform Execution

```go
result, err := runtime.ExecuteIntent(ctx, request)
// Runtime routes this to Investigation capability
// Investigation implements Capability interface
// Returns IntelligenceResult (the contract)
```

### Result (The Contract)

```go
result := IntelligenceResult{
    ResultID:    "res-12345",
    RequestID:   request.RequestID,
    Status:      "success",
    Confidence:  0.94,
    Outcome:     "Root cause: MTU mismatch (R1: 1500, R2: 1400)",
    
    Evidence: []EvidenceItem{
        {CheckName: "interface_mtu", Value: "1500", SourceTrust: 0.95},
        {CheckName: "packet_loss", Value: "0.5%", SourceTrust: 0.92},
    },
    
    AffectedObjects: []ObjectID{"app-sap", "svc-payment"},
    ImpactedServices: []ObjectID{"svc-payment"},
    RevenueAtRisk: 500000, // $500K/min
    
    Recommendation: "Change MTU to 1500 on device R2",
    AlternativeOptions: []RecommendedOption{
        {Description: "Reroute via backup interface", SuccessProbability: 0.60},
    },
}
```

---

## Adding a New Capability

This is why the conformance tests matter.

```
1. Implement Capability interface
2. Pass conformance tests
3. Register with runtime
4. Automatically available to all user intents
5. No changes to platform core needed
```

This is how the platform scales from Investigation → Change Intelligence → Compliance → Prediction without core rewrites.

---

## Adding a New Object Type

If you need to support a new network object (e.g., `TypePolicyMap`):

```go
// 1. Add to ObjectType enum
const TypePolicyMap ObjectType = "policy_map"

// 2. Implement PlatformObject interface
type PolicyMap struct {
    id           ObjectID
    currentState ObjectState
    desiredState ObjectState
    dependencies []ObjectReference
    behaviors    []Behavior
}

// 3. Platform automatically works with it
request := IntentRequest{
    Subject: ObjectReference{
        ID:   "policy-acl-123",
        Type: TypePolicyMap,
    },
}
```

No rewrites needed. The platform is designed for this.

---

## Adding a New Adapter

```go
// 1. Implement Adapter interface
type MyAdapter struct { ... }

func (a *MyAdapter) Type() AdapterType { return "my_transport" }
func (a *MyAdapter) ExecuteCommand(ctx context.Context, cmd string) (string, error) { ... }

// 2. Register with runtime
runtime.RegisterAdapter(ctx, myAdapter)

// 3. Platform automatically uses it for new vendors/protocols
```

---

## The Architecture Review Board's Decision

✅ **APPROVED**

Condition: "No more architecture documents. This code IS the architecture."

- Platform Language (frozen): `platform_spec.go`
- Platform Contracts (frozen): `platform_spec.go`
- Conformance Tests (frozen): `conformance_test.go`
- Everything else: Pluggable, evolving, replaceable

---

## Principles

1. **Code over Documents**: Interfaces enforce contracts better than words.
2. **Conformance over Configuration**: Tests verify compliance automatically.
3. **Stability over Features**: The platform language doesn't change; capabilities do.
4. **Extensibility over Customization**: Add via adapters/capabilities, not core patches.
5. **Multi-tenancy by Default**: Every object tagged with tenant/region/org/environment.
6. **Evidence-Driven**: Every result includes evidence and confidence scores.
7. **Operational Lifecycle**: Objects progress through well-defined states.

---

## Next Steps

1. **Reference Runtime** (this week)
   - Implement Runtime interface
   - Mock capability demonstrating conformance
   - This proves the spec works

2. **Investigation Capability** (weeks 2-3)
   - Refactor existing Investigation engine to implement Capability interface
   - Pass conformance tests
   - Integrate with Runtime

3. **Change Intelligence Capability** (weeks 3-4)
   - New capability for change validation
   - Implements Capability interface
   - Passes conformance tests
   - Zero core changes needed

4. **Additional Capabilities** (ongoing)
   - Prediction
   - Compliance
   - Optimization
   - etc.

Each new capability is a simple drop-in that implements the interface and passes the tests.

---

## This is the Foundation

From this point forward, the platform's permanence comes from the code in this directory, not from documents.

Capabilities will change. Vendors will be added. New object types will be supported. But the platform language—defined here in Go—remains stable.

That's how you build a platform that lasts.
