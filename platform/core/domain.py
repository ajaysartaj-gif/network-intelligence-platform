"""
Domain-agnostic abstractions for any infrastructure problem.

Not OSPF. Not networking. Just "things that have state and configuration."
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from enum import Enum


class DomainType(Enum):
    """Types of infrastructure domains this platform can handle."""
    ROUTING = "routing"                    # OSPF, BGP, ISIS, static routes
    SWITCHING = "switching"                # VLAN, STP, port-channel
    SECURITY = "security"                  # Firewalls, ACLs, NAT
    CLOUD = "cloud"                        # AWS, Azure, GCP
    CONTAINER = "container"                # Kubernetes, Docker
    LOAD_BALANCING = "load_balancing"      # F5, ELB, Nginx
    STORAGE = "storage"                    # SAN, NFS, object storage
    COMPUTE = "compute"                    # VM, instance, pod placement
    APPLICATION = "application"            # Service, dependency, API
    OBSERVABILITY = "observability"        # Monitoring, logging, tracing


class ProblemType(Enum):
    """Types of problems engineers face (domain-agnostic)."""
    CONNECTIVITY = "connectivity"          # Two things can't reach each other
    PERFORMANCE = "performance"            # Things are slow
    RELIABILITY = "reliability"            # Things are flapping/unstable
    CAPACITY = "capacity"                  # Running out of resources
    SECURITY = "security"                  # Unauthorized access or blocking
    DRIFT = "drift"                        # Config doesn't match reality
    DEPENDENCY = "dependency"              # Hidden dependency broken
    UNKNOWN = "unknown"                    # We don't know what's wrong


@dataclass
class Entity:
    """Any infrastructure entity (router, server, pod, policy, etc.)."""
    id: str                                # Unique identifier
    domain: DomainType                     # What type of thing is this?
    name: str                              # Human-readable name
    type: str                              # Specific type (e.g., "router", "firewall", "deployment")
    config: Dict[str, Any]                 # Current configuration
    state: Dict[str, Any]                  # Current runtime state
    metadata: Dict[str, Any]               # Tags, labels, annotations

    def __hash__(self):
        return hash(self.id)


@dataclass
class Relationship:
    """Relationship between two entities."""
    source: Entity                         # From
    target: Entity                         # To
    type: str                              # Type of relationship (e.g., "peering", "allows", "depends_on")
    config: Dict[str, Any]                 # Configuration that defines this relationship
    state: Dict[str, Any]                  # Current state of relationship
    healthy: bool                          # Is it working?


@dataclass
class Observation:
    """An observed fact about the infrastructure."""
    timestamp: float                       # When did we observe this?
    entity: Optional[Entity]               # What was this about? (optional)
    relationship: Optional[Relationship]   # Or this relationship? (optional)
    description: str                       # What did we observe?
    source: str                            # Where did this come from? (CLI, API, telemetry, etc.)
    confidence: float                      # 0.0 to 1.0


@dataclass
class Hypothesis:
    """A potential explanation for why something isn't working."""
    description: str                       # What might be wrong?
    supporting_evidence: List[Observation] # What supports this?
    contradicting_evidence: List[Observation]  # What argues against it?
    confidence: float                      # 0.0 to 1.0
    next_test: Optional[str]              # What would we need to verify this?


@dataclass
class Investigation:
    """An investigation into an infrastructure problem."""
    id: str                                # Unique ID for this investigation
    problem: str                           # What's the problem?
    problem_type: ProblemType              # What category?
    observations: List[Observation]        # What have we learned?
    hypotheses: List[Hypothesis]           # What are our theories?
    primary_hypothesis: Optional[Hypothesis]  # Best guess
    started_at: float                      # When did investigation start?
    confidence: float                      # How sure are we?

    def add_observation(self, obs: Observation):
        """Record an observation."""
        self.observations.append(obs)
        self._update_hypotheses()

    def _update_hypotheses(self):
        """Rank hypotheses based on new observations."""
        # Sort by confidence
        self.hypotheses.sort(key=lambda h: h.confidence, reverse=True)
        if self.hypotheses:
            self.primary_hypothesis = self.hypotheses[0]
            self.confidence = self.primary_hypothesis.confidence


@dataclass
class Recommendation:
    """Recommendation for what to do about a problem."""
    description: str                       # What should we do?
    predicted_outcome: str                 # What will happen if we do this?
    predicted_timeline: str                # How long will it take?
    confidence: float                      # How sure are we?
    blast_radius: Dict[str, Any]          # What else will this affect?
    rollback_plan: Optional[str]          # How do we undo this?
    verification_steps: List[str]         # How do we know it worked?
    risks: List[str]                      # What could go wrong?
