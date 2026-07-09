"""
Tests for NKC Phase 2 — Knowledge Graph Compiler, Identity Resolution,
Ontology (core/knowledge/compiler/identity.py, ontology.py, graph_ops.py,
the validate_graph extension in validation.py, the add_relationship
idempotency fix in core/knowledge_graph.py, and the merge-aware
SemanticCompiler in compiler.py).

No network, no LLM, no real embedding model.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.knowledge.compiler import graph_ops, identity, ontology
from core.knowledge.compiler.compiler import SemanticCompiler
from core.knowledge.compiler.validation import validate_graph
from core.knowledge_graph import GraphRelationship, KnowledgeGraph
from core.vendor.models import NormalizedObject, ObjectType


SAMPLE_CONFIG = """\
vrf definition CUSTOMER_A
 rd 65000:1
!
interface Gi0/1
 ip vrf forwarding CUSTOMER_A
 ip address 10.0.0.1 255.255.255.0
!
"""

# Same interface as above, referred to by its long form and carrying a
# complementary fact (mtu) the short-form mention didn't have.
SAMPLE_CONFIG_LONGFORM_MTU = """\
interface GigabitEthernet0/1
 mtu 1500
!
"""


# ── identity.py ───────────────────────────────────────────────────────────

def test_normalize_interface_name_expands_cisco_abbreviations():
    assert identity.normalize_interface_name("Gi0/1") == "GigabitEthernet0/1"
    assert identity.normalize_interface_name("Te0/1") == "TenGigabitEthernet0/1"
    assert identity.normalize_interface_name("Lo0") == "Loopback0"
    assert identity.normalize_interface_name("GigabitEthernet0/1") == "GigabitEthernet0/1"


def test_normalize_interface_name_leaves_unknown_prefixes_alone():
    # Junos-style names have no Cisco equivalence to assert — passthrough.
    assert identity.normalize_interface_name("ge-0/0/1") == "ge-0/0/1"
    assert identity.normalize_interface_name("") == ""


def test_normalize_protocol_name():
    assert identity.normalize_protocol_name("OSPFv2") == "ospf"
    assert identity.normalize_protocol_name("is-is") == "isis"
    assert identity.normalize_protocol_name("BGP") == "bgp"


def test_merge_attributes_clean_merge_no_conflict():
    merged, conflicts = identity.merge_attributes({"mtu": 1500}, {"description": "uplink"})
    assert merged == {"mtu": 1500, "description": "uplink"}
    assert conflicts == []


def test_merge_attributes_real_conflict_keeps_old_as_primary():
    merged, conflicts = identity.merge_attributes({"mtu": 1500}, {"mtu": 9000})
    assert conflicts == ["mtu"]
    assert merged["mtu"] == 1500
    assert merged["_conflicting_values"]["mtu"] == [1500, 9000]


def test_merge_duplicate_objects_combines_complementary_attributes():
    a = NormalizedObject(type="interface", id="R1:interface:GigabitEthernet0/1",
                         device="R1", attributes={"name": "GigabitEthernet0/1", "ip": "10.0.0.1"})
    b = NormalizedObject(type="interface", id="R1:interface:GigabitEthernet0/1",
                         device="R1", attributes={"name": "GigabitEthernet0/1", "mtu": 1500})
    merged, issues = identity.merge_duplicate_objects([a, b])
    assert len(merged) == 1
    assert merged[0].get("ip") == "10.0.0.1"
    assert merged[0].get("mtu") == 1500
    assert not issues   # no real conflict, nothing to warn about


def test_merge_duplicate_objects_flags_real_conflicts():
    a = NormalizedObject(type="neighbor", id="R1:neighbor:10.0.0.2", device="R1",
                         attributes={"neighbor_ip": "10.0.0.2", "state": "FULL"})
    b = NormalizedObject(type="neighbor", id="R1:neighbor:10.0.0.2", device="R1",
                         attributes={"neighbor_ip": "10.0.0.2", "state": "LOADING"})
    merged, issues = identity.merge_duplicate_objects([a, b])
    assert len(merged) == 1
    assert any(i.code == "merged_conflict" for i in issues)


# ── ontology.py ────────────────────────────────────────────────────────────

def test_every_object_type_has_a_family():
    for member in ObjectType:
        assert ontology.family_of(member.value) != "Uncategorized", member.value


def test_family_of_unknown_type_does_not_raise():
    assert ontology.family_of("totally_made_up_type") == "Uncategorized"
    assert "Uncategorized" in ontology.families()


# ── core/knowledge_graph.py: add_relationship idempotency fix ─────────────

def test_add_relationship_idempotent_on_exact_triple():
    graph = KnowledgeGraph()
    graph.add_node("A", "device")
    graph.add_node("B", "device")
    graph.add_relationship("A", "B", "depends_on", weight=1.0)
    graph.add_relationship("A", "B", "depends_on", weight=2.0, metadata={"k": "v"})
    assert len(graph.relationships) == 1
    assert graph.relationships[0].weight == 2.0
    assert graph.relationships[0].metadata == {"k": "v"}
    assert len(graph.adjacency["A"]) == 1


def test_add_relationship_distinct_types_are_not_deduped():
    graph = KnowledgeGraph()
    graph.add_node("A", "device")
    graph.add_node("B", "device")
    graph.add_relationship("A", "B", "depends_on")
    graph.add_relationship("A", "B", "connected_to")
    assert len(graph.relationships) == 2


def test_add_relationship_repeated_neighbor_style_call_matches_topology_bridge_pattern():
    # Mirrors core/topology/knowledge_graph_bridge.py's call shape: the same
    # (local_ip, neighbor_key, "adjacent_to") triple could be reported by
    # both CDP and LLDP for one physical link.
    graph = KnowledgeGraph()
    graph.add_node("10.0.0.1", "R1")
    graph.add_node("10.0.0.2", "R2")
    graph.add_relationship("10.0.0.1", "10.0.0.2", "adjacent_to", weight=1.0,
                           metadata={"local_interface": "Gi0/1", "protocol": "cdp"})
    graph.add_relationship("10.0.0.1", "10.0.0.2", "adjacent_to", weight=1.0,
                           metadata={"local_interface": "Gi0/1", "protocol": "lldp"})
    assert len(graph.relationships) == 1
    assert graph.get_dependencies("10.0.0.1") == ["10.0.0.2"]


# ── validation.py::validate_graph ──────────────────────────────────────────

def test_validate_graph_detects_orphan_node():
    graph = KnowledgeGraph()
    graph.add_node("A", "device")
    graph.add_node("B", "device")
    graph.add_node("C", "device")
    graph.add_relationship("A", "B", "connected_to")
    issues = validate_graph(graph)
    orphan_ids = {i.object_id for i in issues if i.code == "orphan_node"}
    assert orphan_ids == {"C"}


def test_validate_graph_detects_cycle():
    graph = KnowledgeGraph()
    graph.add_node("A", "device")
    graph.add_node("B", "device")
    graph.add_relationship("A", "B", "depends_on")
    graph.add_relationship("B", "A", "depends_on")
    issues = validate_graph(graph)
    assert any(i.code == "cycle" for i in issues)


def test_validate_graph_detects_duplicate_relationship_forced_directly():
    graph = KnowledgeGraph()
    graph.add_node("A", "device")
    graph.add_node("B", "device")
    # Bypass add_relationship's idempotency to simulate a graph assembled by
    # direct manipulation (or built before the fix).
    graph.relationships.append(GraphRelationship("A", "B", "uses"))
    graph.relationships.append(GraphRelationship("A", "B", "uses"))
    issues = validate_graph(graph)
    assert any(i.code == "duplicate_relationship" for i in issues)


def test_validate_graph_detects_broken_reference_forced_directly():
    graph = KnowledgeGraph()
    graph.add_node("A", "device")
    graph.relationships.append(GraphRelationship("A", "does-not-exist", "uses"))
    issues = validate_graph(graph)
    assert any(i.code == "broken_reference" and i.object_id == "does-not-exist" for i in issues)


# ── graph_ops.py ───────────────────────────────────────────────────────────

def test_export_import_round_trip():
    graph = KnowledgeGraph()
    graph.add_node("A", "device", {"x": 1})
    graph.add_node("B", "device", {"y": 2})
    graph.add_relationship("A", "B", "connected_to", weight=0.5, metadata={"note": "ok"})

    data = graph_ops.export_graph(graph)
    restored = graph_ops.import_graph(data)

    assert set(restored.nodes.keys()) == {"A", "B"}
    assert restored.nodes["A"].attributes == {"x": 1}
    assert len(restored.relationships) == 1
    assert restored.relationships[0].weight == 0.5


def test_optimize_graph_removes_forced_duplicate():
    graph = KnowledgeGraph()
    graph.add_node("A", "device")
    graph.add_node("B", "device")
    graph.relationships.append(GraphRelationship("A", "B", "uses"))
    graph.relationships.append(GraphRelationship("A", "B", "uses"))
    result = graph_ops.optimize_graph(graph)
    assert result["relationships_removed"] == 1
    assert len(graph.relationships) == 1
    assert graph.get_dependencies("A") == ["B"]


def test_diff_graph_reports_added_removed_changed():
    before = {"nodes": [{"node_id": "A", "label": "device", "attributes": {"x": 1}}],
             "relationships": []}
    after = {"nodes": [{"node_id": "A", "label": "device", "attributes": {"x": 2}},
                       {"node_id": "B", "label": "device", "attributes": {}}],
            "relationships": [{"source": "A", "target": "B", "relationship_type": "uses"}]}
    delta = graph_ops.diff_graph(before, after)
    assert delta["added_nodes"] == ["B"]
    assert delta["changed_nodes"] == ["A"]
    assert delta["added_relationships"] == [["A", "B", "uses"]]


def test_merge_into_graph_merges_not_overwrites():
    graph = KnowledgeGraph()
    graph.add_node("R1:interface:GigabitEthernet0/1", "interface", {"ip": "10.0.0.1"})
    obj = NormalizedObject(type="interface", id="R1:interface:GigabitEthernet0/1",
                           device="R1", attributes={"mtu": 1500})
    published, issues = graph_ops.merge_into_graph(graph, [obj])
    node = graph.nodes["R1:interface:GigabitEthernet0/1"]
    assert node.attributes["ip"] == "10.0.0.1"
    assert node.attributes["mtu"] == 1500
    assert not issues


def test_merge_two_graphs_unions_nodes_and_relationships():
    a = KnowledgeGraph()
    a.add_node("X", "vrf", {"rd": "65000:1"})
    b = KnowledgeGraph()
    b.add_node("X", "vrf", {"name": "CUSTOMER_A"})
    b.add_node("Y", "interface", {})
    b.add_relationship("Y", "X", "belongs_to")

    merged = graph_ops.merge_two_graphs(a, b)
    assert merged.nodes["X"].attributes["rd"] == "65000:1"
    assert merged.nodes["X"].attributes["name"] == "CUSTOMER_A"
    assert "Y" in merged.nodes
    assert len(merged.relationships) == 1


# ── SemanticCompiler integration ───────────────────────────────────────────

def test_recompiling_same_text_does_not_duplicate_relationships():
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    r1 = compiler.compile_configuration(SAMPLE_CONFIG, device="R1", vendor="cisco",
                                        source_doc_id="r1.cfg")
    rel_count_after_first = len(compiler.graph.relationships)
    assert rel_count_after_first > 0

    r2 = compiler.compile_configuration(SAMPLE_CONFIG, device="R1", vendor="cisco",
                                        source_doc_id="r1.cfg")
    assert len(compiler.graph.relationships) == rel_count_after_first


def test_identity_resolution_merges_short_and_long_interface_names():
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    compiler.compile_configuration(SAMPLE_CONFIG, device="R1", vendor="cisco",
                                   source_doc_id="short.cfg")
    compiler.compile_configuration(SAMPLE_CONFIG_LONGFORM_MTU, device="R1", vendor="cisco",
                                   source_doc_id="longform.cfg")

    iface_nodes = [n for n in compiler.graph.nodes.values() if n.label == "interface"]
    assert len(iface_nodes) == 1   # Gi0/1 and GigabitEthernet0/1 merged into one node
    assert iface_nodes[0].attributes.get("ip") == "10.0.0.1"
    assert iface_nodes[0].attributes.get("mtu") == 1500
    assert iface_nodes[0].attributes.get("_merge_count", 1) >= 2


def test_compile_incremental_delta_reports_added_node_on_change(tmp_path):
    path = tmp_path / "r1.cfg"
    path.write_text(SAMPLE_CONFIG)
    compiler = SemanticCompiler(graph=KnowledgeGraph())

    first = compiler.compile_incremental(str(path))
    assert not first.skipped

    path.write_text(SAMPLE_CONFIG + "interface Loopback0\n ip address 1.1.1.1 255.255.255.255\n!\n")
    second = compiler.compile_incremental(str(path))
    assert not second.skipped
    delta = second.stats["delta"]
    loopback_ids = [nid for nid in delta["added_nodes"] if "Loopback0" in nid]
    assert loopback_ids


def test_compile_graph_accepts_prebuilt_objects_and_derives_relationships():
    vrf = NormalizedObject(type="vrf", id="R1:vrf:CUSTOMER_A", device="R1",
                           attributes={"name": "CUSTOMER_A"})
    iface = NormalizedObject(type="interface", id="R1:interface:GigabitEthernet0/1", device="R1",
                             attributes={"name": "GigabitEthernet0/1", "vrf": "CUSTOMER_A"})
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    report = compiler.compile_graph([vrf, iface], source_doc_id="external-objects")
    assert len(report.objects) == 2
    assert any(r.relationship_type == "belongs_to" for r in report.relationships)


def test_merge_graph_unions_another_knowledge_graph():
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    other = KnowledgeGraph()
    other.add_node("Z", "device", {"foo": "bar"})
    compiler.merge_graph(other)
    assert "Z" in compiler.graph.nodes


def test_validate_graph_method_and_optimize_graph_method_on_compiler():
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    compiler.compile_configuration(SAMPLE_CONFIG, device="R1", vendor="cisco")
    issues = compiler.validate_graph()
    assert isinstance(issues, list)
    result = compiler.optimize_graph()
    assert "relationships_removed" in result


def test_export_graph_and_import_graph_methods_round_trip():
    compiler = SemanticCompiler(graph=KnowledgeGraph())
    compiler.compile_configuration(SAMPLE_CONFIG, device="R1", vendor="cisco")
    data = compiler.export_graph()
    node_count_before = len(compiler.graph.nodes)

    fresh = SemanticCompiler(graph=KnowledgeGraph())
    fresh.import_graph(data)
    assert len(fresh.graph.nodes) == node_count_before
