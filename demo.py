"""Run: python3 demo.py
Manufactures an R1<->R2 OSPF hello mismatch (adjacency stuck in INIT) and drives
the full RAG -> KP -> mismatch investigation, printing a trace-mode view."""
import os
from knowledge.corpus_loader import load_corpus
from knowledge.rag_engine import KnowledgeEngine, LexicalRetriever, StubExtractor
from adapters.ios_mock import IOSMockAdapter
from strategies.mismatch import MismatchStrategy

CORPUS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")


def side(rid, ip, **ovr):
    d = {"ip": ip, "prefix": 24, "area": "0", "rid": rid, "ntype": "BROADCAST",
         "hello": "10", "dead": "40", "auth": "none", "mtu": "1500", "pid": 1}
    d.update(ovr); return d

scenario = {
    "R1": {"ifcfg": {"GigabitEthernet0/0": side("1.1.1.1", "10.0.12.1")},
           "neighbors": [{"local_if": "GigabitEthernet0/0", "remote_dev": "R2",
                          "remote_if": "GigabitEthernet0/0", "state": "INIT"}]},
    "R2": {"ifcfg": {"GigabitEthernet0/0": side("2.2.2.2", "10.0.12.2", hello="30")},
           "neighbors": []},
}

def trace(event, **kw):
    print(f"  [{event:16}] " + "  ".join(f"{k}={v}" for k, v in kw.items()))

ke = KnowledgeEngine(LexicalRetriever(load_corpus(CORPUS)), StubExtractor())
strat = MismatchStrategy(adapter_for=lambda d: IOSMockAdapter(scenario),
                         knowledge_engine=ke, trace=trace)

print("=== TRACE ===")
findings = strat.investigate("ospf_adjacency", "R1")

print("\n=== FINDINGS (ranked) ===")
for f in findings:
    tag = "CORROBORATED" if f.corroborated else "latent"
    print(f"\n[{tag}] {f.parameter}  ({f.relation}, fatal={f.fatal})  conf={f.confidence}")
    print(f"   local={f.local}  remote={f.remote}   observed_state={f.observed_state}")
    print(f"   predicted symptom: {f.symptom_expected}")
    print(f"   provenance: {f.provenance}")
    for r in f.remediations:
        gate = "APPROVAL REQUIRED" if r.requires_approval else "auto"
        print(f"   fix[{gate}] {r.endpoint} -> aligns {r.aligns_to}:")
        for line in r.config.splitlines():
            print(f"        {line}")
