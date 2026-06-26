"""
core/intelligence/memory/pattern.py
====================================
Pattern Memory — learned CORRELATIONS, the engineer's intuition.

The thing a senior engineer has that a junior doesn't is compressed pattern:
"EXSTART that never reaches FULL → almost always an MTU mismatch", "flapping
right after a deploy → you touched something you didn't mean to". These aren't
facts about the network and they aren't procedures; they are conditional
expectations — antecedent → consequent with an observed strength — distilled
from many episodes.

Patterns are reinforced when the same antecedent→consequent pairing recurs, and
they directly sharpen Prediction (what tends to follow X) and Diagnosis (what
tends to cause Y). A pattern that stops recurring quietly decays.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List

from core.intelligence.memory.store import MemoryStore


def _ckey(kind: str, antecedent: str, consequent: str) -> str:
    raw = f"{kind}|{antecedent.strip().lower()}|{consequent.strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


class PatternMemory(MemoryStore):
    table = "mem_pattern"
    semantic = True
    columns = (
        ("kind", "TEXT"),         # symptom_cause | cause_fix | change_effect | precursor
        ("antecedent", "TEXT"),
        ("consequent", "TEXT"),
        ("protocol", "TEXT"),
        ("observations", "INTEGER"),
    )

    def observe(self, kind: str, antecedent: str, consequent: str, *,
                protocol: str = "", confidence: float = 0.55) -> str:
        key = _ckey(kind, antecedent, consequent)
        ex = self._by_key(key)
        obs = int((ex or {}).get("observations") or 0) + 1
        summary = f"[{kind}] when «{antecedent}» → «{consequent}»"
        return self.learn(
            key, summary, confidence=confidence,
            kind=kind, antecedent=antecedent, consequent=consequent,
            protocol=(protocol or "").lower(), observations=obs)

    def predict_consequents(self, antecedent: str, kind: str = "",
                            top_k: int = 5) -> List[Dict[str, Any]]:
        hits = self.recall_similar(antecedent, top_k=top_k * 2,
                                   kind=kind or None)
        return hits[:top_k]

    def likely_causes(self, symptom: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return self.predict_consequents(symptom, kind="symptom_cause", top_k=top_k)

    def likely_fixes(self, cause: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return self.predict_consequents(cause, kind="cause_fix", top_k=top_k)
