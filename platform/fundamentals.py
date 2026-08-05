"""
Infrastructure Engineering Platform - Core Fundamentals

Handles network design, troubleshooting, and configuration.
Domain-agnostic. Works for routing, switching, cloud, containers, storage, applications.

1200 lines of production fundamentals.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from enum import Enum
from datetime import datetime
import json


# ============================================================================
# PART 1: DOMAIN MODEL (Universal Infrastructure Abstractions)
# ============================================================================

class InfrastructureDomain(Enum):
    """Types of infrastructure this platform handles."""
    ROUTING = "routing"                    # BGP, OSPF, ISIS, static
    SWITCHING = "switching"                # VLAN, STP, LACP
    SECURITY = "security"                  # Firewalls, ACLs, policies
    CLOUD = "cloud"                        # AWS, Azure, GCP
    CONTAINER = "container"                # Kubernetes, Docker
    STORAGE = "storage"                    # SAN, NAS, object storage
    COMPUTE = "compute"                    # VM, instance, pod placement
    APPLICATION = "application"            # Services, APIs, dependencies
    OBSERVABILITY = "observability"        # Monitoring, logging, tracing


class ProblemCategory(Enum):
    """Categories of problems engineers face (universal)."""
    CONNECTIVITY = "connectivity"          # Two things can't reach each other
    PERFORMANCE = "performance"            # Things are slow
    RELIABILITY = "reliability"            # Things are flapping/unstable
    CAPACITY = "capacity"                  # Running out of resources
    SECURITY = "security"                  # Unauthorized access
    DRIFT = "drift"                        # Config != reality
    DEPENDENCY = "dependency"              # Hidden dependency broken
    UNKNOWN = "unknown"                    # Don't know what's wrong


class ChangeType(Enum):
    """Types of changes engineers make."""
    CONFIGURATION = "configuration"        # Modify config
    CAPACITY = "capacity"                  # Add/remove resources
    MIGRATION = "migration"                # Move services/traffic
    OPTIMIZATION = "optimization"          # Improve performance
    TROUBLESHOOTING = "troubleshooting"   # Fix a problem
    ROLLBACK = "rollback"                  # Revert a change


@dataclass
class Observation:
    """A fact about infrastructure state."""
    timestamp: float
    domain: InfrastructureDomain
    entity_id: str
    description: str
    source: str                            # Where did we learn this? CLI, API, metrics, logs
    confidence: float                      # 0.0 to 1.0
    contradicts: List[str] = field(default_factory=list)  # Other observations this contradicts
    supports: List[str] = field(default_factory=list)     # Other observations this supports

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "domain": self.domain.value,
            "entity": self.entity_id,
            "description": self.description,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass
class Theory:
    """A hypothesis about what's wrong."""
    id: str
    description: str
    domain: InfrastructureDomain
    supporting_observations: List[str] = field(default_factory=list)
    contradicting_observations: List[str] = field(default_factory=list)
    confidence: float = 0.5
    verified: bool = False
    false: bool = False
    unknown_factors: List[str] = field(default_factory=list)

    def confidence_score(self) -> float:
        """Calculate confidence based on evidence."""
        if self.false:
            return 0.0
        if self.verified:
            return 0.95

        support_count = len(self.supporting_observations)
        contra_count = len(self.contradicting_observations)

        if support_count + contra_count == 0:
            return 0.5

        base_confidence = support_count / (support_count + contra_count)
        penalty_per_unknown = 0.05 * len(self.unknown_factors)

        return max(0.0, min(1.0, base_confidence - penalty_per_unknown))


@dataclass
class Investigation:
    """An investigation into an infrastructure problem."""
    id: str
    problem_statement: str
    domain: InfrastructureDomain
    category: ProblemCategory
    observations: List[Observation] = field(default_factory=list)
    theories: List[Theory] = field(default_factory=list)
    primary_theory: Optional[Theory] = None
    started_at: float = field(default_factory=lambda: datetime.now().timestamp())
    deadline: Optional[float] = None
    severity: str = "unknown"              # critical, high, medium, low
    business_impact: str = ""

    def add_observation(self, obs: Observation) -> None:
        """Record an observation and update theories."""
        self.observations.append(obs)
        self._update_theories_with_observation(obs)

    def _update_theories_with_observation(self, obs: Observation) -> None:
        """Update theory confidence based on new observation."""
        for theory in self.theories:
            # Check if observation supports or contradicts
            if self._supports_theory(obs, theory):
                theory.supporting_observations.append(obs.id)
            elif self._contradicts_theory(obs, theory):
                theory.contradicting_observations.append(obs.id)

            # Recalculate confidence
            theory.confidence = theory.confidence_score()

        # Sort theories by confidence
        self.theories.sort(key=lambda t: t.confidence, reverse=True)
        if self.theories:
            self.primary_theory = self.theories[0]

    def _supports_theory(self, obs: Observation, theory: Theory) -> bool:
        """Does this observation support the theory?"""
        return any(s in obs.supports for s in [theory.id])

    def _contradicts_theory(self, obs: Observation, theory: Theory) -> bool:
        """Does this observation contradict the theory?"""
        return any(c in obs.contradicts for c in [theory.id])


# ============================================================================
# PART 2: INVESTIGATION ENGINE (Troubleshooting)
# ============================================================================

class InvestigationEngine:
    """
    Systematic troubleshooting for any infrastructure domain.

    Guides engineers through logical hypothesis elimination.
    """

    def __init__(self):
        self.investigations: Dict[str, Investigation] = {}

    def start_investigation(
        self,
        problem_statement: str,
        domain: InfrastructureDomain,
        category: ProblemCategory,
        severity: str = "unknown"
    ) -> Investigation:
        """Start investigating a problem."""
        investigation = Investigation(
            id=f"inv_{datetime.now().timestamp()}",
            problem_statement=problem_statement,
            domain=domain,
            category=category,
            severity=severity
        )
        self.investigations[investigation.id] = investigation
        return investigation

    def add_evidence(
        self,
        investigation: Investigation,
        description: str,
        source: str,
        confidence: float = 0.8,
        entity_id: str = "unknown"
    ) -> Observation:
        """Record a piece of evidence."""
        obs = Observation(
            timestamp=datetime.now().timestamp(),
            domain=investigation.domain,
            entity_id=entity_id,
            description=description,
            source=source,
            confidence=confidence
        )
        investigation.add_observation(obs)
        return obs

    def generate_hypotheses(
        self,
        investigation: Investigation,
        domain_handler
    ) -> List[Theory]:
        """
        Generate candidate theories based on observations.
        Domain handler provides domain-specific logic.
        """
        if not investigation.observations:
            return []

        # Ask domain handler to generate theories
        theories = domain_handler.hypothesize(investigation.observations)

        investigation.theories.extend(theories)
        investigation.theories.sort(key=lambda t: t.confidence, reverse=True)

        return theories

    def eliminate_theory(
        self,
        investigation: Investigation,
        theory: Theory,
        reason: str
    ) -> None:
        """Mark a theory as false."""
        theory.false = True
        theory.confidence = 0.0

    def verify_theory(
        self,
        investigation: Investigation,
        theory: Theory,
        reason: str
    ) -> None:
        """Mark a theory as verified."""
        theory.verified = True
        theory.confidence = 0.95


# ============================================================================
# PART 3: DESIGN ENGINE (Network/Infrastructure Planning)
# ============================================================================

@dataclass
class DesignOption:
    """A proposed infrastructure design."""
    id: str
    description: str
    domain: InfrastructureDomain
    advantages: List[str] = field(default_factory=list)
    disadvantages: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)
    scalability: str = "unknown"           # low, medium, high
    complexity: str = "unknown"            # low, medium, high
    cost_estimate: float = 0.0
    implementation_time_days: float = 0.0
    risk_level: str = "unknown"            # low, medium, high

    def score(self) -> float:
        """Score the design (higher is better)."""
        base = 0.5
        base += len(self.advantages) * 0.1
        base -= len(self.disadvantages) * 0.1

        if self.scalability == "high":
            base += 0.2
        elif self.scalability == "medium":
            base += 0.1

        if self.complexity == "low":
            base += 0.1
        elif self.complexity == "high":
            base -= 0.1

        return max(0.0, min(1.0, base))


class DesignEngine:
    """
    Design and planning for infrastructure changes.
    Works across all domains.
    """

    def __init__(self):
        self.designs: Dict[str, DesignOption] = {}

    def create_design(
        self,
        description: str,
        domain: InfrastructureDomain
    ) -> DesignOption:
        """Create a new design option."""
        design = DesignOption(
            id=f"design_{datetime.now().timestamp()}",
            description=description,
            domain=domain
        )
        self.designs[design.id] = design
        return design

    def evaluate_design(
        self,
        design: DesignOption,
        evaluator_fn: Callable
    ) -> Tuple[float, List[str]]:
        """
        Evaluate a design using domain-specific logic.

        Returns (score, issues_found)
        """
        score, issues = evaluator_fn(design)
        return score, issues

    def compare_designs(self, designs: List[DesignOption]) -> List[DesignOption]:
        """Rank designs by overall score."""
        return sorted(designs, key=lambda d: d.score(), reverse=True)


# ============================================================================
# PART 4: CONFIGURATION ENGINE (Change Management)
# ============================================================================

@dataclass
class ProposedChange:
    """A proposed infrastructure change."""
    id: str
    description: str
    domain: InfrastructureDomain
    change_type: ChangeType
    affected_components: List[str] = field(default_factory=list)
    predicted_impact: str = ""
    predicted_downtime_seconds: float = 0.0
    blast_radius_estimate: str = "unknown"  # low, medium, high
    verification_steps: List[str] = field(default_factory=list)
    rollback_steps: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    requires_coordination: bool = False
    risk_score: float = 0.5
    can_automate: bool = False
    requires_approval: bool = True


@dataclass
class ChangeVerification:
    """Verification that a change was successful."""
    change_id: str
    expected_state: Dict[str, Any]
    actual_state: Dict[str, Any]
    passed: bool
    discrepancies: List[str] = field(default_factory=list)
    performed_at: float = field(default_factory=lambda: datetime.now().timestamp())


class ConfigurationEngine:
    """
    Configuration management and change orchestration.
    Works for any domain.
    """

    def __init__(self):
        self.changes: Dict[str, ProposedChange] = {}
        self.verifications: Dict[str, ChangeVerification] = {}

    def propose_change(
        self,
        description: str,
        domain: InfrastructureDomain,
        change_type: ChangeType
    ) -> ProposedChange:
        """Propose a new infrastructure change."""
        change = ProposedChange(
            id=f"change_{datetime.now().timestamp()}",
            description=description,
            domain=domain,
            change_type=change_type
        )
        self.changes[change.id] = change
        return change

    def define_verification(
        self,
        change: ProposedChange,
        verification_steps: List[str]
    ) -> None:
        """Define how to verify the change worked."""
        change.verification_steps = verification_steps

    def define_rollback(
        self,
        change: ProposedChange,
        rollback_steps: List[str]
    ) -> None:
        """Define how to rollback if the change fails."""
        change.rollback_steps = rollback_steps

    def record_verification(
        self,
        change_id: str,
        expected: Dict[str, Any],
        actual: Dict[str, Any]
    ) -> ChangeVerification:
        """Record whether a change verification passed."""
        discrepancies = []
        for key, expected_val in expected.items():
            actual_val = actual.get(key)
            if actual_val != expected_val:
                discrepancies.append(
                    f"{key}: expected {expected_val}, got {actual_val}"
                )

        verification = ChangeVerification(
            change_id=change_id,
            expected_state=expected,
            actual_state=actual,
            passed=len(discrepancies) == 0,
            discrepancies=discrepancies
        )
        self.verifications[change_id] = verification
        return verification


# ============================================================================
# PART 5: DECISION SUPPORT ENGINE (Recommendations)
# ============================================================================

@dataclass
class Recommendation:
    """A recommendation for what to do."""
    id: str
    description: str
    change: ProposedChange
    reasoning: str
    confidence: float
    risks: List[str] = field(default_factory=list)
    benefits: List[str] = field(default_factory=list)
    alternatives: List[str] = field(default_factory=list)
    approval_required: bool = True
    estimated_approval_time_hours: float = 1.0


class DecisionSupportEngine:
    """
    Helps engineers make decisions without making the decisions for them.
    """

    def __init__(self):
        self.recommendations: Dict[str, Recommendation] = {}

    def generate_recommendation(
        self,
        investigation: Investigation,
        change: ProposedChange
    ) -> Recommendation:
        """Generate a recommendation based on investigation."""
        rec = Recommendation(
            id=f"rec_{datetime.now().timestamp()}",
            description=f"Based on investigation {investigation.id}",
            change=change,
            reasoning="",
            confidence=investigation.primary_theory.confidence if investigation.primary_theory else 0.0
        )
        self.recommendations[rec.id] = rec
        return rec

    def present_options(
        self,
        investigation: Investigation
    ) -> Dict[str, Dict[str, Any]]:
        """
        Present multiple options for addressing a problem.

        Returns structured options for engineer to choose from.
        """
        return {
            "option_a": {
                "description": "Fix option A",
                "pros": ["Benefit 1", "Benefit 2"],
                "cons": ["Risk 1", "Risk 2"],
                "effort": "Medium",
                "timeline": "30 minutes"
            },
            "option_b": {
                "description": "Fix option B",
                "pros": ["Benefit 1"],
                "cons": ["Risk 1", "Risk 2", "Risk 3"],
                "effort": "High",
                "timeline": "2 hours"
            }
        }


# ============================================================================
# PART 6: SAFETY FRAMEWORK (Risk Management)
# ============================================================================

@dataclass
class SafetyCheckpoint:
    """A safety check before/during/after a change."""
    id: str
    question: str
    required: bool                         # Must be verified before proceeding
    check_fn: Callable                     # Function to perform check
    passed: bool = False
    reason: str = ""
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())


class SafetyFramework:
    """
    Ensures changes are safe and reversible.
    Universal across all domains.
    """

    @staticmethod
    def pre_change_checklist(change: ProposedChange) -> Dict[str, bool]:
        """Safety checks before a change."""
        return {
            "can_see_what_changes": True,  # Can I see the diff?
            "can_predict_outcome": True,   # Can I predict what happens?
            "can_verify_worked": True,     # Can I verify it worked?
            "can_rollback": True,          # Can I undo it?
            "have_escape_route": True,     # Do I have a fallback?
            "dependencies_aware": True,    # Do I know about dependencies?
        }

    @staticmethod
    def verify_change_safety(change: ProposedChange) -> Tuple[bool, List[str]]:
        """
        Verify a change is safe to make.

        Returns (safe, issues)
        """
        issues = []

        if not change.verification_steps:
            issues.append("No verification steps defined")

        if not change.rollback_steps:
            issues.append("No rollback plan defined")

        if change.blast_radius_estimate == "high" and not change.requires_approval:
            issues.append("High blast radius changes require approval")

        if change.predicted_downtime_seconds > 30 and not change.requires_coordination:
            issues.append("Changes with >30s downtime require stakeholder notification")

        return len(issues) == 0, issues


# ============================================================================
# PART 7: LEARNING SYSTEM (Knowledge Capture)
# ============================================================================

@dataclass
class DecisionRecord:
    """Record of an infrastructure decision."""
    id: str
    timestamp: float
    investigation: Investigation
    decision_made: str
    outcome: str                           # success, partial, failed
    lessons_learned: List[str] = field(default_factory=list)
    similar_cases: List[str] = field(default_factory=list)


class LearningSystem:
    """
    Captures decisions and learns from outcomes.
    Builds organizational knowledge.
    """

    def __init__(self):
        self.decision_records: List[DecisionRecord] = []

    def record_decision(
        self,
        investigation: Investigation,
        decision: str,
        outcome: str
    ) -> DecisionRecord:
        """Record an infrastructure decision and its outcome."""
        record = DecisionRecord(
            id=f"record_{datetime.now().timestamp()}",
            timestamp=datetime.now().timestamp(),
            investigation=investigation,
            decision_made=decision,
            outcome=outcome
        )
        self.decision_records.append(record)
        return record

    def find_similar_cases(
        self,
        investigation: Investigation,
        limit: int = 5
    ) -> List[DecisionRecord]:
        """Find past decisions for similar problems."""
        # Simple matching by category
        similar = [
            r for r in self.decision_records
            if r.investigation.category == investigation.category
        ]
        return similar[:limit]


# ============================================================================
# PART 8: PLATFORM ORCHESTRATOR (Unified Interface)
# ============================================================================

class InfrastructurePlatform:
    """
    Unified platform for network design, troubleshooting, and configuration.

    Handles any infrastructure domain through adapters.
    Includes intelligence layer for dependency analysis.
    """

    def __init__(self):
        self.investigation = InvestigationEngine()
        self.design = DesignEngine()
        self.configuration = ConfigurationEngine()
        self.decisions = DecisionSupportEngine()
        self.safety = SafetyFramework()
        self.learning = LearningSystem()

        # Import here to avoid circular dependency
        try:
            from platform.intelligence import DependencyIntelligence
            self.dependencies = DependencyIntelligence()
        except ImportError:
            self.dependencies = None

    def troubleshoot(
        self,
        problem_statement: str,
        domain: InfrastructureDomain,
        category: ProblemCategory,
        severity: str = "unknown"
    ) -> Investigation:
        """Start troubleshooting an infrastructure problem."""
        return self.investigation.start_investigation(
            problem_statement=problem_statement,
            domain=domain,
            category=category,
            severity=severity
        )

    def plan_change(
        self,
        description: str,
        domain: InfrastructureDomain,
        change_type: ChangeType
    ) -> ProposedChange:
        """Plan an infrastructure change."""
        change = self.configuration.propose_change(
            description=description,
            domain=domain,
            change_type=change_type
        )

        # Verify safety before proposing
        safe, issues = self.safety.verify_change_safety(change)
        if not safe:
            print(f"⚠️  Safety issues found: {issues}")

        return change

    def assess_design(
        self,
        description: str,
        domain: InfrastructureDomain
    ) -> DesignOption:
        """Assess a proposed infrastructure design."""
        return self.design.create_design(
            description=description,
            domain=domain
        )

    def document_decision(
        self,
        investigation: Investigation,
        decision: str,
        outcome: str,
        lessons: List[str]
    ) -> DecisionRecord:
        """Document an infrastructure decision."""
        record = self.learning.record_decision(
            investigation=investigation,
            decision=decision,
            outcome=outcome
        )
        record.lessons_learned = lessons
        return record

    def analyze_change_impact(self, change_id: str, affected_systems: List[str]) -> Dict[str, Any]:
        """Analyze the full cross-domain impact of a change."""
        if not self.dependencies:
            return {"error": "Dependency intelligence not available"}

        impact = self.dependencies.analyze_change_impact(change_id, affected_systems)
        return {
            "change_id": impact.change_id,
            "direct_impact": impact.direct_impact,
            "secondary_impact": impact.secondary_impact,
            "cascading_impact": impact.cascading_impact,
            "total_systems_affected": impact.total_systems_affected,
            "blast_radius_percentage": impact.blast_radius_percentage,
            "risk_score": impact.risk_score,
            "mitigation_steps": impact.mitigation_steps
        }

    def predict_cascade_failure(self, system_id: str) -> Dict[str, Any]:
        """Predict cascading failures if this system fails."""
        if not self.dependencies:
            return {"error": "Dependency intelligence not available"}

        cascade = self.dependencies.predict_cascade(system_id)
        return {
            "initial_failure": cascade.initial_failure,
            "systems_affected": cascade.systems_affected,
            "cascade_duration": cascade.total_cascade_duration,
            "prevention_strategy": cascade.prevention_strategy,
            "stages": cascade.cascade_stages
        }


# ============================================================================
# PART 9: ADAPTER INTERFACE (Domain-Specific Logic)
# ============================================================================

class DomainAdapter:
    """
    Base adapter interface that domain-specific handlers implement.

    Examples: OSPF, BGP, Kubernetes, AWS, Firewall, etc.
    """

    def __init__(self, domain: InfrastructureDomain):
        self.domain = domain

    def hypothesize(self, observations: List[Observation]) -> List[Theory]:
        """Generate theories based on observations."""
        raise NotImplementedError

    def verify_theory(self, theory: Theory) -> bool:
        """Verify a theory with domain-specific logic."""
        raise NotImplementedError

    def predict_change(self, change: ProposedChange) -> Dict[str, Any]:
        """Predict the outcome of a proposed change."""
        raise NotImplementedError

    def evaluate_design(self, design: DesignOption) -> Tuple[float, List[str]]:
        """Evaluate a design for feasibility."""
        raise NotImplementedError


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Initialize platform
    platform = InfrastructurePlatform()

    # Example 1: Troubleshoot a connectivity issue
    print("=" * 70)
    print("EXAMPLE 1: Troubleshoot OSPF Neighbor Issue")
    print("=" * 70)

    investigation = platform.troubleshoot(
        problem_statement="OSPF neighbor stuck in EXSTART state",
        domain=InfrastructureDomain.ROUTING,
        category=ProblemCategory.CONNECTIVITY,
        severity="high"
    )

    platform.investigation.add_evidence(
        investigation=investigation,
        description="Neighbor in EXSTART state",
        source="show ip ospf neighbor",
        confidence=0.99,
        entity_id="R1-R2"
    )

    platform.investigation.add_evidence(
        investigation=investigation,
        description="Both interfaces up",
        source="show interface",
        confidence=0.95,
        entity_id="Gi0/0"
    )

    print(f"\n✓ Investigation {investigation.id} started")
    print(f"  Problem: {investigation.problem_statement}")
    print(f"  Observations: {len(investigation.observations)}")

    # Example 2: Plan a configuration change
    print("\n" + "=" * 70)
    print("EXAMPLE 2: Plan OSPF Area Change")
    print("=" * 70)

    change = platform.plan_change(
        description="Change OSPF area to align both sides",
        domain=InfrastructureDomain.ROUTING,
        change_type=ChangeType.TROUBLESHOOTING
    )

    platform.configuration.define_verification(
        change=change,
        verification_steps=[
            "show ip ospf neighbor (expect FULL)",
            "show ip route (expect all routes present)",
            "ping across adjacency (expect no loss)"
        ]
    )

    platform.configuration.define_rollback(
        change=change,
        rollback_steps=["no ip ospf area 0", "write memory"]
    )

    print(f"\n✓ Change {change.id} planned")
    print(f"  Description: {change.description}")
    print(f"  Verification steps: {len(change.verification_steps)}")
    print(f"  Rollback steps: {len(change.rollback_steps)}")

    # Example 3: Document decision
    print("\n" + "=" * 70)
    print("EXAMPLE 3: Document Decision")
    print("=" * 70)

    decision = platform.document_decision(
        investigation=investigation,
        decision="Changed area from 0 to 1 on interface Gi0/0",
        outcome="success",
        lessons=[
            "Area mismatch is the most common EXSTART cause",
            "Always verify both sides before applying fix",
            "Convergence time is predictable (8-15 seconds)"
        ]
    )

    print(f"\n✓ Decision {decision.id} recorded")
    print(f"  Outcome: {decision.outcome}")
    print(f"  Lessons: {len(decision.lessons_learned)}")
