"""
core/intelligence/memory/feedback.py
=====================================
The four feedback-scored memories — the loops that make the platform *learn from
being right and wrong*, not merely accumulate.

  • TrustMemory       — empirical self-calibration. For each domain it records
    how its stated confidence compared to what actually happened (a running
    Brier-style score), so confidence can be corrected by evidence instead of
    asserted. This is the difference between "I'm 90% sure" and "I'm 90% sure,
    and history says when I say that I'm right 88% of the time."

  • PredictionMemory  — records predictions WHEN MADE, then scores them when the
    outcome arrives. A prediction faculty that never checks whether it was right
    cannot improve; this closes that loop and exposes its hit-rate.

  • DecisionMemory    — records each act/wait/escalate decision with its context
    and later its outcome, so the decision policy can prefer choices that have
    worked in similar situations (case-based decisioning).

  • VerificationMemory— records which post-conditions actually discriminated
    success from failure (and which were flaky/uninformative), so the outcome
    contract gets sharper about what's worth checking.

All four share the reinforce/decay substrate; each adds its own scoring.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

from core.intelligence.memory.store import MemoryStore


# ── Trust: empirical confidence calibration per domain ───────────────────────
class TrustMemory(MemoryStore):
    table = "mem_trust"
    semantic = False
    columns = (
        ("domain", "TEXT"),
        ("n", "INTEGER"),
        ("brier_sum", "REAL"),    # sum of (confidence - outcome)^2
        ("conf_sum", "REAL"),
        ("hit_sum", "REAL"),
    )

    def record(self, domain: str, stated_confidence: float, was_correct: bool) -> str:
        domain = (domain or "general").lower()
        o = 1.0 if was_correct else 0.0
        c = max(0.0, min(1.0, float(stated_confidence)))
        ex = self._by_key(domain)
        n = int((ex or {}).get("n") or 0) + 1
        brier = float((ex or {}).get("brier_sum") or 0) + (c - o) ** 2
        cs = float((ex or {}).get("conf_sum") or 0) + c
        hs = float((ex or {}).get("hit_sum") or 0) + o
        avg_brier = brier / n
        summary = (f"{domain}: calibration {1 - avg_brier:.2f} over {n} "
                   f"(mean conf {cs/n:.2f}, actual {hs/n:.2f})")
        return self.learn(domain, summary, confidence=round(1 - avg_brier, 4),
                          domain=domain, n=n, brier_sum=brier, conf_sum=cs, hit_sum=hs)

    def calibrate(self, domain: str, raw_confidence: float) -> Dict[str, Any]:
        """Pull a raw confidence toward the platform's demonstrated accuracy."""
        ex = self._by_key((domain or "general").lower())
        if not ex or int(ex.get("n") or 0) < 4:
            return {"calibrated": round(float(raw_confidence), 4),
                    "adjustment": 0.0, "basis": "insufficient history"}
        n = int(ex["n"])
        mean_conf = float(ex["conf_sum"]) / n
        actual = float(ex["hit_sum"]) / n
        # if the platform is habitually over/under-confident in this domain,
        # shift the raw value by the historical gap (damped).
        gap = actual - mean_conf
        cal = max(0.0, min(1.0, float(raw_confidence) + 0.5 * gap))
        return {"calibrated": round(cal, 4), "adjustment": round(0.5 * gap, 4),
                "basis": f"n={n}, hist conf {mean_conf:.2f} vs actual {actual:.2f}"}


# ── Prediction: forecasts scored against reality ─────────────────────────────
class PredictionMemory(MemoryStore):
    table = "mem_prediction"
    semantic = True
    columns = (
        ("subject", "TEXT"),       # what was predicted about (device/protocol/intent)
        ("predicted", "TEXT"),     # the claim
        ("confidence0", "REAL"),   # confidence at prediction time
        ("resolved", "INTEGER"),   # 0 open / 1 resolved
        ("correct", "INTEGER"),    # 1/0 once resolved
        ("made_ts", "REAL"),
    )

    def predict(self, subject: str, predicted: str, confidence: float) -> str:
        key = hashlib.sha1(f"{subject}|{predicted}|{time.time()}".encode()).hexdigest()[:16]
        return self.learn(key, f"PREDICT {subject}: {predicted}",
                          confidence=float(confidence), subject=(subject or "").lower(),
                          predicted=predicted, confidence0=float(confidence),
                          resolved=0, correct=0, made_ts=time.time())

    def resolve(self, key: str, correct: bool) -> None:
        ex = self._by_key(key)
        if not ex:
            return
        self._be.execute(
            f"UPDATE {self.table} SET resolved=1, correct=? WHERE id=?",
            (1 if correct else 0, ex["id"]))
        self._be.commit()

    def open_predictions(self, subject: str = "") -> List[Dict[str, Any]]:
        return self.recent(limit=50, resolved=0,
                           subject=(subject or None) and subject.lower())

    def hit_rate(self) -> Dict[str, Any]:
        rows = self._be.query(
            f"SELECT COUNT(*) n, SUM(correct) c FROM {self.table} WHERE resolved=1")
        r = rows[0] if rows else {}
        n = int(r.get("n") or 0)
        c = int(r.get("c") or 0)
        return {"resolved": n, "correct": c,
                "hit_rate": round(c / n, 3) if n else 0.0}


# ── Decision: choices scored by what followed them ───────────────────────────
class DecisionMemory(MemoryStore):
    table = "mem_decision"
    semantic = True
    columns = (
        ("situation", "TEXT"),     # context signature (symptom/risk/domain)
        ("choice", "TEXT"),        # act | wait | escalate | rollback
        ("rationale", "TEXT"),
        ("outcome", "TEXT"),       # good | bad | unknown
        ("times", "INTEGER"),
        ("good", "INTEGER"),
    )

    def record(self, situation: str, choice: str, *, rationale: str = "",
               outcome: str = "unknown") -> str:
        key = hashlib.sha1(f"{situation.lower()}|{choice.lower()}".encode()).hexdigest()[:16]
        ex = self._by_key(key)
        times = int((ex or {}).get("times") or 0) + 1
        good = int((ex or {}).get("good") or 0) + (1 if outcome == "good" else 0)
        rate = good / times if times else 0.0
        summary = f"In «{situation}» chose {choice}: {rate:.0%} good over {times}"
        return self.learn(key, summary, confidence=round(rate, 4),
                          situation=situation, choice=choice, rationale=rationale,
                          outcome=outcome, times=times, good=good)

    def best_choice(self, situation: str, top_k: int = 3) -> List[Dict[str, Any]]:
        return self.recall_similar(situation, top_k=top_k)


# ── Verification: which checks actually told us the truth ────────────────────
class VerificationMemory(MemoryStore):
    table = "mem_verification"
    semantic = True
    columns = (
        ("check_command", "TEXT"),
        ("protocol", "TEXT"),
        ("informative", "INTEGER"),   # times it discriminated pass/fail meaningfully
        ("flaky", "INTEGER"),         # times it was pending/unknown/contradictory
    )

    def record_check(self, check_command: str, protocol: str, *,
                     informative: bool) -> str:
        key = hashlib.sha1(f"{check_command.lower()}|{protocol.lower()}".encode()).hexdigest()[:16]
        ex = self._by_key(key)
        inf = int((ex or {}).get("informative") or 0) + (1 if informative else 0)
        fl = int((ex or {}).get("flaky") or 0) + (0 if informative else 1)
        tot = inf + fl
        quality = inf / tot if tot else 0.5
        summary = f"check «{check_command}» ({protocol or 'generic'}): {quality:.0%} informative"
        return self.learn(key, summary, confidence=round(quality, 4),
                          check_command=check_command, protocol=(protocol or "").lower(),
                          informative=inf, flaky=fl)

    def best_checks(self, intent: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return self.recall_similar(intent, top_k=top_k)
