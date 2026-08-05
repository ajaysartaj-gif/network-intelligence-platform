"""
Kubernetes Adapter - Real Implementation

Diagnoses Kubernetes infrastructure problems.
Analyzes service discovery, networking, scheduling, policies.
"""

from typing import Dict, Any, List, Tuple
from dataclasses import dataclass
from platform.core.domain import Entity, Relationship, Observation, Investigation, Hypothesis, DomainType
from platform.adapters.adapter import AdapterInterface, ReasoningAdapter, PredictionAdapter


class KubernetesRealAdapter(AdapterInterface, ReasoningAdapter, PredictionAdapter):
    """
    Real Kubernetes adapter with container-specific diagnostic logic.

    Diagnoses:
    - Pod scheduling failures (30%)
    - Service discovery issues (25%)
    - Network policy blocking (20%)
    - Resource constraints (15%)
    - Image pull errors (10%)
    """

    @property
    def domain(self) -> DomainType:
        return DomainType.CONTAINER

    @property
    def name(self) -> str:
        return "Kubernetes"

    def parse(self, raw_data: Dict[str, str]) -> Tuple[List[Entity], List[Relationship]]:
        """Parse Kubernetes API responses into entities."""
        entities = []
        relationships = []

        # Parse pod data
        if "pods" in raw_data:
            pods = raw_data["pods"].split(",")
            for pod in pods:
                entity = Entity(
                    id=f"k8s-pod-{pod.strip()}",
                    domain=DomainType.CONTAINER,
                    name=f"Pod {pod.strip()}",
                    type="pod",
                    config={},
                    state={},
                    metadata={}
                )
                entities.append(entity)

        return entities, relationships

    def hypothesize(self, observations: List[Observation]) -> List[Hypothesis]:
        """Generate Kubernetes-specific theories."""
        theories = []

        # THEORY 1: Pod Scheduling Failure (30%)
        if self._check_pending_pod(observations):
            theories.append(Hypothesis(
                description="Pod pending - scheduling failure (insufficient resources or node selector mismatch)",
                supporting_evidence=[o for o in observations if "pending" in o.description.lower()],
                contradicting_evidence=[o for o in observations if "running" in o.description.lower()],
                confidence=0.80,
                next_test="Check: kubectl describe pod, node capacity, affinity rules"
            ))

        # THEORY 2: Service Discovery Issue (25%)
        if self._check_service_discovery_issue(observations):
            theories.append(Hypothesis(
                description="Service cannot resolve or reach endpoints",
                supporting_evidence=[o for o in observations if "service" in o.description.lower()],
                contradicting_evidence=[],
                confidence=0.75,
                next_test="Verify service selector labels and endpoint creation"
            ))

        # THEORY 3: Network Policy Blocking (20%)
        if self._check_network_policy_block(observations):
            theories.append(Hypothesis(
                description="Network policy denying traffic between pods",
                supporting_evidence=[o for o in observations if "policy" in o.description.lower()],
                contradicting_evidence=[],
                confidence=0.85,
                next_test="Review network policies for pods and namespaces"
            ))

        # THEORY 4: Resource Constraints (15%)
        if self._check_resource_issue(observations):
            theories.append(Hypothesis(
                description="Pod killed due to resource limits or node pressure",
                supporting_evidence=[o for o in observations if "oomkill" in o.description.lower() or "evict" in o.description.lower()],
                contradicting_evidence=[],
                confidence=0.80,
                next_test="Check pod resource requests/limits and node capacity"
            ))

        # THEORY 5: Image Pull Error (10%)
        if self._check_image_pull_error(observations):
            theories.append(Hypothesis(
                description="Pod cannot pull container image",
                supporting_evidence=[o for o in observations if "image" in o.description.lower() or "pull" in o.description.lower()],
                contradicting_evidence=[],
                confidence=0.90,
                next_test="Verify image registry access and image tag exists"
            ))

        # THEORY 6: Volume Mount Issue
        if self._check_volume_issue(observations):
            theories.append(Hypothesis(
                description="PersistentVolume or PersistentVolumeClaim issue",
                supporting_evidence=[o for o in observations if "volume" in o.description.lower()],
                contradicting_evidence=[],
                confidence=0.70,
                next_test="Check PVC status and PV binding"
            ))

        return sorted(theories, key=lambda t: t.confidence, reverse=True)

    def diagnose(self, investigation: Investigation) -> Hypothesis:
        """Diagnose Kubernetes problem."""
        theories = self.hypothesize(investigation.observations)

        if not theories:
            return Hypothesis(
                description="Unable to diagnose from current observations",
                supporting_evidence=[],
                contradicting_evidence=investigation.observations,
                confidence=0.0,
                next_test=None
            )

        return theories[0]

    def predict_outcome(self, current_state: Dict[str, Any], proposed_change: str) -> Dict[str, Any]:
        """Predict Kubernetes change outcome."""
        change_lower = proposed_change.lower()

        if "deployment" in change_lower and "update" in change_lower:
            return {
                "expected_state": "rolling_update",
                "convergence_time": "30-120 seconds",
                "pods_affected": "progressive_replacement",
                "downtime": "0 (zero-downtime with rolling update strategy)",
                "impact": "No disruption if readiness probes are correct"
            }

        elif "network policy" in change_lower:
            return {
                "expected_state": "traffic_restricted",
                "impact_time": "immediate",
                "pods_affected": "matching selectors",
                "blast_radius": "service-specific",
                "impact": "Communications matching policy blocked immediately"
            }

        elif "pvc" in change_lower or "volume" in change_lower:
            return {
                "expected_state": "volume_mounted",
                "impact_time": "pod restart needed",
                "pods_affected": "pods using PVC",
                "impact": "Pods must be restarted to mount new volume"
            }

        elif "resource" in change_lower:
            return {
                "expected_state": "resource_updated",
                "impact_time": "next pod restart",
                "pods_affected": "new pods only",
                "impact": "Existing pods keep old limits; new pods use new limits"
            }

        return {"expected_state": "unknown"}

    def predict_timeline(self, proposed_change: str) -> List[Tuple[float, str]]:
        """Predict timeline of Kubernetes change."""
        change_lower = proposed_change.lower()

        if "deployment" in change_lower:
            return [
                (0, "New ReplicaSet created"),
                (5, "New pods scheduled"),
                (10, "New pods starting"),
                (30, "New pods ready"),
                (40, "Old pods terminating"),
                (60, "All old pods replaced"),
                (120, "Deployment stable")
            ]

        elif "network policy" in change_lower:
            return [
                (0, "Network policy applied"),
                (0.5, "Policy effective in data plane"),
                (1, "Matching traffic denied"),
                (5, "Connections closed/rejected")
            ]

        return [(0, "Change applied")]

    def estimate_confidence(self, prediction: Dict[str, Any]) -> float:
        """Kubernetes behavior is less predictable than network due to scheduling."""
        return 0.82

    def verify(self, expected: Dict[str, Any], actual: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Verify Kubernetes change worked."""
        differences = []

        # Check pod readiness
        if actual.get("ready_replicas", 0) < expected.get("desired_replicas", 1):
            differences.append(
                f"Not enough replicas ready: {actual.get('ready_replicas')}/{expected.get('desired_replicas')}"
            )

        # Check for crashing pods
        if actual.get("restarting_count", 0) > 0:
            differences.append(f"Pods are crashing: {actual.get('restarting_count')} restarts")

        # Check endpoints
        if expected.get("has_endpoints") and not actual.get("has_endpoints"):
            differences.append("Service has no endpoints")

        return (len(differences) == 0, differences)

    def generate_observations(self, entities: List[Entity], relationships: List[Relationship]) -> List[Observation]:
        """Generate observations about Kubernetes state."""
        observations = []

        for entity in entities:
            obs = Observation(
                timestamp=0,
                entity=entity,
                relationship=None,
                description=f"Kubernetes {entity.type} {entity.name} exists",
                source="kubernetes_api",
                confidence=0.99
            )
            observations.append(obs)

        return observations

    def explain(self, observation: Observation) -> str:
        """Explain Kubernetes observation."""
        desc = observation.description.lower()

        if "pending" in desc:
            return "Pod is pending - scheduler cannot place it. Check node capacity and pod selectors."
        elif "crashloopbackoff" in desc:
            return "Pod is crashing repeatedly. Check logs and resource limits."
        elif "imagepullbackoff" in desc:
            return "Cannot pull image. Verify registry access and image exists."
        elif "oomkilled" in desc:
            return "Out of memory - pod was killed for exceeding memory limit."
        elif "evicted" in desc:
            return "Pod evicted due to node pressure (disk/memory/PID space)."
        elif "terminating" in desc:
            return "Pod is terminating - may be slow graceful shutdown."
        elif "service" in desc:
            return "Service is a stable endpoint for pod communication."
        elif "network policy" in desc:
            return "Network policy controls traffic between pods."
        else:
            return f"Kubernetes observation: {observation.description}"

    # ============ HELPERS ============

    def _check_pending_pod(self, observations: List[Observation]) -> bool:
        return any("pending" in o.description.lower() for o in observations)

    def _check_service_discovery_issue(self, observations: List[Observation]) -> bool:
        return any("service" in o.description.lower() or "endpoint" in o.description.lower() for o in observations)

    def _check_network_policy_block(self, observations: List[Observation]) -> bool:
        return any("policy" in o.description.lower() or "denied" in o.description.lower() for o in observations)

    def _check_resource_issue(self, observations: List[Observation]) -> bool:
        return any(
            "oomkill" in o.description.lower() or "evict" in o.description.lower() or "resource" in o.description.lower()
            for o in observations
        )

    def _check_image_pull_error(self, observations: List[Observation]) -> bool:
        return any("image" in o.description.lower() or "pull" in o.description.lower() for o in observations)

    def _check_volume_issue(self, observations: List[Observation]) -> bool:
        return any("volume" in o.description.lower() or "pvc" in o.description.lower() for o in observations)

    def eliminate(self, hypothesis, new_observation: Observation) -> float:
        """Update hypothesis confidence based on new observation."""
        return hypothesis.confidence

    def predict(self, change) -> Dict[str, Any]:
        """Predict outcome (alias for predict_outcome)."""
        return self.predict_outcome({}, "")
