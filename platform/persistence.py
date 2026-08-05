"""
Persistence Layer

Database schema and ORM for storing systems, dependencies, decisions, and outcomes.
Makes platform scalable (1000+ systems) and persistent (survives restarts).
"""

from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
import json


class Database:
    """
    Abstract database interface. Implementations: PostgreSQL, SQLite, etc.
    """

    def __init__(self):
        pass

    def connect(self):
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class InMemoryDatabase(Database):
    """
    In-memory database for development/testing.
    Eventually replace with PostgreSQL.
    """

    def __init__(self):
        super().__init__()
        # Tables
        self.systems: Dict[str, Dict[str, Any]] = {}
        self.dependencies: Dict[tuple, Dict[str, Any]] = {}
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.decisions: Dict[str, Dict[str, Any]] = {}
        self.cascade_chains: List[Dict[str, Any]] = []
        self.observations: List[Dict[str, Any]] = []

    def connect(self):
        """Open connection (no-op for in-memory)."""
        pass

    def close(self):
        """Close connection (no-op for in-memory)."""
        pass

    # ============ SYSTEMS ============

    def save_system(self, system_id: str, domain: str, name: str, criticality: str) -> None:
        """Save a system."""
        self.systems[system_id] = {
            "id": system_id,
            "domain": domain,
            "name": name,
            "criticality": criticality,
            "created_at": datetime.now().isoformat(),
            "health_status": "unknown"
        }

    def get_system(self, system_id: str) -> Optional[Dict]:
        """Retrieve a system."""
        return self.systems.get(system_id)

    def list_systems(self, domain: Optional[str] = None) -> List[Dict]:
        """List all systems, optionally filtered by domain."""
        systems = list(self.systems.values())
        if domain:
            systems = [s for s in systems if s["domain"] == domain]
        return systems

    def get_systems_by_criticality(self, criticality: str) -> List[Dict]:
        """Get all systems with given criticality."""
        return [s for s in self.systems.values() if s["criticality"] == criticality]

    # ============ DEPENDENCIES ============

    def save_dependency(
        self,
        source_id: str,
        target_id: str,
        dep_type: str,
        confidence: float,
        failure_probability: float,
        time_to_propagate: float
    ) -> None:
        """Save a dependency."""
        key = (source_id, target_id)
        self.dependencies[key] = {
            "source": source_id,
            "target": target_id,
            "type": dep_type,
            "confidence": confidence,
            "failure_probability": failure_probability,
            "time_to_propagate": time_to_propagate,
            "created_at": datetime.now().isoformat(),
            "discovered_from": []
        }

    def get_dependency(self, source_id: str, target_id: str) -> Optional[Dict]:
        """Retrieve a dependency."""
        return self.dependencies.get((source_id, target_id))

    def get_dependencies_from(self, source_id: str) -> List[Dict]:
        """Get all dependencies originating from this system."""
        return [d for d in self.dependencies.values() if d["source"] == source_id]

    def get_dependencies_to(self, target_id: str) -> List[Dict]:
        """Get all dependencies targeting this system."""
        return [d for d in self.dependencies.values() if d["target"] == target_id]

    def strengthen_dependency(self, source_id: str, target_id: str, incident_id: str) -> None:
        """Strengthen dependency confidence after incident."""
        key = (source_id, target_id)
        if key in self.dependencies:
            dep = self.dependencies[key]
            dep["confidence"] = min(1.0, dep["confidence"] + 0.05)
            if incident_id not in dep["discovered_from"]:
                dep["discovered_from"].append(incident_id)

    # ============ INCIDENTS ============

    def save_incident(
        self,
        incident_id: str,
        description: str,
        severity: str,
        affected_systems: List[str],
        duration_minutes: float
    ) -> None:
        """Save an incident."""
        self.incidents[incident_id] = {
            "id": incident_id,
            "description": description,
            "severity": severity,
            "affected_systems": affected_systems,
            "duration_minutes": duration_minutes,
            "created_at": datetime.now().isoformat(),
            "cascade_chain": []
        }

    def get_incident(self, incident_id: str) -> Optional[Dict]:
        """Retrieve an incident."""
        return self.incidents.get(incident_id)

    def list_incidents(self, severity: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """List incidents, optionally filtered by severity."""
        incidents = list(self.incidents.values())
        if severity:
            incidents = [i for i in incidents if i["severity"] == severity]
        return incidents[-limit:]

    def get_incident_cascade_chain(self, incident_id: str) -> List[tuple]:
        """Get the cascade chain for an incident."""
        if incident_id in self.incidents:
            return self.incidents[incident_id].get("cascade_chain", [])
        return []

    def save_cascade_chain(self, incident_id: str, chain: List[tuple]) -> None:
        """Save cascade chain for an incident."""
        if incident_id in self.incidents:
            self.incidents[incident_id]["cascade_chain"] = chain

    # ============ DECISIONS ============

    def save_decision(
        self,
        decision_id: str,
        investigation_id: str,
        decision: str,
        outcome: str,
        lessons: List[str]
    ) -> None:
        """Save a decision record."""
        self.decisions[decision_id] = {
            "id": decision_id,
            "investigation_id": investigation_id,
            "decision": decision,
            "outcome": outcome,
            "lessons": lessons,
            "created_at": datetime.now().isoformat()
        }

    def get_decision(self, decision_id: str) -> Optional[Dict]:
        """Retrieve a decision."""
        return self.decisions.get(decision_id)

    def get_decisions_for_investigation(self, investigation_id: str) -> List[Dict]:
        """Get all decisions for an investigation."""
        return [d for d in self.decisions.values() if d["investigation_id"] == investigation_id]

    def list_decisions(self, outcome: Optional[str] = None, limit: int = 100) -> List[Dict]:
        """List decisions, optionally filtered by outcome."""
        decisions = list(self.decisions.values())
        if outcome:
            decisions = [d for d in decisions if d["outcome"] == outcome]
        return decisions[-limit:]

    # ============ OBSERVATIONS ============

    def save_observation(
        self,
        observation_id: str,
        system_id: str,
        description: str,
        source: str,
        confidence: float
    ) -> None:
        """Save an observation."""
        self.observations.append({
            "id": observation_id,
            "system_id": system_id,
            "description": description,
            "source": source,
            "confidence": confidence,
            "timestamp": datetime.now().isoformat()
        })

    def get_observations_for_system(self, system_id: str) -> List[Dict]:
        """Get all observations for a system."""
        return [o for o in self.observations if o["system_id"] == system_id]

    def get_recent_observations(self, hours: int = 24, limit: int = 1000) -> List[Dict]:
        """Get recent observations."""
        cutoff = datetime.now().timestamp() - (hours * 3600)
        recent = [
            o for o in self.observations
            if datetime.fromisoformat(o["timestamp"]).timestamp() > cutoff
        ]
        return recent[-limit:]

    # ============ ANALYTICS ============

    def get_most_critical_systems(self, limit: int = 10) -> List[Dict]:
        """Get systems with most dependencies."""
        system_dep_count = {}
        for dep in self.dependencies.values():
            source = dep["source"]
            target = dep["target"]
            system_dep_count[source] = system_dep_count.get(source, 0) + 1
            system_dep_count[target] = system_dep_count.get(target, 0) + 1

        sorted_systems = sorted(system_dep_count.items(), key=lambda x: x[1], reverse=True)
        return [self.systems[s[0]] for s in sorted_systems[:limit] if s[0] in self.systems]

    def get_cascade_statistics(self) -> Dict[str, Any]:
        """Get statistics on cascades."""
        return {
            "total_incidents": len(self.incidents),
            "total_affected_systems": sum(
                len(i["affected_systems"]) for i in self.incidents.values()
            ),
            "average_cascade_size": (
                sum(len(i["affected_systems"]) for i in self.incidents.values()) /
                len(self.incidents) if self.incidents else 0
            ),
            "average_duration": (
                sum(i["duration_minutes"] for i in self.incidents.values()) /
                len(self.incidents) if self.incidents else 0
            )
        }

    def get_dependency_graph_stats(self) -> Dict[str, Any]:
        """Get statistics on the dependency graph."""
        high_confidence_deps = [
            d for d in self.dependencies.values()
            if d["confidence"] > 0.8
        ]

        return {
            "total_systems": len(self.systems),
            "total_dependencies": len(self.dependencies),
            "high_confidence_dependencies": len(high_confidence_deps),
            "average_confidence": (
                sum(d["confidence"] for d in self.dependencies.values()) /
                len(self.dependencies) if self.dependencies else 0
            ),
            "systems_by_domain": self._count_by_domain(),
            "systems_by_criticality": self._count_by_criticality()
        }

    def _count_by_domain(self) -> Dict[str, int]:
        """Count systems by domain."""
        counts = {}
        for system in self.systems.values():
            domain = system["domain"]
            counts[domain] = counts.get(domain, 0) + 1
        return counts

    def _count_by_criticality(self) -> Dict[str, int]:
        """Count systems by criticality."""
        counts = {}
        for system in self.systems.values():
            crit = system["criticality"]
            counts[crit] = counts.get(crit, 0) + 1
        return counts

    # ============ BULK OPERATIONS ============

    def export_graph(self) -> Dict[str, Any]:
        """Export entire dependency graph."""
        return {
            "systems": list(self.systems.values()),
            "dependencies": list(self.dependencies.values()),
            "exported_at": datetime.now().isoformat()
        }

    def import_graph(self, data: Dict[str, Any]) -> None:
        """Import dependency graph."""
        for system in data.get("systems", []):
            system_id = system.pop("id")
            self.systems[system_id] = system

        for dep in data.get("dependencies", []):
            source = dep.pop("source")
            target = dep.pop("target")
            self.dependencies[(source, target)] = dep


# Global database instance
_db: Optional[Database] = None


def get_database() -> Database:
    """Get the global database instance."""
    global _db
    if _db is None:
        _db = InMemoryDatabase()
        _db.connect()
    return _db


def set_database(db: Database) -> None:
    """Set the global database instance."""
    global _db
    _db = db
    _db.connect()


def close_database() -> None:
    """Close the global database connection."""
    global _db
    if _db:
        _db.close()
        _db = None
