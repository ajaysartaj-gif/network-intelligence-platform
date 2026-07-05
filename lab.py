"""Wires the vendor-independent stack from a scenario dict:
   transport (per device) + doc-driven resolver + generic adapter + KP engine.
Nothing here is protocol- or vendor-specific."""
import os
from knowledge.corpus_loader import load_corpus
from knowledge.rag_engine import KnowledgeEngine, LexicalRetriever, StubExtractor
from knowledge.capability import DocDrivenResolver
from adapters.transport import MockTransport
from adapters.generic import GenericAdapter

ROOT = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(ROOT, "corpus")
VENDOR = os.path.join(CORPUS, "vendor")


def load_vendor_docs():
    docs = {}
    for fn in os.listdir(VENDOR):
        if not fn.endswith(".txt"):
            continue
        text = open(os.path.join(VENDOR, fn), encoding="utf-8").read()
        vendor = text.split("VENDOR:")[1].split()[0].strip()
        docs[vendor] = text
    return docs


def build(scenario):
    """scenario = { device: {platform, ifcfg:{if:{...}}, neighbors:[...]} }"""
    resolver = DocDrivenResolver(load_vendor_docs())
    ke = KnowledgeEngine(LexicalRetriever(load_corpus(CORPUS)), StubExtractor())

    def adapter_for(device):
        d = scenario[device]
        return GenericAdapter(vendor=d["platform"],
                              transport=MockTransport(d["platform"], d["ifcfg"]),
                              resolver=resolver, topology=scenario, device=device)
    return adapter_for, ke
