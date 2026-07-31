"""
mismatch_bridge.py — the one new call site the Troubleshooting Engine gains.

run_mismatch_investigation() is the single entry point core/troubleshooting/
engine.py calls. It:

  1. builds a KnowledgeEngine (live RAG retriever, offline lexical fallback,
     LLM extractor via the engine's own ai_call, offline stub fallback)
  2. builds a GatewayDeviceAdapter bound to the engine's real VendorGateway
  3. runs strategies.mismatch.MismatchStrategy.investigate() — UNCHANGED,
     deterministic, no LLM in the compare hot-loop
  4. converts each Finding into exactly the Hypothesis / Observation / Evidence
     objects the rest of the engine already understands, so convergence,
     fix generation, verification planning and report.to_markdown() all run
     through the SAME code path as an LLM-seeded investigation.

Nothing here duplicates the confidence math in hypotheses.py: a Finding's own
deterministic confidence becomes the Hypothesis's prior directly.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_CORPUS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "corpus")

# query keyword -> relationship_type this platform's corpus documents. Extending
# this to a new relationship = one more entry here + one more corpus/*.txt file;
# no engine or strategy code changes.
_RELATIONSHIP_KEYWORDS = {
    "mpls_l3vpn_peering": ("mpls_l3vpn",),
    "vxlan_evpn_peering": ("vxlan_evpn",),
    "pim_neighbor": ("multicast_pim",),
    "eigrp_adjacency": ("eigrp",),
    "vrrp_pairing": ("vrrp",),
    "ospf_adjacency": ("ospf",),
    "hsrp_pairing": ("hsrp",),
}


def detect_relationship_type(query: str) -> Optional[str]:
    q = (query or "").lower()
    for rel, keywords in _RELATIONSHIP_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return rel
    return None


def _build_knowledge_engine(ai_call: Optional[Callable[[str], str]]):
    from knowledge.rag_engine import KnowledgeEngine, LexicalRetriever, StubExtractor
    from knowledge.corpus_loader import load_corpus
    from .live_retriever import LiveRAGRetriever, FallbackRetriever, ensure_corpus_ingested

    # Best-effort: make the curated corpus available in the live index. Cheap
    # no-op if already ingested; silently skipped if live RAG deps aren't
    # installed in this environment (FallbackRetriever handles that case too).
    try:
        ensure_corpus_ingested(_CORPUS_DIR)
    except Exception as exc:
        logger.info("Corpus ingestion skipped: %s", exc)

    try:
        offline_chunks = load_corpus(_CORPUS_DIR)
    except Exception:
        offline_chunks = []
    retriever = FallbackRetriever(LiveRAGRetriever(), LexicalRetriever(offline_chunks))

    extractor = StubExtractor()
    if ai_call is not None:
        try:
            from ._ai_extractor import AiCallExtractor
            extractor = _FallbackExtractor(AiCallExtractor(ai_call), StubExtractor())
        except Exception as exc:
            logger.info("LLM-backed KP extraction unavailable (%s); using offline extractor.", exc)

    return KnowledgeEngine(retriever=retriever, extractor=extractor)


class _FallbackExtractor:
    """Try the LLM-grounded extractor; fall back to the deterministic offline
    one (which parses the corpus's own PARAM:/ENUMERATE:/HEALTHY: tags) if the
    LLM call or its JSON parsing fails for any reason. A KP is only ever used
    if it passes KnowledgePackage.validate() either way."""

    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback

    def extract(self, relationship_type, chunks):
        try:
            return self.primary.extract(relationship_type, chunks)
        except Exception as exc:
            logger.info("Primary KP extractor failed (%s); falling back to offline extractor.", exc)
            return self.fallback.extract(relationship_type, chunks)


def run_mismatch_investigation(
    *,
    relationship_type: str,
    devices: List[Any],
    ip_to_device: Dict[str, Any],
    gateway: Any,
    ai_call: Optional[Callable[[str], str]],
    session: Any,
    hmgr: Any,
    graph: Any,
) -> bool:
    """Runs the Mismatch Investigation and seeds `session`/`hmgr`/`graph` from
    its Findings. Returns True if at least one hypothesis was seeded.

    Safe to call speculatively: any failure (no gateway, no corpus, KP
    extraction failure, zero relationship instances found) is caught and
    logged, returning False so the caller falls through to the normal
    LLM-driven investigation loop unaffected.
    """
    if gateway is None or not ip_to_device:
        return False

    from .gateway_adapter import GatewayDeviceAdapter
    from strategies.mismatch import MismatchStrategy
    from core.troubleshooting.models import ConfidenceDelta, Effect, Evidence, Observation

    topology_graph = None
    try:
        from core.topology.knowledge_graph_bridge import build_knowledge_graph
        topology_graph = build_knowledge_graph(devices)
    except Exception as exc:
        logger.info("Real topology graph unavailable (%s); adapter will use its "
                    "single-interface fallback heuristic instead.", exc)

    try:
        ke = _build_knowledge_engine(ai_call)
        adapter = GatewayDeviceAdapter(gateway, ip_to_device, relationship_type,
                                       topology_graph=topology_graph)
        seed_device = next(iter(ip_to_device.keys()))
        findings = MismatchStrategy(lambda _dev: adapter, ke).investigate(
            relationship_type, seed_device)
    except Exception as exc:
        logger.info("Mismatch investigation did not run (%s); falling back to LLM path.", exc)
        return False

    if not findings:
        return False

    seeded = False
    for f in findings:
        statement = (f"{f.parameter} {f.relation.replace('_', ' ')} violated on "
                     f"{relationship_type} between {f.local_device or '?'} and "
                     f"{f.remote_device or '?'} (local={f.local}, remote={f.remote})")
        rationale = (f.symptom_expected or "Deterministic parameter comparison "
                     "from the Knowledge Package.") + f" [source: {f.provenance}]"
        h = hmgr.add(statement, rationale=rationale,
                     discriminating_signals=[f.parameter], prior=max(0.01, min(0.99, f.confidence)))
        if h is None:
            continue
        seeded = True

        obs_local = Observation(
            device=f.local_device, subject=relationship_type, attribute=f.parameter,
            value=f.local, source_command="mismatch_investigation",
            raw_snippet=f"local={f.local} remote={f.remote} state={f.observed_state}"[:200],
        )
        obs_remote = Observation(
            device=f.remote_device, subject=relationship_type, attribute=f.parameter,
            value=f.remote, source_command="mismatch_investigation",
            raw_snippet=f"local={f.local} remote={f.remote} state={f.observed_state}"[:200],
        )
        for obs in (obs_local, obs_remote):
            session.observations.append(obs)
            try:
                graph.add_observation(obs)
            except Exception:
                pass
            ev = Evidence(
                observation_id=obs.id, hypothesis_id=h.id, effect=Effect.SUPPORT,
                weight=round(max(0.0, min(1.0, f.confidence)), 3),
                reason=f"{f.parameter}: local={f.local} vs remote={f.remote}; "
                       f"corroborated={f.corroborated}",
            )
            session.evidence.append(ev)
            # A zero-log-odds delta: the prior above already encodes this
            # evidence's deterministic confidence, so applying it must NOT
            # shift confidence a second time (that would double-count the
            # same finding) — but it MUST still land in h.deltas via
            # h.apply(), not just h.evidence_ids. This is a real,
            # non-tautological cross-device parameter comparison (actual
            # local vs remote values, corroborated against the observed
            # state) — exactly what Hypothesis.has_grounded_evidence exists
            # to recognize. Recording it as a bare evidence_id link (the
            # previous behavior) left h.deltas completely empty until this
            # hypothesis merged with its compiled-signature counterpart
            # (see HypothesisManager.add()'s discriminating-signal merge)
            # and received THAT signature's own deterministic-state-match
            # tautology delta — at which point has_grounded_evidence's scan
            # over deltas found only the tautological one and (wrongly)
            # judged a genuinely evidence-backed hypothesis ungrounded,
            # permanently blocking RootCauseRanker.converged() and any fix
            # from ever being proposed despite a clear, real diagnosis.
            delta = ConfidenceDelta(
                evidence_id=ev.id, effect=Effect.SUPPORT, weight=ev.weight,
                log_odds_change=0.0, reason=ev.reason,
            )
            h.apply(delta, ev.id)

        # Stash the strategy's own dual-ended remediation candidates so a later
        # fix step can offer them without recomputing anything.
        if f.remediations:
            session.__dict__.setdefault("mismatch_remediation_candidates", []).append({
                "hypothesis_id": h.id, "parameter": f.parameter,
                "candidates": [
                    {"endpoint": r.endpoint, "config": r.config,
                     "aligns_to": r.aligns_to, "requires_approval": r.requires_approval}
                    for r in f.remediations
                ],
            })

    hmgr.reap()
    return seeded
