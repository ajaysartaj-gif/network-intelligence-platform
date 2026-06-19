"""
core/knowledge/citation_tracker.py
==================================
Tracks citations as commands flow through plan generation, execution,
and analysis.

Used by IntentEngine to show the operator EXACTLY where each piece of
knowledge came from — cache, vendor docs, or AI guess.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from core.knowledge.base import Citation, ConfidenceLevel, KnowledgeEntry

logger = logging.getLogger("NetBrain.Knowledge.CitationTracker")


@dataclass
class CitationTracker:
    """Tracks citations for an entire intent cycle (one operator question)."""

    # command → KnowledgeEntry that backs it
    entries: Dict[str, KnowledgeEntry] = field(default_factory=dict)

    def add(self, command: str, entry: KnowledgeEntry) -> None:
        """Register a knowledge entry for a command."""
        self.entries[command.strip()] = entry

    def get(self, command: str) -> KnowledgeEntry:
        """Get the entry for a command, or return UNVERIFIED if absent."""
        cmd = command.strip()
        return self.entries.get(cmd, KnowledgeEntry.unverified("", cmd))

    def has(self, command: str) -> bool:
        return command.strip() in self.entries

    def all_citations(self) -> List[Citation]:
        return [e.citation for e in self.entries.values()]

    def summary(self) -> Dict[str, int]:
        """Count commands by confidence level."""
        counts = {level.value: 0 for level in ConfidenceLevel}
        for e in self.entries.values():
            counts[e.citation.confidence.value] += 1
        return counts

    def format_command_badges(self) -> str:
        """
        Render all citations as a compact markdown block for display.
        """
        if not self.entries:
            return ""

        lines: List[str] = []
        for cmd, entry in self.entries.items():
            badge = entry.citation.to_markdown_badge()
            lines.append(f"  - `{cmd}` &nbsp; {badge}")

        summary = self.summary()
        summary_line = (
            f"**Confidence summary:** "
            f"🟢 {summary['high']} verified · "
            f"🔵 {summary['medium']} cached · "
            f"🟡 {summary['low']} partial · "
            f"⚠️ {summary['unverified']} unverified"
        )

        return summary_line + "\n\n" + "\n".join(lines)
