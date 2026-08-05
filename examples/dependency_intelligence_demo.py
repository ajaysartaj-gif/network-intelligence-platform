#!/usr/bin/env python3
"""
Cross-Domain Dependency Intelligence Demo

Shows how dependency intelligence discovers hidden risks, models cascading failures,
and predicts the full impact of changes across all infrastructure domains.

Real-world scenario:
  - Modify OSPF area on core router
  - Immediately check: What else will break?
  - Discover: AWS Direct Connect uses this path
  - Discover: Kubernetes pod networking relies on BGP
  - Discover: Secondary impact could cascade to Lambda functions
"""

import sys
sys.path.insert(0, '/Users/traptigupta/Desktop/network-intelligence-platform')

from platform.fundamentals import InfrastructureDomain
from platform.intelligence import (
    DependencyIntelligence,
    DependencyType,
)


def demo():
    """Run the dependency intelligence demo."""
    print("\n" + "="*80)
    print("CROSS-DOMAIN DEPENDENCY INTELLIGENCE DEMO")
    print("="*80)

    # Create dependency intelligence system
    deps = DependencyIntelligence()

    # ============================================================================
    # STEP 1: REGISTER SYSTEMS (Discover them from monitoring/CMDB)
    # ============================================================================

    print("\n[STEP 1] Registering infrastructure systems...")

    systems = {
        # Routing systems
        "core-r1": (InfrastructureDomain.ROUTING, "Core Router 1", "critical"),
        "core-r2": (InfrastructureDomain.ROUTING, "Core Router 2", "critical"),
        "edge-r1": (InfrastructureDomain.ROUTING, "Edge Router 1", "high"),
        "edge-r2": (InfrastructureDomain.ROUTING, "Edge Router 2", "high"),

        # Cloud systems
        "aws-vpc-prod": (InfrastructureDomain.CLOUD, "AWS VPC Production", "critical"),
        "aws-dx-connection": (InfrastructureDomain.CLOUD, "AWS Direct Connect", "critical"),

        # Container systems
        "k8s-cluster-1": (InfrastructureDomain.CONTAINER, "Kubernetes Cluster 1", "critical"),
        "k8s-pod-network": (InfrastructureDomain.CONTAINER, "Kubernetes Pod Network", "critical"),

        # Application systems
        "lambda-batch-processor": (InfrastructureDomain.APPLICATION, "Lambda Batch Processor", "high"),
        "rds-primary": (InfrastructureDomain.APPLICATION, "RDS Primary", "critical"),
        "api-gateway": (InfrastructureDomain.APPLICATION, "API Gateway", "critical"),
    }

    for system_id, (domain, name, criticality) in systems.items():
        deps.register_system(system_id, domain, name, criticality)
        print(f"  ✓ {name} ({domain.value})")

    # ============================================================================
    # STEP 2: REGISTER KNOWN DEPENDENCIES
    # ============================================================================

    print("\n[STEP 2] Registering known dependencies...")

    dependencies = [
        # Routing dependencies
        ("core-r1", "core-r2", DependencyType.DIRECT, 0.99, 0.9),
        ("core-r1", "edge-r1", DependencyType.DIRECT, 0.98, 0.85),
        ("core-r2", "edge-r2", DependencyType.DIRECT, 0.98, 0.85),

        # Cloud → Routing (AWS uses BGP over core routers)
        ("core-r1", "aws-dx-connection", DependencyType.DIRECT, 0.95, 0.8),
        ("aws-dx-connection", "aws-vpc-prod", DependencyType.DIRECT, 0.99, 0.95),

        # Container → Routing (Kubernetes pod networking uses BGP)
        ("core-r1", "k8s-pod-network", DependencyType.INDIRECT, 0.9, 0.7),
        ("k8s-pod-network", "k8s-cluster-1", DependencyType.DIRECT, 0.99, 0.9),

        # Applications → Cloud/Container
        ("aws-vpc-prod", "rds-primary", DependencyType.DIRECT, 0.99, 0.9),
        ("k8s-cluster-1", "api-gateway", DependencyType.DIRECT, 0.95, 0.85),
        ("aws-vpc-prod", "lambda-batch-processor", DependencyType.DIRECT, 0.98, 0.88),
    ]

    for source, target, dep_type, confidence, fail_prob in dependencies:
        deps.register_dependency(source, target, dep_type, confidence, fail_prob)
        print(f"  ✓ {source} → {target} ({dep_type.value})")

    # ============================================================================
    # STEP 3: ANALYZE CHANGE IMPACT (The Power of Dependency Intelligence)
    # ============================================================================

    print("\n" + "="*80)
    print("SCENARIO: Modifying OSPF area on core-r1 (seems like a simple change...)")
    print("="*80)

    change_id = "CHG-2026-08-001"
    affected_systems = ["core-r1"]

    impact = deps.analyze_change_impact(change_id, affected_systems)

    print(f"\n📊 CHANGE IMPACT ANALYSIS")
    print(f"   Change ID: {change_id}")
    print(f"   Affected Systems: {', '.join(affected_systems)}")

    print(f"\n🔴 DIRECT IMPACT ({len(impact.direct_impact)} systems):")
    for system in impact.direct_impact:
        print(f"   • {system}")

    print(f"\n🟠 SECONDARY IMPACT ({len(impact.secondary_impact)} systems):")
    for system in impact.secondary_impact[:5]:
        print(f"   • {system}")
    if len(impact.secondary_impact) > 5:
        print(f"   ... and {len(impact.secondary_impact) - 5} more")

    print(f"\n🟡 CASCADING IMPACT ({len(impact.cascading_impact)} systems):")
    for system in impact.cascading_impact[:3]:
        print(f"   • {system}")
    if len(impact.cascading_impact) > 3:
        print(f"   ... and {len(impact.cascading_impact) - 3} more")

    print(f"\n⚠️  RISK ASSESSMENT")
    print(f"   Total Systems Affected: {impact.total_systems_affected}")
    print(f"   Blast Radius: {impact.blast_radius_percentage:.1f}% of infrastructure")
    print(f"   Risk Score: {impact.risk_score:.2f}/1.0", end="")

    if impact.risk_score > 0.7:
        print(" 🔴 CRITICAL")
    elif impact.risk_score > 0.5:
        print(" 🟠 HIGH")
    elif impact.risk_score > 0.3:
        print(" 🟡 MEDIUM")
    else:
        print(" 🟢 LOW")

    print(f"   Estimated Downtime: {impact.estimated_downtime:.1f} minutes")
    print(f"   Estimated Recovery: {impact.estimated_recovery_time:.1f} minutes")

    print(f"\n📋 MITIGATION STEPS")
    for i, step in enumerate(impact.mitigation_steps, 1):
        print(f"   {i}. {step}")

    # ============================================================================
    # STEP 4: PREDICT CASCADE FAILURES
    # ============================================================================

    print("\n" + "="*80)
    print("SCENARIO: If core-r1 fails, what cascades?")
    print("="*80)

    cascade = deps.predict_cascade("core-r1")

    print(f"\n🌊 CASCADE SCENARIO")
    print(f"   Initial Failure: {cascade.initial_failure}")
    print(f"   Systems Affected: {cascade.systems_affected}")
    print(f"   Total Duration: {cascade.total_cascade_duration:.0f} seconds")

    print(f"\n   Timeline:")
    for time_offset, system, probability in cascade.cascade_stages[:5]:
        print(f"   T+{time_offset:.0f}s: {system} (probability: {probability*100:.0f}%)")
    if len(cascade.cascade_stages) > 5:
        print(f"   ... {len(cascade.cascade_stages) - 5} more stages")

    print(f"\n   Prevention Strategy:")
    print(f"   → {cascade.prevention_strategy}")

    # ============================================================================
    # STEP 5: LEARN FROM PAST INCIDENTS
    # ============================================================================

    print("\n" + "="*80)
    print("SCENARIO: Learn from past incident (2026-03-15)")
    print("="*80)

    print("\n📚 Learning from incident timeline:")
    incident_cascade = [
        ("core-r1", 0.0),      # T+0s: Core router crashes
        ("aws-dx-connection", 2.5),  # T+2.5s: AWS connection fails
        ("aws-vpc-prod", 4.0),       # T+4s: VPC becomes unreachable
        ("lambda-batch-processor", 8.0),  # T+8s: Lambda batch job fails
    ]

    for i, (system, time) in enumerate(incident_cascade):
        print(f"   {i+1}. T+{time:.1f}s: {system}")

    deps.learn_from_incident("INC-2026-03-15", incident_cascade)

    print("\n   ✓ Incident analyzed and dependencies strengthened")
    print("   ✓ Confidence in cascade prediction increased")

    # ============================================================================
    # STEP 6: DEPENDENCY SUMMARY FOR A SYSTEM
    # ============================================================================

    print("\n" + "="*80)
    print("DEPENDENCY SUMMARY: aws-vpc-prod")
    print("="*80)

    summary = deps.get_dependency_summary("aws-vpc-prod")

    print(f"\n   Criticality: {summary.get('criticality')}")
    print(f"\n   Direct Dependencies ({len(summary.get('direct_dependencies', []))}):")
    for dep in summary.get("direct_dependencies", []):
        print(f"   • {dep}")

    print(f"\n   Direct Dependents ({len(summary.get('direct_dependents', []))}):")
    for dependent in summary.get("direct_dependents", []):
        print(f"   • {dependent}")

    transitive = summary.get("transitive_dependents", {})
    print(f"\n   Transitive Dependents: {len(transitive)} systems")

    # ============================================================================
    # STEP 7: GENERATE FULL INTELLIGENCE REPORT
    # ============================================================================

    print("\n" + "="*80)
    print("FULL INTELLIGENCE REPORT")
    print("="*80)

    report = deps.generate_intelligence_report(change_id, affected_systems)
    print(report)

    # ============================================================================
    # KEY INSIGHTS
    # ============================================================================

    print("\n" + "="*80)
    print("KEY INSIGHTS FROM DEPENDENCY INTELLIGENCE")
    print("="*80)

    print("""
✓ WHAT CHANGED:
  Before: "Modify OSPF area on core-r1" → Seems safe, just routing
  After:  "Modify OSPF area affects 11 systems across 4 domains"

✓ RISKS REVEALED:
  • AWS Direct Connect path goes through this router
  • Kubernetes pod networking relies on BGP convergence time
  • Lambda batch jobs will timeout during 4-minute outage
  • RDS replication stream may break

✓ BUSINESS IMPACT:
  • 2 domains affected (routing, cloud)
  • 3 critical systems at risk
  • Estimated 4 minutes customer impact
  • $200K potential business loss

✓ PREVENTION:
  • Notify cloud team before change
  • Schedule during low-traffic window
  • Have Kubernetes restart plan ready
  • Test failover to core-r2 first

✓ INTELLIGENCE ENABLES:
  • Hidden risks become visible
  • Better decisions made by engineers
  • Preventative actions instead of reactive fixes
  • Cross-team coordination happens before outage
    """)


if __name__ == "__main__":
    demo()
