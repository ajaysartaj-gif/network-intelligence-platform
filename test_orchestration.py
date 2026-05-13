#!/usr/bin/env python3
"""
NetBrain AI Orchestration Test Suite - Validates core autonomous capabilities.
"""

from core.orchestration_engine import OperationsOrchestrator
from core.state_manager import DeviceMetrics
import json
import time

def test_orchestrator_initialization():
    """Test 1: Orchestrator Initialization"""
    print("\n" + "=" * 70)
    print("TEST 1: Orchestrator Initialization")
    print("=" * 70)
    
    orch = OperationsOrchestrator()
    health = orch.health_check()
    
    assert health["status"] in ["healthy", "degraded"], "Health check failed"
    assert health["devices"] >= 30, "Should have 30+ devices"
    assert health["components"]["state_manager"] == "ok", "State manager failed"
    assert health["components"]["simulator"] == "ok", "Simulator failed"
    assert health["components"]["telemetry"] == "ok", "Telemetry failed"
    assert health["components"]["event_engine"] == "ok", "Event engine failed"
    
    print(f"✓ Orchestrator initialized successfully")
    print(f"  - Status: {health['status']}")
    print(f"  - Devices: {health['devices']}")
    print(f"  - Components: {list(health['components'].keys())}")
    return orch


def test_simulation_engine(orch):
    """Test 2: Simulation Engine"""
    print("\n" + "=" * 70)
    print("TEST 2: Simulation Engine")
    print("=" * 70)
    
    result = orch.run_cycle()
    assert result["status"] == "success", "Cycle should complete successfully"
    assert orch.run_count == 1, "Should complete one cycle"
    
    topology = orch.simulator.get_topology_summary()
    assert topology["total_devices"] >= 30, "Should have devices"
    assert topology["total_links"] > 0, "Should have links"
    
    print(f"✓ Simulation cycle completed")
    print(f"  - Devices: {topology['total_devices']}")
    print(f"  - Links: {topology['total_links']}")
    print(f"  - Device types: {list(topology['device_types'].keys())}")


def test_telemetry_engine(orch):
    """Test 3: Telemetry Engine"""
    print("\n" + "=" * 70)
    print("TEST 3: Telemetry Engine")
    print("=" * 70)
    
    metrics = orch.state.get_all_device_metrics()
    assert len(metrics) > 0, "Should have device metrics"
    
    health_metrics = orch.telemetry.get_health_metrics()
    assert "cpu" in health_metrics, "Should have CPU metrics"
    assert "memory" in health_metrics, "Should have memory metrics"
    
    print(f"✓ Telemetry collection working")
    print(f"  - Devices with metrics: {len(metrics)}")
    print(f"  - Avg CPU: {health_metrics['cpu']['average']:.1f}%")
    print(f"  - Avg Memory: {health_metrics['memory']['average']:.1f}%")
    print(f"  - Avg Latency: {health_metrics['latency_ms']['average']:.1f}ms")


def test_state_management(orch):
    """Test 4: State Management"""
    print("\n" + "=" * 70)
    print("TEST 4: State Management")
    print("=" * 70)
    
    # Test service dependencies
    services = orch.state.service_dependencies
    assert len(services) > 0, "Should have service dependencies"
    
    # Get operational summary
    summary = orch.state.get_operational_summary()
    assert "operational_score" in summary, "Should have operational score"
    assert summary["operational_score"] >= 0, "Score should be valid"
    
    print(f"✓ State management operational")
    print(f"  - Services: {len(services)}")
    print(f"  - Operational score: {summary['operational_score']:.1f}%")
    print(f"  - Total devices: {summary['total_devices']}")
    print(f"  - Critical devices: {summary['critical_devices']}")


def test_anomaly_detection(orch):
    """Test 5: Anomaly Detection"""
    print("\n" + "=" * 70)
    print("TEST 5: Anomaly Detection")
    print("=" * 70)
    
    # Force an anomaly for testing
    hostname = list(orch.state.device_metrics.keys())[0]
    metrics = orch.state.device_metrics[hostname]
    metrics.cpu = 95.0
    orch.state.update_device_metrics(hostname, metrics)
    
    # Detect anomalies
    anomalies = orch.telemetry.detect_anomalies()
    assert len(anomalies) > 0, "Should detect CPU anomaly"
    assert anomalies[0]["type"] == "cpu_spike", "Should be CPU spike"
    
    print(f"✓ Anomaly detection working")
    print(f"  - Detected anomalies: {len(anomalies)}")
    print(f"  - Anomaly type: {anomalies[0]['type']}")
    print(f"  - Severity: {anomalies[0]['severity']}")


def test_incident_creation(orch):
    """Test 6: Incident Creation from Anomalies"""
    print("\n" + "=" * 70)
    print("TEST 6: Incident Creation")
    print("=" * 70)
    
    # Get anomalies and create incidents
    anomalies = orch.telemetry.detect_anomalies()
    if anomalies:
        incidents = orch.events.process_anomalies(anomalies)
        assert len(incidents) > 0, "Should create incidents"
        
        # Check incident in state
        all_incidents = orch.state.get_all_incidents()
        assert len(all_incidents) > 0, "Should have incidents in state"
        
        print(f"✓ Incident creation working")
        print(f"  - Incidents created: {len(incidents)}")
        print(f"  - Total incidents: {len(all_incidents)}")
        
        if all_incidents:
            inc = list(all_incidents.values())[0]
            print(f"  - Sample incident: {inc['title']}")
            print(f"  - Severity: {inc['severity']}")
    else:
        print("⚠ No anomalies to create incidents from")


def test_event_engine(orch):
    """Test 7: Event Engine"""
    print("\n" + "=" * 70)
    print("TEST 7: Event Engine")
    print("=" * 70)
    
    # Check workflow chains are registered
    chains = orch.events.workflow_chains
    assert len(chains) > 0, "Should have workflow chains"
    
    # Check handlers are registered
    handlers = orch.events.handlers
    assert len(handlers) > 0, "Should have handlers"
    
    print(f"✓ Event engine operational")
    print(f"  - Workflow chains: {len(chains)}")
    print(f"  - Chain types: {list(chains.keys())}")
    print(f"  - Event handlers: {len(handlers)}")
    print(f"  - Handler types: {list(handlers.keys())[:5]}")


def test_orchestration_queries(orch):
    """Test 8: Orchestration Queries"""
    print("\n" + "=" * 70)
    print("TEST 8: Orchestration Queries")
    print("=" * 70)
    
    # Test operational status
    status = orch.get_operational_status()
    assert "operational_summary" in status, "Should have operational summary"
    
    # Test AI context
    context = orch.get_ai_context("Test query")
    assert "operational_state" in context, "Should have operational state"
    assert "telemetry" in context, "Should have telemetry"
    
    # Test topology
    topology = orch.get_topology()
    assert "devices" in topology, "Should have devices"
    assert "links" in topology, "Should have links"
    
    print(f"✓ All query methods working")
    print(f"  - Operational status: ✓")
    print(f"  - AI context: ✓")
    print(f"  - Topology: ✓")
    print(f"  - Total devices in topology: {len(topology['devices'])}")


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("NetBrain AI Orchestration Test Suite")
    print("=" * 70)
    
    try:
        # Test 1: Initialization
        orch = test_orchestrator_initialization()
        
        # Test 2: Simulation
        test_simulation_engine(orch)
        
        # Test 3: Telemetry
        test_telemetry_engine(orch)
        
        # Test 4: State Management
        test_state_management(orch)
        
        # Test 5: Anomaly Detection
        test_anomaly_detection(orch)
        
        # Test 6: Incident Creation
        test_incident_creation(orch)
        
        # Test 7: Event Engine
        test_event_engine(orch)
        
        # Test 8: Queries
        test_orchestration_queries(orch)
        
        # Final health check
        print("\n" + "=" * 70)
        print("FINAL HEALTH CHECK")
        print("=" * 70)
        final_health = orch.health_check()
        print(f"✓ Final status: {final_health['status']}")
        print(f"  - Run count: {final_health['run_count']}")
        print(f"  - Devices: {final_health['devices']}")
        print(f"  - Incidents: {final_health['incidents']}")
        
        print("\n" + "=" * 70)
        print("✓ ALL TESTS PASSED")
        print("=" * 70)
        print("\nKey Capabilities Validated:")
        print("  1. Multi-engine orchestration ✓")
        print("  2. Network simulation ✓")
        print("  3. Dynamic telemetry collection ✓")
        print("  4. State management ✓")
        print("  5. Anomaly detection ✓")
        print("  6. Incident creation ✓")
        print("  7. Event-driven workflows ✓")
        print("  8. AI context generation ✓")
        
    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
