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

from core.knowledge.compiler.protocol_registry import all_keywords, get_spec, reactive_specs

from .evidence_graph import EvidenceGraph
from .hypotheses import (
    ConfidenceCalculator, HypothesisManager, RootCauseRanker, content_tokens,
)
from .memory import ExecutedCommandsMemory, SessionMemory, normalize_command
from .models import (
    ConfidenceDelta, Effect, Evidence, Fix, Goal, Hypothesis, HypothesisState, Observation,
    ResolutionStatus, Session, TroubleshootReport, VerificationPlan,
)
from .reasoning import Reasoner, safe_ai_call

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
        # safe_ai_call filters out the raw ai_call's "AI Error: ..." string
        # (returned deliberately by app.py's plain-chat mode so a human sees
        # it inline) so a transient API failure is never mistaken for a real
        # answer by structured consumers of self.ai — e.g. run_mismatch_
        # investigation's ai_call=self.ai below.
        self.ai = safe_ai_call(ai_call)
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
    def run(self, query: str, excluded_causes: Optional[List[str]] = None,
            partial_causes: Optional[Dict[str, str]] = None) -> TroubleshootReport:
        """`excluded_causes`: root-cause statements already deployed and
        confirmed (by a human) NOT to have resolved the issue for this exact
        target — e.g. a caller re-investigating the same neighbor/interface
        right after its just-applied fix's own verification came back still
        broken. Without this, a fresh run() re-seeds the identical compiled
        signature from its identical prior every time, so the SAME hypothesis
        (and therefore the SAME fix) keeps winning again — a real production
        report showed this exact cycle: MTU-mismatch fix applied, verification
        still broken, re-investigate, MTU-mismatch wins again, same fix
        proposed again, repeating indefinitely with confidence never moving
        and no record that this was already tried. Matching hypotheses are
        eliminated immediately after seeding instead of merely left to
        compete — a human-confirmed failure is a fact, not a probabilistic
        signal, the same treatment _bind_compiled_signature_evidence already
        gives a deterministic state contradiction.

        `partial_causes`: root-cause statement -> reason, for a fix that
        genuinely helped SOME but not all of its targets (see
        _apply_partial_refinements). Unlike excluded_causes this does not
        eliminate the hypothesis — it survives, penalized, so it can still
        win if nothing better turns up, rather than being thrown away and
        forcing a full restart on a hypothesis that was partly right."""
        session = Session()
        self._excluded_causes = set(excluded_causes or [])
        self._partial_causes = dict(partial_causes or {})
        # Accumulates real {source, title, text} retrieved across BOTH
        # _grounder(...) calls this run() makes (here, and again before fix
        # generation) — used once at the end (_finish()) to synthesize one
        # multi-source-cited answer. Kept off the persisted Session model
        # itself since it's raw retrieved text, not a durable session fact.
        self._grounding_materials: List[Dict[str, str]] = []
        device_ips = [ip for ip in self._ip_to_dev.keys() if ip]
        grounding = self._grounder(query, self.devices)
        self._record_grounding_citations(session)
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
        self._ensure_protocol_state_observed(session, hmgr, conf, device_ips)
        self._bind_compiled_signature_evidence(session, hmgr, conf)
        self._eliminate_excluded_causes(session)
        self._apply_partial_refinements(session)
        # reap() otherwise only runs inside the main loop, after a
        # successful evidence round. If the loop exits on its very first
        # iteration (e.g. the deterministic anchor above already gathered
        # everything there was to gather, so _next_evidence_via_gateway()
        # finds nothing further non-redundant to fetch and breaks before
        # ever reaching its own reap() call), a hypothesis already
        # deterministically ruled out by the observed state above would
        # never actually get eliminated for the entire session — it would
        # sit at its demoted-but-nonzero confidence, active, for a report
        # that never prunes it. Reaping here means that pruning happens
        # even when the loop contributes nothing further at all.
        hmgr.reap()

        # Now that the actual protocol state (if any) has been observed,
        # check it against what the user's own question claimed — before
        # any further LLM hypothesis generation, so the report can flag a
        # contradicted premise from the very start rather than as an
        # afterthought bolted onto a conclusion about a different state.
        try:
            self._check_goal_evidence_match(session, query)
        except Exception as exc:
            logger.debug("Goal-evidence match check skipped: %s", exc)

        # 1. seed hypotheses FROM the objective + the state just observed —
        #    the LLM EXTENDS the deterministic seed above, it never replaces it
        #    (existing statements are passed so it doesn't duplicate them).
        existing_statements = [h.statement for h in session.hypotheses]
        for h in self.reasoner.generate_hypotheses(
                session.goal.objective, grounding, self._evidence_summary(session),
                existing_statements):
            hmgr.add(h.get("statement", ""), h.get("rationale", ""),
                     h.get("discriminating_signals", []), float(h.get("prior", 0.2) or 0.2))
        self._eliminate_excluded_causes(session)
        self._apply_partial_refinements(session)

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

        for spec in reactive_specs():
            self._bind_reactive_evidence(spec, output, device_ip, command, session, hmgr, conf)

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
                # STP's err-disable reason (udld/link-flap/bpduguard/...) —
                # the one piece of evidence that decides whether this port
                # is safe to auto-recover or must stay a human decision.
                if kv.get("errdisable_reason"):
                    facts.append({"subject": f"neighbor.{oid or '?'}",
                                 "attribute": "errdisable_reason", "value": kv["errdisable_reason"]})
                # The specific interface this neighbor relationship is ON
                # (e.g. OSPF's neighbor table's own trailing "Interface"
                # column) — lets a remediation fix be safely scoped to the
                # actual interface under investigation instead of falling
                # back to whatever interface.*.mtu observation happened to
                # be recorded first, or refusing the fix outright for lack
                # of any interface context at all.
                if kv.get("interface"):
                    facts.append({"subject": f"neighbor.{oid or '?'}",
                                 "attribute": "interface", "value": kv["interface"]})
            elif otype == "protocol":
                if kv.get("adjacency"):
                    facts.append({"subject": f"protocol.{oid or '?'}",
                                 "attribute": "adjacency", "value": kv["adjacency"]})
                if kv.get("state"):
                    facts.append({"subject": f"protocol.{oid or '?'}",
                                 "attribute": "state", "value": kv["state"]})
            elif otype == "interface":
                if kv.get("mtu"):
                    facts.append({"subject": f"interface.{oid or '?'}",
                                 "attribute": "mtu", "value": kv["mtu"]})
                # ip_mtu (from `ip mtu <n>`, IosLikeAdapter's dedicated
                # running-config parse) is kept as its OWN, distinctly-named
                # fact — never merged into "mtu" — since it's a different,
                # independently-configurable value from the interface's
                # hardware MTU, and conflating them is exactly what made a
                # real ip-mtu-based OSPF mismatch invisible before.
                if kv.get("ip_mtu"):
                    facts.append({"subject": f"interface.{oid or '?'}",
                                 "attribute": "ip_mtu", "value": kv["ip_mtu"]})
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
        self._eliminate_excluded_causes(session)
        self._apply_partial_refinements(session)

    def _eliminate_excluded_causes(self, session: Session) -> None:
        """A human already confirmed (via a deployed fix's own post-apply
        verification) that one of these exact root-cause statements does
        NOT explain the current problem for this target — eliminate it
        outright rather than let it keep competing on its original prior.
        This is what stops the exact cycle a real report showed: MTU-
        mismatch fix applied, verification still broken, re-investigate,
        MTU-mismatch (re-seeded from its own unchanged compiled prior) wins
        again, identical fix proposed again, repeating indefinitely.
        A confirmed failure is a fact, not a probabilistic signal — same
        treatment _bind_compiled_signature_evidence already gives an
        observed-state contradiction.

        Overrides CONFIRMED too, not just ACTIVE: run_mismatch_investigation()
        (called from _seed_deterministic_hypotheses, before this method's
        first call in a given run()) runs its OWN internal hmgr.reap() —
        real cross-device evidence plus a high compiled prior can confirm a
        hypothesis in that very first seeding step, before this method ever
        sees it while still ACTIVE. A hypothesis is only ever unreachable
        here once it's ELIMINATED."""
        excluded = getattr(self, "_excluded_causes", None)
        if not excluded:
            return
        for h in session.hypotheses:
            if h.state == HypothesisState.ELIMINATED or h.statement not in excluded:
                continue
            h.state = HypothesisState.ELIMINATED
            h.rationale = (
                (h.rationale + " " if h.rationale else "")
                + "[Already applied and confirmed NOT to have resolved this issue in a "
                  "prior attempt on this target — excluded without new evidence.]"
            )

    def _apply_partial_refinements(self, session: Session) -> None:
        """A prior attempt at one of these exact root-cause statements
        genuinely helped SOME but not all of its targets (see
        copilot_engine.py's _classify_verification_outcome) — unlike
        _eliminate_excluded_causes, this is not treated as disproven: a
        partially-correct hypothesis should stay in play, just penalized,
        so it can still win if nothing better turns up rather than forcing
        a full restart on a cause that was partly right. Applied as an
        ordinary CONTRADICT delta at half the weight of a deterministic
        state contradiction (that's a certain fact; this is "didn't fully
        explain it," a weaker signal) — reap()'s existing confidence floor
        will eventually retire it on its own after enough repeated partial
        failures, with no new elimination path needed."""
        partial = getattr(self, "_partial_causes", None)
        if not partial:
            return
        for h in session.hypotheses:
            if h.state == HypothesisState.ELIMINATED or h.statement not in partial:
                continue
            if any((d.reason or "").startswith("partial-outcome-penalty") for d in h.deltas):
                continue
            reason = partial[h.statement]
            weight = 0.3   # half of _bind_compiled_signature_evidence's deterministic 0.6
            delta = ConfidenceDelta(
                evidence_id="", effect=Effect.CONTRADICT, weight=weight,
                log_odds_change=-ConfidenceCalculator.CONTRADICT_GAIN * weight,
                reason=f"partial-outcome-penalty: {reason}",
            )
            h.apply(delta, "")
            h.rationale = (
                (h.rationale + " " if h.rationale else "")
                + f"[Partially confirmed in a prior attempt on this target — {reason} "
                  "Confidence reduced; still under consideration.]"
            )

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

    def _observed_protocol_state_obs(self, session: Session,
                                     target_ip: Optional[str] = None) -> Optional[Observation]:
        """Best-effort deterministic read of the most recent observation that
        reports an actual protocol/neighbor stuck-state (e.g. 'EXSTART') — the
        same vocabulary compiled FailureSignatures key off of via stuck_state.

        Prefers a "neighbor.*" fact (the specific per-neighbor FSM state:
        Down/Attempt/Init/2-Way/ExStart/Exchange/Loading/Full) over a
        "protocol.*" fact (a coarse up/down summary across ALL neighbors —
        see IosLikeAdapter's PROTOCOL object). Falling back to the coarse
        flag only when no neighbor-specific fact exists avoids the coarse
        "down" (meaning merely "no FULL neighbor yet") outranking the real,
        specific observed state and being compared against it instead.

        When `target_ip` is given — the specific neighbor THIS investigation
        is actually about, e.g. a re-investigation query that explicitly
        names "the OSPF neighbor 192.168.20.2" — scopes the search to
        observations naming that neighbor specifically (its subject
        contains its IP, e.g. "neighbor.192.168.20.2"). Without this, a
        coincidentally more-recent fact about a COMPLETELY DIFFERENT
        neighbor collected in the same evidence round (get_neighbors()
        naturally returns every neighbor on a device, not just the one
        under investigation) could silently stand in for "the observed
        state". A real report showed exactly this: a continuation whose
        Goal named 192.168.20.2 nonetheless compared against a "neighbor
        FULL" fact that was actually about a different, healthy neighbor
        (192.168.21.2) queried in the same sweep — the investigation's
        target had silently shifted with no explanation. When target_ip is
        given but nothing matches it yet, returns None rather than falling
        back to an unrelated neighbor's fact — an unscoped guess here is
        worse than honestly admitting nothing is known yet about THIS
        neighbor."""
        if target_ip:
            for o in reversed(session.observations):
                if (o.attribute == "state" and "neighbor" in o.subject.lower()
                        and o.value and target_ip in o.subject):
                    return o
            return None
        for o in reversed(session.observations):
            if o.attribute == "state" and "neighbor" in o.subject.lower() and o.value:
                return o
        for o in reversed(session.observations):
            if o.attribute == "state" and "protocol" in o.subject.lower() and o.value:
                return o
        return None

    # Matches how people actually phrase this kind of question ("stuck in
    # ExStart", "stuck at Down", "stuck into the Exstart") — deliberately
    # anchored on "stuck" so a query that merely mentions a state word in
    # passing ("the link went down") isn't misread as a deliberate claim
    # about the FSM state.
    _ASKED_STATE_RE = re.compile(r"stuck\s+(?:in|at|into)\s+(?:the\s+)?([A-Za-z0-9\-]+)", re.IGNORECASE)

    # Matches how _continue_investigation_if_needed() (copilot_engine.py)
    # phrases a re-investigation query: "...the OSPF neighbor 192.168.20.2
    # on interface X stuck in Y" — capturing the specific neighbor this
    # investigation is scoped to, if any.
    _QUERY_TARGET_IP_RE = re.compile(r"\bneighbor\s+(\d{1,3}(?:\.\d{1,3}){3})\b", re.IGNORECASE)

    def _query_target_ip(self, query: str) -> Optional[str]:
        m = self._QUERY_TARGET_IP_RE.search(query or "")
        return m.group(1) if m else None

    def _check_goal_evidence_match(self, session: Session, query: str) -> None:
        """Detects when the user's own question names a specific FSM state
        (e.g. "why is OSPF stuck in ExStart") that the actually-observed
        state contradicts (e.g. the neighbor is really in Down).

        Before this, the engine would silently investigate and correctly
        diagnose the REAL observed state while the report's Goal text kept
        repeating the user's original, factually-contradicted premise
        verbatim — nothing anywhere told the user their own question's
        premise didn't match reality. A human engineer's first move here is
        to say so explicitly, not silently answer a different question.
        Sets session.goal_mismatch so the report can surface an explicit
        correction; never blocks the rest of the investigation, since the
        actually-observed state is still a real, worth-investigating
        problem.

        Prefers real PER-NEIGHBOR state facts (neighbor_states) over the
        coarse protocol-level up/down summary flag — a real report showed
        the banner falling back to that flag and displaying "neighbor state
        = up", which is both wrong (there is no per-neighbor state named
        "up" in any FSM this platform models — the flag means "at least one
        neighbor reached Full", not a specific neighbor's own state) and too
        generic to act on. When no per-neighbor fact exists at all, the
        coarse flag is still reported, but honestly labeled as a protocol-
        level status rather than disguised as a neighbor's FSM state.

        When the query names a specific neighbor (_query_target_ip — the
        re-investigation phrasing "...the OSPF neighbor 192.168.20.2..."),
        scopes neighbor_obs to THAT neighbor only. Without this, a
        coincidentally-collected fact about a DIFFERENT, unrelated neighbor
        (e.g. a healthy one queried in the same get_neighbors() sweep) could
        be compared against instead — a real report showed a continuation
        whose Goal named one neighbor produce a mismatch banner built from
        a completely different, healthy neighbor's state, with the
        investigation's actual target silently shifting with no
        explanation. If a target is named but nothing about it has been
        collected yet, this returns without asserting anything, rather than
        falling back to an unrelated neighbor's fact."""
        m = self._ASKED_STATE_RE.search(query or "")
        if not m:
            return
        protocol = self._detect_protocol(query)
        from core.knowledge.compiler.protocol_models import build_protocol_model
        model = build_protocol_model(protocol)
        if model is None:
            return
        asked_norm = self._norm_state(m.group(1))
        asked_state = next((s for s in model.states if self._norm_state(s) == asked_norm), None)
        if not asked_state:
            return

        target_ip = self._query_target_ip(query)
        all_neighbor_obs = [o for o in session.observations
                           if o.attribute == "state" and "neighbor" in o.subject.lower() and o.value]
        neighbor_obs = ([o for o in all_neighbor_obs if target_ip in o.subject]
                       if target_ip else all_neighbor_obs)
        if target_ip and not neighbor_obs:
            return   # named a specific neighbor but have no evidence about it yet
        if neighbor_obs:
            if any(self._norm_state(o.value) == asked_norm for o in neighbor_obs):
                return   # a neighbor genuinely IS in the asked state -> no mismatch
            rep = neighbor_obs[0]
            observed_norm = self._norm_state(rep.value)
            observed_state = next((s for s in model.states if self._norm_state(s) == observed_norm), rep.value)
            devices = sorted({o.device for o in neighbor_obs
                             if self._norm_state(o.value) == observed_norm and o.device})
            session.goal_mismatch = {
                "asked_state": asked_state, "observed_state": observed_state, "devices": devices,
                "neighbor_states": [{"device": o.device, "subject": o.subject, "value": o.value}
                                   for o in neighbor_obs],
            }
            return

        if target_ip:
            return   # named a specific neighbor; never fall back to a device-wide coarse flag
        # No per-neighbor fact was ever collected this round — only the
        # coarse protocol-level up/down summary exists. Report it honestly
        # as a protocol status, never disguised as a specific neighbor's
        # FSM state.
        obs = next((o for o in reversed(session.observations)
                   if o.attribute == "state" and "protocol" in o.subject.lower() and o.value), None)
        if obs is None or self._norm_state(obs.value) == asked_norm:
            return
        session.goal_mismatch = {
            "asked_state": asked_state, "observed_state": None,
            "devices": [obs.device] if obs.device else [],
            "neighbor_states": [], "protocol_status": obs.value,
        }

    def _hypothesis_stuck_state(self, hyp: Hypothesis, model) -> Optional[str]:
        """Which FSM state (if any) this hypothesis's own compiled lineage
        claims to explain. Checks discriminating_signals FIRST — unioned
        across every HypothesisManager.add() merge, so a hypothesis that
        started as a compiled signature and later merged with a Mismatch
        Investigation Finding (a real production case: the OSPF ExStart
        signature merging with a cross-device interface_mtu comparison)
        reliably keeps its own state name even though the SURVIVING
        statement/rationale text came from the OTHER source — e.g. "the
        adjacency hangs in EXSTART/EXCHANGE because the database-
        description exchange fails", which never literally contains
        "stuck in 'ExStart'". Relying on the old rationale-regex-only
        lookup silently skipped exactly these merged hypotheses: they never
        got deterministically confirmed OR contradicted by
        _bind_compiled_signature_evidence, so a merged hypothesis kept its
        full compiled-prior confidence even once the CURRENTLY observed
        state stopped matching what it claims to explain — the direct cause
        of a report that stayed at 92% "MTU mismatch (ExStart)" while, two
        sections above in the SAME report, the goal-evidence-mismatch check
        (which reads observations directly, not this lookup) correctly said
        no neighbor was in ExStart at all.
        Falls back to parsing rationale text only when no protocol model is
        available (a caller that couldn't detect the protocol at all)."""
        if model is not None:
            s = next((s for s in model.states if s in (hyp.discriminating_signals or [])), None)
            if s:
                return s
        m = self._STUCK_STATE_RE.search(hyp.rationale or "")
        return m.group(1) if m else None

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
        stuck_state (via _hypothesis_stuck_state — see its own docstring for
        why discriminating_signals, not rationale text, is the reliable
        source once hypotheses have merged) — nothing else. Every other
        hypothesis (LLM-authored, mismatch-investigation-seeded with no
        compiled lineage at all) is untouched. Runs at most once per
        hypothesis (idempotent via the delta reason tag) so it never
        double-counts across rounds. Scoped to the specific neighbor named
        in the query when the query names one (a re-investigation of one
        particular neighbor) — see _observed_protocol_state_obs's own
        docstring for why comparing against an unrelated neighbor's
        coincidentally-more-recent fact is a real, previously-reported
        bug."""
        query = session.goal.query if session.goal else ""
        target_ip = self._query_target_ip(query)
        obs = self._observed_protocol_state_obs(session, target_ip=target_ip)
        if obs is None:
            return
        observed_norm = self._norm_state(obs.value)
        if not observed_norm:
            return
        protocol = self._detect_protocol(query)
        from core.knowledge.compiler.protocol_models import build_protocol_model
        model = build_protocol_model(protocol)
        for hyp in session.active_hypotheses():
            stuck_state = self._hypothesis_stuck_state(hyp, model)
            if not stuck_state:
                continue
            if any((d.reason or "").startswith("deterministic-state-match") for d in hyp.deltas):
                continue
            stuck_norm = self._norm_state(stuck_state)
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

    def _bind_reactive_evidence(self, spec, output: str, device_ip: str, command: str,
                                session: Session, hmgr: HypothesisManager,
                                conf: ConfidenceCalculator) -> None:
        """Replaces what used to be three separately hand-written methods
        (_bind_acl_deny_evidence / _bind_nat_role_evidence /
        _bind_vlan_native_mismatch_evidence) whose only real difference
        was a handful of strings and one compile function — now declared
        once per protocol in protocol_registry.py's ProtocolSpec and
        rendered generically here.

        None of ACL/NAT/VLAN fit the "seed a prior, then bind evidence
        later" shape every FSM protocol above uses — there's no prior to
        seed before the relevant device output has actually been read;
        the deny rule / missing NAT role / CDP mismatch IS the evidence,
        discovered reactively the moment it's observed. So unlike
        _bind_compiled_signature_evidence, this both seeds AND confirms
        in one step, immediately, the first time each distinct signature
        is observed (idempotent via the existing hypothesis-statement
        dedup in hmgr.add())."""
        if not spec.reactive_compile_fn:
            return
        try:
            from core.vendor.models import NormalizedObject
        except Exception:
            return
        matched: List[NormalizedObject] = []
        for line in (output or "").splitlines():
            m = self._GATEWAY_OBJ_LINE.match(line.strip())
            if not m or m.group("type") != spec.reactive_object_type:
                continue
            kv: Dict[str, str] = {}
            for pair in m.group("kv").split(", "):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    kv[k.strip()] = v.strip()
            matched.append(NormalizedObject(type=spec.reactive_object_type, id=m.group("id"),
                                            device=m.group("device"), attributes=kv))
        if not matched:
            return
        existing = {h.statement for h in session.hypotheses}
        for sig in spec.reactive_compile_fn(matched):
            if sig.likely_cause in existing:
                continue
            h = hmgr.add(
                sig.likely_cause,
                rationale=(f"Compiled {spec.reactive_rationale_label} signature "
                          f"(confidence {sig.confidence:.2f}). Source: core.knowledge."
                          f"compiler.failure_signatures — {spec.reactive_rationale_reason}"),
                discriminating_signals=list(sig.evidence_fields) + [spec.name],
                prior=sig.confidence)
            if h is None:
                continue
            self._note_knowledge_source(
                session, f"compiled {spec.reactive_note_label} signature: {sig.stuck_state}")
            obs = Observation(device=device_ip, subject=f"{spec.name}.{sig.stuck_state}",
                              attribute="detected", value="true", source_command=command,
                              raw_snippet=sig.likely_cause[:200])
            session.observations.append(obs)
            try:
                self.graph.add_observation(obs)
            except Exception:
                pass
            ev = Evidence(observation_id=obs.id, hypothesis_id=h.id, effect=Effect.SUPPORT,
                         weight=spec.reactive_evidence_weight, reason=spec.reactive_evidence_reason)
            session.evidence.append(ev)
            conf.update(h, ev, obs)

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
        # protocol_registry.all_keywords() is the single source of truth
        # for every protocol this platform models — "eigrp" is the one
        # keyword here that ISN'T (genuinely unmodeled, kept only so this
        # fallback still recognizes the word instead of falling to
        # "general"). This used to be a second, independently-maintained
        # copy of intent_engine.py's own list — the two had already
        # drifted apart for real once (STP was missing from the other
        # list for the entire time its signatures existed).
        for p in (*all_keywords(), "eigrp"):
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
            # Seed EVERY known compiled signature for the protocol — never
            # narrow by matching the query's wording against a stuck_state
            # name. That narrowing used to seed only the signature whose name
            # appeared in the query text, but a casual phrase like "OSPF down
            # state" (meaning "not working", not the literal FSM state) is
            # indistinguishable from a deliberate "stuck in Down" report —
            # and narrowing to the wrong signature permanently locked out the
            # correct one (it was never seeded, so no later evidence could
            # ever resurrect it) AND starved the command planner's
            # discriminating-signal prompt (Down's only signal is
            # "admin_state", so "show ip ospf neighbor" — the one command
            # that reveals the real state — was never even suggested).
            # _bind_compiled_signature_evidence() already deterministically
            # confirms the matching signature and contradicts the rest once
            # real evidence arrives, so seeding all of them costs nothing and
            # loses nothing.
            signatures = compile_failure_signatures(protocol)

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

    def _ensure_protocol_state_observed(self, session: Session, hmgr: HypothesisManager,
                                        conf: ConfidenceCalculator, device_ips: List[str]) -> None:
        """Closes the real gap behind "why do I get a different answer every
        time, and why does it never converge to a fix": every compiled
        FailureSignature just seeded above is keyed off an observed
        stuck_state (Down/Init/ExStart/...), but nothing GUARANTEED the one
        command that reveals it (show ip ospf neighbor / show ip bgp
        summary / ...) ever actually got collected — plan_operations() is
        entirely LLM-driven, sees only a bare list of operation NAMES (no
        descriptions), and the discriminating-signal hints derived from
        each signature's evidence_fields (mtu/areas/admin_state/...) never
        include the state itself as a signal, so the LLM had no reliable
        reason to prioritize it over get_interface_details/get_configuration.
        Without it, _bind_compiled_signature_evidence's one deterministic,
        high-weight (0.6) confirm/contradict pass never fires for ANY
        signature, every run just drifts on weak LLM-derived guesses, and
        which secondary command the LLM happens to reach for first (and in
        what order) varies call to call — the literal mechanism behind
        "different output for the same issue."

        Deterministically fetches whichever operation this protocol's own
        adapter defines as neighbor/state-revealing (GET_NEIGHBORS for
        OSPF/BGP, GET_INTERFACE_DETAILS for LACP/HSRP/VRRP/STP) exactly
        once, before the LLM ever forms or extends a hypothesis — same
        "deterministic anchor before any LLM judgment" precedent as
        _seed_deterministic_hypotheses and _bind_compiled_signature_evidence
        themselves. A no-op if the state is already known (e.g. re-seeded
        from session memory), if this isn't an FSM protocol (ACL/NAT/VLAN
        are reactive-only, no state_model), or outside gateway/adapter mode.

        Tries GET_NEIGHBORS first and falls back to GET_INTERFACE_DETAILS
        only if that didn't actually surface a state — deliberately NOT
        gated on VendorGateway.supports_operation(), which turned out to be
        far too permissive to use as a per-protocol capability check (it
        allows every operation name except two hardcoded exceptions,
        regardless of whether this protocol's own AdapterSpec.commands
        maps that operation to anything at all — confirmed directly
        against an adapter's own build_command() implementation. Trusting
        it here would have silently no-op'd for LACP/STP/HSRP/VRRP (whose
        commands dict has no "get_neighbors" key) while claiming to have
        tried it."""
        if self.gateway is None:
            return
        try:
            protocol = self._detect_protocol(session.goal.query)
            spec = get_spec(protocol)
            if spec is None or spec.state_model is None:
                return
            # Scoped to the specific neighbor named in the query, if any —
            # otherwise this stops probing the moment ANY neighbor's state
            # is known, even an unrelated one collected incidentally (e.g.
            # a device's OTHER, healthy adjacency returned by the same
            # get_neighbors() call) — the same staleness risk documented on
            # _observed_protocol_state_obs itself.
            target_ip = self._query_target_ip(session.goal.query)
            if self._observed_protocol_state_obs(session, target_ip=target_ip) is not None:
                return
            from core.vendor.operations import Op, Operation

            for opname in (Op.GET_NEIGHBORS, Op.GET_INTERFACE_DETAILS):
                params = {"protocol": protocol}
                sig = self._op_signature(opname, params)
                targets = [ip for ip in device_ips if not self.cmd_memory.has(ip, sig)]
                if not targets:
                    if self._observed_protocol_state_obs(session, target_ip=target_ip) is not None:
                        break
                    continue
                session.next_best_command = (
                    f"[operation] {opname} {params} → {targets[0] if len(targets) == 1 else 'all'}")
                for ip in targets:
                    device = self._ip_to_dev.get(ip)
                    if device is None:
                        continue
                    objects, err = self.gateway.collect(device, Operation(
                        opname, params, "deterministic neighbor/protocol-state anchor"))
                    if err is not None:
                        text = f"error[{err.error_class.value}]: {err.message}"
                    else:
                        text = "\n".join(o.summary() for o in objects) or "(no normalized objects)"
                    session.executed.append(self.cmd_memory.record(
                        ip, sig, text, "deterministic neighbor/protocol-state anchor", reused=False))
                    self._ingest_output(sig, ip, text, session, hmgr, conf)
                if self._observed_protocol_state_obs(session, target_ip=target_ip) is not None:
                    self._note_knowledge_source(
                        session, f"deterministic neighbor/protocol-state anchor: {protocol}/{opname}")
                    break
        except Exception as exc:
            logger.debug("Deterministic protocol-state anchor skipped: %s", exc)

    def _note_knowledge_source(self, session: Session, source: str) -> None:
        """Records provenance for the report's 'Knowledge Sources Consulted'
        section — only called where compiled NKC knowledge actually
        contributed, so a session with none stayed pure-LLM."""
        if source not in session.knowledge_sources:
            session.knowledge_sources.append(source)

    def _record_grounding_citations(self, session: Session) -> None:
        """IntentEngine._ground() genuinely executes real RAG/MCP lookups
        (self._grounder(...), called just above) — but before this existed,
        whatever it actually found (or didn't) left no trace in the final
        report: a user had no way to tell whether their conclusion was
        informed by real documentation or not. Reads IntentEngine._ground()'s
        own self._last_grounding_citations (reset fresh on every _ground()
        call) and records each into session.knowledge_sources, exactly like
        every compiled-signature citation already is. Deliberately does NOT
        feed these into ConfidenceCalculator — RAG/MCP relevance is a best-
        effort heuristic (see core.knowledge.mcp.devnet_content_source's own
        confidence scoring), not verified ground truth, so it stays
        informational context a human can weigh, never a silent input to
        the audited confidence math.

        Also accumulates IntentEngine._last_grounding_materials (the real
        {source, title, text} behind each citation, not just its label)
        into self._grounding_materials, deduped by (source, title) so the
        two _grounder(...) calls run() makes don't feed the same hit into
        synthesize_answer() twice — see _finish()'s own use of this."""
        for source in getattr(self._intent, "_last_grounding_citations", None) or []:
            self._note_knowledge_source(session, source)
        seen = {(m["source"], m["title"]) for m in self._grounding_materials}
        for m in getattr(self._intent, "_last_grounding_materials", None) or []:
            key = (m.get("source", ""), m.get("title", ""))
            if key not in seen:
                seen.add(key)
                self._grounding_materials.append(m)

    def _persist(self, session: Session) -> None:
        try:
            self.session_memory.save(session)
        except Exception:
            pass

    # ── conclusion ──────────────────────────────────────────────────────────────
    def _compiled_remediation_intent(self, session: Session, root_cause_statement: str,
                                     allowed_intents: List[str], protocol: str,
                                     discriminating_signals: Optional[List[str]] = None,
                                     device_ip: str = "") -> Optional[dict]:
        """Checks the NKC's compiled RemediationTemplate mapping
        (core.knowledge.compiler.reasoning_artifact_compiler) for a
        deterministic cause->intent mapping BEFORE asking the LLM to guess
        one. Returns None (falls through to the LLM) for any cause the
        compiled library doesn't cover.

        Matches primarily via discriminating_signals against the protocol's
        FSM state names (same technique as _compile_reasoning_chain), NOT
        by exact statement-text equality alone: after HypothesisManager.
        add()'s discriminating-signal merge (a mismatch-investigation
        hypothesis + its compiled-signature counterpart naming the same
        parameter), the SURVIVING hypothesis keeps whichever statement was
        seeded first — usually the mismatch investigation's templated text
        ("interface_mtu must equal violated..."), NOT the compiled
        signature's canned likely_cause ("MTU mismatch between OSPF
        neighbors prevents DBD packet exchange") that
        RemediationTemplate.applicable_signature was built from. Comparing
        root_cause_statement against applicable_signature by exact equality
        would then never match for a merged hypothesis, silently falling
        through to an LLM guess (or nothing at all, given an ai_call that
        contributes nothing) despite a compiled remediation genuinely
        existing for this exact cause. Falls back to the original exact-text
        match for hypotheses with no compiled-signature lineage at all (pure
        LLM-authored, no discriminating_signals matching any FSM state).

        `protocol` is passed in by the caller (already correctly detected
        from session.goal.query) rather than re-derived from the hypothesis
        statement text here — re-deriving it from the statement only ever
        worked for OSPF by coincidence (every OSPF signature's likely_cause
        happens to mention "OSPF" literally); BGP's signatures don't all
        mention "BGP" (e.g. "Repeated TCP connection failures..."), so
        re-detecting from that text would silently fall back to "general"
        and never find a match — the same class of bug as the earlier
        query-wording seeding issue, fixed the same way: use the value
        that's already known to be correct instead of re-guessing it.

        `device_ip`: when set, every observation/executed-command scan below
        is scoped to facts recorded against THIS device only — needed
        because a cross-device root cause (e.g. an MTU mismatch) has two
        different, genuinely different interface values, one per side; an
        unscoped scan would give both devices whichever value was recorded
        last in the whole session, not each device's own. Empty (default)
        preserves the original unscoped behavior for the single-device case."""
        try:
            from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
            from core.knowledge.compiler.failure_signatures import compile_failure_signatures
            from core.knowledge.compiler.protocol_models import build_protocol_model
        except Exception:
            return None
        target_signature = root_cause_statement
        model = build_protocol_model(protocol)
        if model is not None and discriminating_signals:
            stuck_state = next((s for s in model.states if s in discriminating_signals), None)
            if stuck_state:
                sig = next((s for s in compile_failure_signatures(protocol)
                           if s.stuck_state == stuck_state), None)
                if sig:
                    target_signature = sig.likely_cause
        try:
            for template in ReasoningArtifactCompiler().compile_remediation(protocol):
                if template.applicable_signature != target_signature:
                    continue
                if allowed_intents and template.intent_name not in allowed_intents:
                    continue
                iface = ""
                neighbor_ip = ""
                errdisable_reason = ""
                # Prefer the interface EXPLICITLY named in the most recent
                # get_interface_details call — that's the interface actually
                # under investigation right now. The fallback below (first
                # interface.*.mtu observation ever recorded) picks whichever
                # interface was scanned earliest in the WHOLE session, which
                # can be a completely unrelated interface on a multi-interface
                # device (e.g. a generic first-pass read of FastEthernet0/0
                # winning over the Gi1/0 that's actually part of the broken
                # adjacency under investigation).
                for ec in reversed(session.executed):
                    if device_ip and ec.device != device_ip:
                        continue
                    m = re.search(r"get_interface_details\([^)]*\binterface=([^,)]+)", ec.command)
                    if m and m.group(1):
                        iface = m.group(1)
                        break
                # Second priority: the specific interface named in the
                # neighbor table row for the adjacency actually under
                # investigation (e.g. OSPF's "show ip ospf neighbor" own
                # trailing Interface column) — more reliable than the
                # generic mtu-observation fallback below, which can pick an
                # unrelated interface on a multi-interface device.
                if not iface:
                    for o in reversed(session.observations):
                        if device_ip and o.device != device_ip:
                            continue
                        if o.subject.startswith("neighbor.") and o.attribute == "interface" and o.value:
                            iface = o.value
                            break
                for o in session.observations:
                    if device_ip and o.device != device_ip:
                        continue
                    if o.subject.startswith("interface.") and o.attribute == "mtu" and not iface:
                        iface = o.subject.split(".", 1)[1]
                    # BGP (and any future neighbor-scoped protocol) remediation
                    # intents act on a specific peer, not an interface — e.g.
                    # "no neighbor <ip> shutdown" needs the actual neighbor
                    # identity, which OSPF's interface-scoped intents never
                    # needed to carry.
                    if o.subject.startswith("neighbor.") and o.attribute == "state" and not neighbor_ip:
                        neighbor_ip = o.subject.split(".", 1)[1]
                    # STP's enable_errdisable_recovery intent needs the actual
                    # observed cause word (udld/link-flap/...) to fill in
                    # "errdisable recovery cause {errdisable_reason}" — unlike
                    # every other compiled intent, this value is a VALUE fact,
                    # not an id recovered from the observation's subject.
                    if o.subject.startswith("neighbor.") and o.attribute == "errdisable_reason" and not errdisable_reason:
                        errdisable_reason = o.value
                self._note_knowledge_source(
                    session, f"compiled remediation template: {protocol}/{template.intent_name}")
                return {"name": template.intent_name,
                       "params": {"protocol": protocol, "interface": iface, "neighbor_ip": neighbor_ip,
                                 "errdisable_reason": errdisable_reason},
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

    def _synthesize_answer(self, session: Session) -> None:
        """Populates session.synthesized_answer — one short, multi-source-
        cited answer from whatever real RAG/vendor-doc/MCP material
        _grounder(...) actually retrieved this run (accumulated in
        self._grounding_materials by _record_grounding_citations()).

        Directly answers a gap identified from a user's own Google AI
        Overview screenshot: that overview synthesizes ONE cited answer
        from multiple real sources (e.g. "Vendor Docs +2") rather than
        listing them separately. This tool already retrieved multiple
        real sources and cited them (session.knowledge_sources) but never
        synthesized them into a single coherent, attributed answer the
        way a search engine's own overview does — this closes that gap.

        A no-op (empty string, nothing set) when nothing real was
        retrieved this session — matches Reasoner.synthesize_answer()'s
        own refusal to synthesize from zero sources. Purely presentational:
        does not feed ConfidenceCalculator or hypothesis ranking, same
        boundary _record_grounding_citations() already documents for
        session.knowledge_sources itself."""
        materials = getattr(self, "_grounding_materials", None) or []
        if not materials:
            return
        try:
            query = session.goal.query if session.goal else ""
            session.synthesized_answer = self.reasoner.synthesize_answer(query, materials)
        except Exception as exc:
            logger.debug("Answer synthesis skipped: %s", exc)

    def _record_ambiguous_outcome(self, session: Session) -> None:
        """Broadens the learning loop beyond deployed-fix outcomes. Until
        now, NetworkIntelligenceSupplyChain only ever learned from a
        session that reached a human Confirm/Deny click on a deployed fix
        (core.copilot_engine._record_ts_outcome) — a session that ends
        ESCALATE or LIKELY_CAUSE_PRESENT never reaches that click, so it
        was invisible to recurring-failure detection even though "we
        investigated this shape of problem and never confirmed a cause"
        is itself operationally significant and worth surfacing if it
        keeps recurring. Reuses record_failed_resolution (not a new
        method) since that's what already feeds OperationalMemory.
        recurring_failures()/build_failure_signatures() by signature —
        best-effort, never blocks or fails a session over it."""
        if session.status not in (ResolutionStatus.ESCALATE, ResolutionStatus.LIKELY_CAUSE_PRESENT):
            return
        try:
            from core.knowledge.compiler.supply_chain import NetworkIntelligenceSupplyChain
            top = session.top()
            query = session.goal.query if session.goal else ""
            protocol = self._detect_protocol(query) if query else ""
            device_ip = session.goal.devices[0] if (session.goal and session.goal.devices) else ""
            reason = (session.escalation_reason or (top.statement if top else "") or
                      "no root cause reached the confirmation threshold")
            NetworkIntelligenceSupplyChain().record_failed_resolution(
                query, device_ip, reason=reason, protocol=protocol)
        except Exception as exc:
            logger.debug("Ambiguous/escalated outcome recording skipped: %s", exc)

    _LOCAL_REMOTE_RE = re.compile(r"\(local=([^,]+), remote=([^)]+)\)")

    def _compile_reasoning_chain(self, session: Session, top: Hypothesis) -> None:
        """Populates session.reasoning_chain: what the observed protocol state
        already confirms succeeded, what being stuck there specifically means
        is failing, and (when available) the concrete evidence comparison —
        so the report shows the diagnostic reasoning chain an engineer would
        otherwise have to reconstruct mentally, instead of jumping straight
        from a confidence score to a bare conclusion.

        Narrates the ACTUALLY, CURRENTLY observed state
        (_observed_protocol_state_obs) — never top's own static
        discriminating_signals tag in isolation. A real production report
        showed why that distinction matters: the winning hypothesis was a
        compiled ExStart signature merged with a Mismatch Investigation
        Finding, so it permanently carries "ExStart" as a signal from
        seed time — but THIS run's real evidence never showed any neighbor
        in ExStart at all (a different, healthier condition was observed).
        The old lookup didn't care; it built a full "Observed: ExStart ->
        MTU mismatch, 85% confidence" narrative anyway, directly
        contradicting the Question vs. Evidence Mismatch banner two
        sections above in the SAME report. Two independent code paths were
        each deciding "what state is this" from a different source of
        truth and could disagree.
        Also requires top's OWN claimed state (_hypothesis_stuck_state —
        same merge-safe discriminating_signals lookup
        _bind_compiled_signature_evidence uses) to AGREE with that real
        observation before rendering anything: if the winning hypothesis
        doesn't actually explain the state that was just observed, there is
        nothing honest to narrate, and the chain is skipped entirely rather
        than explaining a state nobody saw.

        Scoped to the specific neighbor named in the query when the query
        names one — see _observed_protocol_state_obs's own docstring for
        why an unrelated neighbor's coincidentally-more-recent fact must
        never silently stand in for "what was observed" here.
        """
        query = session.goal.query if session.goal else ""
        protocol = self._detect_protocol(query)
        from core.knowledge.compiler.protocol_models import build_protocol_model
        model = build_protocol_model(protocol)
        if model is None:
            return
        target_ip = self._query_target_ip(query)
        obs = self._observed_protocol_state_obs(session, target_ip=target_ip)
        if obs is None:
            return
        observed_norm = self._norm_state(obs.value)
        stuck_state = next((s for s in model.states if self._norm_state(s) == observed_norm), None)
        if not stuck_state:
            return
        top_stuck_state = self._hypothesis_stuck_state(top, model)
        if top_stuck_state is None or self._norm_state(top_stuck_state) != observed_norm:
            return
        from core.knowledge.compiler.failure_signatures import explain_stuck_state
        chain = explain_stuck_state(protocol, stuck_state)
        if not chain:
            return
        m = self._LOCAL_REMOTE_RE.search(top.statement or "")
        if m:
            chain["evidence_comparison"] = {"local": m.group(1).strip(), "remote": m.group(2).strip()}
        session.reasoning_chain = chain

    def _finish(self, session: Session, ranker: RootCauseRanker) -> TroubleshootReport:
        top = session.top()
        self._synthesize_answer(session)

        if top:
            try:
                from core.knowledge.compiler.reasoning_artifact_compiler import ReasoningArtifactCompiler
                risk = ReasoningArtifactCompiler().compile_risk(
                    self._detect_protocol(session.goal.query),
                    affected_object_count=len(session.observations),
                    observed_confidence=top.confidence)
                session.risk = {
                    "severity": risk.severity, "probability": risk.probability,
                    "impact": risk.impact, "affected_object_count": risk.affected_object_count,
                    "mitigation_reference": risk.mitigation_reference,
                }
            except Exception as exc:
                logger.debug("Risk compilation skipped: %s", exc)

        if top:
            try:
                self._compile_reasoning_chain(session, top)
            except Exception as exc:
                logger.debug("Reasoning chain compilation skipped: %s", exc)

        if top and ranker.converged(session) and self.gateway is not None:
            # Vendor-agnostic remediation: engine emits a NEUTRAL intent; the
            # adapter (via gateway) produces vendor fix + rollback + verification.
            # Looped per participant device rather than a single call: a real
            # production report showed an MTU mismatch (inherently two-sided)
            # fixed with `ip ospf mtu-ignore` pushed to ONLY one of the two
            # devices involved, because target_ip used to be a single
            # arbitrary index into session.goal.devices — the asymmetric
            # one-sided apply made the adjacency regress from EXSTART to
            # INIT instead of reaching FULL. When the root cause names two
            # participant devices ("... between A and B ...", the exact
            # convention strategies/mismatch_bridge.py already produces for
            # every cross-device Finding), remediate() is now called once
            # per participant, each with ITS OWN correctly device-scoped
            # interface (see _compiled_remediation_intent's device_ip param)
            # — not the same single target as before.
            from core.vendor.operations import RemediationIntent
            from .strategies.device_pair import extract_between_devices

            default_target = session.goal.devices[0] if session.goal.devices else ""
            pair = extract_between_devices(top.statement)
            if pair and all(ip in self._ip_to_dev for ip in pair):
                participant_ips = list(pair)
            else:
                # No named pair, or one of the two isn't in this session's
                # device scope -- exactly today's single-device behavior.
                # Deliberately NOT "apply to whichever one IS known": that
                # would just manufacture a new one-sided fix, the very shape
                # of bug this loop exists to fix.
                participant_ips = [default_target]

            protocol = self._detect_protocol(session.goal.query)
            all_fix_cmds: List[str] = []
            all_rollback_cmds: List[str] = []
            verif_cmds: List[str] = []
            per_device_plan: Dict[str, Any] = {}
            last_intent_name = ""
            last_explanation = ""
            for ip in participant_ips:
                device = self._ip_to_dev.get(ip) or (self.devices[0] if self.devices else None)
                if device is None:
                    continue
                allowed = []
                try:
                    allowed = self.gateway.supported_intents(device)
                except Exception:
                    allowed = []
                intent_raw = self._compiled_remediation_intent(
                    session, top.statement, allowed, protocol, top.discriminating_signals,
                    device_ip=ip) or \
                            self.reasoner.propose_intent(
                                top.statement, session.goal.objective,
                                self._evidence_summary(session), allowed)
                intent = RemediationIntent(
                    name=str(intent_raw.get("name", "")).strip(),
                    params=intent_raw.get("params", {}) or {},
                    target_device=ip,
                    rationale=intent_raw.get("rationale", ""),
                )
                plan = self.gateway.remediate(device, intent) if intent.name else None
                if not (plan and plan.supported and plan.fix_commands):
                    continue
                per_device_plan[ip] = plan
                last_intent_name = intent.name
                last_explanation = plan.explanation or intent.rationale
                # Tag each line only when there's more than one participant —
                # a single-device fix stays byte-identical to today's output.
                tag = f"(on {ip}) " if len(participant_ips) > 1 else ""
                all_fix_cmds.extend(tag + c for c in plan.fix_commands)
                all_rollback_cmds.extend(tag + c for c in plan.rollback_commands)
                verif_cmds.extend(plan.verification_commands)

            if per_device_plan:
                validation_md = f"Vendor-validated by adapter for intent `{last_intent_name}`."
                if len(per_device_plan) > 1:
                    validation_md += f" Applied across {len(per_device_plan)} devices."
                skipped = [ip for ip in participant_ips if ip not in per_device_plan]
                if skipped:
                    validation_md += f" (no fix produced for: {', '.join(skipped)})"
                session.fix = Fix(
                    root_cause=top.statement, config_commands=all_fix_cmds,
                    rollback_commands=all_rollback_cmds,
                    explanation=last_explanation, syntax_ok=True,
                    validation_md=validation_md,
                    target_devices=list(per_device_plan.keys()),
                )
                compiled_verif = self._compiled_verification(session, protocol)
                # both participants likely share verification commands
                # verbatim (e.g. "show ip ospf neighbor") -- de-dup, preserve order.
                seen: set = set()
                verif_cmds = [c for c in verif_cmds if not (c in seen or seen.add(c))]
                session.verification = VerificationPlan(
                    commands=verif_cmds,
                    success_criteria=(compiled_verif["success_criteria"] if compiled_verif
                                     else "Adapter-defined verification of the applied intent."),
                    rollback_on_fail=all_rollback_cmds,
                )
                session.status = ResolutionStatus.RESOLVED_PENDING_APPROVAL
                if top.state == HypothesisState.ACTIVE:
                    top.state = HypothesisState.CONFIRMED
            else:
                session.status = ResolutionStatus.LIKELY_CAUSE_PRESENT
            self._record_ambiguous_outcome(session)
            self._persist(session)
            return TroubleshootReport(session)

        if top and ranker.converged(session):
            # Fix Generator (approval-gated) + Verification Planner
            grounding = self._grounder(session.goal.query, self.devices)
            self._record_grounding_citations(session)
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
            # "No hypothesis survived" is NOT the same fact as "confirmed
            # healthy" — a real production report showed this exact
            # confusion: a re-investigation's own target-scoping correctly
            # refused to bind evidence for an unrelated neighbor and
            # correctly declined to raise a goal-mismatch banner without
            # real evidence for the NAMED target, leaving zero hypotheses —
            # and this branch then converted that into "🟢 No fault found",
            # even though the SAME session's observations plainly showed a
            # different neighbor stuck in EXSTART (not the protocol's
            # healthy terminal state). Before declaring healthy, check
            # whether any neighbor/protocol observation this session
            # actually gathered contradicts that — if so, this is an
            # "insufficient evidence to explain what we DID see" case, not
            # a clean bill of health.
            session.status = ResolutionStatus.HEALTHY
            protocol = self._detect_protocol(session.goal.query)
            from core.knowledge.compiler.protocol_models import build_protocol_model
            model = build_protocol_model(protocol)
            if model is not None and model.states:
                good = self._norm_state(model.states[-1])
                for o in session.observations:
                    subj = o.subject.lower()
                    if ("neighbor" not in subj and "protocol" not in subj):
                        continue
                    if o.attribute not in ("state", "adjacency") or not o.value:
                        continue
                    if self._norm_state(o.value) != good:
                        session.status = ResolutionStatus.ESCALATE
                        session.escalation_reason = (
                            f"observed {o.attribute} '{o.value}' on {o.subject} is not "
                            f"this protocol's healthy terminal state ('{model.states[-1]}'), "
                            "but no hypothesis could be confidently formed to explain it — "
                            "escalating rather than reporting healthy.")
                        break
        else:
            if session.status == ResolutionStatus.IN_PROGRESS:
                session.status = ResolutionStatus.ESCALATE
                session.escalation_reason = session.escalation_reason or (
                    "evidence was insufficient to confirm a single root cause above the "
                    "confidence threshold.")

        session.next_best_command = "" if session.status in (
            ResolutionStatus.RESOLVED_PENDING_APPROVAL, ResolutionStatus.HEALTHY
        ) else session.next_best_command

        self._record_ambiguous_outcome(session)

        try:
            self.session_memory.save(session)
        except Exception:
            pass
        return TroubleshootReport(session)
