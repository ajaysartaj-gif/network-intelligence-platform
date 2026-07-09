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
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .evidence_graph import EvidenceGraph
from .hypotheses import (
    ConfidenceCalculator, HypothesisManager, RootCauseRanker, content_tokens,
)
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
        gateway: Optional[object] = None,
    ) -> None:
        self.ai = ai_call
        self.devices = devices or []
        self.cfg = config or TSConfig()
        # Optional Universal Vendor Adapter Framework gateway. When present, the
        # engine reasons on normalized operations/intents and delegates ALL vendor
        # specifics to adapters via the SDK. Branching is on gateway PRESENCE only,
        # never on vendor — the engine stays 100% vendor-agnostic.
        self.gateway = gateway
        self.reasoner = Reasoner(ai_call)
        self.cmd_memory = ExecutedCommandsMemory()
        self.graph = EvidenceGraph()
        self.session_memory = SessionMemory(session_store)
        self._unstable_keys: set = set()   # fact keys with inconsistent values

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

        # 0. EVIDENCE-FIRST: observe the objective's own state with one read-only
        #    probe round BEFORE forming any hypothesis, so causes are anchored in
        #    what was seen — not in priors. (Fixes the "first incorrect decision":
        #    hypotheses were generated from an empty evidence argument.)
        self._observe_initial_state(session, hmgr, conf, grounding, device_ips)

        # 0.5. DETERMINISTIC SEEDING — before any LLM hypothesis call. Two
        #      previously-unwired, already-built sources: the Mismatch
        #      Investigation (deterministic cross-device parameter compare)
        #      and the NKC's compiled FailureSignature library (textbook
        #      root causes with real confidence, not a 0.05-0.4 LLM guess).
        self._seed_deterministic_hypotheses(session, hmgr, query)
        self._bind_compiled_signature_evidence(session, hmgr, conf)

        # 1. seed hypotheses FROM the objective + the state just observed —
        #    the LLM EXTENDS the deterministic seed above, it never replaces it
        #    (existing statements are passed so it doesn't duplicate them).
        existing_statements = [h.statement for h in session.hypotheses]
        for h in self.reasoner.generate_hypotheses(
                session.goal.objective, grounding, self._evidence_summary(session),
                existing_statements):
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
            active = [{"id": h.id, "statement": h.statement, "confidence": h.confidence,
                       "discriminating_signals": h.discriminating_signals}
                      for h in session.ranked()]

            already = sorted(self.cmd_memory.all_normalized())

            # 3. collect (reuse memory when possible) — Evidence Collector.
            #    Gateway-mode uses normalized operations; otherwise raw commands.
            evidence_label = ""
            if self.gateway is not None:
                outputs = self._next_evidence_via_gateway(session, active, grounding, already, device_ips)
                evidence_label = session.next_best_command
            else:
                candidates = self.reasoner.plan_commands(
                    session.goal.objective, active, grounding, already, device_ips)
                picked = self._pick_command(candidates)
                if picked:
                    device_ip, command, purpose = picked
                    session.next_best_command = f"(on {device_ip}) {command}"
                    evidence_label = command
                    outputs = self._collect(device_ip, command, purpose, session)
                else:
                    outputs = None

            if not outputs:
                session.status = ResolutionStatus.ESCALATE
                session.escalation_reason = (
                    "no further non-redundant evidence adds diagnostic value "
                    "(requesting more evidence rather than guessing).")
                break

            # 4. analyze each output — Result Analyzer
            for dev_ip, output in outputs.items():
                self._ingest_output(evidence_label, dev_ip, output, session, hmgr, conf)
            self._bind_compiled_signature_evidence(session, hmgr, conf)

            # 5. lifecycle + contradiction awareness
            hmgr.reap()
            # Consume the contradiction signal instead of only logging it: fact
            # keys with inconsistent values must not RAISE confidence (Q5 fix).
            self._unstable_keys = set(self.graph.contradictory_keys())
            if self._unstable_keys:
                logger.info("Unstable fact keys (support suppressed): %s", self._unstable_keys)

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

    def _next_evidence_via_gateway(self, session: Session, active: List[dict],
                                   grounding: str, already: List[str],
                                   device_ips: List[str]) -> Optional[Dict[str, str]]:
        """Plan a normalized Operation and collect normalized objects via the SDK.

        The engine never sees a vendor command here — the adapter builds/parses it.
        """
        from core.vendor.operations import KNOWN_OPERATIONS, Operation  # local import: framework optional

        cands = self.reasoner.plan_operations(
            session.goal.objective, active, grounding, already, device_ips,
            sorted(KNOWN_OPERATIONS))
        # choose best, non-duplicate operation
        best = None
        for c in cands:
            opname = (c.get("operation") or "").strip()
            if not opname:
                continue
            params = c.get("params") or {}
            sig = self._op_signature(opname, params)
            dev = (c.get("device") or "all").strip()
            targets = ([dev] if dev in self._ip_to_dev else list(self._ip_to_dev.keys()))
            # skip operations no target adapter can express (avoids invalid commands
            # like an unsupported 'get_telemetry' being retried forever)
            targets = [t for t in targets
                       if self.gateway.supports_operation(self._ip_to_dev.get(t), opname)]
            if not targets:
                continue
            if all(self.cmd_memory.has(t, sig) for t in targets):
                continue
            best = (dev if dev in self._ip_to_dev else "all", opname, params,
                    c.get("purpose", ""), sig, targets)
            break
        if not best:
            return None

        dev, opname, params, purpose, sig, targets = best
        session.next_best_command = f"[operation] {opname} {params or ''} → {dev}"
        outputs: Dict[str, str] = {}
        for ip in targets:
            device = self._ip_to_dev.get(ip)
            if device is None:
                continue
            if self.cmd_memory.has(ip, sig):
                ec = self.cmd_memory.get(ip, sig)
                outputs[ip] = ec.output
                session.executed.append(self.cmd_memory.record(ip, sig, ec.output, purpose, reused=True))
                continue
            objects, err = self.gateway.collect(device, Operation(opname, params, purpose))
            if err is not None:
                text = f"error[{err.error_class.value}]: {err.message}"
            else:
                text = "\n".join(o.summary() for o in objects) or "(no normalized objects)"
            session.executed.append(self.cmd_memory.record(ip, sig, text, purpose, reused=False))
            outputs[ip] = text
        return outputs

    @staticmethod
    def _op_signature(opname: str, params: dict) -> str:
        parts = ",".join(f"{k}={params[k]}" for k in sorted(params or {}))
        return f"op:{opname}({parts})"

    def _ingest_output(self, command: str, device_ip: str, output: str,
                       session: Session, hmgr: HypothesisManager,
                       conf: ConfidenceCalculator) -> None:
        low = (output or "").lower()
        if (not output.strip() or output.startswith("error[")
                or "invalid input" in low or "no parseable data" in low
                or "% " in output[:3]):
            return                                        # errors are not evidence
        # DETERMINISTIC EXTRACTION FIRST — Phase 1's compiler extractors
        # (core.knowledge.compiler.semantic_analyzer) run over the same raw
        # output before the LLM does. These facts are recorded as
        # observations unconditionally: guaranteed-correct regex extraction
        # (mtu, timers, neighbor state, ...) supplements the LLM's free-form
        # analyze() call below rather than depending on it to notice and
        # correctly phrase the same thing. Deliberately NOT wired into the
        # impact/evidence-binding below (that logic is inherently tied to
        # the LLM's own per-analysis judgment about which hypothesis a fact
        # supports/contradicts) — this only guarantees the fact enters
        # session.observations/the evidence graph, available to every
        # evidence-gate check and every subsequent LLM call's context.
        for det in self._deterministic_facts(output):
            det_obs = Observation(device=device_ip, subject=det["subject"],
                                  attribute=det["attribute"], value=det["value"],
                                  source_command=command, raw_snippet=output[:200])
            session.observations.append(det_obs)
            try:
                self.graph.add_observation(det_obs)
            except Exception:
                pass

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
                # EVIDENCE GATE: an observation may move a hypothesis ONLY if it
                # concerns that hypothesis's own declared discriminating signal.
                # This is what stops an unrelated fact (interface up) from
                # inflating an unrelated hypothesis (network type). Fail-open when
                # a hypothesis declared no signals, so nothing is silently starved.
                if not self._obs_matches_signals(obs, hyp.discriminating_signals):
                    continue
                # Never RAISE confidence from a fact that is inconsistent across
                # reads (flapping / stale) — consumes the contradiction signal.
                if effect == Effect.SUPPORT and obs.key in self._unstable_keys:
                    continue
                weight = float(imp.get("weight", 0.5) or 0.5)
                ev = Evidence(observation_id=obs.id, hypothesis_id=hyp.id,
                              effect=effect, weight=weight, reason=str(imp.get("reason", "")))
                session.evidence.append(ev)
                conf.update(hyp, ev, obs)
            # only bind impacts once (to the first/most-specific fact of this analysis)
            parsed["impacts"] = []

    # Matches core.vendor.models.NormalizedObject.summary()'s own format
    # exactly: f"{type}[{id}]@{device} {{{kv}}}" — the text
    # _next_evidence_via_gateway() feeds into this same pipeline. Handled
    # separately from semantic_analyzer's CLI-table extractors (which parse
    # a fundamentally different text shape) so a gateway-mode neighbor/
    # protocol object's real id/state is read from its OWN attributes
    # dict, not guessed from free-form text.
    _GATEWAY_OBJ_LINE = re.compile(
        r"^(?P<type>\w+)\[(?P<id>[^\]]*)\]@(?P<device>\S+)\s*\{(?P<kv>.*)\}\s*$")

    def _gateway_object_facts(self, output: str) -> List[Dict[str, str]]:
        facts: List[Dict[str, str]] = []
        for line in (output or "").splitlines():
            m = self._GATEWAY_OBJ_LINE.match(line.strip())
            if not m:
                continue
            otype, oid = m.group("type"), m.group("id")
            kv: Dict[str, str] = {}
            for pair in m.group("kv").split(", "):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    kv[k.strip()] = v.strip()
            if otype == "neighbor" and kv.get("state"):
                facts.append({"subject": f"neighbor.{oid or '?'}",
                             "attribute": "state", "value": kv["state"]})
            elif otype == "protocol":
                if kv.get("adjacency"):
                    facts.append({"subject": f"protocol.{oid or '?'}",
                                 "attribute": "adjacency", "value": kv["adjacency"]})
                if kv.get("state"):
                    facts.append({"subject": f"protocol.{oid or '?'}",
                                 "attribute": "state", "value": kv["state"]})
            elif otype == "interface" and kv.get("mtu"):
                facts.append({"subject": f"interface.{oid or '?'}",
                             "attribute": "mtu", "value": kv["mtu"]})
        return facts

    def _deterministic_facts(self, output: str) -> List[Dict[str, str]]:
        """Runs Phase 1's deterministic semantic extractors
        (core.knowledge.compiler.semantic_analyzer, built for exactly this
        kind of line-oriented CLI/show-output text) over raw command output,
        PLUS a dedicated reader for gateway-mode NormalizedObject.summary()
        lines (a different text shape semantic_analyzer's CLI-table
        extractors aren't meant to parse). Returns the same
        {"subject","attribute","value"} shape analyze()'s LLM output already
        uses, so callers don't need a second code path. Best-effort: any
        failure returns [] and the LLM-only path is unaffected."""
        facts: List[Dict[str, str]] = list(self._gateway_object_facts(output))
        try:
            from core.knowledge.compiler.ast_builder import build_ast
            from core.knowledge.compiler.semantic_analyzer import analyze as extract_semantic
        except Exception:
            return facts
        try:
            findings = extract_semantic(build_ast(output or ""))
        except Exception:
            return facts

        for f in findings:
            attrs = f.attributes
            if f.kind == "interface":
                name = attrs.get("name", "?")
                for key in ("mtu", "area", "admin_state", "vrf", "vlan",
                           "acl_ref", "qos_policy", "ip", "mask"):
                    if attrs.get(key) not in (None, ""):
                        facts.append({"subject": f"interface.{name}", "attribute": key,
                                     "value": str(attrs[key])})
            elif f.kind == "neighbor":
                if attrs.get("state"):
                    facts.append({"subject": f"neighbor.{attrs.get('neighbor_ip','?')}",
                                 "attribute": "state", "value": str(attrs["state"])})
            elif f.kind == "protocol":
                if attrs.get("areas"):
                    facts.append({"subject": f"protocol.{attrs.get('protocol','?')}",
                                 "attribute": "areas",
                                 "value": ",".join(str(a) for a in attrs["areas"])})
            elif f.kind == "timer":
                facts.append({"subject": f"timer.{attrs.get('context','?')}",
                             "attribute": str(attrs.get("timer_type", "value")),
                             "value": str(attrs.get("value", ""))})
            elif f.kind == "acl_rule":
                facts.append({"subject": f"acl.{attrs.get('acl_name','?')}",
                             "attribute": "action", "value": str(attrs.get("action", ""))})
            elif f.kind in ("error", "warning"):
                facts.append({"subject": f.kind, "attribute": "message",
                             "value": str(attrs.get("message", attrs.get("code", "")))})
        return facts

    @staticmethod
    def _obs_matches_signals(obs, signals) -> bool:
        """True if this observation concerns one of the hypothesis's declared
        discriminating signals. Matches on SUBJECT tokens (ospf/mtu/area/neighbor
        …), not on generic attribute words (state/value/up), so 'interface up'
        does not spuriously match 'ospf neighbor state'."""
        if not signals:
            return True
        ot = content_tokens(f"{getattr(obs, 'subject', '')} {getattr(obs, 'attribute', '')}")
        if not ot:
            return True
        return any(ot & content_tokens(sig) for sig in signals)

    def _widen(self, session: Session, hmgr: HypothesisManager, grounding: str) -> None:
        ev_summary = self._evidence_summary(session)
        existing = [h.statement for h in session.hypotheses]
        for h in self.reasoner.generate_hypotheses(
                session.goal.objective, grounding, ev_summary, existing, max_new=2):
            hmgr.add(h.get("statement", ""), h.get("rationale", ""),
                     h.get("discriminating_signals", []), float(h.get("prior", 0.15) or 0.15))

    def _observe_initial_state(self, session: Session, hmgr: HypothesisManager,
                              conf: ConfidenceCalculator, grounding: str,
                              device_ips: List[str]) -> None:
        """One read-only probe round derived from the OBJECTIVE (no hypotheses yet)
        so the first hypotheses are anchored in observed state. Reuses the same
        plan/collect/analyze path as the main loop — no new capability."""
        already = sorted(self.cmd_memory.all_normalized())
        try:
            if self.gateway is not None:
                outputs = self._next_evidence_via_gateway(session, [], grounding, already, device_ips)
            else:
                candidates = self.reasoner.plan_commands(
                    session.goal.objective, [], grounding, already, device_ips)
                picked = self._pick_command(candidates)
                if not picked:
                    return
                device_ip, command, purpose = picked
                session.next_best_command = f"(on {device_ip}) {command}"
                outputs = self._collect(device_ip, command, purpose, session)
        except Exception:
            return
        for dev_ip, output in (outputs or {}).items():
            # no active hypotheses yet -> this records OBSERVATIONS only; nothing
            # is bound as evidence until hypotheses exist.
            self._ingest_output(session.next_best_command or "state",
                                dev_ip, output, session, hmgr, conf)

    def _evidence_summary(self, session: Session) -> str:
        lines = [f"{o.device} {o.subject}.{o.attribute}={o.value}" for o in session.observations[-12:]]
        return "; ".join(lines)

    _STUCK_STATE_RE = re.compile(r"stuck in '([^']+)'")

    @staticmethod
    def _norm_state(s: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", (s or "").upper())

    def _observed_protocol_state_obs(self, session: Session) -> Optional[Observation]:
        """Best-effort deterministic read of the most recent observation that
        reports an actual protocol/neighbor stuck-state (e.g. 'EXSTART') — the
        same vocabulary compiled FailureSignatures key off of via stuck_state.

        Prefers a "neighbor.*" fact (the specific per-neighbor FSM state:
        Down/Attempt/Init/2-Way/ExStart/Exchange/Loading/Full) over a
        "protocol.*" fact (a coarse up/down summary across ALL neighbors —
        see IosLikeAdapter's PROTOCOL object). Falling back to the coarse
        flag only when no neighbor-specific fact exists avoids the coarse
        "down" (meaning merely "no FULL neighbor yet") outranking the real,
        specific observed state and being compared against it instead."""
        for o in reversed(session.observations):
            if o.attribute == "state" and "neighbor" in o.subject.lower() and o.value:
                return o
        for o in reversed(session.observations):
            if o.attribute == "state" and "protocol" in o.subject.lower() and o.value:
                return o
        return None

    def _bind_compiled_signature_evidence(self, session: Session, hmgr: HypothesisManager,
                                          conf: ConfidenceCalculator) -> None:
        """Closes a gap _ingest_output's docstring deliberately left open:
        deterministic facts are recorded as observations but never bound as
        evidence there (that binding is inherently the LLM's own judgment
        call). Left unclosed, compiled-signature hypotheses seeded in
        _seed_deterministic_hypotheses() never move past their static prior
        — even when the actually observed protocol state overwhelmingly
        confirms one and rules out the rest, leaving a cluttered, unconverged
        hypothesis list. This binds exactly that one fully-deterministic
        comparison — observed stuck-state vs. each compiled signature's own
        stuck_state (recovered from the rationale string stamped at seed
        time) — nothing else. Every other hypothesis (LLM-authored,
        mismatch-investigation-seeded) is untouched. Runs at most once per
        hypothesis (idempotent via the delta reason tag) so it never
        double-counts across rounds."""
        obs = self._observed_protocol_state_obs(session)
        if obs is None:
            return
        observed_norm = self._norm_state(obs.value)
        if not observed_norm:
            return
        for hyp in session.active_hypotheses():
            m = self._STUCK_STATE_RE.search(hyp.rationale or "")
            if not m:
                continue
            if any((d.reason or "").startswith("deterministic-state-match") for d in hyp.deltas):
                continue
            stuck_norm = self._norm_state(m.group(1))
            if not stuck_norm:
                continue
            if stuck_norm == observed_norm:
                effect, weight = Effect.SUPPORT, 0.6
                reason = f"deterministic-state-match: observed state '{obs.value}' confirms this signature"
            else:
                effect, weight = Effect.CONTRADICT, 0.6
                reason = f"deterministic-state-match: observed state '{obs.value}' rules out this signature"
            ev = Evidence(observation_id=obs.id, hypothesis_id=hyp.id,
                         effect=effect, weight=weight, reason=reason)
            session.evidence.append(ev)
            conf.update(hyp, ev, obs)

    # ── deterministic seeding (runs BEFORE any LLM hypothesis call) ─────────────
    def _detect_protocol(self, query: str) -> str:
        """Reuses IntentEngine._detect_scenario when available (the real
        production path — copilot_engine.py always constructs one); falls
        back to a minimal keyword check for callers that supply their own
        collector/validator/grounder/fix_validator and so never build an
        IntentEngine (e.g. this package's own unit tests)."""
        if self._intent is not None:
            try:
                return self._intent._detect_scenario(query)
            except Exception:
                pass
        q = (query or "").lower()
        for p in ("ospf", "bgp", "eigrp", "stp", "vlan", "acl", "nat"):
            if p in q:
                return p
        return "general"

    def _seed_deterministic_hypotheses(self, session: Session, hmgr: HypothesisManager,
                                       query: str) -> None:
        """Seeds hypotheses deterministically, before any LLM call, from two
        already-built sources that were never wired into this engine:

          1. The Mismatch Investigation
             (core.troubleshooting.strategies.mismatch_bridge) — deterministic
             cross-device parameter comparison. Its own module docstring says
             it's "the single entry point core/troubleshooting/engine.py
             calls" — it wasn't actually called anywhere; this is that call.
          2. Compiled FailureSignatures
             (core.knowledge.compiler.failure_signatures) for the detected
             protocol — textbook root causes with real, non-arbitrary
             confidence, seeded as a genuine prior instead of an LLM guessing
             blind inside a fixed 0.05-0.4 band.

        Both are best-effort: any failure is caught and logged, and the
        LLM-driven path in run() proceeds unaffected either way — this
        function only ever ADDS hypotheses, never blocks the existing flow.
        """
        try:
            from core.troubleshooting.strategies.mismatch_bridge import (
                detect_relationship_type, run_mismatch_investigation,
            )
            rel_type = detect_relationship_type(query)
            if rel_type and self.gateway is not None and self._ip_to_dev:
                run_mismatch_investigation(
                    relationship_type=rel_type, devices=self.devices,
                    ip_to_device=self._ip_to_dev, gateway=self.gateway,
                    ai_call=self.ai, session=session, hmgr=hmgr, graph=self.graph,
                )
        except Exception as exc:
            logger.debug("Mismatch investigation seeding skipped: %s", exc)

        try:
            from core.knowledge.compiler.failure_signatures import compile_failure_signatures
            protocol = self._detect_protocol(query)
            signatures = compile_failure_signatures(protocol)
            if signatures:
                # If the query names a specific stuck state (e.g. "EXSTART"),
                # seed only that signature — otherwise seed all known
                # signatures for the protocol and let confidence sort them.
                def _norm(s: str) -> str:
                    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())
                q_norm = _norm(query)
                named = [s for s in signatures if _norm(s.stuck_state) in q_norm]
                signatures = named or signatures

            existing = {h.statement for h in session.hypotheses}
            for sig in signatures:
                if sig.likely_cause in existing:
                    continue
                hmgr.add(
                    sig.likely_cause,
                    rationale=(f"Compiled failure signature: {protocol} stuck in "
                              f"'{sig.stuck_state}' (confidence {sig.confidence:.2f}). "
                              f"Source: core.knowledge.compiler.failure_signatures — "
                              f"compiled, not an LLM guess."),
                    discriminating_signals=list(sig.evidence_fields) + [sig.stuck_state],
                    prior=sig.confidence,
                )
                self._note_knowledge_source(
                    session, f"compiled failure signature: {protocol}/{sig.stuck_state} "
                            f"(confidence {sig.confidence:.2f})")
        except Exception as exc:
            logger.debug("Compiled failure-signature seeding skipped: %s", exc)

    def _note_knowledge_source(self, session: Session, source: str) -> None:
        """Records provenance for the report's 'Knowledge Sources Consulted'
        section — only called where compiled NKC knowledge actually
        contributed, so a session with none stayed pure-LLM."""
        if source not in session.knowledge_sources:
            session.knowledge_sources.append(source)

    def _persist(self, session: Session) -> None:
        try:
            self.session_memory.save(session)
        except Exception:
            pass

    # ── conclusion ──────────────────────────────────────────────────────────────
    def _compiled_remediation_intent(self, session: Session, root_cause_statement: str,
                                     allowed_intents: List[str]) -> Optional[dict]:
        """Checks the NKC's compiled RemediationTemplate mapping
        (core.knowledge.compiler.reasoning_artifact_compiler) for a
        deterministic cause->intent mapping BEFORE asking the LLM to guess
        one. Matches by exact statement text — the compiled
        FailureSignature.likely_cause seeded as a hypothesis in
        _seed_deterministic_hypotheses() is the SAME string
        RemediationTemplate.applicable_signature carries, so a hypothesis
        that originated from compiled knowledge gets a compiled remediation
        too, not a fresh LLM guess. Returns None (falls through to the LLM)
        for any cause the compiled library doesn't cover."""
        try:
            from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
        except Exception:
            return None
        protocol = self._detect_protocol(root_cause_statement)
        try:
            for template in ReasoningArtifactCompiler().compile_remediation(protocol):
                if template.applicable_signature != root_cause_statement:
                    continue
                if allowed_intents and template.intent_name not in allowed_intents:
                    continue
                iface = ""
                for o in session.observations:
                    if o.subject.startswith("interface.") and o.attribute == "mtu":
                        iface = o.subject.split(".", 1)[1]
                        break
                self._note_knowledge_source(
                    session, f"compiled remediation template: {protocol}/{template.intent_name}")
                return {"name": template.intent_name, "params": {"protocol": protocol, "interface": iface},
                       "rationale": f"Compiled remediation template (risk={template.risk_level}): "
                                   f"{'; '.join(template.prerequisites)}"}
        except Exception as exc:
            logger.debug("Compiled remediation lookup skipped: %s", exc)
        return None

    def _compiled_verification(self, session: Session, protocol: str) -> Optional[Dict[str, Any]]:
        """Checks reasoning_artifact_compiler.compile_verification(protocol)
        for a compiled command/success-criteria template before falling
        back to the LLM's plan_verification(). Substitutes any observed
        interface into a `<interface>` placeholder so the commands are
        directly usable, not just descriptive."""
        try:
            from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
            templates = ReasoningArtifactCompiler().compile_verification(protocol)
        except Exception as exc:
            logger.debug("Compiled verification lookup skipped: %s", exc)
            return None
        if not templates:
            return None
        tmpl = templates[0]
        iface = ""
        for o in session.observations:
            if o.subject.startswith("interface.") and o.attribute == "mtu":
                iface = o.subject.split(".", 1)[1]
                break
        commands = [c.replace("<interface>", iface) if iface else c for c in tmpl.commands]
        self._note_knowledge_source(session, f"compiled verification template: {protocol}")
        return {"commands": commands, "success_criteria": tmpl.success_criteria}

    def _finish(self, session: Session, ranker: RootCauseRanker) -> TroubleshootReport:
        top = session.top()

        if top:
            try:
                from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
                risk = ReasoningArtifactCompiler().compile_risk(
                    self._detect_protocol(session.goal.query),
                    affected_object_count=len(session.observations))
                session.risk = {
                    "severity": risk.severity, "probability": risk.probability,
                    "impact": risk.impact, "affected_object_count": risk.affected_object_count,
                    "mitigation_reference": risk.mitigation_reference,
                }
            except Exception as exc:
                logger.debug("Risk compilation skipped: %s", exc)

        if top and ranker.converged(session) and self.gateway is not None:
            # Vendor-agnostic remediation: engine emits a NEUTRAL intent; the
            # adapter (via gateway) produces vendor fix + rollback + verification.
            from core.vendor.operations import RemediationIntent

            target_ip = (session.goal.devices[0] if session.goal.devices else "")
            device = self._ip_to_dev.get(target_ip) or (self.devices[0] if self.devices else None)
            allowed = []
            try:
                if device is not None:
                    allowed = self.gateway.supported_intents(device)
            except Exception:
                allowed = []
            protocol = self._detect_protocol(session.goal.query)
            intent_raw = self._compiled_remediation_intent(session, top.statement, allowed) or \
                        self.reasoner.propose_intent(
                            top.statement, session.goal.objective, self._evidence_summary(session), allowed)
            intent = RemediationIntent(
                name=str(intent_raw.get("name", "")).strip(),
                params=intent_raw.get("params", {}) or {},
                target_device=target_ip,
                rationale=intent_raw.get("rationale", ""),
            )
            plan = self.gateway.remediate(device, intent) if (device and intent.name) else None
            if plan and plan.supported and plan.fix_commands:
                session.fix = Fix(
                    root_cause=top.statement, config_commands=plan.fix_commands,
                    rollback_commands=plan.rollback_commands,
                    explanation=plan.explanation or intent.rationale, syntax_ok=True,
                    validation_md=f"Vendor-validated by adapter for intent `{intent.name}`.",
                )
                compiled_verif = self._compiled_verification(session, protocol)
                session.verification = VerificationPlan(
                    commands=plan.verification_commands,
                    success_criteria=(compiled_verif["success_criteria"] if compiled_verif
                                     else "Adapter-defined verification of the applied intent."),
                    rollback_on_fail=plan.rollback_commands,
                )
                session.status = ResolutionStatus.RESOLVED_PENDING_APPROVAL
                if top.state == HypothesisState.ACTIVE:
                    top.state = HypothesisState.CONFIRMED
            else:
                session.status = ResolutionStatus.LIKELY_CAUSE_PRESENT
            self._persist(session)
            return TroubleshootReport(session)

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

                protocol = self._detect_protocol(session.goal.query)
                ver_raw = self._compiled_verification(session, protocol) or \
                         self.reasoner.plan_verification(top.statement, cfgs)
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
