from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class IncidentRecord:
    title: str
    description: str
    affected_service: str
    device: Optional[str] = None
    severity: str = "low"
    status: str = "new"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    incident_id: Optional[str] = None
    correlated_ids: List[str] = field(default_factory=list)


class IncidentEngine:
    """Incident lifecycle engine for scoring and correlation."""

    SEVERITY_WEIGHTS = {
        "low": 10,
        "medium": 50,
        "high": 80,
        "critical": 100,
    }

    STATUS_FLOW = ["new", "investigating", "mitigating", "resolved", "closed"]

    def create_incident(
        self,
        title: str,
        description: str,
        affected_service: str,
        device: Optional[str] = None,
        impact: int = 1,
        urgency: int = 1,
        visibility: int = 1,
    ) -> IncidentRecord:
        severity = self.score_severity(impact, urgency, visibility)
        incident_id = f"INC-{int(datetime.utcnow().timestamp())}-{len(title)}"
        return IncidentRecord(
            title=title,
            description=description,
            affected_service=affected_service,
            device=device,
            severity=severity,
            status="new",
            incident_id=incident_id,
        )

    def score_severity(self, impact: int, urgency: int, visibility: int) -> str:
        score = max(0, min(100, impact * 40 + urgency * 35 + visibility * 25))
        if score >= 85:
            return "critical"
        if score >= 60:
            return "high"
        if score >= 30:
            return "medium"
        return "low"

    def correlate_incidents(self, incidents: List[IncidentRecord]) -> List[IncidentRecord]:
        groups: Dict[str, List[IncidentRecord]] = {}
        for incident in incidents:
            key = incident.affected_service.lower().strip() or incident.title.lower().strip()
            groups.setdefault(key, []).append(incident)

        for key, group in groups.items():
            if len(group) <= 1:
                continue
            master = group[0]
            for duplicate in group[1:]:
                master.correlated_ids.append(duplicate.incident_id or "")
                duplicate.status = "correlated"
                duplicate.updated_at = datetime.utcnow()
        return incidents

    def update_status(self, incident: IncidentRecord, status: str) -> IncidentRecord:
        if status not in self.STATUS_FLOW:
            raise ValueError(f"Invalid status: {status}")
        incident.status = status
        incident.updated_at = datetime.utcnow()
        return incident

    def track_status(self, incident: IncidentRecord) -> Dict[str, object]:
        current_index = self.STATUS_FLOW.index(incident.status) if incident.status in self.STATUS_FLOW else 0
        return {
            "incident_id": incident.incident_id,
            "current_status": incident.status,
            "next_status": self.STATUS_FLOW[min(current_index + 1, len(self.STATUS_FLOW) - 1)],
            "history": self.STATUS_FLOW[: current_index + 1],
        }
