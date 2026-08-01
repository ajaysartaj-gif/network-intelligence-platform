// Package spec defines the Network Intelligence Platform Language and Grammar.
// This is the canonical specification that all capabilities must conform to.
//
// Architecture Principle: This file IS the architecture.
// Not documents. Code.
package spec

import (
	"context"
	"time"
)

// PlatformLanguage: Canonical Network Objects
// These objects are immutable at the platform level.
// Capabilities may enrich them, but never change their fundamental structure.

// ObjectID uniquely identifies any platform object.
type ObjectID string

// ObjectType categorizes platform objects.
type ObjectType string

const (
	TypeDevice      ObjectType = "device"
	TypeInterface   ObjectType = "interface"
	TypeNetwork     ObjectType = "network"
	TypeService     ObjectType = "service"
	TypeApplication ObjectType = "application"
	TypeCustomer    ObjectType = "customer"
	TypeCircuit     ObjectType = "circuit"
	TypeAnomaly     ObjectType = "anomaly"
	TypePath        ObjectType = "path"
	TypeVRF         ObjectType = "vrf"
)

// PlatformObject is the base interface all objects must implement.
type PlatformObject interface {
	// Identity
	ID() ObjectID
	Type() ObjectType
	Tenant() string
	Region() string

	// Versioning
	Version() int64
	Revision() int64
	Timestamp() time.Time
	Source() string
	Confidence() float64

	// State
	CurrentState() ObjectState
	DesiredState() ObjectState
	PredictedState() ObjectState
	HistoricalState() []ObjectStateSnapshot

	// Relationships
	Dependencies() []ObjectReference    // What this object depends on
	Dependents() []ObjectReference      // What depends on this object
	Impacts() []ObjectReference         // What this object impacts

	// Behaviors
	Behaviors() []Behavior
}

// ObjectState represents the current state of an object.
type ObjectState struct {
	Status      string                 `json:"status"`       // up, down, degraded, unknown
	Attributes  map[string]interface{} `json:"attributes"`   // Protocol-specific attributes
	Timestamp   time.Time              `json:"timestamp"`    // When this state was observed
	Confidence  float64                `json:"confidence"`   // How confident we are in this state
	Source      string                 `json:"source"`       // Which system reported this
}

// ObjectStateSnapshot is a historical snapshot of object state.
type ObjectStateSnapshot struct {
	Timestamp  time.Time
	State      ObjectState
	Evidence   []string // Which checks/observations led to this state
	Confidence float64
}

// ObjectReference refers to another platform object.
type ObjectReference struct {
	ID           ObjectID   `json:"id"`
	Type         ObjectType `json:"type"`
	Name         string     `json:"name"`
	RelationType string     `json:"relation_type"` // depends_on, impacts, hosts, etc.
}

// Behavior defines what an object can do.
type Behavior interface {
	Name() string
	Description() string
	Execute(ctx context.Context, obj PlatformObject, params map[string]interface{}) (BehaviorResult, error)
}

// BehaviorResult is the outcome of executing a behavior.
type BehaviorResult struct {
	Success     bool
	Output      interface{}
	Confidence  float64
	Evidence    []string
	Timestamp   time.Time
	NextBehaviors []string
}

// ---
// Platform Lifecycle: States every object transitions through
// ---

type ObjectLifecycleState string

const (
	StateUnknown     ObjectLifecycleState = "unknown"
	StateDiscovered  ObjectLifecycleState = "discovered"
	StateManaged     ObjectLifecycleState = "managed"
	StateHealthy     ObjectLifecycleState = "healthy"
	StateDegraded    ObjectLifecycleState = "degraded"
	StateFailed      ObjectLifecycleState = "failed"
	StateRecovered   ObjectLifecycleState = "recovered"
	StateRetired     ObjectLifecycleState = "retired"
)

// LifecycleTransition defines allowed state transitions.
type LifecycleTransition struct {
	From   ObjectLifecycleState
	To     ObjectLifecycleState
	Reason string
	Evidence []string
	Timestamp time.Time
}

// ---
// Platform Grammar: How intents are expressed and understood
// ---

// IntentType categorizes user intents.
type IntentType string

const (
	IntentDiagnose       IntentType = "diagnose"        // Find root cause
	IntentPredict        IntentType = "predict"         // Forecast issues
	IntentValidateChange IntentType = "validate_change" // Pre-change risk assessment
	IntentOptimize       IntentType = "optimize"        // Improve performance/cost
	IntentEnsureCompliance IntentType = "ensure_compliance" // Regulatory validation
)

// IntentRequest is how users express what they want the platform to do.
// This is the canonical grammar for all platform communication.
type IntentRequest struct {
	// Identity
	RequestID   string    `json:"request_id"`
	Timestamp   time.Time `json:"timestamp"`
	RequestedBy string    `json:"requested_by"`

	// Tenant/Environment
	Tenant       string `json:"tenant"`
	Region       string `json:"region"`
	Organization string `json:"organization"`
	Environment  string `json:"environment"`

	// Intent Structure (THE GRAMMAR)
	Intent              IntentType              `json:"intent"`               // What the user wants
	Subject             ObjectReference         `json:"subject"`             // What they're asking about
	Scope               []ObjectReference       `json:"scope"`               // What infrastructure to consider
	Constraints         []Constraint            `json:"constraints"`         // What can't change
	SuccessCriteria     []SuccessCriterion      `json:"success_criteria"`    // How to know we succeeded
	Policy              []PolicyRequirement     `json:"policy"`              // What policies apply
	RequiredEvidence    []EvidenceType          `json:"required_evidence"`   // What data types we need
}

// Constraint limits what the platform can do.
type Constraint struct {
	Type  string      `json:"type"`  // time_window, approved_devices, no_packet_loss, etc.
	Value interface{} `json:"value"` // The actual constraint value
}

// SuccessCriterion defines how to measure success.
type SuccessCriterion struct {
	Metric string      `json:"metric"`
	Target interface{} `json:"target"`
	Unit   string      `json:"unit"`
}

// PolicyRequirement enforces business/security policies.
type PolicyRequirement struct {
	Rule  string `json:"rule"`  // require_approval, simulation_required, etc.
	Value bool   `json:"value"`
}

// EvidenceType categorizes what kind of evidence is needed.
type EvidenceType string

const (
	EvidenceTypeConfiguration EvidenceType = "configuration"
	EvidenceTypeState         EvidenceType = "state"
	EvidenceTypeTelemetry     EvidenceType = "telemetry"
	EvidenceTypeEvent         EvidenceType = "event"
	EvidenceTypeRelationship  EvidenceType = "relationship"
)

// ---
// Platform Contracts: What enters and leaves the platform
// ---

// IntelligenceResult is the canonical output of platform analysis.
type IntelligenceResult struct {
	// Identity
	ResultID   string    `json:"result_id"`
	RequestID  string    `json:"request_id"`
	Timestamp  time.Time `json:"timestamp"`

	// Result
	Intent           IntentType      `json:"intent"`
	Status           string          `json:"status"` // success, partial, failure
	Outcome          interface{}     `json:"outcome"`
	Confidence       float64         `json:"confidence"`
	Evidence         []EvidenceItem  `json:"evidence"`
	AffectedObjects  []ObjectID      `json:"affected_objects"`

	// Business Impact
	ImpactedServices   []ObjectID  `json:"impacted_services"`
	ImpactedCustomers  []ObjectID  `json:"impacted_customers"`
	RevenueAtRisk      float64     `json:"revenue_at_risk"`
	UsersAffected      int         `json:"users_affected"`
	SLACompliance      float64     `json:"sla_compliance"`

	// Recommendation
	Recommendation   string             `json:"recommendation"`
	AlternativeOptions []RecommendedOption `json:"alternative_options"`
	ValidationPlan   interface{}        `json:"validation_plan"`
	ExecutionPlan    interface{}        `json:"execution_plan"`

	// Metadata
	ExecutionTime    time.Duration `json:"execution_time"`
	CapabilitiesUsed []string      `json:"capabilities_used"`
	KnowledgeGaps    []string      `json:"knowledge_gaps"`
}

// EvidenceItem is one piece of evidence collected during investigation.
type EvidenceItem struct {
	CheckName       string      `json:"check_name"`
	EvidenceType    EvidenceType `json:"evidence_type"`
	CollectedFrom   ObjectID    `json:"collected_from"`
	Value           interface{} `json:"value"`
	Timestamp       time.Time   `json:"timestamp"`
	SourceTrust     float64     `json:"source_trust"`
	FreshnessScore  float64     `json:"freshness_score"`
	Contradictions  []string    `json:"contradictions"`
}

// RecommendedOption is one possible action the platform recommends.
type RecommendedOption struct {
	Description            string  `json:"description"`
	SuccessProbability     float64 `json:"success_probability"`
	RiskLevel              string  `json:"risk_level"`
	EstimatedMTTRMinutes   int     `json:"estimated_mttr_minutes"`
	RequiresApproval       bool    `json:"requires_approval"`
	BlastRadius            []ObjectID `json:"blast_radius"`
	ValidationRequired     bool    `json:"validation_required"`
}

// ---
// Capability Interface: How capabilities integrate with the platform
// ---

// Capability is the interface all platform capabilities must implement.
// This is how the platform ensures conformance.
type Capability interface {
	// Metadata
	Name() string
	Version() string
	Description() string

	// Capability Declaration
	CanHandle(intent IntentType) bool
	RequiredObjects() []ObjectType
	ProvidedBehaviors() []string

	// Execution
	Execute(ctx context.Context, request IntentRequest, objects []PlatformObject) (IntelligenceResult, error)

	// State Management
	GetState(ctx context.Context) CapabilityState
	SetState(ctx context.Context, state CapabilityState) error

	// Health
	HealthCheck(ctx context.Context) HealthStatus
}

// CapabilityState tracks internal capability state.
type CapabilityState struct {
	Ready           bool
	ResourcesUsed   map[string]interface{}
	LastExecution   time.Time
	ExecutionCount  int64
	ErrorCount      int64
	AverageLatency  time.Duration
}

// HealthStatus reports capability health.
type HealthStatus struct {
	Healthy   bool
	Latency   time.Duration
	ErrorRate float64
	Details   string
}

// ---
// Adapter Interface: How external systems connect
// ---

// AdapterType categorizes connection types.
type AdapterType string

const (
	AdapterCLI       AdapterType = "cli"
	AdapterNETCONF   AdapterType = "netconf"
	AdapterGNMI      AdapterType = "gnmi"
	AdapterREST      AdapterType = "rest"
	AdapterSNMP      AdapterType = "snmp"
	AdapterTelemetry AdapterType = "telemetry"
	AdapterCloud     AdapterType = "cloud"
)

// Adapter is the interface all transport adapters must implement.
type Adapter interface {
	// Identity
	Type() AdapterType
	Name() string
	Version() string

	// Connection
	Connect(ctx context.Context, target ObjectReference, credentials map[string]string) error
	Disconnect(ctx context.Context) error
	IsConnected(ctx context.Context) bool

	// Operations
	ExecuteCommand(ctx context.Context, command string) (string, error)
	GetConfiguration(ctx context.Context) (string, error)
	SetConfiguration(ctx context.Context, config string) error
	GetTelemetry(ctx context.Context, metrics []string) (map[string]interface{}, error)

	// Health
	HealthCheck(ctx context.Context) error
}

// ---
// Conformance Testing
// ---

// ConformanceRequirement defines what capabilities must implement.
type ConformanceRequirement struct {
	Name        string
	Description string
	Test        func(context.Context, Capability) error
	Required    bool // Must pass vs should pass
}

// ConformanceSuite is the set of tests all capabilities must pass.
type ConformanceSuite struct {
	Requirements []ConformanceRequirement
}

// VerifyCapability tests whether a capability conforms to the platform spec.
func (cs *ConformanceSuite) VerifyCapability(ctx context.Context, cap Capability) []ConformanceViolation {
	var violations []ConformanceViolation

	for _, req := range cs.Requirements {
		if err := req.Test(ctx, cap); err != nil {
			violations = append(violations, ConformanceViolation{
				Requirement: req.Name,
				Error:       err.Error(),
				Required:    req.Required,
			})
		}
	}

	return violations
}

// ConformanceViolation reports a capability that doesn't conform.
type ConformanceViolation struct {
	Requirement string
	Error       string
	Required    bool
}

// ---
// Platform Runtime: The minimal kernel
// ---

// Runtime is the core platform engine that coordinates everything.
type Runtime interface {
	// Object Management
	RegisterObject(ctx context.Context, obj PlatformObject) error
	GetObject(ctx context.Context, id ObjectID) (PlatformObject, error)
	UpdateObject(ctx context.Context, obj PlatformObject) error
	QueryObjects(ctx context.Context, filter map[string]interface{}) ([]PlatformObject, error)

	// Intent Execution
	ExecuteIntent(ctx context.Context, intent IntentRequest) (IntelligenceResult, error)

	// Capability Management
	RegisterCapability(ctx context.Context, cap Capability) error
	GetCapability(ctx context.Context, name string) (Capability, error)
	ListCapabilities(ctx context.Context) ([]string, error)

	// Adapter Management
	RegisterAdapter(ctx context.Context, adapter Adapter) error
	GetAdapter(ctx context.Context, adapterType AdapterType) (Adapter, error)

	// State & Persistence
	SaveState(ctx context.Context, id ObjectID, state ObjectState) error
	GetHistory(ctx context.Context, id ObjectID, since time.Time) ([]ObjectStateSnapshot, error)
}
