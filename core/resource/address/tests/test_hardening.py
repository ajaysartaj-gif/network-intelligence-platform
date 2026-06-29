"""
NRIE · PR-001.1 Hardening · Unit Tests
======================================
Covers the five refinements: Pool aggregate root, richer Business Context,
Context Builder, strengthened ontology, and resource-domain extensibility.
Runnable: python -m core.resource.address.tests.test_hardening
"""
from __future__ import annotations

from core.resource.address.domain.aggregates import Pool
from core.resource.address.domain.entities import (
    BusinessContext, NetworkResource, Reservation,
)
from core.resource.address.domain.value_objects import (
    ArchitecturePattern, AvailabilityRequirement, Capacity, Criticality,
    Fragmentation, GrowthExpectation, GrowthInfo, Identifier, OperationalModel,
    Ownership, ResourceDomain, ResourceStatus, ResourceType, RiskClassification,
    Utilization,
)
from core.resource.address.knowledge import ontology, relationships
from core.resource.address.context import (
    DefaultContextBuilder, ResourceContextBundle,
)


# ── 3. Pool is the Address aggregate root ────────────────────────────────────
def test_pool_is_aggregate_root_owning_members():
    pool = Pool(id=Identifier.new("pool"), purpose="branch_lan")
    sub = NetworkResource(id=Identifier.new("res"), resource_type=ResourceType.SUBNET, name="lan")
    pool.add_subnet(sub)
    pool.add_reservation(Reservation(id=Identifier.new("rsv"), reserved_for="growth"))
    pool.record_capacity(Capacity(total_hosts=254, used_hosts=120))
    pool.record_utilization(Utilization(percent=47.2))
    pool.record_fragmentation(Fragmentation(free_blocks=3, largest_free_block_hosts=64))
    pool.record_growth(GrowthInfo(growth_pct=30, horizon="12m"))
    assert pool.list_subnets()[0].name == "lan"
    assert pool.list_reservations()[0].reserved_for == "growth"
    assert pool.reservations[pool.list_reservations()[0].id.value].pool_id == pool.id
    assert pool.capacity.utilization_pct == round(100*120/254, 2)
    names = [type(e).__name__ for e in pool.pull_events()]
    assert "PoolRegistered" in names and "SubnetAttachedToPool" in names and "ReservationRecorded" in names


def test_pool_only_owns_subnets():
    pool = Pool(id=Identifier.new("pool"))
    vlan = NetworkResource(id=Identifier.new(), resource_type=ResourceType.VLAN, name="v")
    try:
        pool.add_subnet(vlan)
        assert False, "expected ValueError"
    except ValueError:
        pass


# ── 1. Richer Business Context ───────────────────────────────────────────────
def test_business_context_is_richer():
    bc = BusinessContext(
        id=Identifier.new("ctx"),
        business_capability="Order Fulfilment", business_service="WMS",
        business_owner=Ownership(owner="ops-lead"),
        availability=AvailabilityRequirement(target="99.99%", rto="15m", rpo="5m"),
        growth_expectation=GrowthExpectation(horizon="12m", expected_pct=30),
        operational_model=OperationalModel.CO_MANAGED,
        architecture_pattern=ArchitecturePattern.SDWAN,
        risk_classification=RiskClassification.HIGH,
        criticality=Criticality.HIGH, compliance=["pci"])
    assert bc.business_capability and bc.business_service
    assert bc.operational_model == OperationalModel.CO_MANAGED
    assert bc.risk_classification == RiskClassification.HIGH


# ── 4. Strengthened ontology (reusable across domains) ───────────────────────
def test_ontology_relationship_vocabulary():
    for rel in ("belongs_to", "contains", "supports", "depends_on", "connected_to",
                "protected_by", "owned_by", "uses", "allocated_from", "managed_by"):
        assert ontology.is_known_relationship(rel)
    # backward compatibility preserved
    assert ("subnet", "assigned_to", "vlan") in ontology.RESOURCE_ONTOLOGY
    # new reusable edges present
    assert ("subnet", "allocated_from", "address_pool") in ontology.RESOURCE_ONTOLOGY
    # relationships map to known reusable types
    assert relationships.relationship_of("carved_from") == "allocated_from"


# ── 5. Extensibility: Address is not assumed to be the only domain ───────────
def test_resource_domain_extensibility():
    assert ResourceDomain.ADDRESS.value == "address"
    pool = Pool(id=Identifier.new("pool"))
    assert pool.domain == ResourceDomain.ADDRESS         # tagged, not hard-coded everywhere


# ── 2. Context Builder (reusable, no allocation) ─────────────────────────────
def test_context_builder_merges_single_resource_context():
    from core.resource.address.domain.entities import EnterpriseEntity, OrganizationalKnowledge
    from core.resource.address.domain.value_objects import EnterpriseLevel

    builder = DefaultContextBuilder()
    site = EnterpriseEntity(id=Identifier.new("ent"), level=EnterpriseLevel.SITE, name="S1",
                            owner=Ownership(owner="netops"))
    org = EnterpriseEntity(id=Identifier.new("ent"), level=EnterpriseLevel.ORGANIZATION, name="Acme")
    res = NetworkResource(id=Identifier.new("res"), resource_type=ResourceType.SUBNET,
                          name="lan", purpose="user_lan", status=ResourceStatus.PLANNED)
    bc = BusinessContext(id=Identifier.new("ctx"), attached_to=site.id,
                         business_capability="Manufacturing",
                         operational_model=OperationalModel.DISTRIBUTED,
                         risk_classification=RiskClassification.MODERATE)
    know = [OrganizationalKnowledge(id=Identifier.new(), kind="address_standard", title="RFC1918")]
    pool = Pool(id=Identifier.new("pool"), purpose="branch_lan")
    pool.add_subnet(res)

    bundle = builder.for_resource(res, enterprise_node=site, ancestors=[org],
                                  business_context=bc, knowledge=know, pool=pool)
    assert isinstance(bundle, ResourceContextBundle)
    assert bundle.domain == "address"
    assert bundle.resource.pool_ref == pool.id.value
    assert bundle.enterprise.ancestors == ["Acme"]
    assert bundle.business.business_capability == "Manufacturing"
    assert bundle.business.operational_model == "distributed"
    assert "address_standard" in bundle.organizational.applicable_standard_kinds
    d = bundle.to_dict()
    assert set(d.keys()) == {"domain", "resource", "enterprise", "business", "organizational"}


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nALL {len(fns)} PR-001.1 HARDENING TESTS PASSED")


if __name__ == "__main__":
    _run_all()
