"""
AI Configuration Engine
=======================
Enterprise-grade, business-intent-driven, 100% vendor-independent. Reasons on
normalized objects and emits normalized ConfigIntent; ALL vendor syntax is
produced through the Vendor Gateway / Vendor SDK. Never deploys without approval.

Spec component → implementation
-------------------------------
 1 Goal Manager          → engine.run() goal phase + models.Goal
 2 Intent Manager        → reasoning.parse_intent → normalized ConfigIntent
 3 Requirement Analyzer  → reasoning.find_missing + NEEDS_INPUT gate (ask, never assume)
 4 Technology Advisor    → reasoning.advise_technology
 5 Dependency Analyzer   → reasoning.analyze_dependencies
 6 Policy Engine         → policy.PolicyEngine (deterministic)
 7 Standards Validator   → policy.StandardsValidator (deterministic)
 8 Best Practice Advisor → reasoning.best_practices
 9 Design Validator      → reasoning.validate_design + critical gate
10 Configuration Planner → reasoning.plan_steps
11 Config Generator      → normalized ConfigIntent (no vendor syntax)
12 Impact Analyzer       → reasoning.analyze_impact
13 Risk Analyzer         → policy.RiskScorer (deterministic) + reasoning.mitigations
14 Conflict Detector     → policy.ConflictDetector (overlap/duplicate, deterministic)
15 Compliance Validator  → engine compliance aggregation
16 Config Validator      → policy.ConfigurationValidator (final)
17 Simulation Planner    → engine (lab-agnostic; never required)
18 Verification Planner  → Vendor Gateway (per-device verification)
19 Rollback Planner      → Vendor Gateway (mandatory rollback)
20 Approval Manager      → engine._build_approval (summaries; approval-gated)
21 Deployment Planner    → engine._plan_deployment (extensible strategy)
22 Session Memory        → audit.SessionStore
23 Audit Trail           → ConfigSession.record + audit.SessionStore.audit_log

Vendor syntax is produced ONLY in _build_vendor_artifacts via gateway.remediate();
the engine core contains no vendor names, products or commands.

Usage
-----
    from core.config_engine import AIConfigurationEngine
    from core.vendor import VendorGateway
    eng = AIConfigurationEngine(ai_call=call_ai, devices=devs,
                                gateway=VendorGateway(send=ssh_send, hint_provider=hints))
    report = eng.run("enable OSPF on the core uplinks in area 0")
    if report.session.status.value == "needs_input":
        ...  # ask the questions in report.session.missing, then re-run with provided={...}
    print(report.to_markdown())
"""
from .engine import AIConfigurationEngine, ConfigEngineConfig
from .models import ConfigReport, ConfigSession, ConfigStatus, RiskLevel, DeploymentStrategy

__all__ = [
    "AIConfigurationEngine", "ConfigEngineConfig", "ConfigReport", "ConfigSession",
    "ConfigStatus", "RiskLevel", "DeploymentStrategy",
]
