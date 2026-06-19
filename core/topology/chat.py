"""
core/topology/chat.py
======================
AI-driven Q&A over a built TopologyGraph.

Follows the same principle as core/intent_engine.py: AI decides the
answer from the real graph data fed to it — no hardcoded question
patterns, no static answer templates. The graph (nodes, links, ports,
roles) is serialized as plain text context and handed to the AI model,
which reasons about it directly.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from core.topology.topology_models import TopologyGraph

logger = logging.getLogger("NetBrain.Topology.Chat")


class TopologyChatEngine:
    """
    Scoped AI chat for one site's topology.
    Usage:
        engine = TopologyChatEngine(ai_call=call_ai)
        answer = engine.ask("what connects to R1?", graph)
    """

    def __init__(self, ai_call: Callable[[str], str]):
        self.ai_call = ai_call

    def ask(self, query: str, graph: TopologyGraph) -> str:
        query = (query or "").strip()
        if not query:
            return "Please ask a question about this site's topology."

        if graph.node_count() == 0:
            return (
                "This site's topology hasn't been built yet, or no devices "
                "were discovered. Click **Build Topology** first."
            )

        context = graph.to_ai_context()

        prompt = (
            "You are NetBrain AI — a network engineer analyzing a site's "
            "physical topology, discovered via real CDP/LLDP data from the "
            "devices below.\n\n"
            f"{context}\n\n"
            f"OPERATOR QUESTION: {query}\n\n"
            "Answer using ONLY the topology data above. Reference exact "
            "hostnames, IPs, and port names from the data. If the question "
            "asks about something not present in this topology (e.g. a "
            "device that isn't listed), say so clearly rather than guessing. "
            "Be concise and technical."
        )

        try:
            return self.ai_call(prompt) or "AI unavailable."
        except Exception as exc:
            logger.error(f"Topology chat AI call failed: {exc}")
            return f"AI error: {exc}"
