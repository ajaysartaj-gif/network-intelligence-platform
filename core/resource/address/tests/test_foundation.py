"""
NRIE · Address Foundation · Unit Tests
======================================
Covers domain (value objects, policies, aggregates, specifications), the
knowledge layer, and a service round-trip through the reused Memory Platform.
Pure-domain tests are fully isolated; service tests use unique names so they are
robust against the shared development database.

Runnable with pytest OR directly:  python -m core.resource.address.tests.test_foundation
"""
from __future__ import annotations

import uuid

from core.resource.address.domain import specifications as spec
from core.resource.address.domain.aggregates import (
    EnterpriseHierarchy, OrganizationalMemory, ResourceInventory,
)
from core.resource.address.domain.entities import (
    BusinessContext, EnterpriseEntity, NetworkResource, OrganizationalKnowledge,
)
from core.resource.address.domain.policies import (
    HierarchyLevelOrderPolicy, ParentMustExistPolicy, PolicyViolation,
)
from core.resource.address.domain.value_objects import (
    EnterpriseLevel, Identifier, Metadata, ResourceType, Tags,
)
from core.resource.address.knowledge import (
    glossary, ontology, reasoning, standards, taxonomy,
)
from core.resource.address.api.service import NRIEFoundationService
from core.resource.address.contracts.commands import (
    AttachBusinessContext, CaptureOrganizationalKnowledge, RecordResource,
    RegisterEnterpriseEntity,
)


# ── value objects ────────────────────────────────────────────────────────────
def test_enterprise_level_ordering():
    assert EnterpriseLevel.ORGANIZATION.rank < EnterpriseLevel.SITE.rank < EnterpriseLevel.FLOOR.rank


def test_tags_and_metadata_are_immutable_views():
    t = Tags.of("Core", "core", "EDGE")
    assert set(t) == {"core", "edge"}
    m = Metadata({"a": 1}).merged(b=2)
    assert m.get("a") == 1 and m.get("b") == 2


# ── policies ─────────────────────────────────────────────────────────────────
def test_parent_must_exist_policy():
    child = EnterpriseEntity(id=Identifier.new(), level=EnterpriseLevel.SITE,
                             name="s", parent_id=Identifier("missing"))
    try:
        ParentMustExistPolicy().check(child, None)
        assert False, "expected PolicyViolation"
    except PolicyViolation:
        pass


def test_hierarchy_level_order_policy():
    parent = EnterpriseEntity(id=Identifier.new(), level=EnterpriseLevel.SITE, name="site")
    bad = EnterpriseEntity(id=Identifier.new(), level=EnterpriseLevel.ORGANIZATION,
                           name="org", parent_id=parent.id)
    try:
        HierarchyLevelOrderPolicy().check(bad, parent)
        assert False, "expected PolicyViolation"
    except PolicyViolation:
        pass


# ── aggregates ───────────────────────────────────────────────────────────────
def test_enterprise_hierarchy_aggregate_registers_and_emits():
    h = EnterpriseHierarchy()
    org = h.register(EnterpriseEntity(id=Identifier.new(), level=EnterpriseLevel.ORGANIZATION, name="Acme"))
    site = h.register(EnterpriseEntity(id=Identifier.new(), level=EnterpriseLevel.SITE,
                                       name="S1", parent_id=org.id))
    assert site.id in org.children_ids
    events = h.pull_events()
    assert [type(e).__name__ for e in events] == ["EnterpriseEntityRegistered", "EnterpriseEntityRegistered"]


def test_resource_inventory_and_org_memory():
    inv = ResourceInventory()
    r = inv.record(NetworkResource(id=Identifier.new(), resource_type=ResourceType.SUBNET, name="lan"))
    inv.attach_context(BusinessContext(id=Identifier.new(), attached_to=r.id), r)
    assert r.business_context_id is not None
    mem = OrganizationalMemory()
    mem.capture(OrganizationalKnowledge(id=Identifier.new(), kind="runbook", title="rb"))
    assert len(mem.by_kind("runbook")) == 1


# ── specifications ───────────────────────────────────────────────────────────
def test_specifications_compose():
    r = NetworkResource(id=Identifier.new(), resource_type=ResourceType.SUBNET,
                        name="x", purpose="user_lan")
    s = spec.by_resource_type("subnet") & spec.by_purpose("user_lan")
    assert s.is_satisfied_by(r)
    assert not (spec.by_resource_type("vlan")).is_satisfied_by(r)


# ── knowledge layer ──────────────────────────────────────────────────────────
def test_knowledge_definitions():
    assert ("subnet", "assigned_to", "vlan") in ontology.RESOURCE_ONTOLOGY
    assert taxonomy.category_of("subnet") == "addressing"
    assert standards.is_known_kind("address_standard")
    assert glossary.define("vrf")
    assert reasoning.IMPLEMENTS_AI is False     # boundary: no AI in this PR


# ── service round-trip (reuses Memory Platform persistence) ──────────────────
def test_service_roundtrip():
    svc = NRIEFoundationService()
    tag = uuid.uuid4().hex[:6]
    org = svc.register_enterprise_entity(RegisterEnterpriseEntity(level="organization", name=f"Org-{tag}"))
    site = svc.register_enterprise_entity(RegisterEnterpriseEntity(level="site", name=f"Site-{tag}", parent_id=org))
    svc.record_resource(RecordResource(resource_type="vrf", name=f"vrf-{tag}", hierarchy_ref=site))
    svc.attach_business_context(AttachBusinessContext(attached_to=site, site_type="branch", users=50, criticality="normal"))
    svc.capture_knowledge(CaptureOrganizationalKnowledge(kind="lesson_learned", title=f"lesson-{tag}"))

    ids = {n.id for n in svc.enterprise_hierarchy()}
    assert org in ids and site in ids
    assert any(r.name == f"vrf-{tag}" for r in svc.resource_hierarchy(hierarchy_ref=site))
    assert svc.business_context(site).users == 50
    assert any(k.title == f"lesson-{tag}" for k in svc.knowledge(kind="lesson_learned"))


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nALL {len(fns)} NRIE FOUNDATION TESTS PASSED")


if __name__ == "__main__":
    _run_all()
