# NetBrain AI Orchestration - Quick Reference Guide

## Initialization

```python
from core.orchestration_engine import OperationsOrchestrator

# Initialize orchestrator (all engines auto-initialized)
orch = OperationsOrchestrator()

# Verify health
health = orch.health_check()
assert health["status"] == "healthy"
```

## Core Operations

### Run Orchestration Cycle
```python
result = orch.run_cycle()
# Returns:
# {
#     "status": "success",
#     "cycle": 1,
#     "anomalies_detected": 0,
#     "incidents_created": 0,
#     "critical_devices": 0,
#     "operational_summary": {...}
# }
```

### Get Operational Status
```python
status = orch.get_operational_status()
# Returns:
# {
#     "operational_summary": {...},
#     "critical_devices": [...],
#     "incidents": {"total": 0, "by_status": {...}},
#     "topology": {...}
# }
```

### Get Device Details
```python
device_info = orch.get_device_details("dc1-delhi")
# Returns: device config, metrics, health score, timeline
```

### Detect Anomalies
```python
anomalies = orch.telemetry.detect_anomalies()
# Returns list of detected anomalies with severity/value
```

### Create Incidents from Anomalies
```python
incident_ids = orch.events.process_anomalies(anomalies)
# Auto-creates incidents for critical anomalies
```

### Get AI Context
```python
context = orch.get_ai_context("Why is BGP flapping in Delhi DC?")
# Provides operational context for AI analysis:
# - Current incidents
# - Device telemetry
# - Recent events
# - Topology state
# - Service status
```

## State Management

### Device Metrics
```python
# Get all device metrics
metrics = orch.state.get_all_device_metrics()

# Get specific device
device_metrics = orch.state.get_device_metrics("dc1-delhi")
print(f"CPU: {device_metrics.cpu}%")
print(f"Memory: {device_metrics.memory}%")
print(f"Latency: {device_metrics.latency_ms}ms")
```

### Service Dependencies
```python
# Get service status
status = orch.state.get_service_status("Finance Portal")

# Calculate service impact
impact = orch.state.calculate_service_impact(["dc1-delhi", "fw-delhi"])
# Returns: impacted_services, impact_level
```

### Incidents
```python
# Get all incidents
incidents = orch.state.get_all_incidents()

# Get incident details
incident = orch.state.get_incident("INC-1234567890")

# Get incidents by status
open_incidents = orch.state.get_incidents_by_status("new")
```

### Operational Scoring
```python
# Get health metrics
health = orch.telemetry.get_health_metrics()
print(f"Avg CPU: {health['cpu']['average']}%")
print(f"Avg Memory: {health['memory']['average']}%")

# Get device health score
score = orch.telemetry.get_device_health_score("dc1-delhi")
print(f"Score: {score['score']}, Status: {score['status']}")

# Get overall operational score
operational_score = orch.state.calculate_operational_score()
```

## Event Workflows

### Register Event Handler
```python
def my_handler(event):
    print(f"Event: {event['type']}")
    return {"type": "downstream_event"}

orch.events.register_handler(
    event_type="custom_event",
    handler_func=my_handler,
    priority=10
)
```

### Emit Event
```python
event = {
    "type": "cpu_spike_detected",
    "severity": "high",
    "source": "telemetry_engine",
    "description": "High CPU detected",
    "data": {"device": "dc1-delhi", "value": 95.0}
}
downstream = orch.events.emit_event(event)
```

### Get Event History
```python
events = orch.events.get_event_history(limit=20)
for event in events:
    print(f"{event['timestamp']}: {event['type']}")
```

## Simulation & Telemetry

### Get Topology Summary
```python
summary = orch.simulator.get_topology_summary()
print(f"Devices: {summary['total_devices']}")
print(f"Links: {summary['total_links']}")
print(f"Sites: {summary['sites']}")
```

### Get Devices by Type/Site
```python
routers = orch.simulator.get_devices_by_type("router")
delhi_devices = orch.simulator.get_devices_by_site("delhi")
```

### Get Critical Devices
```python
critical = orch.state.get_critical_devices()
# Returns devices with CPU>90%, Memory>90%, or packet_loss>5%
```

### Get Telemetry Timeline
```python
timeline = orch.telemetry.get_device_timeline("dc1-delhi", limit=50)
for sample in timeline:
    print(f"{sample['timestamp']}: CPU={sample['cpu']}%, Memory={sample['memory']}%")
```

## Debugging & Export

### Health Check
```python
health = orch.health_check()
print(f"Status: {health['status']}")
print(f"Components: {health['components']}")
```

### Export Full State
```python
state = orch.export_orchestration_state()
# Includes: simulation state, telemetry, events, incidents
import json
with open("state_backup.json", "w") as f:
    json.dump(state, f, indent=2)
```

### Export Telemetry State
```python
telemetry_state = orch.telemetry.export_telemetry_state()
# Includes: health metrics, anomalies, critical devices
```

### Export Event State
```python
event_state = orch.events.export_event_state()
# Includes: event history, workflow chains, pending events
```

## Key Thresholds & Tuning

### Anomaly Detection Thresholds
```
CPU Spike:       >= 90%
Memory Spike:    >= 90%
Latency Spike:   > 100ms
Packet Loss:     > 5%
BGP Sessions:    > 0 down
```

### Anomaly Generation
```
General Anomaly Probability: 3% per simulation step
Simulation update frequency: CPU/Memory drift: ±3-8% per step
```

### Workflow Chains
1. **Link Failure**: link_failure → packet_loss → bgp_flap → incident
2. **CPU Spike**: cpu_spike → memory_pressure → degradation → incident
3. **Interface Flap**: interface_flap → packet_loss → incident
4. **WAN Degradation**: latency_spike → wan_degradation → incident

## Integration with Streamlit

```python
# In app.py
from core.orchestration_engine import OperationsOrchestrator

# Initialize once at module level
orchestrator = OperationsOrchestrator()

# Use in Streamlit callbacks
def update_dashboard():
    status = orchestrator.get_operational_status()
    st.metric("Health Score", 
              f"{status['operational_summary']['operational_score']:.1f}%")
    
    # Display critical devices
    critical = orchestrator.state.get_critical_devices()
    st.error(f"Critical devices: {len(critical)}")
```

## Performance Tips

### Cycle Frequency
```python
# Recommended: 1-2 cycles per second for real-time responsiveness
# Each cycle takes ~500ms with 39 devices
```

### Memory Management
```python
# Telemetry is auto-capped at 1000 samples per device
# State manager automatically cleans up old data
```

### Scalability
```python
# Current: 39 devices, 60 links, ~500ms per cycle
# Can scale to 100+ devices with performance tuning
```

## Troubleshooting

### No Anomalies Detected
```python
# Check baseline metrics
metrics = orch.state.get_all_device_metrics()
for name, m in list(metrics.items())[:3]:
    print(f"{name}: CPU={m.cpu}%, Memory={m.memory}%")
    
# If all healthy, force an anomaly for testing
hostname = list(metrics.keys())[0]
metrics[hostname].cpu = 95.0
orch.state.update_device_metrics(hostname, metrics[hostname])
```

### Incidents Not Creating
```python
# Verify handlers registered
handlers = orch.events.handlers
print(f"Registered handlers: {len(handlers)}")

# Ensure process_anomalies called
anomalies = orch.telemetry.detect_anomalies()
incidents = orch.events.process_anomalies(anomalies)
```

### Memory Growing
```python
# Check state export size
state_size = len(orch.export_orchestration_state())
print(f"State size: {state_size} bytes")

# Verify telemetry buffer cleanup
history_len = len(orch.state.telemetry_history.get("dc1-delhi", []))
print(f"Telemetry samples: {history_len}")  # Should stay <=1000
```

## Best Practices

1. **Always call health_check() after initialization**
   - Ensures all components are operational
   - Catches configuration issues early

2. **Run cycles at consistent intervals**
   - For Streamlit: every page load or via interval timer
   - For APIs: background task every 1-2 seconds

3. **Process anomalies → incidents → events in order**
   - Maintains data consistency
   - Proper event causality

4. **Use AI context for troubleshooting queries**
   - Provides comprehensive operational state
   - Enables better AI reasoning

5. **Export state periodically for audit trail**
   - Supports compliance tracking
   - Enables debugging production issues

6. **Monitor critical devices in dashboard**
   - Real-time visibility
   - Quick remediation

---

For detailed architecture, see: **ORCHESTRATION_SUMMARY.md**  
For test examples, see: **test_orchestration.py**
