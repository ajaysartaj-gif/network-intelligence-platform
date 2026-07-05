"""
Knowledge Package (KP) schema.

This is the ONLY thing that couples the RAG engine to the Mismatch strategy.
- The RAG engine's job is to PRODUCE a validated KP from documentation.
- The Mismatch strategy's job is to CONSUME a KP and run a fixed, deterministic
  investigation loop over it.

Neither side contains a single OSPF-specific line of logic. OSPF (or HSRP, BGP,
duplex, MTU...) lives entirely inside a KP instance = "declared structure +
causality, never a stored conclusion" (Constitution v1).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Relation(str, Enum):
    # The two ends of a relationship must agree on this parameter...
    MUST_EQUAL = "must_equal"
    # ...or must NOT collide on it (e.g. OSPF router-id, eBGP peer AS).
    MUST_DIFFER = "must_differ"


@dataclass(frozen=True)
class MatchParameter:
    name: str                      # normalized, VENDOR-NEUTRAL semantic name
    relation: Relation
    fatal_if_violated: bool        # does a violation break the relationship?
    read_intent: str               # WHAT to read (semantic) - adapter maps to a command
    symptom_if_violated: str = ""  # causal claim: observable symptom this violation predicts
    applies_when: str = ""         # optional guard, e.g. "network_type != point_to_point"
    provenance: str = ""           # doc/section this parameter was derived from


@dataclass
class KnowledgePackage:
    relationship_type: str         # e.g. "ospf_adjacency"
    enumerate_intent: str          # how to list instances of this relationship + peer state
    healthy_states: tuple          # states that mean "this relationship is fine"
    parameters: list               # list[MatchParameter]
    source_provenance: list = field(default_factory=list)  # docs the whole KP came from
    version: str = "1"

    def validate(self) -> "KnowledgePackage":
        assert self.relationship_type, "relationship_type required"
        assert self.parameters, "a KP with no parameters cannot investigate anything"
        names = [p.name for p in self.parameters]
        assert len(names) == len(set(names)), f"duplicate parameter names: {names}"
        for p in self.parameters:
            assert isinstance(p.relation, Relation)
            assert p.read_intent, f"parameter {p.name} has no read_intent"
        return self
