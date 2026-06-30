"""
NetBrain · Command Resolver
===========================
THE single place any code asks "what command does X on a <vendor> device?".
No caller ever holds a command literal. The resolver follows a strict chain:

    cache  →  RAG (live OEM knowledge: Cisco/Juniper/Aruba/…)  →  MCP  →  grounded AI

The first three are exactly the order requested. The fourth (an LLM grounded by
the RAG context it just fetched) is a *generation* fallback, NOT a hardcoded
table — it exists so the tool never has to fall back to a stale literal when a
brand-new platform or a never-seen purpose shows up. Every resolved command is
written back to the cache, so the system gets faster and more consistent over
time instead of relying on hand-written command lists.

Callers pass an abstract PURPOSE ("ospf neighbor state", "interface status",
"verify bgp adjacency") plus vendor/os — never a command. That is what keeps the
codebase free of hardcoded commands: the *intent* is stable, the *command* is
resolved live and may differ per vendor, per OS, and over time.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("command_resolver")

_CACHE_PATH = os.environ.get(
    "NETBRAIN_CMD_CACHE", os.path.join(os.path.dirname(__file__), ".command_cache.json"))
_CACHE_TTL = int(os.environ.get("NETBRAIN_CMD_CACHE_TTL", str(30 * 24 * 3600)))  # 30d

# command-shaped line detector (vendor-neutral): starts with a verb-ish token and
# contains no prose punctuation. Used to extract commands from RAG/MCP/AI text.
_CMD_LINE = re.compile(r"^[a-z][a-z0-9\-]+(\s+[\S]+)*\s*$", re.IGNORECASE)
_PROSE = re.compile(r"[.!?:]|\b(the|this|will|should|because|note|example)\b", re.IGNORECASE)


@dataclass
class ResolvedCommands:
    purpose: str
    vendor: str
    os: str
    phase: str
    commands: List[str] = field(default_factory=list)
    source: str = "none"          # cache | rag | mcp | ai | none

    def __bool__(self) -> bool:
        return bool(self.commands)


class CommandResolver:
    def __init__(self, ai_call: Optional[Callable[[str], str]] = None):
        self._ai = ai_call or self._default_ai
        self._cache = self._load_cache()

    # ── public API ────────────────────────────────────────────────────────────
    def resolve(self, purpose: str, *, vendor: str = "cisco", os_: str = "ios",
                phase: str = "diagnostic", context: str = "", n: int = 4) -> ResolvedCommands:
        """Resolve an abstract PURPOSE to concrete commands via cache→RAG→MCP→AI."""
        key = self._key(purpose, vendor, os_, phase)

        cached = self._from_cache(key)
        if cached:
            return ResolvedCommands(purpose, vendor, os_, phase, cached[:n], "cache")

        for source, fn in (("rag", self._from_rag), ("mcp", self._from_mcp),
                           ("ai", self._from_ai)):
            try:
                cmds = fn(purpose, vendor, os_, phase, context)
            except Exception as exc:
                logger.debug("resolver %s failed: %s", source, exc)
                cmds = []
            cmds = self._clean(cmds)[:n]
            if cmds:
                self._to_cache(key, cmds)
                return ResolvedCommands(purpose, vendor, os_, phase, cmds, source)

        return ResolvedCommands(purpose, vendor, os_, phase, [], "none")

    def resolve_set(self, anomaly_type: str, *, vendor: str = "cisco", os_: str = "ios",
                    context: str = "") -> Dict[str, List[str]]:
        """Resolve the diagnostic / fix / verify command sets for an anomaly.
        Replaces any static per-anomaly command table."""
        human = anomaly_type.replace("_", " ")
        out: Dict[str, List[str]] = {}
        for phase, intent in (("diagnostic", f"diagnose {human}"),
                              ("fix", f"remediate {human}"),
                              ("verify", f"verify {human} is resolved")):
            out[phase] = self.resolve(intent, vendor=vendor, os_=os_, phase=phase,
                                      context=context).commands
        return out

    # ── chain links ───────────────────────────────────────────────────────────
    def _from_rag(self, purpose, vendor, os_, phase, context) -> List[str]:
        try:
            from core.orchestration_engine import get_orchestrator
            hits = get_orchestrator().rag_query(
                f"{vendor} {os_} CLI command to {purpose}", top_k=3) or []
        except Exception:
            return []
        text = "\n".join(getattr(h, "text", "") or "" for h in hits)
        return self._extract(text)

    def _from_mcp(self, purpose, vendor, os_, phase, context) -> List[str]:
        # MCP is the LAST documentation source (after RAG). Best-effort: use the
        # orchestrator's fetcher if present; never block if MCP is unavailable.
        try:
            from core.orchestration_engine import get_orchestrator
            orch = get_orchestrator()
            fetch = getattr(orch, "fetch_commands", None) or getattr(orch, "mcp_query", None)
            if not fetch:
                return []
            res = fetch(f"{vendor} {os_} {purpose}")  # type: ignore
            if isinstance(res, str):
                return self._extract(res)
            if isinstance(res, (list, tuple)):
                return [str(x) for x in res]
        except Exception:
            return []
        return []

    def _from_ai(self, purpose, vendor, os_, phase, context) -> List[str]:
        # GROUNDED generation — not a hardcoded table. We feed the model the live
        # RAG context first so the command reflects current OEM knowledge.
        grounding = ""
        try:
            from core.orchestration_engine import get_orchestrator
            hits = get_orchestrator().rag_query(f"{vendor} {os_} {purpose}", top_k=2) or []
            grounding = "\n".join(getattr(h, "text", "")[:300] for h in hits)
        except Exception:
            pass
        prompt = (
            f"You are a {vendor} {os_} CLI expert. Give ONLY the exact command(s) to "
            f"{purpose} on a {vendor} {os_} device"
            + (f" (context: {context})" if context else "") + ".\n"
            + (f"\nRelevant vendor knowledge:\n{grounding}\n" if grounding else "")
            + "\nReturn ONLY commands, one per line, no prose, no numbering, no markdown.")
        out = self._ai(prompt) or ""
        return self._extract(out)

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _default_ai(prompt: str) -> str:
        try:
            from core.ai_engine import ask_ai
            txt = ask_ai(prompt)
            return txt if isinstance(txt, str) and "unavailable" not in txt.lower() else ""
        except Exception:
            return ""

    @staticmethod
    def _extract(text: str) -> List[str]:
        cmds: List[str] = []
        for raw in (text or "").splitlines():
            line = raw.strip().strip("`").lstrip("-*0123456789. ").strip()
            if not line or _PROSE.search(line):
                continue
            if _CMD_LINE.match(line) and 1 < len(line) <= 80:
                cmds.append(line)
        # de-dupe, preserve order
        seen, out = set(), []
        for c in cmds:
            if c.lower() not in seen:
                seen.add(c.lower())
                out.append(c)
        return out

    @staticmethod
    def _clean(cmds: List[str]) -> List[str]:
        return [c for c in (cmds or []) if c and isinstance(c, str)]

    @staticmethod
    def _key(purpose, vendor, os_, phase) -> str:
        return f"{vendor.lower()}|{os_.lower()}|{phase.lower()}|{purpose.lower().strip()}"

    def _from_cache(self, key: str) -> List[str]:
        rec = self._cache.get(key)
        if not rec:
            return []
        if time.time() - rec.get("ts", 0) > _CACHE_TTL:
            return []
        return list(rec.get("commands", []))

    def _to_cache(self, key: str, cmds: List[str]) -> None:
        self._cache[key] = {"commands": cmds, "ts": time.time()}
        try:
            with open(_CACHE_PATH, "w") as fh:
                json.dump(self._cache, fh)
        except Exception as exc:
            logger.debug("cache write failed: %s", exc)

    @staticmethod
    def _load_cache() -> Dict[str, dict]:
        try:
            with open(_CACHE_PATH) as fh:
                return json.load(fh)
        except Exception:
            return {}


_RESOLVER: Optional[CommandResolver] = None


def get_command_resolver(ai_call: Optional[Callable[[str], str]] = None) -> CommandResolver:
    global _RESOLVER
    if _RESOLVER is None or ai_call is not None:
        _RESOLVER = CommandResolver(ai_call=ai_call)
    return _RESOLVER
