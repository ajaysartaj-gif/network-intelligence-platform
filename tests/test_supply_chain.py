"""
Tests for NKC Phase 5 — the Network Intelligence Supply Chain facade
(core/knowledge/compiler/supply_chain.py).

Isolation notes:
  - EnterpriseKnowledgeLayer: real instance, FakeEmbedder + temp ChromaDB
    dir (the established pattern from tests/test_knowledge_parsers.py).
  - KnowledgeGraph: fresh instance per test.
  - OperationalMemory: real instance, but pointed at a temp sqlite file
    via its own db_path constructor param (clean dependency injection
    that already existed pre-NKC) — so record_incident/record_resolution/
    record_failed_resolution/build_failure_signatures are tested against
    real behavior, fully isolated from the platform's real memory file.
  - LearningEngine: core.intelligence.learning.engine.LearningEngine's
    retrospect()/learn_from() reach through Corpus/learners to GLOBAL
    module-level singletons (core.intelligence.operational_memory.
    get_operational_memory(), core.intelligence.memory.get_memory_system())
    that hardcode ".ai_net_studio_memory.sqlite" with no dependency injection
    — a pre-existing constraint, not introduced by this phase (see
    docs/nkc_supply_chain.md's gap report). Rather than touch the real
    platform memory file from a test run, those facade methods are tested
    with a lightweight STUB learning engine (a plain object exposing just
    learn_from/retrospect/digest) — this verifies the FACADE's delegation
    logic in isolation, which is this phase's actual deliverable; it does
    not re-test LearningEngine's own internals (already a separate,
    pre-existing, trusted subsystem).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.compiler import failure_signatures as failure_signatures_module
from core.knowledge.compiler.artifacts import FailureSignature
from core.knowledge.compiler.supply_chain import NetworkIntelligenceSupplyChain
from core.knowledge.enterprise.knowledge_layer import (
    EnterpriseKnowledgeLayer, SourceType,
)
from core.knowledge.rag.embedder import FakeEmbedder
from core.knowledge.rag.rag_engine import RAGEngine
from core.knowledge_graph import KnowledgeGraph
from core.intelligence.operational_memory import OperationalMemory


def _layer(tmp_path, name="supply-chain-test"):
    rag = RAGEngine(embedder=FakeEmbedder(), persist_dir=str(tmp_path / "chroma"), collection_name=name)
    return EnterpriseKnowledgeLayer(rag=rag)


class _StubLearningEngine:
    """Records calls and returns canned data — isolates supply_chain.py's
    delegation logic from the real, globally-wired LearningEngine."""
    def __init__(self):
        self.learn_from_calls = []
        self.retrospect_calls = []

    def learn_from(self, event):
        self.learn_from_calls.append(event)
        return {"event": event.kind, "lessons_emitted": 1}

    def retrospect(self, **kwargs):
        self.retrospect_calls.append(kwargs)
        return {"pattern_learner": {"patterns_found": 2},
               "confidence_learner": {"calibration_lessons": 1},
               "corpus_events": 5, "lessons_after": 3}

    def digest(self):
        return {"events_seen": 5, "lessons": {"total": 3, "validated": 1}}


def _supply_chain(tmp_path, name="supply-chain-test"):
    return NetworkIntelligenceSupplyChain(
        layer=_layer(tmp_path, name=name),
        graph=KnowledgeGraph(),
        # dsn="" (not the default None/"auto") forces local SQLite regardless
        # of AI_NET_STUDIO_MEMORY_DSN in os.environ — these tests must never reach
        # the real shared Postgres backend, even if something else in this
        # pytest process (e.g. importing app.py) has bridged that env var in.
        memory=OperationalMemory(db_path=str(tmp_path / "memory.sqlite"), dsn=""),
        learning_engine=_StubLearningEngine(),
    )


# ── Level 1 — Raw Knowledge ─────────────────────────────────────────────────

def test_ingest_document_and_search_raw_sources_round_trip(tmp_path):
    sc = _supply_chain(tmp_path)
    doc = tmp_path / "cisco_ospf.md"
    doc.write_text("OSPF neighbors stuck in EXSTART usually indicate an MTU mismatch.")

    result = sc.ingest_document(str(doc), SourceType.VENDOR_DOCS, vendor="cisco")
    assert not result.get("skipped")

    hits = sc.search_raw_sources("OSPF EXSTART MTU mismatch")
    assert hits and "MTU mismatch" in hits[0].text


def test_detect_changes_true_on_new_then_false_on_unchanged(tmp_path):
    sc = _supply_chain(tmp_path)
    doc = tmp_path / "r1.cfg"
    doc.write_text("interface GigabitEthernet0/1\n mtu 1500\n!\n")

    assert sc.detect_changes(str(doc), SourceType.GOLDEN_CONFIG) is True
    assert sc.detect_changes(str(doc), SourceType.GOLDEN_CONFIG) is False   # unchanged -> dedup skip


def test_version_source_tracks_version_bumps(tmp_path):
    sc = _supply_chain(tmp_path)
    doc = tmp_path / "r1.cfg"
    doc.write_text("v1 content")
    sc.ingest_document(str(doc), SourceType.GOLDEN_CONFIG, doc_id="r1-golden")
    assert sc.version_source("r1-golden") == 1

    doc.write_text("v2 content, changed")
    sc.ingest_document(str(doc), SourceType.GOLDEN_CONFIG, doc_id="r1-golden")
    assert sc.version_source("r1-golden") == 2


def test_archive_source_marks_metadata(tmp_path):
    sc = _supply_chain(tmp_path)
    doc = tmp_path / "old_guide.md"
    doc.write_text("A design guide that is now retired but kept as evidence.")
    sc.ingest_document(str(doc), SourceType.DESIGN_GUIDE, doc_id="old-guide")

    assert sc.archive_source("old-guide") is True
    assert sc.archive_source("does-not-exist") is False


# ── Level 2 — Compiled Knowledge ────────────────────────────────────────────

SAMPLE_CONFIG = "interface Gi0/1\n ip address 10.0.0.1 255.255.255.0\n mtu 1500\n!\n"


def test_compile_document_delegates_to_semantic_compiler(tmp_path):
    sc = _supply_chain(tmp_path)
    doc = tmp_path / "r1.cfg"
    doc.write_text(SAMPLE_CONFIG)
    report = sc.compile_document(str(doc), device="R1", vendor="cisco")
    assert report.objects
    assert any(o.type == "interface" for o in report.objects)


def test_compile_reasoning_delegates_to_reasoning_compiler(tmp_path):
    sc = _supply_chain(tmp_path)
    artifact = sc.compile_reasoning("ospf")
    assert artifact.protocol == "ospf"
    assert artifact.risk is not None


def test_validate_optimize_export_knowledge_compose_correctly(tmp_path):
    sc = _supply_chain(tmp_path)
    doc = tmp_path / "r1.cfg"
    doc.write_text(SAMPLE_CONFIG)
    sc.compile_document(str(doc), device="R1", vendor="cisco")

    validation = sc.validate_knowledge()
    assert "graph_issues" in validation

    optimization = sc.optimize_knowledge()
    assert "graph" in optimization

    export = sc.export_compiled_knowledge()
    assert export["nodes"]


# ── Level 3 — Operational Intelligence ──────────────────────────────────────

def test_record_incident_and_resolution_write_real_memory_events(tmp_path):
    sc = _supply_chain(tmp_path)
    incident_id = sc.record_incident("OSPF adjacency down", device="R1", protocol="ospf")
    assert incident_id

    ids = sc.record_resolution("ignore_protocol_mtu", "R1", commands=["interface Gi0/1", "ip ospf mtu-ignore"],
                               protocol="ospf")
    assert ids
    events = sc.memory.temporal(limit=10)
    assert any(e["id"] == incident_id for e in events)


def test_record_failed_resolution_enables_recurring_failure_detection(tmp_path):
    sc = _supply_chain(tmp_path)
    for _ in range(3):
        sc.record_failed_resolution("configure_ospf_interface", "R1", reason="area mismatch", protocol="ospf")

    recurring = sc.memory.recurring_failures(min_count=2)
    assert recurring
    assert recurring[0]["count"] >= 2


def test_build_failure_signatures_from_operational_history(tmp_path):
    sc = _supply_chain(tmp_path)
    for _ in range(4):
        sc.record_failed_resolution("configure_ospf_interface", "R1", reason="area mismatch", protocol="ospf")

    signatures = sc.build_failure_signatures(min_count=2)
    assert signatures
    sig = signatures[0]
    assert isinstance(sig, FailureSignature)
    assert sig.stuck_state.startswith("recurring:")
    assert 0.0 < sig.confidence <= 0.9


def test_confidence_scales_with_recurrence_count():
    # Tests the pure conversion function directly (deterministic, hand-crafted
    # counts) rather than through OperationalMemory.record_from_contract(),
    # whose internal row-per-call multiplier (deployment + verification +
    # conditional recurring-failure events) is an implementation detail of a
    # pre-existing subsystem this phase doesn't own or need to reverse-engineer.
    low = failure_signatures_module.compile_operational_failure_signatures(
        [{"signature": "a", "count": 2, "intent": "x", "protocol": "ospf"}])
    high = failure_signatures_module.compile_operational_failure_signatures(
        [{"signature": "b", "count": 6, "intent": "y", "protocol": "bgp"}])
    assert low[0].confidence < high[0].confidence
    assert high[0].confidence == 0.9   # capped, same ceiling as the textbook signatures


def test_learn_from_incident_delegates_to_stub_engine(tmp_path):
    sc = _supply_chain(tmp_path)
    result = sc.learn_from_incident(success=False, intent="configure_ospf_interface",
                                    device="R1", protocol="ospf")
    assert result["event"] == "incident"
    assert len(sc.learning.learn_from_calls) == 1
    assert sc.learning.learn_from_calls[0].protocol == "ospf"


def test_compile_operational_patterns_and_confidence_and_lessons(tmp_path):
    sc = _supply_chain(tmp_path)
    patterns = sc.compile_operational_patterns()
    assert patterns == {"patterns_found": 2}

    confidence = sc.update_confidence()
    assert confidence == {"calibration_lessons": 1}

    lessons = sc.generate_lessons_learned()
    assert lessons["events_seen"] == 5
    # one retrospect() call each from compile_operational_patterns(),
    # update_confidence(), and generate_lessons_learned() above
    assert len(sc.learning.retrospect_calls) == 3


# ── publish_operational_intelligence: cross-layer provenance ───────────────

def test_publish_operational_intelligence_writes_both_layers(tmp_path):
    sc = _supply_chain(tmp_path)
    for _ in range(3):
        sc.record_failed_resolution("configure_ospf_interface", "R1", reason="area mismatch", protocol="ospf")
    signatures = sc.build_failure_signatures(min_count=2)
    assert signatures

    result = sc.publish_operational_intelligence(signatures[0])
    assert not result["knowledge_layer"].get("skipped")
    assert result["graph_node_ids"]

    # searchable in the EnterpriseKnowledgeLayer (Level 1)
    hits = sc.search_raw_sources("ospf stuck")
    assert hits

    # present as a node in the KnowledgeGraph (Level 2), with provenance
    # tracing back to the operational pattern that produced it.
    node_id = result["graph_node_ids"][0]
    node = sc.graph.nodes[node_id]
    assert node.label == "reasoning_artifact"
    assert any("operational_memory" in e for e in node.attributes.get("evidence", []))
