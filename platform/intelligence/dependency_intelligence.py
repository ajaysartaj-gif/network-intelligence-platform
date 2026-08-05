"""
Cross-Domain Dependency Intelligence

Discovers dependencies from incidents, models cascading failures, and predicts
the full impact of changes across routing, cloud, containers, storage, and applications.

73% of outages are caused by hidden dependencies. This layer makes them visible.
"""

from typing import Dict, Any, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
from platform.core.domain import Observation, Investigation, DomainType


class DependencyType(Enum):
    """Types of dependencies between systems."""
    DIRECT = "direct"  # A directly needs B
    INDIRECT = "indirect"  # A needs B through C
    CASCADING = "cascading"  # A fails → B fails → C fails
    TIMING = "timing"  # A must complete before B
    RESOURCE = "resource"  # A and B compete for same resource
    TRANSITIVE = "transitive"  # A → B → C (discovered through incidents)


@dataclass
class DependencyEdge:
    """An edge in the dependency graph."""
    source_id: str
    target_id: str
    dependency_type: DependencyType
    confidence: float  # How sure are we this dependency exists? (0.0-1.0)
    discovered_from: List[str] = field(default_factory=list)  # Incident IDs that revealed this
    failure_probability: float = 0.0  # If source fails, probability target fails
    time_to_propagate: float = 0.0  # How long (seconds) until failure propagates
    severity: str = "medium"  # low, medium, high, critical


@dataclass
class DependencyNode:
    """A system or component in the dependency graph."""
    id: str
    domain: DomainType
    name: str
    criticality: str  # low, medium, high, critical
    health_status: str = "unknown"  # healthy, degraded, failing, unknown
    dependencies: List[DependencyEdge] = field(default_factory=list)
    dependents: List[DependencyEdge] = field(default_factory=list)
    failure_history: List[Tuple[float, str]] = field(default_factory=list)  # (timestamp, reason)


@dataclass
class ChangeImpact:
    """The predicted impact of a change."""
    change_id: str
    direct_impact: List[str]  # Systems directly affected
    secondary_impact: List[str]  # Systems affected indirectly
    cascading_impact: List[str]  # Systems affected through cascades
    total_systems_affected: int
    estimated_downtime: float  # minutes
    estimated_recovery_time: float  # minutes
    blast_radius_percentage: float  # % of infrastructure affected
    confidence: float  # How confident in this prediction? (0.0-1.0)
    risk_score: float  # 0.0-1.0, higher = riskier
    mitigation_steps: List[str] = field(default_factory=list)


@dataclass
class CascadeScenario:
    """A predicted cascade of failures."""
    initial_failure: str
    cascade_stages: List[Tuple[float, str, float]]  # (time_offset, system_affected, probability)
    total_cascade_duration: float  # seconds
    systems_affected: int
    probability: float  # Likelihood this cascade happens (0.0-1.0)
    prevention_strategy: Optional[str] = None


class DependencyGraph:
    """Maps all system dependencies and their properties."""

    def __init__(self):
        self.nodes: Dict[str, DependencyNode] = {}
        self.edges: Dict[Tuple[str, str], DependencyEdge] = {}

    def add_node(self, node: DependencyNode) -> None:
        """Add a system to the graph."""
        self.nodes[node.id] = node

    def add_edge(self, edge: DependencyEdge) -> None:
        """Add a dependency between systems."""
        key = (edge.source_id, edge.target_id)
        self.edges[key] = edge

        # Update node references
        if edge.source_id in self.nodes:
            self.nodes[edge.source_id].dependents.append(edge)
        if edge.target_id in self.nodes:
            self.nodes[edge.target_id].dependencies.append(edge)

    def find_path(self, from_id: str, to_id: str) -> Optional[List[str]]:
        """Find dependency path from one system to another."""
        visited = set()
        path = []

        def dfs(current_id: str) -> bool:
            if current_id == to_id:
                path.append(current_id)
                return True

            visited.add(current_id)

            if current_id not in self.nodes:
                return False

            for edge in self.nodes[current_id].dependencies:
                if edge.source_id not in visited:
                    if dfs(edge.source_id):
                        path.append(current_id)
                        return True

            return False

        if dfs(from_id):
            return list(reversed(path))
        return None

    def find_transitive_dependencies(self, system_id: str, depth: int = 3) -> Dict[str, int]:
        """Find all systems that transitively depend on this one."""
        transitive = {}
        visited = set()

        def explore(current_id: str, current_depth: int) -> None:
            if current_id in visited or current_depth == 0:
                return

            visited.add(current_id)

            if current_id not in self.nodes:
                return

            for edge in self.nodes[current_id].dependents:
                target_id = edge.target_id
                if target_id not in transitive:
                    transitive[target_id] = current_depth
                explore(target_id, current_depth - 1)

        explore(system_id, depth)
        return transitive

    def discover_from_incident(self, incident_id: str, cascade_chain: List[Tuple[str, float]]) -> None:
        """Learn dependencies from an incident where failures cascaded."""
        # cascade_chain: [(system_id, time_offset), ...]
        for i in range(len(cascade_chain) - 1):
            source_id, source_time = cascade_chain[i]
            target_id, target_time = cascade_chain[i + 1]
            time_delta = target_time - source_time

            key = (source_id, target_id)
            if key in self.edges:
                edge = self.edges[key]
                edge.discovered_from.append(incident_id)
                edge.confidence = min(1.0, edge.confidence + 0.05)
                edge.time_to_propagate = time_delta
            else:
                edge = DependencyEdge(
                    source_id=source_id,
                    target_id=target_id,
                    dependency_type=DependencyType.CASCADING,
                    confidence=0.6,
                    discovered_from=[incident_id],
                    time_to_propagate=time_delta,
                    failure_probability=0.85,
                )
                self.add_edge(edge)


class ChangeImpactAnalyzer:
    """Analyzes the impact of proposed changes across the dependency graph."""

    def __init__(self, graph: DependencyGraph):
        self.graph = graph

    def analyze(self, change_id: str, affected_systems: List[str]) -> ChangeImpact:
        """Predict the full impact of a change to specific systems."""
        direct_impact = set(affected_systems)
        secondary_impact: Set[str] = set()
        cascading_impact: Set[str] = set()

        # Find all systems that depend on the affected systems
        for system_id in affected_systems:
            # Direct dependents
            if system_id in self.graph.nodes:
                for edge in self.graph.nodes[system_id].dependents:
                    secondary_impact.add(edge.target_id)

                    # Cascading dependents (systems that depend on the dependents)
                    transitive = self.graph.find_transitive_dependencies(system_id, depth=2)
                    cascading_impact.update(transitive.keys())

        total_systems = len(direct_impact) + len(secondary_impact) + len(cascading_impact)

        # Calculate blast radius
        total_nodes = len(self.graph.nodes)
        blast_radius = (total_systems / total_nodes * 100) if total_nodes > 0 else 0

        # Estimate downtime and recovery
        estimated_downtime = self._estimate_downtime(direct_impact, secondary_impact)
        estimated_recovery = self._estimate_recovery_time(cascading_impact)

        # Generate risk score
        risk_score = self._calculate_risk_score(
            len(direct_impact),
            len(secondary_impact),
            len(cascading_impact),
            blast_radius
        )

        # Mitigation steps
        mitigation = self._generate_mitigation_steps(
            affected_systems,
            secondary_impact,
            cascading_impact
        )

        confidence = self._estimate_confidence(affected_systems)

        return ChangeImpact(
            change_id=change_id,
            direct_impact=list(direct_impact),
            secondary_impact=list(secondary_impact),
            cascading_impact=list(cascading_impact),
            total_systems_affected=total_systems,
            estimated_downtime=estimated_downtime,
            estimated_recovery_time=estimated_recovery,
            blast_radius_percentage=blast_radius,
            confidence=confidence,
            risk_score=risk_score,
            mitigation_steps=mitigation
        )

    def _estimate_downtime(self, direct: Set[str], secondary: Set[str]) -> float:
        """Estimate customer-facing downtime in minutes."""
        base_time = len(direct) * 0.5  # 30 seconds per direct system
        secondary_time = len(secondary) * 0.25  # 15 seconds per secondary system
        return base_time + secondary_time

    def _estimate_recovery_time(self, cascading: Set[str]) -> float:
        """Estimate total recovery time in minutes."""
        if not cascading:
            return 1.0
        return len(cascading) * 0.5 + 2.0  # Base recovery time

    def _calculate_risk_score(self, direct: int, secondary: int, cascading: int, blast_radius: float) -> float:
        """Calculate risk score 0.0-1.0."""
        # More systems affected = higher risk
        system_risk = min(1.0, (direct + secondary * 0.5 + cascading * 0.25) / 10)

        # Larger blast radius = higher risk
        radius_risk = blast_radius / 100

        # Weighted combination
        return (system_risk * 0.6 + radius_risk * 0.4)

    def _generate_mitigation_steps(self, affected: List[str], secondary: Set[str], cascading: Set[str]) -> List[str]:
        """Generate steps to mitigate change impact."""
        steps = []

        if secondary:
            steps.append(f"Notify {len(secondary)} dependent systems before change")
            steps.append("Establish post-change verification for dependent systems")

        if cascading:
            steps.append(f"Monitor for cascading failures affecting {len(cascading)} systems")
            steps.append("Have rollback plan for all impacted systems ready")

        if len(affected) > 3:
            steps.append("Consider staged rollout instead of all-at-once change")

        steps.append("Post-change: Verify dependent systems within 5 minutes")

        return steps

    def _estimate_confidence(self, affected_systems: List[str]) -> float:
        """How confident are we in this impact prediction?"""
        confidence = 0.8

        for system_id in affected_systems:
            if system_id in self.graph.nodes:
                node = self.graph.nodes[system_id]
                # Higher confidence for nodes with well-understood dependencies
                known_deps = len([e for e in node.dependents if e.confidence > 0.7])
                if known_deps > 0:
                    confidence += 0.05

        return min(1.0, confidence)


class CascadePredictor:
    """Predicts cascading failures and their probability."""

    def __init__(self, graph: DependencyGraph):
        self.graph = graph

    def predict_cascade(self, initial_failure_id: str) -> CascadeScenario:
        """Predict what will fail if this system fails."""
        stages: List[Tuple[float, str, float]] = []
        affected_systems = {initial_failure_id}
        current_time = 0.0

        # BFS to find cascade stages
        current_wave = [initial_failure_id]
        visited = {initial_failure_id}

        while current_wave:
            next_wave = []
            stage_time = current_time

            for system_id in current_wave:
                if system_id not in self.graph.nodes:
                    continue

                # Find systems that depend on this one
                for edge in self.graph.nodes[system_id].dependents:
                    target_id = edge.target_id

                    if target_id not in visited:
                        visited.add(target_id)
                        next_wave.append(target_id)
                        affected_systems.add(target_id)

                        # Record this stage
                        propagation_time = edge.time_to_propagate if edge.time_to_propagate > 0 else 5.0
                        probability = edge.failure_probability
                        stages.append((stage_time + propagation_time, target_id, probability))

            current_time += 10.0  # Wait between cascade waves
            current_wave = next_wave

        # Calculate prevention strategy
        prevention = self._suggest_prevention(initial_failure_id, affected_systems)

        total_duration = stages[-1][0] if stages else 0.0

        return CascadeScenario(
            initial_failure=initial_failure_id,
            cascade_stages=stages,
            total_cascade_duration=total_duration,
            systems_affected=len(affected_systems),
            probability=self._calculate_cascade_probability(stages),
            prevention_strategy=prevention
        )

    def _calculate_cascade_probability(self, stages: List[Tuple[float, str, float]]) -> float:
        """Calculate overall cascade probability as product of individual probabilities."""
        if not stages:
            return 0.0

        probability = 1.0
        for _, _, stage_prob in stages:
            probability *= stage_prob

        return probability

    def _suggest_prevention(self, system_id: str, affected: Set[str]) -> str:
        """Suggest how to prevent this cascade."""
        if len(affected) <= 2:
            return "This cascade is limited. Monitor for early warning signs."

        return f"Implement circuit breaker for {system_id} to prevent cascading failures to {len(affected)-1} dependent systems"


class DependencyIntelligence:
    """Main class coordinating dependency intelligence."""

    def __init__(self):
        self.graph = DependencyGraph()
        self.impact_analyzer = ChangeImpactAnalyzer(self.graph)
        self.cascade_predictor = CascadePredictor(self.graph)

    def register_system(
        self,
        system_id: str,
        domain: DomainType,
        name: str,
        criticality: str = "medium"
    ) -> None:
        """Register a system in the dependency graph."""
        node = DependencyNode(
            id=system_id,
            domain=domain,
            name=name,
            criticality=criticality
        )
        self.graph.add_node(node)

    def register_dependency(
        self,
        source_id: str,
        target_id: str,
        dependency_type: DependencyType = DependencyType.DIRECT,
        confidence: float = 0.9,
        failure_probability: float = 0.8
    ) -> None:
        """Register a known dependency."""
        edge = DependencyEdge(
            source_id=source_id,
            target_id=target_id,
            dependency_type=dependency_type,
            confidence=confidence,
            failure_probability=failure_probability
        )
        self.graph.add_edge(edge)

    def analyze_change_impact(self, change_id: str, affected_systems: List[str]) -> ChangeImpact:
        """Analyze the full impact of a change."""
        return self.impact_analyzer.analyze(change_id, affected_systems)

    def predict_cascade(self, failed_system_id: str) -> CascadeScenario:
        """Predict what will cascade if this system fails."""
        return self.cascade_predictor.predict_cascade(failed_system_id)

    def learn_from_incident(self, incident_id: str, cascade_chain: List[Tuple[str, float]]) -> None:
        """Learn dependencies from an incident."""
        self.graph.discover_from_incident(incident_id, cascade_chain)

    def get_dependency_summary(self, system_id: str) -> Dict[str, Any]:
        """Get a summary of a system's dependencies."""
        if system_id not in self.graph.nodes:
            return {}

        node = self.graph.nodes[system_id]
        direct_deps = [e.source_id for e in node.dependencies]
        direct_dependents = [e.target_id for e in node.dependents]
        transitive = self.graph.find_transitive_dependencies(system_id)

        return {
            "system_id": system_id,
            "criticality": node.criticality,
            "direct_dependencies": direct_deps,
            "direct_dependents": direct_dependents,
            "transitive_dependents": transitive,
            "failure_history": node.failure_history
        }

    def generate_intelligence_report(self, change_id: str, affected_systems: List[str]) -> str:
        """Generate a human-readable intelligence report for a change."""
        impact = self.analyze_change_impact(change_id, affected_systems)

        report = f"""
╔════════════════════════════════════════════════════════════════╗
║         CROSS-DOMAIN DEPENDENCY INTELLIGENCE REPORT            ║
╚════════════════════════════════════════════════════════════════╝

CHANGE: {change_id}
SYSTEMS BEING MODIFIED: {', '.join(affected_systems)}

━━ IMPACT ANALYSIS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Direct Impact (immediate):
  Systems: {len(impact.direct_impact)}
  {chr(10).join(['  • ' + s for s in impact.direct_impact])}

Secondary Impact (1 hop away):
  Systems: {len(impact.secondary_impact)}
  {chr(10).join(['  • ' + s for s in impact.secondary_impact][:5])}
  {'  ... and ' + str(len(impact.secondary_impact) - 5) + ' more' if len(impact.secondary_impact) > 5 else ''}

Cascading Impact (multiple hops):
  Systems: {len(impact.cascading_impact)}
  {chr(10).join(['  • ' + s for s in impact.cascading_impact][:3])}
  {'  ... and ' + str(len(impact.cascading_impact) - 3) + ' more' if len(impact.cascading_impact) > 3 else ''}

━━ RISK ASSESSMENT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Total Systems Affected: {impact.total_systems_affected}
Blast Radius: {impact.blast_radius_percentage:.1f}% of infrastructure
Risk Score: {impact.risk_score:.2f}/1.0 {'🔴 CRITICAL' if impact.risk_score > 0.7 else '🟠 HIGH' if impact.risk_score > 0.5 else '🟡 MEDIUM' if impact.risk_score > 0.3 else '🟢 LOW'}

Estimated Downtime: {impact.estimated_downtime:.1f} minutes
Estimated Recovery Time: {impact.estimated_recovery_time:.1f} minutes
Prediction Confidence: {impact.confidence * 100:.0f}%

━━ MITIGATION STEPS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{chr(10).join([f'{i+1}. {step}' for i, step in enumerate(impact.mitigation_steps)])}

━━ CASCADE RISK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For each affected system, here's what could cascade:
"""
        for system_id in impact.direct_impact:
            cascade = self.predict_cascade(system_id)
            report += f"""
{system_id}:
  If it fails → {cascade.systems_affected} more systems could fail
  Cascade duration: {cascade.total_cascade_duration:.0f} seconds
  Prevention: {cascade.prevention_strategy}
"""

        return report
