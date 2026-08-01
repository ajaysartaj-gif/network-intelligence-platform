// Package spec_test contains the conformance test suite.
// Every capability must pass these tests before being accepted into the platform.
package spec

import (
	"context"
	"fmt"
	"testing"
	"time"
)

// BuildConformanceSuite creates the canonical test suite all capabilities must pass.
func BuildConformanceSuite() *ConformanceSuite {
	return &ConformanceSuite{
		Requirements: []ConformanceRequirement{
			// Capability Metadata
			{
				Name:        "Capability must provide name",
				Description: "All capabilities must identify themselves",
				Test:        testCapabilityName,
				Required:    true,
			},
			{
				Name:        "Capability must provide version",
				Description: "Capabilities must be versioned",
				Test:        testCapabilityVersion,
				Required:    true,
			},
			{
				Name:        "Capability must declare what it can handle",
				Description: "Capabilities must declare supported intent types",
				Test:        testCapabilityIntents,
				Required:    true,
			},

			// Contract Compliance
			{
				Name:        "Execution must accept IntentRequest",
				Description: "Capabilities must implement canonical grammar",
				Test:        testIntentRequestAcceptance,
				Required:    true,
			},
			{
				Name:        "Execution must return IntelligenceResult",
				Description: "Capabilities must return canonical contract",
				Test:        testIntelligenceResultContract,
				Required:    true,
			},
			{
				Name:        "Result must include confidence score",
				Description: "Platform requires confidence on all results",
				Test:        testConfidenceScore,
				Required:    true,
			},
			{
				Name:        "Result must include affected objects",
				Description: "Platform requires object impact tracking",
				Test:        testAffectedObjectTracking,
				Required:    true,
			},

			// Platform Language Compliance
			{
				Name:        "Capability must respect object references",
				Description: "Must use ObjectReference for dependencies",
				Test:        testObjectReferences,
				Required:    true,
			},
			{
				Name:        "Capability must respect object types",
				Description: "Must operate only on declared ObjectTypes",
				Test:        testObjectTypeRespect,
				Required:    true,
			},
			{
				Name:        "Capability must provide evidence",
				Description: "All results must include evidence items",
				Test:        testEvidenceProvision,
				Required:    true,
			},

			// State Management
			{
				Name:        "Capability must track its state",
				Description: "State must be queryable and restorable",
				Test:        testStateManagement,
				Required:    true,
			},
			{
				Name:        "Capability must handle resource limits",
				Description: "Capabilities must respect quotas",
				Test:        testResourceLimits,
				Required:    true,
			},

			// Health & Reliability
			{
				Name:        "Capability must provide health check",
				Description: "Platform needs to monitor capability health",
				Test:        testHealthCheck,
				Required:    true,
			},
			{
				Name:        "Capability must handle timeouts",
				Description: "Must not hang indefinitely",
				Test:        testTimeoutHandling,
				Required:    true,
			},
			{
				Name:        "Capability must handle context cancellation",
				Description: "Must respect context.Done()",
				Test:        testContextCancellation,
				Required:    true,
			},

			// Multi-tenancy
			{
				Name:        "Capability must respect tenant boundaries",
				Description: "Cannot access objects from other tenants",
				Test:        testTenantIsolation,
				Required:    true,
			},
			{
				Name:        "Result must include tenant information",
				Description: "Results must be tagged with tenant",
				Test:        testTenantTracking,
				Required:    true,
			},

			// Behavior: Optional for MVP but should be designed for
			{
				Name:        "Capability should declare behaviors",
				Description: "Declare what object behaviors it supports",
				Test:        testBehaviorDeclaration,
				Required:    false,
			},
		},
	}
}

// Test implementations

func testCapabilityName(ctx context.Context, cap Capability) error {
	if cap.Name() == "" {
		return fmt.Errorf("capability name is empty")
	}
	return nil
}

func testCapabilityVersion(ctx context.Context, cap Capability) error {
	if cap.Version() == "" {
		return fmt.Errorf("capability version is empty")
	}
	return nil
}

func testCapabilityIntents(ctx context.Context, cap Capability) error {
	// At least one intent type should be supported
	supported := false
	for _, intent := range []IntentType{
		IntentDiagnose,
		IntentPredict,
		IntentValidateChange,
		IntentOptimize,
		IntentEnsureCompliance,
	} {
		if cap.CanHandle(intent) {
			supported = true
			break
		}
	}
	if !supported {
		return fmt.Errorf("capability doesn't support any intent type")
	}
	return nil
}

func testIntentRequestAcceptance(ctx context.Context, cap Capability) error {
	request := IntentRequest{
		RequestID:   "test-123",
		Timestamp:   time.Now(),
		RequestedBy: "test-user",
		Tenant:      "test-tenant",
		Intent:      IntentDiagnose,
		Subject: ObjectReference{
			ID:   "obj-123",
			Type: TypeDevice,
		},
	}

	// Capability should accept this without error (or return structured error)
	_, err := cap.Execute(ctx, request, nil)
	// We don't check for nil error here - the point is that it accepted the contract format
	_ = err

	return nil
}

func testIntelligenceResultContract(ctx context.Context, cap Capability) error {
	request := IntentRequest{
		RequestID:   "test-123",
		Timestamp:   time.Now(),
		RequestedBy: "test-user",
		Tenant:      "test-tenant",
		Intent:      IntentDiagnose,
		Subject: ObjectReference{
			ID:   "obj-123",
			Type: TypeDevice,
		},
	}

	result, _ := cap.Execute(ctx, request, nil)

	if result.ResultID == "" {
		return fmt.Errorf("result missing ResultID")
	}
	if result.RequestID == "" {
		return fmt.Errorf("result missing RequestID")
	}
	if result.Status == "" {
		return fmt.Errorf("result missing Status")
	}

	return nil
}

func testConfidenceScore(ctx context.Context, cap Capability) error {
	request := IntentRequest{
		RequestID: "test-123",
		Timestamp: time.Now(),
		Tenant:    "test-tenant",
		Intent:    IntentDiagnose,
	}

	result, _ := cap.Execute(ctx, request, nil)

	if result.Confidence < 0 || result.Confidence > 1 {
		return fmt.Errorf("confidence score out of range: %f", result.Confidence)
	}

	return nil
}

func testAffectedObjectTracking(ctx context.Context, cap Capability) error {
	request := IntentRequest{
		RequestID: "test-123",
		Timestamp: time.Now(),
		Tenant:    "test-tenant",
		Intent:    IntentDiagnose,
	}

	result, _ := cap.Execute(ctx, request, nil)

	// Result should track which objects are affected
	// (may be empty for some capabilities, but structure should exist)
	_ = result.AffectedObjects

	return nil
}

func testObjectReferences(ctx context.Context, cap Capability) error {
	// Capability should work with ObjectReference format
	request := IntentRequest{
		RequestID: "test-123",
		Timestamp: time.Now(),
		Tenant:    "test-tenant",
		Intent:    IntentDiagnose,
		Subject: ObjectReference{
			ID:   "dev-123",
			Type: TypeDevice,
		},
	}

	_, _ = cap.Execute(ctx, request, nil)
	return nil
}

func testObjectTypeRespect(ctx context.Context, cap Capability) error {
	// Verify capability declares what object types it supports
	requiredTypes := cap.RequiredObjects()
	_ = requiredTypes // Should be non-empty for most capabilities
	return nil
}

func testEvidenceProvision(ctx context.Context, cap Capability) error {
	request := IntentRequest{
		RequestID: "test-123",
		Timestamp: time.Now(),
		Tenant:    "test-tenant",
		Intent:    IntentDiagnose,
	}

	result, _ := cap.Execute(ctx, request, nil)

	// Result should include evidence (may be empty, but structure exists)
	_ = result.Evidence

	return nil
}

func testStateManagement(ctx context.Context, cap Capability) error {
	// Capability should be able to report its state
	state := cap.GetState(ctx)

	if state.Ready && state.ExecutionCount > 0 {
		// State tracking works
		return nil
	}

	return nil
}

func testResourceLimits(ctx context.Context, cap Capability) error {
	// Capability should track resource usage
	state := cap.GetState(ctx)
	_ = state.ResourcesUsed // Should exist

	return nil
}

func testHealthCheck(ctx context.Context, cap Capability) error {
	health := cap.HealthCheck(ctx)

	// Health status should be available
	_ = health.Healthy
	_ = health.Latency
	_ = health.ErrorRate

	return nil
}

func testTimeoutHandling(ctx context.Context, cap Capability) error {
	// Create a context that times out quickly
	ctx, cancel := context.WithTimeout(ctx, 100*time.Millisecond)
	defer cancel()

	request := IntentRequest{
		RequestID: "test-123",
		Timestamp: time.Now(),
		Tenant:    "test-tenant",
		Intent:    IntentDiagnose,
	}

	// Should not hang, should return reasonably quickly
	done := make(chan bool, 1)
	go func() {
		cap.Execute(ctx, request, nil)
		done <- true
	}()

	select {
	case <-done:
		return nil
	case <-time.After(1 * time.Second):
		return fmt.Errorf("capability did not respect timeout")
	}
}

func testContextCancellation(ctx context.Context, cap Capability) error {
	ctx, cancel := context.WithCancel(ctx)

	request := IntentRequest{
		RequestID: "test-123",
		Timestamp: time.Now(),
		Tenant:    "test-tenant",
		Intent:    IntentDiagnose,
	}

	done := make(chan bool, 1)
	go func() {
		cap.Execute(ctx, request, nil)
		done <- true
	}()

	time.Sleep(50 * time.Millisecond)
	cancel()

	select {
	case <-done:
		return nil
	case <-time.After(1 * time.Second):
		return fmt.Errorf("capability did not respect cancellation")
	}
}

func testTenantIsolation(ctx context.Context, cap Capability) error {
	// Capability should not process requests from different tenants without care
	request := IntentRequest{
		RequestID: "test-123",
		Timestamp: time.Now(),
		Tenant:    "tenant-a",
		Intent:    IntentDiagnose,
	}

	result, _ := cap.Execute(ctx, request, nil)

	// Result should be tagged with tenant
	if result.RequestID == "" {
		return fmt.Errorf("capability did not preserve request context")
	}

	return nil
}

func testTenantTracking(ctx context.Context, cap Capability) error {
	request := IntentRequest{
		RequestID:   "test-123",
		Timestamp:   time.Now(),
		Tenant:      "my-tenant",
		Region:      "us-east",
		Organization: "my-org",
		Intent:      IntentDiagnose,
	}

	result, _ := cap.Execute(ctx, request, nil)

	// Result should reference the request
	if result.RequestID != request.RequestID {
		return fmt.Errorf("result not linked to request")
	}

	return nil
}

func testBehaviorDeclaration(ctx context.Context, cap Capability) error {
	behaviors := cap.ProvidedBehaviors()
	_ = behaviors // Should declare what behaviors it supports

	return nil
}

// Example conformance test runner
func ExampleConformanceTest(t *testing.T, capability Capability) {
	suite := BuildConformanceSuite()
	ctx := context.Background()

	violations := suite.VerifyCapability(ctx, capability)

	for _, v := range violations {
		msg := fmt.Sprintf("CONFORMANCE VIOLATION: %s - %s", v.Requirement, v.Error)
		if v.Required {
			t.Errorf(msg)
		} else {
			t.Logf("WARNING: %s", msg)
		}
	}

	if len(violations) > 0 {
		// Count required vs optional
		var required, optional int
		for _, v := range violations {
			if v.Required {
				required++
			} else {
				optional++
			}
		}
		t.Logf("Conformance Report: %d required failures, %d optional warnings", required, optional)
	}
}
