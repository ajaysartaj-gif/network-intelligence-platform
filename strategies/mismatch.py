"""
Mismatch strategy = ONE fixed loop, parameterized entirely by a Knowledge Package.

    for each instance of the relationship (both ends resolved):
        for each parameter the KP says must agree/differ:
            read normalized value from each end via the adapter   (READ-ONLY)
            deterministically test the relation
        corroborate each violation against the observed state     (raises confidence)
        emit findings + approval-gated remediation candidates

No OSPF/HSRP/BGP logic appears below. The comparison is deterministic on purpose:
the LLM builds the KP, but it is never in the compare hot-loop.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from .relation_eval import violates, applies
from knowledge.schema import KnowledgePackage, MatchParameter


@dataclass
class Remediation:
    endpoint: str          # which end this would change
    config: str            # proposed config (NOT applied)
    aligns_to: str         # the value it would align this end to
    requires_approval: bool = True   # invariant: writes always gated


@dataclass
class Finding:
    parameter: str
    relation: str
    local: str
    remote: str
    fatal: bool
    observed_state: str
    symptom_expected: str
    confidence: float          # 0..1
    logodds_delta: float       # additive evidence for your hypothesis engine
    corroborated: bool         # observed symptom matches the KP's predicted symptom
    provenance: str
    remediations: list = field(default_factory=list)   # candidate fixes, both ends
    local_device: str = ""     # inst.local.device — which physical/virtual device this end is
    remote_device: str = ""    # inst.remote.device — same, for the far end


def _corroborate(symptom: str, observed_state: str, healthy: tuple) -> tuple[bool, float]:
    """Does the ACTUAL observed state match the symptom the KP predicts for this
    violation? If yes -> strong evidence. If the relationship is merely unhealthy
    -> moderate. If it looks healthy despite the mismatch -> latent/low."""
    st = (observed_state or "").upper()
    sym = (symptom or "").upper()
    if st in [h.upper() for h in healthy]:
        return False, 0.4                      # mismatch present but adjacency fine -> latent
    # direct hit: the state token the KP named shows up in the live state
    for token in ("INIT", "EXSTART", "EXCHANGE", "2WAY", "DOWN", "FLAP"):
        if token in sym and token in st:
            return True, 2.2                    # symptom predicted this exact state
    return False, 1.1                           # unhealthy + a real mismatch, weaker link


class MismatchStrategy:
    def __init__(self, adapter_for, knowledge_engine, trace=None):
        # adapter_for(device) -> DeviceAdapter (your vendor gateway does this today)
        self.adapter_for = adapter_for
        self.ke = knowledge_engine
        self.trace = trace or (lambda *a, **k: None)

    def investigate(self, relationship_type: str, seed_device: str) -> list[Finding]:
        kp: KnowledgePackage = self.ke.get_package(relationship_type)
        self.trace("kp.loaded", relationship_type=relationship_type,
                   params=[p.name for p in kp.parameters], sources=kp.source_provenance)

        seed_adapter = self.adapter_for(seed_device)
        instances = seed_adapter.enumerate_relationship(relationship_type, kp.enumerate_intent)
        findings: list[Finding] = []

        for inst in instances:
            self.trace("instance", key=inst.key, state=inst.observed_state)
            la, ra = self.adapter_for(inst.local.device), self.adapter_for(inst.remote.device)

            for p in kp.parameters:
                lv = la.read_parameter(inst.local, p.read_intent)
                rv = ra.read_parameter(inst.remote, p.read_intent)

                if not (lv.available and rv.available):
                    # precondition failure: mismatch investigation needs BOTH ends.
                    self.trace("param.unreadable", param=p.name,
                               local_ok=lv.available, remote_ok=rv.available)
                    continue
                if not applies(p, la, inst.local):
                    continue

                self.trace("param.read", param=p.name, local=lv.value, remote=rv.value,
                           local_raw=lv.raw, remote_raw=rv.raw)

                if not violates(p.relation, lv.value, rv.value):
                    continue

                corr, delta = _corroborate(p.symptom_if_violated, inst.observed_state,
                                           kp.healthy_states)
                # base evidence weighted by fatality, plus corroboration bump
                logodds = (1.5 if p.fatal_if_violated else 0.5) + delta
                confidence = 1 - 2 ** (-logodds)     # squashing to 0..1

                # remediation candidates for BOTH ends. We do NOT auto-pick a
                # winner: authoritative value comes from a human or design-intent.
                rems = [
                    Remediation(endpoint=str(inst.local),
                                config=la.generate_remediation(inst.local, p.name, rv.value),
                                aligns_to=f"remote={rv.value}"),
                    Remediation(endpoint=str(inst.remote),
                                config=ra.generate_remediation(inst.remote, p.name, lv.value),
                                aligns_to=f"local={lv.value}"),
                ]
                f = Finding(
                    parameter=p.name, relation=p.relation.value,
                    local=lv.value, remote=rv.value, fatal=p.fatal_if_violated,
                    observed_state=inst.observed_state, symptom_expected=p.symptom_if_violated,
                    confidence=round(confidence, 3), logodds_delta=round(logodds, 3),
                    corroborated=corr, provenance=p.provenance, remediations=rems,
                    local_device=inst.local.device, remote_device=inst.remote.device,
                )
                findings.append(f)
                self.trace("finding", param=p.name, local=lv.value, remote=rv.value,
                           corroborated=corr, confidence=f.confidence)

        # strongest, corroborated, fatal findings first
        findings.sort(key=lambda x: (x.corroborated, x.fatal, x.confidence), reverse=True)
        return findings
