"""python3 demo_multivendor.py
Same OSPF investigation across a Cisco IOS <-> Juniper Junos link. Watch:
 - each end is read with ITS OWN vendor command (resolved from its guide, not code)
 - area 0 vs 0.0.0.0 and BROADCAST vs LAN normalize equal -> no false mismatch
 - the real hello mismatch is caught, and each fix uses that vendor's syntax
"""
from lab import build
from strategies.mismatch import MismatchStrategy

scenario = {
    "R1": {"platform": "cisco_ios",
           "ifcfg": {"GigabitEthernet0/0": {
               "ip": "10.0.12.1", "prefix": 24, "area": "0", "rid": "1.1.1.1",
               "ntype": "BROADCAST", "hello": "10", "dead": "40", "auth": "None", "mtu": "1500"}},
           "neighbors": [{"local_if": "GigabitEthernet0/0", "remote_dev": "R2",
                          "remote_if": "ge-0/0/0.0", "state": "INIT"}]},
    "R2": {"platform": "juniper_junos",
           "ifcfg": {"ge-0/0/0.0": {
               "ip": "10.0.12.2", "prefix": 24, "area": "0.0.0.0", "rid": "2.2.2.2",
               "ntype": "LAN", "hello": "30", "dead": "40", "auth": "None", "mtu": "1500"}},
           "neighbors": []},
}

def trace(event, **kw):
    if event == "param.read":
        print(f"  read {kw['param']:22} IOS({kw['local']}) == JUNOS({kw['remote']}) ?"
              f"  -> {'MATCH' if kw['local']==kw['remote'] else 'DIFFER'}")

adapter_for, ke = build(scenario)
findings = MismatchStrategy(adapter_for, ke, trace=trace).investigate("ospf_adjacency", "R1")

print("\nnormalized comparison (note area 0==0.0.0.0, broadcast==lan collapse to MATCH):\n")
print("=== VERDICT ===")
for f in findings:
    print(f"\n{f.parameter}: {f.local} vs {f.remote}  "
          f"[{'corroborated' if f.corroborated else 'latent'}, conf={f.confidence}, "
          f"observed={f.observed_state}]")
    for r in f.remediations:
        end = "R1/IOS" if "R1" in r.endpoint else "R2/Junos"
        print(f"  fix @ {end} (approval required): {r.config.replace(chr(10),' ; ')}")
if not findings:
    print("no mismatch")
