"""
Workflow Tracker — records every step of the autonomous remediation pipeline.
Each WorkflowRun tracks: detection → analysis → RCA → planning → fixing → verification → closure.
The Streamlit UI polls this to render the real-time step-by-step display.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
from enum import Enum


class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"


STEP_ICONS = {
    StepStatus.PENDING:   "⬜",
    StepStatus.RUNNING:   "🔄",
    StepStatus.COMPLETED: "✅",
    StepStatus.FAILED:    "❌",
    StepStatus.SKIPPED:   "⏭️",
}


@dataclass
class WorkflowStep:
    step_id: int
    name: str
    description: str
    status: StepStatus = StepStatus.PENDING
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    output: List[str] = field(default_factory=list)   # log lines
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def start(self) -> None:
        self.status = StepStatus.RUNNING
        self.started_at = datetime.utcnow().isoformat()

    def complete(self, output_line: str = "") -> None:
        self.status = StepStatus.COMPLETED
        self.completed_at = datetime.utcnow().isoformat()
        if output_line:
            self.output.append(output_line)

    def fail(self, error: str) -> None:
        self.status = StepStatus.FAILED
        self.completed_at = datetime.utcnow().isoformat()
        self.error = error

    def log(self, line: str) -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        self.output.append(f"[{ts}] {line}")

    @property
    def icon(self) -> str:
        return STEP_ICONS[self.status]

    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at and self.completed_at:
            start = datetime.fromisoformat(self.started_at)
            end   = datetime.fromisoformat(self.completed_at)
            return (end - start).total_seconds() * 1000
        return None


STANDARD_STEPS = [
    ("Telemetry Collection",    "Collecting live metrics from all devices"),
    ("Anomaly Detection",       "Scanning for threshold violations and pattern anomalies"),
    ("Root Cause Analysis",     "AI-powered RCA to identify the failure root cause"),
    ("Remediation Planning",    "Generating safe fix commands and approval workflow"),
    ("Fix Execution",           "Executing remediation commands on the affected device"),
    ("Recovery Verification",   "Verifying metrics returned to normal thresholds"),
    ("Incident Closure",        "Closing incident and updating audit trail"),
]


@dataclass
class WorkflowRun:
    run_id: str
    incident_id: str
    device: str
    anomaly_type: str
    severity: str
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    status: str = "running"  # running | completed | failed
    steps: List[WorkflowStep] = field(default_factory=list)
    summary: str = ""

    def __post_init__(self) -> None:
        if not self.steps:
            self.steps = [
                WorkflowStep(step_id=i + 1, name=name, description=desc)
                for i, (name, desc) in enumerate(STANDARD_STEPS)
            ]

    def get_step(self, step_id: int) -> Optional[WorkflowStep]:
        return next((s for s in self.steps if s.step_id == step_id), None)

    def current_step(self) -> Optional[WorkflowStep]:
        running = [s for s in self.steps if s.status == StepStatus.RUNNING]
        if running:
            return running[0]
        pending = [s for s in self.steps if s.status == StepStatus.PENDING]
        return pending[0] if pending else None

    def complete(self, summary: str = "") -> None:
        self.status = "completed"
        self.completed_at = datetime.utcnow().isoformat()
        self.summary = summary

    def fail(self, reason: str) -> None:
        self.status = "failed"
        self.completed_at = datetime.utcnow().isoformat()
        self.summary = reason

    @property
    def progress_pct(self) -> int:
        done = sum(1 for s in self.steps if s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED))
        return int(done / len(self.steps) * 100) if self.steps else 0

    @property
    def elapsed_seconds(self) -> float:
        start = datetime.fromisoformat(self.created_at)
        end_str = self.completed_at or datetime.utcnow().isoformat()
        end = datetime.fromisoformat(end_str)
        return (end - start).total_seconds()


class WorkflowTracker:
    """
    Central registry for all autonomous workflow runs.
    The Streamlit UI reads from this to render real-time workflow visualization.
    """

    def __init__(self, max_history: int = 50):
        self.runs: Dict[str, WorkflowRun] = {}   # run_id → WorkflowRun
        self.max_history = max_history
        self._counter = 0

    def create_run(
        self,
        incident_id: str,
        device: str,
        anomaly_type: str,
        severity: str,
    ) -> WorkflowRun:
        self._counter += 1
        run_id = f"WF-{datetime.utcnow().strftime('%H%M%S%f')}-{self._counter:04d}"
        run = WorkflowRun(
            run_id=run_id,
            incident_id=incident_id,
            device=device,
            anomaly_type=anomaly_type,
            severity=severity,
        )
        self.runs[run_id] = run
        self._trim()
        return run

    def get_run(self, run_id: str) -> Optional[WorkflowRun]:
        return self.runs.get(run_id)

    def get_active_runs(self) -> List[WorkflowRun]:
        return [r for r in self.runs.values() if r.status == "running"]

    def get_recent_runs(self, limit: int = 10) -> List[WorkflowRun]:
        sorted_runs = sorted(self.runs.values(), key=lambda r: r.created_at, reverse=True)
        return sorted_runs[:limit]

    def get_latest_run(self) -> Optional[WorkflowRun]:
        runs = self.get_recent_runs(1)
        return runs[0] if runs else None

    def _trim(self) -> None:
        if len(self.runs) > self.max_history:
            oldest = sorted(self.runs.keys(), key=lambda k: self.runs[k].created_at)
            for key in oldest[:len(self.runs) - self.max_history]:
                del self.runs[key]

    def step_start(self, run_id: str, step_id: int) -> None:
        run = self.runs.get(run_id)
        if run:
            step = run.get_step(step_id)
            if step:
                step.start()

    def step_log(self, run_id: str, step_id: int, line: str) -> None:
        run = self.runs.get(run_id)
        if run:
            step = run.get_step(step_id)
            if step:
                step.log(line)

    def step_complete(self, run_id: str, step_id: int, output: str = "", data: Dict[str, Any] = None) -> None:
        run = self.runs.get(run_id)
        if run:
            step = run.get_step(step_id)
            if step:
                step.complete(output)
                if data:
                    step.data.update(data)

    def step_fail(self, run_id: str, step_id: int, error: str) -> None:
        run = self.runs.get(run_id)
        if run:
            step = run.get_step(step_id)
            if step:
                step.fail(error)

    def export_summary(self) -> Dict[str, Any]:
        runs = self.get_recent_runs(20)
        return {
            "total_runs": len(self.runs),
            "active_runs": len(self.get_active_runs()),
            "completed_runs": sum(1 for r in self.runs.values() if r.status == "completed"),
            "failed_runs": sum(1 for r in self.runs.values() if r.status == "failed"),
            "recent": [
                {
                    "run_id": r.run_id,
                    "device": r.device,
                    "anomaly": r.anomaly_type,
                    "status": r.status,
                    "progress": r.progress_pct,
                    "elapsed": f"{r.elapsed_seconds:.1f}s",
                }
                for r in runs
            ],
        }
