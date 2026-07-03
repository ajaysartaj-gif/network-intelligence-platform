"""
Universal Vendor Adapter Framework
==================================
ONE universal Troubleshooting Engine; ALL OEM-specific behavior isolated in
Vendor Adapters behind a single SDK. The engine reasons only on normalized
objects and remediation intent, and never contains `if vendor == ...` logic.

Open for extension, closed for modification: adding a vendor means adding one
adapter module under `core/vendor/adapters/` — no change to the engine,
reasoning, evidence graph, hypothesis manager, planner, confidence calculator,
ranker, verification planner or session memory.

Design map
----------
Vendor SDK             → sdk.VendorAdapter (detect/capabilities/discover/
                         build_command/execute/parse_output/normalize/build_fix/
                         build_verification/build_rollback/validate/translate_error)
Registry & discovery   → registry.register / discover_adapters / detect_adapter
Normalized objects     → models.NormalizedObject (+ ObjectType, extensible)
Normalized operations  → operations.Operation / Op
Remediation intent     → operations.RemediationIntent / RemediationPlan
Normalized errors      → models.NormalizedError / ErrorClass
Capability discovery   → adapter.capabilities() + VendorProfile.capabilities
Single engine facade   → gateway.VendorGateway  (the engine's ONLY vendor door)
Reference adapters     → adapters/*.py  (illustrative; not the full set)

Usage
-----
    from core.vendor import VendorGateway
    gw = VendorGateway(send=my_ssh_send, hint_provider=my_hint_provider)

    from core.vendor.operations import Operation, Op, RemediationIntent
    neighbors, err = gw.collect(device, Operation(Op.GET_NEIGHBORS, {"protocol": "ospf"}))
    plan = gw.remediate(device, RemediationIntent("ignore_protocol_mtu",
                                                  {"protocol": "ospf", "interface": "Gi0/0"}))
"""
from .gateway import VendorGateway
from .registry import register, discover_adapters, detect_adapter, all_adapters, get_adapter
from .sdk import VendorAdapter, DeviceProbe, Transport
from .models import (
    NormalizedObject, ObjectType, NormalizedError, ErrorClass, VendorProfile,
    ValidationResult, obj,
)
from .operations import Operation, Op, RemediationIntent, RemediationPlan, KNOWN_OPERATIONS

__all__ = [
    "VendorGateway", "VendorAdapter", "DeviceProbe", "Transport",
    "register", "discover_adapters", "detect_adapter", "all_adapters", "get_adapter",
    "NormalizedObject", "ObjectType", "NormalizedError", "ErrorClass", "VendorProfile",
    "ValidationResult", "obj",
    "Operation", "Op", "RemediationIntent", "RemediationPlan", "KNOWN_OPERATIONS",
]
