"""
NRIE · Learning · Outcome Tracker
=================================
Captures execution outcomes (success/failure/override/feedback/accuracy/
operational result/lessons) as a structured record for the feedback loop. No
deployment; consumes outcomes reported by the existing Verification/Deployment
pipeline.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Outcome:
    resource_id: str
    success: bool
    user_override: str = ""
    user_feedback: str = ""
    prediction_id: str = ""
    prediction_actual: Optional[float] = None
    operational_outcome: str = ""
    lessons_learned: str = ""
    deployment_ref: str = ""
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__
