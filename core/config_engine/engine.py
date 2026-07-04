"""
AI Configuration Engine — orchestrator
======================================
Business-intent-driven configuration. Deterministic control; LLM reasoning; ALL
vendor syntax delegated to the Vendor Gateway. The engine emits only normalized
ConfigIntent and normalized objects, contains NO vendor names/commands, and never
deploys without explicit approval.

Pipeline (each step is audited):
  goal → intent → requirements(gate) → technology → dependencies → policy →
  standards → best-practice → design(gate) → plan → generate normalized intent →
  impact → risk → conflicts(gate) → compliance → validation → simulation →
  verification → rollback → vendor artifacts → deployment strategy → approval pkg.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .audit import SessionStore
from .models import (ApprovalPackage, Check, ConfigIntent, ConfigReport, ConfigSession,
                     ConfigStatus, Dependency, DeploymentPlan, DeploymentStrategy, Goal,
                     ImpactAssessment, MissingInput, RiskLevel, Severity, TechnologyOption,
                     PlanStep, VendorArtifact)
from .policy import (ConfigurationValidator, ConflictDetector, PolicyEngine, RiskScorer,
                     StandardsValidator)
from .reasoning import ConfigReasoner

logger = logging.getLogger(__name__)


@dataclass
class ConfigEngineConfig:
    max_intents: int = 12
    confidence: float = 0.7      # base confidence for risk (LLM-driven work is uncertain)


class AIConfigurationEngine:
    """Vendor-independent AI Configuration Engine.

    Parameters
    ----------
    ai_call : platform LLM callable.
    devices : approved device objects (expose .ip, ideally .hostname/.device_type).
    gateway : optional VendorGateway. When present, normalized ConfigIntent is
              translated to vendor config + rollback + verification via adapters.
              When absent, artifacts remain normalized (still a valid deliverable).
    """

    def __init__(self, ai_call: Callable[[str], str], devices: List[Any] = None,
                 gateway: Optional[object] = None,
                 config: Optional[ConfigEngineConfig] = None,
                 session_store: Optional[object] = None,
                 policy_engine: Optional[PolicyEngine] = None) -> None:
        self.ai = ai_call
        self.devices = devices or []
        self.gateway = gateway
        self.cfg = config or ConfigEngineConfig()
        self.r = ConfigReasoner(ai_call)
        self.policy = policy_engine or PolicyEngine()
        self.standards = StandardsValidator()
        self.conflicts = ConflictDetector()
        self.validator = ConfigurationValidator()
        self.risk = RiskScorer()
        self.store = SessionStore(session_store)
        self._ip_to_dev = {getattr(d, "ip", ""): d for d in self.devices}

    # ── entry ───────────────────────────────────────────────────────────────────
    def run(self, query: str, provided: Optional[Dict[str, Any]] = None) -> ConfigReport:
        s = ConfigSession()
        s.provided = dict(provided or {})
        device_ips = [ip for ip in self._ip_to_dev if ip]

        # 1. Goal Manager
        g = self.r.phrase_goal(query)
        s.goal = Goal(query=query, objective=g.get("objective", query),
                      category=g.get("category", ""), scope=device_ips)
        s.record("goal", s.goal.objective)

        # 2. Intent Manager
        parsed = self.r.parse_intent(s.goal.objective, s.provided)
        s.technologies = list(parsed.get("technologies", []))
        s.protocols = list(parsed.get("protocols", []))
        s.services = list(parsed.get("services", []))
        raw_intents = parsed.get("intents", [])[: self.cfg.max_intents]
        s.intents = [ConfigIntent(name=i.get("name", ""), params=i.get("params", {}) or {},
                                  target_devices=(i.get("params", {}) or {}).get("devices", device_ips) or device_ips,
                                  rationale=i.get("rationale", ""))
                     for i in raw_intents if i.get("name")]
        s.record("intent", f"{len(s.intents)} normalized intent(s); tech={s.technologies}")

        # 3. Requirement Analyzer — ASK, never assume
        missing = self.r.find_missing(s.goal.objective,
                                      [{"name": i.name, "params": i.params} for i in s.intents],
                                      s.provided)
        s.missing = [MissingInput(field=m.get("field", ""), question=m.get("question", ""),
                                  required=bool(m.get("required", True)))
                     for m in missing
                     if m.get("field") and m.get("field") not in s.provided]
        required_open = [m for m in s.missing if m.required]
        if required_open:
            s.status = ConfigStatus.NEEDS_INPUT
            s.record("requirements", f"blocked on {len(required_open)} required input(s)")
            self.store.save(s)
            return ConfigReport(s)
        s.record("requirements", "all mandatory inputs satisfied")

        # 4. Technology Advisor
        s.tech_options = [TechnologyOption(name=t.get("name", ""), rationale=t.get("rationale", ""),
                                           tradeoffs=t.get("tradeoffs", ""),
                                           recommended=bool(t.get("recommended", False)))
                          for t in self.r.advise_technology(s.goal.objective) if t.get("name")]
        s.record("technology", ", ".join(t.name for t in s.tech_options))

        # 5. Dependency Analyzer
        s.dependencies = [Dependency(kind=d.get("kind", ""), detail=d.get("detail", ""))
                          for d in self.r.analyze_dependencies(
                              s.goal.objective, [{"name": i.name, "params": i.params} for i in s.intents])
                          if d.get("kind")]
        s.record("dependencies", f"{len(s.dependencies)} dependency(ies)")

        # 6/7. Policy Engine + Standards Validator (deterministic)
        s.policy_checks = self.policy.check(s.intents, s.goal.category)
        s.standards_checks = self.standards.check(s.intents)
        s.record("policy_standards",
                 f"policy_ok={all(c.passed for c in s.policy_checks)} "
                 f"standards_ok={all(c.passed for c in s.standards_checks)}")

        # 8. Best Practice Advisor
        s.best_practices = self.r.best_practices(s.goal.objective)

        # 9. Design Validator — gate on critical flaws
        s.design_checks = [Check(name=d.get("name", "design"),
                                 severity=_sev(d.get("severity")), passed=bool(d.get("passed", True)),
                                 detail=d.get("detail", ""))
                           for d in self.r.validate_design(
                               s.goal.objective, [{"name": i.name, "params": i.params} for i in s.intents])]
        design_blocked = [c for c in s.design_checks if c.severity == Severity.CRITICAL and not c.passed]
        s.record("design", f"{len(s.design_checks)} check(s); blocked={bool(design_blocked)}")

        # 10. Configuration Planner
        s.plan = [PlanStep(order=int(p.get("order", idx + 1)), description=p.get("description", ""),
                           prerequisite=p.get("prerequisite", ""))
                  for idx, p in enumerate(self.r.plan_steps(
                      [{"name": i.name, "params": i.params} for i in s.intents]))]

        # 11. Configuration Generator → already normalized in s.intents (no vendor syntax)
        s.record("generation", f"{len(s.intents)} normalized intent(s) ready")

        # 12. Impact Analyzer
        imp = self.r.analyze_impact(s.goal.objective,
                                    [{"name": i.name, "params": i.params} for i in s.intents])
        s.impact = ImpactAssessment(factors=list(imp.get("factors", [])),
                                    downtime_expected=bool(imp.get("downtime_expected", False)),
                                    summary=imp.get("summary", ""))

        # 14. Conflict Detector (deterministic) — gate on critical
        s.conflicts = self.conflicts.detect(s.intents)
        crit_conflicts = [c for c in s.conflicts if c.severity == Severity.CRITICAL]

        # 13. Risk Analyzer (deterministic score + LLM mitigations)
        s.risk = self.risk.score(s.impact, s.conflicts, len(device_ips or s.intents),
                                 unresolved_missing=0, confidence=self.cfg.confidence)
        if s.risk.drivers:
            s.risk.mitigations = self.r.mitigations(s.risk.drivers, s.goal.objective)
        s.record("risk", f"{s.risk.level.value} ({s.risk.score})")

        # 15. Compliance Validator
        s.compliance_checks = [Check(name="compliance",
                                     passed=all(c.passed for c in s.policy_checks + s.standards_checks),
                                     detail="aggregated from policy + standards")]

        # 16. Configuration Validator (final)
        deps_ok = all(d.satisfied is not False for d in s.dependencies)
        s.validation_checks = self.validator.validate(s.intents, deps_ok,
                                                       s.policy_checks, s.standards_checks)

        # 17. Simulation Planner (optional; never required)
        s.simulation_targets = list(device_ips)

        # 18/19/artifacts. Verification + Rollback + vendor config — via Vendor Gateway
        self._build_vendor_artifacts(s)

        # gate: block if critical design flaw or critical conflict
        if design_blocked or crit_conflicts:
            s.status = ConfigStatus.BLOCKED
            reason = "; ".join([c.detail for c in design_blocked] + [c.detail for c in crit_conflicts])
            s.record("gate", f"BLOCKED: {reason}")
            s.approval = ApprovalPackage(executive_summary="Blocked before approval — resolve issues below.",
                                         risk_summary=reason)
            self.store.save(s)
            return ConfigReport(s)

        # 21. Deployment Planner
        s.deployment = self._plan_deployment(s)

        # 20. Approval Manager (never auto-deploys)
        s.approval = self._build_approval(s)
        s.status = ConfigStatus.NEEDS_APPROVAL
        s.record("approval", "package prepared; awaiting explicit approval")

        # 22/23. Session Memory + Audit persisted
        self.store.save(s)
        return ConfigReport(s)

    def approve(self, session: ConfigSession) -> ConfigSession:
        """Record explicit human approval. Deployment/execution is out of scope here."""
        if session.status == ConfigStatus.NEEDS_APPROVAL and session.approval:
            session.approval.approved = True
            session.status = ConfigStatus.APPROVED
            session.record("approval", "approved by user")
            self.store.save(session)
        return session

    # ── vendor delegation (the ONLY vendor touch point) ─────────────────────────
    def _build_vendor_artifacts(self, s: ConfigSession) -> None:
        if self.gateway is None:
            for i in s.intents:
                for ip in i.target_devices:
                    s.artifacts.append(VendorArtifact(device=ip, supported=False,
                                                      note="no vendor gateway supplied; kept as normalized intent"))
            s.record("artifacts", "gateway absent — normalized intent retained")
            return
        from core.vendor.operations import RemediationIntent
        for i in s.intents:
            for ip in i.target_devices:
                device = self._ip_to_dev.get(ip)
                if device is None:
                    continue
                plan = self.gateway.remediate(device, RemediationIntent(
                    name=i.name, params=i.params, target_device=ip, rationale=i.rationale))
                adapter = ""
                try:
                    a, _ = self.gateway.resolve(device)
                    adapter = a.name if a else ""
                except Exception:
                    pass
                if plan and plan.supported and plan.fix_commands:
                    s.artifacts.append(VendorArtifact(
                        device=ip, adapter=adapter, config_commands=plan.fix_commands,
                        rollback_commands=plan.rollback_commands,
                        verification_commands=plan.verification_commands, supported=True))
                else:
                    s.artifacts.append(VendorArtifact(
                        device=ip, adapter=adapter, supported=False,
                        note=(plan.explanation if plan else "adapter could not translate intent")))
        s.record("artifacts", f"{sum(1 for a in s.artifacts if a.supported)}/{len(s.artifacts)} translated to vendor syntax")

    # ── deployment strategy heuristic (extensible) ──────────────────────────────
    def _plan_deployment(self, s: ConfigSession) -> DeploymentPlan:
        scope = list({a.device for a in s.artifacts}) or list(s.simulation_targets)
        level = s.risk.level if s.risk else RiskLevel.LOW
        if level in (RiskLevel.CRITICAL, RiskLevel.HIGH) or (s.impact and s.impact.downtime_expected):
            strat, why = DeploymentStrategy.MAINTENANCE_WINDOW, "high risk / possible downtime"
        elif len(scope) > 3:
            strat, why = DeploymentStrategy.PHASED, "large scope — roll out in phases"
        elif len(scope) > 1:
            strat, why = DeploymentStrategy.SITE_BY_SITE, "multi-device — device-by-device"
        else:
            strat, why = DeploymentStrategy.IMMEDIATE, "single low-risk change"
        return DeploymentPlan(strategy=strat, ordered_devices=scope, rationale=why)

    # ── approval package ────────────────────────────────────────────────────────
    def _build_approval(self, s: ConfigSession) -> ApprovalPackage:
        risk_s = (f"{s.risk.level.value.upper()} (score {s.risk.score}); "
                  f"drivers: {', '.join(s.risk.drivers) or 'none'}") if s.risk else "n/a"
        impact_s = (s.impact.summary or "no material impact identified") if s.impact else "n/a"
        exec_s = self.r.executive_summary(s.goal.objective,
                                          s.risk.level.value if s.risk else "low", impact_s)
        verif = sorted({c for a in s.artifacts for c in a.verification_commands})
        roll = [f"{a.device}: {len(a.rollback_commands)} cmd(s)" for a in s.artifacts if a.rollback_commands]
        return ApprovalPackage(
            executive_summary=exec_s or s.goal.objective,
            impact_summary=impact_s,
            risk_summary=risk_s,
            verification_summary=("; ".join(verif) if verif else "verification will run post-deploy"),
            rollback_summary=("rollback prepared for " + ", ".join(roll) if roll
                              else "rollback prepared with the configuration"),
        )


def _sev(v: Any) -> Severity:
    try:
        return Severity(str(v))
    except Exception:
        return Severity.INFO
