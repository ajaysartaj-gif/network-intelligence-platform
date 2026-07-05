"""Pure, deterministic relation logic. No I/O, no LLM. Trivially unit-testable."""
from __future__ import annotations
import re
from knowledge.schema import Relation, MatchParameter


def violates(relation: Relation, local, remote) -> bool:
    if local is None or remote is None:
        return False   # can't compare -> not a confirmed violation
    if relation == Relation.MUST_EQUAL:
        return str(local) != str(remote)
    if relation == Relation.MUST_DIFFER:
        return str(local) == str(remote)
    raise ValueError(relation)


def applies(param: MatchParameter, adapter, endpoint) -> bool:
    """Evaluate a simple guard like 'network_type != point_to_point'.
    Guards reference other semantic read_intents so they stay vendor-neutral."""
    cond = param.applies_when.strip()
    if not cond:
        return True
    m = re.match(r"(\w+)\s*(==|!=)\s*(\S+)", cond)
    if not m:
        return True  # unparseable guard -> fail open (still read the param)
    intent, op, want = m.groups()
    got = adapter.read_parameter(endpoint, intent).value
    got = (got or "").lower()
    want = want.lower()
    return got != want if op == "!=" else got == want
