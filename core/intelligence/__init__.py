"""
core/intelligence
=================
The architectural backbone for NetBrain's Network Intelligence model.

Network Intelligence = Knowledge + Context + Memory + Reasoning
                     + Topology Understanding + Dependency Awareness
                     + Risk Assessment + Prediction + Decision Making
                     + Autonomous Execution + Continuous Learning

Each pillar is a first-class, code-bound, self-reporting Capability. Read the
whole-platform status with get_capability_registry().report().
"""
from core.intelligence.capability_model import (
    Capability, CapabilityStatus, CapabilityHealth,
    CapabilityRegistry, get_capability_registry, build_default_registry,
)

__all__ = [
    "Capability", "CapabilityStatus", "CapabilityHealth",
    "CapabilityRegistry", "get_capability_registry", "build_default_registry",
]
