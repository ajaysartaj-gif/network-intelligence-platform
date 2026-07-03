"""
Troubleshooting Engine — orchestrator
=====================================
Implements the confidence-driven control loop that ties the 14 components
together. Deterministic control; the LLM (via Reasoner) only reasons.

Reuse-first: SSH collection, command safety and fix validation are delegated to
the existing IntentEngine so this engine never re-implements transport or safety.

Control loop (per step):
  plan next command → validate (read-only) → dedup against memory →
  collect (reuse memory if seen) → analyze → update evidence graph →
  update confidence (traceable) → reap/rank → decide (converge / plateau / cap).

Stopping rules (spec "stop when confidence no longer improves"):
  - top hypothesis ≥ threshold with margin  → generate fix (approval-gated)
  - best confidence hasn't improved for `patience` steps → present alternatives / escalate
  - no new high-value command available     → escalate ("request evidence, don't guess")
  - safety cap on steps
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .evidence_graph import EvidenceGraph
from .hypotheses import ConfidenceCalculator, HypothesisManager, RootCauseRanker
from .memory import ExecutedCommandsMemory, SessionMemory, normalize_command
from .models import (
    Effect, Evidence, Fix, Goal, HypothesisState, Observation, ResolutionStatus,
    Session, TroubleshootReport, VerificationPlan,
)
from .reasoning import Reasoner

logger = logging.getLogger(__name__)


@dataclass
class TSConfig:
    max_steps: int = 8              # hard safety cap on diagnostic steps
    patience: int = 2               # stop after N steps with no confidence improvement
    min_improvement: float = 0.03   # what counts as "improvement"
    max_active_hypotheses: int = 6


class TroubleshootingEngine:
    """Autonomous, evidence-first troubleshooting.

    Parameters
    ----------
    ai_call   : the platform LLM callable (Groq).
    devices   : approved device objects (must expose .ip, ideally .hostname).
    collector : optional callable(device, [cmds]) -> {cmd: output}. Defaults to
                the platform IntentEngine SSH collector (read-only).
    validator : optional callable(cmd) -> bool (True = safe read-only). Defaults to
                IntentEngine.is_read_only / is_dangerous.
    grounder  : optional callable(query, devices) -> str context (RAG). Defaults to
                IntentEngine._ground.
    """

    def __init__(
        self,
        ai_call: Callable[[str], str],
        devices: List[Any],
        collector: Optional[Callable[[Any, List[str]], Dict[str, str]]] = None,
        validator: Optional[Callable[[str], bool]] = None,
        grounder: Optional[Callable[[str, List[Any]], str]] = None,
        fix_validator: Optional[Callable[[List[str], List[Any], List[Any]], str]] = None,
        config: Optional[TSConfig] = None,
        session_store: Optional[object] = None,
    ) -> None:
        self.ai = ai_call
        self.devices = devices or []
        self.cfg = config or TSConfig()
        self.reasoner = Reasoner(ai_call)
        self.cmd_memory = ExecutedCommandsMemory()
        self.graph = EvidenceGraph()
        self.session_memory = SessionMemory(session_store)

        self._intent = None
        if collector is None or validator is None or grounder is None or fix_validator is None:
            try:
                from core.intent_engine import IntentEngine
                self._intent = IntentEngine(ai_call=ai_call, approved_devices=devices)
            except Exception as exc:  # pragma: no cover - platform import guard
                logger.warning("IntentEngine unavailable, using minimal fallbacks: %s", exc)

        self._collector = collector or self._default_collect
        self._validator = validator or self._default_is_read_only
        self._grounder = grounder or self._default_ground
        self._fix_validator = fix_validator or self._default_fix_validation

        self._ip_to_dev = {getattr(d, "ip", ""): d for d in self.devices}

    # ── default delegations to the existing platform stack ──────────────────────
    def _default_collect(self, device: Any, cmds: List[str]) -> Dict[str, str]:
        if self._intent is None:
            return {c: "(collector unavailable)" for c in cmds}
        dr = self._intent._ssh_collect(device, cmds)
        return dict(dr.outputs)

    def _default_is_read_only(self, cmd: str) -> bool:
        if self._intent is None:
            low = cmd.lower().strip()
            return low.startswith(("show", "display")) and not any(
                b in low for b in ("debug", "clear", "reload", "test", "conf", "write", "erase"))
        return self._intent.is_read_only(cmd) and not self._intent.is_dangerous(cmd)

    def _default_ground(self, query: str, devices: List[Any]) -> str:
        if self._intent is None:
            return ""
        try:
            return self._intent._ground(query, devices) or ""
        except Exception:
            return ""

    def _default_fix_validation(self, cmds: List[str], all_devices: List[Any],
                                device_results: List[Any]) -> str:
        if self._intent is None:
            return ""
        try:
            return self._intent._validate_fix_commands(cmds, all_devices, device_results) or ""
        except Exception:
            return ""

    # ── main entry ──────────────────────────────────────────────────────────────
    def run(self, query: str) -> TroubleshootReport:
        session = Session()
        device_ips = [ip for ip in self._ip_to_dev.keys() if ip]
        grounding = self._grounder(query, self.devices)
        session.goal = Goal(query=query, devices=device_ips,
                            objective=self.reasoner.phrase_objective(query))

        hmgr = HypothesisManager(session)
        conf = ConfidenceCalculator()
        ranker = RootCauseRanker()

        # 1. seed hypotheses
        for h in self.reasoner.generate_hypotheses(session.goal.objective, grounding, "", []):
            hmgr.add(h.get("statement", ""), h.get("rationale", ""),
                     h.get("discriminating_signals", []), float(h.get("prior", 0.2) or 0.2))

        if not session.active_hypotheses():
            session.status = ResolutionStatus.ESCALATE
            session.escalation_reason = "the model could not form any testable hypothesis."
            return self._finish(session, ranker)

        best_so_far = 0.0
        stale = 0

        # 2. confidence-driven loop
        for _step in range(self.cfg.max_steps):
            session.steps_taken += 1
            active = [{"id": h.id, "statement": h.statement, "confidence": h.confidence}
                      for h in session.ranked()]

            already = sorted(self.cmd_memory.all_normalized())
            candidates = self.reasoner.plan_commands(
                session.goal.objective, active, grounding, already, device_ips)

            picked = self._pick_command(candidates)
            if not picked:
                session.status = ResolutionStatus.ESCALATE
                session.escalation_reason = (
                    "no further non-redundant read-only command adds diagnostic value "
                    "(requesting more evidence rather than guessing).")
                break

            device_ip, command, purpose = picked
            session.next_best_command = f"(on {device_ip}) {command}"

            # 3. collect (reuse memory when possible) — Evidence Collector
            outputs = self._collect(device_ip, command, purpose, session)

            # 4. analyze each output — Result Analyzer
            for dev_ip, output in outputs.items():
                self._ingest_output(command, dev_ip, output, session, hmgr, conf)

            # 5. lifecycle + contradiction awareness
            hmgr.reap()
            contradictions = self.graph.contradictions()
            if contradictions:
                logger.info("Evidence contradictions noted: %s", contradictions)

            top = session.top()
            best = top.confidence if top else 0.0
            session.best_confidence_history.append(best)

            # 6. decision
            if ranker.converged(session):
                break
            if best - best_so_far >= self.cfg.min_improvement:
                best_so_far = best
                stale = 0
            else:
                stale += 1
            if stale >= self.cfg.patience:
                break  # confidence no longer improving

            # optionally widen hypothesis space if everything is weak
            if best < ranker.PRESENT_THRESHOLD and len(session.active_hypotheses()) < self.cfg.max_active_hypotheses:
                self._widen(session, hmgr, grounding)

        return self._finish(session, ranker)

    # ── loop helpers ────────────────────────────────────────────────────────────
    def _pick_command(self, candidates: List[dict]) -> Optional[tuple]:
        """Choose the highest-value, safe, non-duplicate command."""
        scored = []
        for c in candidates:
            command = (c.get("command") or "").strip()
            if not command:
                continue
            if not self._validator(command):        # Command Validator: read-only only
                logger.info("Rejected non-read-only diagnostic: %s", command)
                continue
            dev = (c.get("device") or "all").strip()
            targets = [dev] if dev not in ("all", "", "*") and dev in self._ip_to_dev else list(self._ip_to_dev.keys())
            # dedup: skip if every target already has this command in memory
            fresh_targets = [t for t in targets if not self.cmd_memory.has(t, command)]
            if not fresh_targets:
                continue
            value = float(c.get("value", 0.5) or 0.5)
            n_hyp = len(c.get("tests_hypotheses", []) or [])
            score = value + 0.1 * n_hyp
            scored.append((score, fresh_targets[0] if len(fresh_targets) == 1 else "all",
                           command, c.get("purpose", "")))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        _, dev, command, purpose = scored[0]
        return dev, command, purpose

    def _collect(self, device_ip: str, command: str, purpose: str,
                 session: Session) -> Dict[str, str]:
        targets = list(self._ip_to_dev.keys()) if device_ip in ("all", "", "*") else [device_ip]
        outputs: Dict[str, str] = {}
        for ip in targets:
            dev = self._ip_to_dev.get(ip)
            if dev is None:
                continue
            if self.cmd_memory.has(ip, command):          # reuse — never re-run
                ec = self.cmd_memory.get(ip, command)
                outputs[ip] = ec.output
                rec = self.cmd_memory.record(ip, command, ec.output, purpose, reused=True)
                session.executed.append(rec)
                continue
            got = self._collector(dev, [command]) or {}
            out = got.get(command) or next(iter(got.values()), "") if got else ""
            rec = self.cmd_memory.record(ip, command, out, purpose, reused=False)
            session.executed.append(rec)
            outputs[ip] = out
        return outputs

    def _ingest_output(self, command: str, device_ip: str, output: str,
                       session: Session, hmgr: HypothesisManager,
                       conf: ConfidenceCalculator) -> None:
        active = [{"id": h.id, "statement": h.statement} for h in session.active_hypotheses()]
        parsed = self.reasoner.analyze(command, device_ip, output, active)

        for f in parsed.get("facts", []):
            obs = Observation(
                device=device_ip, subject=str(f.get("subject", "")),
                attribute=str(f.get("attribute", "")), value=str(f.get("value", "")),
                source_command=command, raw_snippet=output[:200],
            )
            if not obs.subject:
                continue
            session.observations.append(obs)
            self.graph.add_observation(obs)

            # attach the most recent obs id to impacts referencing this analysis
            for imp in parsed.get("impacts", []):
                hyp = hmgr.get(str(imp.get("hypothesis_id", "")))
                if not hyp or hyp.state != HypothesisState.ACTIVE:
                    continue
                try:
                    effect = Effect(str(imp.get("effect", "neutral")))
                except ValueError:
                    effect = Effect.NEUTRAL
                if effect == Effect.NEUTRAL:
                    continue
                weight = float(imp.get("weight", 0.5) or 0.5)
                ev = Evidence(observation_id=obs.id, hypothesis_id=hyp.id,
                              effect=effect, weight=weight, reason=str(imp.get("reason", "")))
                session.evidence.append(ev)
                conf.update(hyp, ev, obs)
            # only bind impacts once (to the first/most-specific fact of this analysis)
            parsed["impacts"] = []

    def _widen(self, session: Session, hmgr: HypothesisManager, grounding: str) -> None:
        ev_summary = self._evidence_summary(session)
        existing = [h.statement for h in session.hypotheses]
        for h in self.reasoner.generate_hypotheses(
                session.goal.objective, grounding, ev_summary, existing, max_new=2):
            hmgr.add(h.get("statement", ""), h.get("rationale", ""),
                     h.get("discriminating_signals", []), float(h.get("prior", 0.15) or 0.15))

    def _evidence_summary(self, session: Session) -> str:
        lines = [f"{o.device} {o.subject}.{o.attribute}={o.value}" for o in session.observations[-12:]]
        return "; ".join(lines)

    # ── conclusion ──────────────────────────────────────────────────────────────
    def _finish(self, session: Session, ranker: RootCauseRanker) -> TroubleshootReport:
        top = session.top()

        if top and ranker.converged(session):
            # Fix Generator (approval-gated) + Verification Planner
            grounding = self._grounder(session.goal.query, self.devices)
            fix_raw = self.reasoner.generate_fix(
                top.statement, session.goal.objective, self._evidence_summary(session), grounding)
            cfgs = [c for c in (fix_raw.get("config_commands") or []) if c and c.strip()]
            # Command Validator: a fix must NOT contain disruptive verbs beyond config intent
            cfgs = [c for c in cfgs if "debug" not in c.lower() and "reload" not in c.lower()]
            if cfgs:
                fix = Fix(
                    root_cause=top.statement,
                    config_commands=cfgs,
                    rollback_commands=[c for c in (fix_raw.get("rollback_commands") or []) if c and c.strip()],
                    explanation=fix_raw.get("explanation", ""),
                )
                try:
                    fix.validation_md = self._fix_validator(cfgs, self.devices, [])
                    fix.syntax_ok = "blocked" not in (fix.validation_md or "").lower()
                except Exception:
                    fix.syntax_ok = False
                session.fix = fix

                ver_raw = self.reasoner.plan_verification(top.statement, cfgs)
                vcmds = [c for c in (ver_raw.get("commands") or []) if self._validator(c)]
                session.verification = VerificationPlan(
                    commands=vcmds, success_criteria=ver_raw.get("success_criteria", ""),
                    rollback_on_fail=fix.rollback_commands,
                )
                session.status = ResolutionStatus.RESOLVED_PENDING_APPROVAL
                if top.state == HypothesisState.ACTIVE:
                    top.state = HypothesisState.CONFIRMED
            else:
                session.status = ResolutionStatus.LIKELY_CAUSE_PRESENT
        elif top and top.confidence >= ranker.PRESENT_THRESHOLD:
            session.status = ResolutionStatus.LIKELY_CAUSE_PRESENT
        elif not session.ranked() and session.observations:
            session.status = ResolutionStatus.HEALTHY
        else:
            if session.status == ResolutionStatus.IN_PROGRESS:
                session.status = ResolutionStatus.ESCALATE
                session.escalation_reason = session.escalation_reason or (
                    "evidence was insufficient to confirm a single root cause above the "
                    "confidence threshold.")

        session.next_best_command = "" if session.status in (
            ResolutionStatus.RESOLVED_PENDING_APPROVAL, ResolutionStatus.HEALTHY
        ) else session.next_best_command

        try:
            self.session_memory.save(session)
        except Exception:
            pass
        return TroubleshootReport(session)
