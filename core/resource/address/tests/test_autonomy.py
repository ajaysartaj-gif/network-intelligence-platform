"""
NRIE · AI-native Autonomy · Unit Tests
======================================
Intent → location → full hierarchy → plan/allocate → subnet records → IP scan +
descriptions. Scanning is injected (sandbox has no live network); the scanner
itself reuses the platform DeviceDiscoveryEngine in production.

Runnable: python -m core.resource.address.tests.test_autonomy
"""
from __future__ import annotations

from core.resource.address.api.service import get_nrie_service
from core.resource.address.autonomy.site_designer import SiteDesigner
from core.resource.address.intent.intent_parser import parse, derive_demands
from core.resource.address.location.location_map import resolve
from core.resource.address.discovery.ip_scanner import ScannedIP


def test_intent_parser_fallback():
    si = parse("I want to deploy a 20 users site in Mumbai")
    assert si.users == 20
    assert si.location.lower() == "mumbai"
    assert si.is_valid()
    demands = derive_demands(si)
    assert any(d.purpose == "user_lan" and d.host_count == 20 for d in demands)


def test_location_resolution():
    loc = resolve("Mumbai")
    assert loc.city == "Mumbai" and loc.state == "Maharashtra"
    assert loc.country == "India" and loc.region == "APAC"
    assert loc.is_resolved()


def test_autonomous_site_design_builds_full_chain_and_plan():
    svc = get_nrie_service()
    designer = SiteDesigner(svc)
    injected = [
        ScannedIP(ip="10.40.0.1", hostname="R1", vendor="Cisco", open_ports=[22, 179], source="gns3"),
        ScannedIP(ip="10.40.0.10", hostname="cam-01", vendor="Hikvision", open_ports=[554, 80]),
        ScannedIP(ip="10.40.0.20", hostname="ws-22", open_ports=[445]),
    ]
    res = designer.design("deploy a 20 users site in Mumbai",
                          address_space="10.40.0.0/16", scanned_override=injected)

    # full hierarchy Region > Country > State > City > Campus > Site > Building > Floor
    levels = [n["level"] for n in res.hierarchy.ordered()]
    for lv in ("region", "country", "state", "city", "campus", "site", "building", "floor"):
        assert lv in levels, f"missing hierarchy level {lv}"
    assert res.hierarchy.names["city"] == "Mumbai"
    assert res.hierarchy.names["region"] == "APAC"

    # autonomous plan produced real subnets + recorded them under the floor
    assert res.plan is not None and res.plan.plan.subnets
    assert res.subnet_resource_ids
    assert res.plan.plan.vrfs and res.plan.plan.vlans

    # active IPs identified with a description + where engaged
    assert len(res.scanned_ips) == 3
    r1 = next(d for d in res.scanned_ips if d.ip == "10.40.0.1")
    assert r1.description and r1.engaged_as
    cam = next(d for d in res.scanned_ips if d.ip == "10.40.0.10")
    assert "CCTV" in cam.engaged_as or "camera" in cam.engaged_as.lower()

    # leaf hierarchy: Subnet > IP details retrievable
    first_cidr = res.plan.plan.subnets[0].cidr
    inv = designer._inventory.by_subnet(first_cidr)
    assert len(inv) == 3


def test_site_profiles_differ_by_type():
    mfg = derive_demands(parse("deploy 50 users manufacturing site in Pune"))
    assert any(d.purpose == "ot" for d in mfg)          # manufacturing → OT zone
    branch = derive_demands(parse("deploy 50 users branch in Noida"))
    assert not any(d.purpose == "ot" for d in branch)   # branch → no OT


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\nALL {len(fns)} NRIE AUTONOMY TESTS PASSED")


if __name__ == "__main__":
    _run_all()
