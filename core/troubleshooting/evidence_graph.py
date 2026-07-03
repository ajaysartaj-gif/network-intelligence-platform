"""
Troubleshooting Engine — evidence graph
=======================================
Turns observations into a small relationship graph linking devices, interfaces,
protocols and facts, and detects contradictions so the engine never builds a
conclusion on mutually inconsistent evidence.

Deliberately lightweight and dependency-free. It can be backed by the platform
KnowledgeGraph later; the interface (add_observation / contradictions / summary)
is what the engine depends on.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Tuple

from .models import Observation


class EvidenceGraph:
    def __init__(self) -> None:
        # node id -> {"type": ..., "attrs": {...}}
        self.nodes: Dict[str, dict] = {}
        # (src, relation, dst)
        self.edges: List[Tuple[str, str, str]] = []
        # (device|subject|attribute) -> list of (value, observation_id)
        self._facts: Dict[str, List[Tuple[str, str]]] = defaultdict(list)

    def _ensure(self, node_id: str, ntype: str, **attrs) -> str:
        if node_id not in self.nodes:
            self.nodes[node_id] = {"type": ntype, "attrs": dict(attrs)}
        else:
            self.nodes[node_id]["attrs"].update(attrs)
        return node_id

    def add_observation(self, obs: Observation) -> None:
        dev = self._ensure(f"device:{obs.device}", "device", ip=obs.device)
        subj = self._ensure(f"{obs.device}:{obs.subject}", "subject", name=obs.subject)
        fact = self._ensure(
            f"{obs.device}:{obs.subject}:{obs.attribute}",
            "fact", attribute=obs.attribute, value=obs.value,
        )
        self.edges.append((dev, "has", subj))
        self.edges.append((subj, "attribute", fact))
        # protocol / interface tagging for readability
        low = obs.subject.lower()
        for proto in ("ospf", "bgp", "eigrp", "isis", "stp", "vrrp", "hsrp"):
            if proto in low:
                self.edges.append((fact, "concerns", self._ensure(f"proto:{proto}", "protocol", name=proto)))
        self._facts[obs.key].append((obs.value, obs.id))

    def contradictions(self) -> List[str]:
        """Same (device, subject, attribute) asserted with different values."""
        out: List[str] = []
        for key, vals in self._facts.items():
            distinct = {v for v, _ in vals}
            if len(distinct) > 1:
                out.append(f"{key} has conflicting values: {sorted(distinct)}")
        return out

    def summary(self) -> str:
        devs = sum(1 for n in self.nodes.values() if n["type"] == "device")
        facts = sum(1 for n in self.nodes.values() if n["type"] == "fact")
        protos = [n["attrs"].get("name") for n in self.nodes.values() if n["type"] == "protocol"]
        proto_s = f", protocols: {', '.join(sorted(set(p for p in protos if p)))}" if protos else ""
        return f"{devs} device(s), {facts} fact(s){proto_s}"
