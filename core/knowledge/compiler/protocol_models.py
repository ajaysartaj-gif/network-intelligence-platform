"""
core/knowledge/compiler/protocol_models.py
=============================================
Thin, backward-compatible shim over protocol_registry.py, which is now
the single canonical source of truth for every protocol's state model.
`ProtocolTransition`, `ProtocolStateModel`, `PROTOCOL_STATE_MODELS`, and
`build_protocol_model()` all keep their exact prior names/signatures/
behavior — nothing importing from this module needs to change.

See protocol_registry.py's own docstring for why the six state models
(OSPF/STP/BGP/LACP/HSRP/VRRP) live there now instead of here: adding a
protocol used to mean touching this file AND five others; now it's one
ProtocolSpec entry in protocol_registry.py.
"""
from __future__ import annotations

from typing import Dict, Optional

from core.knowledge.compiler.protocol_registry import (
    PROTOCOL_SPECS, ProtocolStateModel, ProtocolTransition,
)

__all__ = ["ProtocolTransition", "ProtocolStateModel", "PROTOCOL_STATE_MODELS", "build_protocol_model"]

PROTOCOL_STATE_MODELS: Dict[str, ProtocolStateModel] = {
    name: spec.state_model for name, spec in PROTOCOL_SPECS.items() if spec.state_model is not None
}


def build_protocol_model(protocol: str) -> Optional[ProtocolStateModel]:
    """Returns the seeded model for `protocol`, or None — deliberately
    never fabricates a transition table for a protocol not in the
    registry."""
    return PROTOCOL_STATE_MODELS.get((protocol or "").strip().lower())
