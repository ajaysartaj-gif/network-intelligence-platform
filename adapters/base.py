"""
Adapter boundary. The engine NEVER knows the vendor.

The adapter owns exactly one thing the engine is not allowed to know:
the mapping from a semantic `read_intent` -> a real command -> a normalized value.
That mapping is DATA (a dict), not code, so a new vendor is a new data table
(and, later, a RAG-populated one) rather than new engine logic.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Endpoint:
    device: str          # opaque device handle/name
    context: str = ""    # e.g. interface "GigabitEthernet0/0"; group id; peer ip


@dataclass
class RelationshipInstance:
    key: str                     # stable id for this instance
    local: Endpoint
    remote: Endpoint
    observed_state: str          # current state as the device reports it (e.g. "INIT", "FULL")


@dataclass
class ParameterValue:
    value: Optional[str]         # NORMALIZED value used for comparison (vendor-neutral)
    raw: str = ""                # raw text the value was parsed from (for trace mode)
    available: bool = True       # False if this end couldn't be read (far-end unmanaged, etc.)


class DeviceAdapter(ABC):
    vendor: str = "abstract"

    @abstractmethod
    def enumerate_relationship(self, relationship_type: str,
                               enumerate_intent: str) -> list[RelationshipInstance]:
        """Resolve BOTH ends of every instance of this relationship on the seed device."""

    @abstractmethod
    def read_parameter(self, endpoint: Endpoint, read_intent: str) -> ParameterValue:
        """Read + normalize one semantic parameter from one end. READ-ONLY."""

    @abstractmethod
    def generate_remediation(self, endpoint: Endpoint, param_name: str,
                             target_value: str) -> str:
        """Return the config that WOULD align this end to target_value.
        This is a proposal string only. It is NEVER applied here."""
