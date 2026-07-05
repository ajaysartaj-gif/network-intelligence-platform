import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lab import build
from strategies.mismatch import MismatchStrategy


def mixed(hello_r2="10"):
    """R1 = Cisco IOS  <-->  R2 = Juniper Junos, over one OSPF link.
    Note the vendor-native encodings that MUST normalize equal:
      area:  IOS '0'         vs Junos '0.0.0.0'
      ntype: IOS 'BROADCAST' vs Junos 'LAN'
    """
    return {
        "R1": {"platform": "cisco_ios",
               "ifcfg": {"GigabitEthernet0/0": {
                   "ip": "10.0.12.1", "prefix": 24, "area": "0", "rid": "1.1.1.1",
                   "ntype": "BROADCAST", "hello": "10", "dead": "40",
                   "auth": "None", "mtu": "1500"}},
               "neighbors": [{"local_if": "GigabitEthernet0/0", "remote_dev": "R2",
                              "remote_if": "ge-0/0/0.0", "state": "INIT"}]},
        "R2": {"platform": "juniper_junos",
               "ifcfg": {"ge-0/0/0.0": {
                   "ip": "10.0.12.2", "prefix": 24, "area": "0.0.0.0", "rid": "2.2.2.2",
                   "ntype": "LAN", "hello": hello_r2, "dead": "40",
                   "auth": "None", "mtu": "1500"}},
               "neighbors": []},
    }


def run(s):
    adapter_for, ke = build(s)
    return MismatchStrategy(adapter_for, ke).investigate("ospf_adjacency", "R1")


def test_no_false_mismatch_across_vendors():
    """Everything is actually consistent; only the encodings differ. A tool that
    compared raw strings would scream area + network-type mismatch. We must not."""
    assert run(mixed(hello_r2="10")) == []


def test_real_mismatch_still_caught_across_vendors():
    top = run(mixed(hello_r2="30"))[0]
    assert top.parameter == "ospf_hello_interval"
    assert (top.local, top.remote) == ("10", "30")   # normalized ints
    assert top.corroborated                          # INIT matches predicted symptom


def test_remediation_uses_each_vendors_own_syntax():
    f = run(mixed(hello_r2="30"))[0]
    by_end = {("R1" if "R1" in r.endpoint else "R2"): r.config for r in f.remediations}
    assert "ip ospf hello-interval" in by_end["R1"]                 # IOS syntax
    assert "set protocols ospf area 0.0.0.0 interface" in by_end["R2"]  # Junos syntax


def test_adding_juniper_touched_no_engine_code():
    """Guardrail: the vendor layer is data. If someone smuggles OSPF/vendor logic
    back into the engine or strategy, this catches it. Scans executable code only
    (comments and docstrings are stripped, since those legitimately say 'no OSPF here')."""
    import ast, re
    import strategies.mismatch as m, knowledge.rag_engine as r, adapters.generic as g

    def code_only(path):
        src = open(path).read()
        tree = ast.parse(src)
        docstrings = set()
        for node in ast.walk(tree):
            ds = ast.get_docstring(node, clean=False) if isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef)) else None
            if ds:
                docstrings.add(ds)
        for ds in docstrings:
            src = src.replace(ds, "")
        src = re.sub(r"#.*", "", src)          # strip line comments
        return src.lower()

    for mod in (m, r, g):
        src = code_only(mod.__file__)
        assert "ospf" not in src.replace("ospf_adjacency", ""), f"{mod.__file__} leaks OSPF"
        assert "cisco" not in src and "juniper" not in src, f"{mod.__file__} names a vendor"
