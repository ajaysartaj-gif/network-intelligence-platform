import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lab import build
from strategies.mismatch import MismatchStrategy


def side(rid, ip, **ovr):
    d = {"ip": ip, "prefix": 24, "area": "0", "rid": rid, "ntype": "BROADCAST",
         "hello": "10", "dead": "40", "auth": "None", "mtu": "1500"}
    d.update(ovr); return d


def base():
    return {
        "R1": {"platform": "cisco_ios",
               "ifcfg": {"GigabitEthernet0/0": side("1.1.1.1", "10.0.12.1")},
               "neighbors": [{"local_if": "GigabitEthernet0/0", "remote_dev": "R2",
                              "remote_if": "GigabitEthernet0/0", "state": "FULL"}]},
        "R2": {"platform": "cisco_ios",
               "ifcfg": {"GigabitEthernet0/0": side("2.2.2.2", "10.0.12.2")},
               "neighbors": []},
    }


def run(scenario):
    adapter_for, ke = build(scenario)
    return MismatchStrategy(adapter_for, ke).investigate("ospf_adjacency", "R1")


def test_kp_built_from_docs_not_code():
    _, ke = build(base())
    kp = ke.get_package("ospf_adjacency")
    names = {p.name for p in kp.parameters}
    assert "ospf_hello_interval" in names and "interface_mtu" in names
    assert any(p.relation.value == "must_differ" for p in kp.parameters)


def test_healthy():
    assert run(base()) == []


def test_hello_mismatch_corroborated():
    s = base()
    s["R2"]["ifcfg"]["GigabitEthernet0/0"]["hello"] = "30"
    s["R1"]["neighbors"][0]["state"] = "INIT"
    top = run(s)[0]
    assert top.parameter == "ospf_hello_interval"
    assert (top.local, top.remote) == ("10", "30")
    assert top.corroborated and top.confidence > 0.9


def test_mtu_mismatch_on_exstart():
    s = base()
    s["R2"]["ifcfg"]["GigabitEthernet0/0"]["mtu"] = "9000"
    s["R1"]["neighbors"][0]["state"] = "EXSTART"
    mtu = [x for x in run(s) if x.parameter == "interface_mtu"][0]
    assert mtu.corroborated and mtu.fatal


def test_router_id_collision_must_differ():
    s = base()
    s["R2"]["ifcfg"]["GigabitEthernet0/0"]["rid"] = "1.1.1.1"
    s["R1"]["neighbors"][0]["state"] = "2WAY"
    rid = [x for x in run(s) if x.parameter == "ospf_router_id"][0]
    assert rid.relation == "must_differ" and rid.local == rid.remote == "1.1.1.1"


def test_remediation_dual_ended_and_gated():
    s = base()
    s["R2"]["ifcfg"]["GigabitEthernet0/0"]["hello"] = "30"
    f = run(s)[0]
    assert len(f.remediations) == 2 and all(r.requires_approval for r in f.remediations)
    cfgs = " ".join(r.config for r in f.remediations)
    assert "hello-interval 30" in cfgs and "hello-interval 10" in cfgs
