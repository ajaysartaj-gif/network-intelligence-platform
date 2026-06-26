"""
core/intelligence/learning/learners.py
========================================
The learners — each turns experience into durable improvement along one platform
dimension. Every learner can act ONLINE (react to a single event the moment it
happens) and/or in RETROSPECT (mine the whole corpus for what only becomes
visible at scale: emergent patterns, repeated mistakes, winning strategies).

Together they make the guarantee concrete: every success, every failure, every
operator interaction, every deployment, every incident improves the platform —
across knowledge, memory, reasoning, prediction, decision, risk, execution,
confidence, trust and planning — and none of it retrains the LLM.
"""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from typing import Any, Dict, List

from core.intelligence.learning.base import (
    Learner, LearnerSpec, Lesson, LessonType, LessonStore, LearningEvent, Corpus,
)


def _sys():
    from core.intelligence.memory import get_memory_system
    return get_memory_system()


def _symptoms(ev: LearningEvent) -> str:
    fails = [c.get("description") or c.get("reason") or ""
             for c in ev.conditions if str(c.get("verdict") or "").lower() == "fail"]
    return "; ".join([s for s in fails if s]) or ev.metadata.get("symptom", "")


def _cause(ev: LearningEvent) -> str:
    return ev.metadata.get("root_cause") or ev.signature or ""


# ════════════════════════════════════════════════════════════════════════════
class PatternLearner(Learner):
    """Knowledge / Reasoning / Prediction — discovers correlations."""
    def observe(self, ev: LearningEvent) -> List[str]:
        out = []
        sym, cause = _symptoms(ev), _cause(ev)
        if ev.success and ev.commands:
            fix = "; ".join(ev.commands[:4])
            try:
                _sys().pattern.observe("cause_fix", ev.intent, fix,
                                       protocol=ev.protocol)
            except Exception:
                pass
            out.append(self._emit(Lesson(
                LessonType.PATTERN.value,
                f"For «{ev.intent}», the fix that worked: {fix}",
                trigger=ev.intent, recommendation=fix, scope=ev.domain,
                dimensions=["knowledge", "reasoning", "prediction"],
                confidence=0.6, source=self.spec.key)))
        if sym and (cause or ev.intent):
            try:
                _sys().pattern.observe("symptom_cause", sym, cause or ev.intent,
                                       protocol=ev.protocol)
            except Exception:
                pass
        return out

    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        # co-occurrence mining: which (signature → resolving intent) pairs recur.
        pairs = Counter()
        by_sig = defaultdict(list)
        for e in corpus.events():
            sig = e.get("signature") or ""
            if sig:
                by_sig[sig].append(e)
        discovered = 0
        for sig, evs in by_sig.items():
            fixes = Counter(e.get("intent") or e.get("summary", "")
                            for e in evs if e.get("outcome") == "success")
            for fix, n in fixes.items():
                if n >= 2 and fix:
                    pairs[(sig, fix)] += n
                    self._emit(Lesson(
                        LessonType.PATTERN.value,
                        f"Signature «{sig[:40]}» is resolved by «{fix}» "
                        f"({n}× observed)",
                        trigger=sig, recommendation=fix, scope="global",
                        dimensions=["knowledge", "prediction", "reasoning"],
                        confidence=min(0.9, 0.5 + 0.1 * n), validated=n >= 3,
                        evidence_count=n, source=self.spec.key))
                    discovered += 1
        return {"patterns_discovered": discovered}


# ════════════════════════════════════════════════════════════════════════════
class MistakeLearner(Learner):
    """Risk / Execution / Decision — identifies repeated mistakes."""
    def observe(self, ev: LearningEvent) -> List[str]:
        if ev.success is False:
            harm = _symptoms(ev) or "change failed its post-conditions"
            try:
                _sys().failure.record_scar(
                    ev.intent, f"{ev.protocol or 'generic'} on {ev.device or 'device'}",
                    harm, signature=ev.signature, severity=0.65)
            except Exception:
                pass
            return [self._emit(Lesson(
                LessonType.MISTAKE.value,
                f"«{ev.intent}» on {ev.protocol or 'device'} failed: {harm}",
                trigger=ev.intent, recommendation=f"avoid/repair before retrying: {harm}",
                scope=ev.domain, dimensions=["risk", "execution", "decision"],
                confidence=0.6, source=self.spec.key))]
        return []

    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        # the heart of "identify repeated mistakes": failures that keep recurring.
        named = 0
        for rf in corpus.recurring_failures(min_count=2):
            count = int(rf.get("count") or rf.get("occurrences") or 2)
            self._emit(Lesson(
                LessonType.MISTAKE.value,
                f"REPEATED MISTAKE: {rf.get('summary') or rf.get('signature','')} "
                f"has recurred {count}×",
                trigger=rf.get("signature", ""),
                recommendation="treat as systemic; fix root cause, not symptom",
                scope="global", dimensions=["risk", "decision", "planning"],
                confidence=min(0.95, 0.6 + 0.08 * count), validated=True,
                evidence_count=count, source=self.spec.key,
                metadata={"systemic": True}))
            named += 1
        # repeated mistakes by intent (same intent failing across devices)
        fail_intents = Counter(e.get("intent") or "" for e in corpus.by_outcome(False))
        for intent, n in fail_intents.items():
            if intent and n >= 3:
                self._emit(Lesson(
                    LessonType.MISTAKE.value,
                    f"«{intent}» fails often ({n}×) — likely a flawed approach",
                    trigger=intent, recommendation="revise the standard approach for this intent",
                    scope="global", dimensions=["execution", "planning"],
                    confidence=min(0.9, 0.5 + 0.1 * n), validated=n >= 3,
                    evidence_count=n, source=self.spec.key))
                named += 1
        return {"repeated_mistakes_named": named}


# ════════════════════════════════════════════════════════════════════════════
class StrategyLearner(Learner):
    """Planning / Execution — identifies successful strategies."""
    def observe(self, ev: LearningEvent) -> List[str]:
        if ev.success and ev.commands:
            try:
                _sys().procedural.learn_outcome(ev.intent, ev.protocol,
                                                ev.commands, True, device=ev.device)
            except Exception:
                pass
            if ev.resolution_time_s and ev.resolution_time_s < 300:
                return [self._emit(Lesson(
                    LessonType.STRATEGY.value,
                    f"Fast win: «{ev.intent}» resolved in "
                    f"{ev.resolution_time_s:.0f}s with a known procedure",
                    trigger=ev.intent, recommendation="; ".join(ev.commands[:4]),
                    scope=ev.domain, dimensions=["planning", "execution"],
                    confidence=0.6, source=self.spec.key))]
        return []

    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        promoted = 0
        try:
            playbooks = _sys().procedural.playbooks(limit=100)
        except Exception:
            playbooks = []
        for pb in playbooks:
            att = int(pb.get("attempts") or 0)
            succ = int(pb.get("successes") or 0)
            rate = succ / att if att else 0
            if att >= 3 and rate >= 0.8:
                self._emit(Lesson(
                    LessonType.STRATEGY.value,
                    f"BEST PRACTICE: «{pb.get('intent')}» — {rate:.0%} success "
                    f"over {att}; prefer this proven procedure",
                    trigger=pb.get("intent", ""), recommendation="use the proven procedure",
                    scope=(pb.get("protocol") or "global"),
                    dimensions=["planning", "execution", "decision"],
                    confidence=round(rate, 3), validated=True, evidence_count=att,
                    source=self.spec.key))
                promoted += 1
        return {"strategies_promoted": promoted}


# ════════════════════════════════════════════════════════════════════════════
class KnowledgeLearner(Learner):
    """Knowledge — turns validated lessons into retrievable knowledge (no LLM
    retrain): writes them as semantic facts and exposes them as documents."""
    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        promoted = 0
        for lt in (LessonType.PATTERN, LessonType.STRATEGY, LessonType.MISTAKE):
            for l in self.store.of_type(lt.value, limit=100):
                if int(l.get("validated") or 0) != 1:
                    continue
                try:
                    _sys().semantic.assert_fact(
                        l.get("trigger") or l.get("scope") or "network",
                        "lesson_" + lt.value, l.get("summary", ""),
                        scope="domain", confidence=float(l.get("confidence") or 0.6),
                        source="learning")
                    promoted += 1
                except Exception:
                    pass
        return {"knowledge_promoted": promoted}

    def as_documents(self, limit: int = 200) -> List[Dict[str, str]]:
        docs = []
        for l in self.store.top(limit=limit, validated=1):
            docs.append({
                "title": f"[{l.get('lesson_type')}] {l.get('trigger','')[:60]}",
                "content": f"{l.get('summary','')}. Recommendation: "
                           f"{l.get('recommendation','')}",
                "source": "institutional-learning"})
        return docs


# ════════════════════════════════════════════════════════════════════════════
class ReasoningLearner(Learner):
    """Reasoning — synthesises if-then heuristics from validated patterns."""
    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        made = 0
        try:
            patterns = _sys().pattern.top(limit=100)
        except Exception:
            patterns = []
        for p in patterns:
            if p.get("kind") not in ("symptom_cause", "cause_fix"):
                continue
            if float(p.get("weight") or 0) < 0.3:
                continue
            ante = p.get("antecedent", "")
            cons = p.get("consequent", "")
            if ante and cons:
                self._emit(Lesson(
                    LessonType.HEURISTIC.value,
                    f"IF {ante} THEN suspect/apply {cons}",
                    trigger=ante, recommendation=cons, scope=(p.get("protocol") or "global"),
                    dimensions=["reasoning", "prediction"],
                    confidence=float(p.get("confidence") or 0.55),
                    evidence_count=int(p.get("observations") or 1),
                    validated=int(p.get("observations") or 1) >= 3,
                    source=self.spec.key))
                made += 1
        return {"heuristics_synthesised": made}


# ════════════════════════════════════════════════════════════════════════════
class RiskLearner(Learner):
    """Risk — learns which conditions precede harm."""
    def observe(self, ev: LearningEvent) -> List[str]:
        if ev.success is False:
            cond = ev.metadata.get("risk_condition") or \
                   f"{ev.protocol or 'change'} on {ev.device or 'device'}"
            return [self._emit(Lesson(
                LessonType.RISK_RULE.value,
                f"Harm followed: {cond}",
                trigger=cond, recommendation="raise risk weight; require extra checks",
                scope=ev.domain, dimensions=["risk", "prediction", "decision"],
                confidence=0.55, source=self.spec.key))]
        return []

    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        # which domains/contexts carry the most failures → durable risk rules.
        fails = corpus.by_outcome(False)
        by_proto = Counter(e.get("protocol") or "general" for e in fails)
        succ = corpus.by_outcome(True)
        succ_proto = Counter(e.get("protocol") or "general" for e in succ)
        rules = 0
        for proto, nf in by_proto.items():
            ns = succ_proto.get(proto, 0)
            tot = nf + ns
            if tot >= 4 and nf / tot >= 0.5:
                self._emit(Lesson(
                    LessonType.RISK_RULE.value,
                    f"{proto} changes are historically risky ({nf}/{tot} failed)",
                    trigger=proto, recommendation="treat as high-risk; mandatory rollback staging",
                    scope=proto, dimensions=["risk", "prediction"],
                    confidence=round(nf / tot, 3), validated=True, evidence_count=tot,
                    source=self.spec.key))
                rules += 1
        return {"risk_rules": rules}


# ════════════════════════════════════════════════════════════════════════════
class ConfidenceLearner(Learner):
    """Confidence / Trust — recalibrates from predicted-vs-actual."""
    def observe(self, ev: LearningEvent) -> List[str]:
        if ev.success is not None and ev.stated_confidence > 0:
            try:
                _sys().trust.record(ev.domain, ev.stated_confidence, ev.success)
            except Exception:
                pass
        return []

    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        made = 0
        try:
            rows = _sys().trust.top(limit=100)
        except Exception:
            rows = []
        for r in rows:
            n = int(r.get("n") or 0)
            if n < 6:
                continue
            mean_conf = float(r.get("conf_sum") or 0) / n
            actual = float(r.get("hit_sum") or 0) / n
            gap = actual - mean_conf
            if abs(gap) >= 0.2:
                direction = "over-confident" if gap < 0 else "under-confident"
                self._emit(Lesson(
                    LessonType.CALIBRATION.value,
                    f"{r.get('domain')}: platform is {direction} "
                    f"(says {mean_conf:.0%}, achieves {actual:.0%})",
                    trigger=r.get("domain", ""),
                    recommendation=f"shift confidence by {gap:+.0%} in this domain",
                    scope=r.get("domain", "global"),
                    dimensions=["confidence", "trust", "prediction"],
                    confidence=min(0.95, n / 50), validated=n >= 10,
                    evidence_count=n, source=self.spec.key))
                made += 1
        return {"calibration_lessons": made}


# ════════════════════════════════════════════════════════════════════════════
class PlanningLearner(Learner):
    """Planning — learns which step-orderings and checks actually succeed."""
    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        # compare verification checks present in successes vs failures per intent.
        good_checks = Counter()
        bad_checks = Counter()
        for e in corpus.events():
            checks = (e.get("metadata") or {}).get("checks") or []
            tgt = good_checks if e.get("outcome") == "success" else bad_checks
            for c in checks:
                tgt[c] += 1
        made = 0
        for chk, g in good_checks.items():
            b = bad_checks.get(chk, 0)
            if g >= 3 and g > 2 * (b + 1):
                self._emit(Lesson(
                    LessonType.PLANNING_RULE.value,
                    f"Include check «{chk}» in plans — strongly associated with success",
                    trigger=chk, recommendation=f"always verify: {chk}",
                    scope="global", dimensions=["planning", "execution"],
                    confidence=min(0.9, g / (g + b + 1)), validated=True,
                    evidence_count=g, source=self.spec.key))
                made += 1
        return {"planning_rules": made}


# ════════════════════════════════════════════════════════════════════════════
class OperatorLearner(Learner):
    """Decision / Trust — learns the operator's habits and preferences."""
    def observe(self, ev: LearningEvent) -> List[str]:
        if not ev.operator or not ev.operator_action:
            return []
        approved = ev.operator_action == "approved"
        from core.intelligence.memory.consolidation import _class_intent
        subject = f"{ev.protocol or 'generic'}:{_class_intent(ev.intent)}"
        try:
            _sys().operator.record_decision(ev.operator, "approval", subject,
                                            approved=approved)
        except Exception:
            pass
        if ev.operator_action in ("rejected", "edited"):
            return [self._emit(Lesson(
                LessonType.PREFERENCE.value,
                f"{ev.operator} {ev.operator_action} «{ev.intent}» "
                f"({ev.protocol or 'generic'})",
                trigger=subject,
                recommendation=("propose differently; this operator pushed back"),
                scope=ev.operator, dimensions=["decision", "trust"],
                confidence=0.6, source=self.spec.key))]
        return []

    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        made = 0
        try:
            for op_row in _sys().operator.top(limit=100):
                appr = int(op_row.get("approvals") or 0)
                rej = int(op_row.get("rejections") or 0)
                if appr + rej >= 4:
                    stance = op_row.get("stance", "review_first")
                    self._emit(Lesson(
                        LessonType.PREFERENCE.value,
                        f"Operator preference: {op_row.get('summary','')}",
                        trigger=op_row.get("subject", ""),
                        recommendation=f"default to: {stance}",
                        scope=op_row.get("operator", "default"),
                        dimensions=["decision", "trust"],
                        confidence=float(op_row.get("confidence") or 0.6),
                        validated=True, evidence_count=appr + rej, source=self.spec.key))
                    made += 1
        except Exception:
            pass
        return {"preference_lessons": made}


# ════════════════════════════════════════════════════════════════════════════
class DecisionLearner(Learner):
    """Decision — learns which act/wait/escalate choices led to good outcomes."""
    def observe(self, ev: LearningEvent) -> List[str]:
        choice = ev.metadata.get("decision")
        if not choice:
            return []
        outcome = "good" if ev.success else "bad" if ev.success is False else "unknown"
        situation = ev.metadata.get("situation") or f"{ev.protocol}:{ev.intent[:40]}"
        try:
            _sys().decision.record(situation, choice, rationale=ev.metadata.get("rationale", ""),
                                   outcome=outcome)
        except Exception:
            pass
        return []

    def retrospect(self, corpus: Corpus) -> Dict[str, Any]:
        made = 0
        try:
            for d in _sys().decision.top(limit=100):
                times = int(d.get("times") or 0)
                good = int(d.get("good") or 0)
                if times >= 3 and good / times >= 0.75:
                    self._emit(Lesson(
                        LessonType.HEURISTIC.value,
                        f"In «{d.get('situation')}», choosing {d.get('choice')} "
                        f"works ({good}/{times})",
                        trigger=d.get("situation", ""),
                        recommendation=f"prefer: {d.get('choice')}",
                        scope="global", dimensions=["decision", "planning"],
                        confidence=round(good / times, 3), validated=True,
                        evidence_count=times, source=self.spec.key))
                    made += 1
        except Exception:
            pass
        return {"decision_heuristics": made}


def build_learners(store: LessonStore) -> List[Learner]:
    specs = [
        (PatternLearner, "pattern_learner", "Pattern Learner", "knowledge",
         "Discovers symptom→cause→fix correlations."),
        (MistakeLearner, "mistake_learner", "Mistake Learner", "risk",
         "Identifies repeated mistakes and anti-patterns."),
        (StrategyLearner, "strategy_learner", "Strategy Learner", "planning",
         "Identifies and promotes successful strategies."),
        (KnowledgeLearner, "knowledge_learner", "Knowledge Learner", "knowledge",
         "Turns validated lessons into retrievable knowledge."),
        (ReasoningLearner, "reasoning_learner", "Reasoning Learner", "reasoning",
         "Synthesises if-then heuristics from patterns."),
        (RiskLearner, "risk_learner", "Risk Learner", "risk",
         "Learns conditions that precede harm."),
        (ConfidenceLearner, "confidence_learner", "Confidence Learner", "confidence",
         "Recalibrates confidence from predicted-vs-actual."),
        (PlanningLearner, "planning_learner", "Planning Learner", "planning",
         "Learns which steps/checks actually succeed."),
        (OperatorLearner, "operator_learner", "Operator Learner", "decision",
         "Learns operator habits and preferences."),
        (DecisionLearner, "decision_learner", "Decision Learner", "decision",
         "Learns which choices lead to good outcomes."),
    ]
    out = []
    for cls, key, name, dim, purpose in specs:
        out.append(cls(LearnerSpec(key, name, dim, purpose), store))
    return out
