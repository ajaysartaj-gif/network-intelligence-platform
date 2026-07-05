"""
CapabilityResolver -- the fix for the hardcoded adapter.

Mirrors your CommandResolver chain (cache -> RAG -> MCP -> grounded-AI), but for
BOTH directions of vendor knowledge that used to be hardcoded:

  resolve_observe(vendor, read_intent)  -> ObservationCapability {command, extraction}
  resolve_remediate(vendor, param)      -> RemediationCapability  {command_template}
  resolve_enumerate(vendor, rel_type)   -> command

Resolution order for any (vendor, thing):
  1. cache            -- resolved once, reused (provenance-stamped)
  2. RAG              -- retrieve the VENDOR's own command/troubleshooting guide,
                         grounded-AI derives the command + an extraction spec from
                         the doc's example output
  3. MCP / structured -- prefer NETCONF/YANG / gNMI / pyATS-Genie: structured data,
                         no screen-scraping (the AI-native path)
  4. grounded-AI      -- last resort: LLM reads raw output + doc and extracts a
                         validated value; result is cached so it's deterministic after

The offline DocDrivenResolver below stands in for steps 2-4: it reads the vendor
guide files in corpus/vendor/. In production these are replaced by real retrieval
over Cisco/Juniper references + a Groq grounded-extraction pass. The point: adding
Juniper is a NEW DOC, not a new adapter. The Cisco guide is now actually consulted.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class ObservationCapability:
    vendor: str
    read_intent: str
    command: str            # command to run, may contain {ctx}
    method: str             # "regex" | "structured"
    spec: str               # regex pattern, or dotted path for structured data
    provenance: str         # which doc this was resolved from


@dataclass
class RemediationCapability:
    vendor: str
    param: str
    template: str           # config template, {ctx}/{val}/{area} placeholders
    provenance: str


def apply_extraction(cap: ObservationCapability, raw):
    """Turn transport output into a raw (pre-normalization) value."""
    if cap.method == "regex":
        m = re.search(cap.spec, raw if isinstance(raw, str) else str(raw))
        return m.group(1) if m else None
    if cap.method == "structured":            # raw is a dict from NETCONF/YANG
        cur = raw
        for key in cap.spec.split("/"):
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
        return str(cur)
    raise ValueError(cap.method)


class CapabilityResolver(ABC):
    @abstractmethod
    def resolve_observe(self, vendor: str, read_intent: str) -> ObservationCapability: ...
    @abstractmethod
    def resolve_remediate(self, vendor: str, param: str) -> RemediationCapability: ...
    @abstractmethod
    def resolve_enumerate(self, vendor: str, relationship_type: str) -> tuple[str, str]: ...


class DocDrivenResolver(CapabilityResolver):
    """Reads vendor guides (corpus/vendor/*.txt) and caches what it resolves.
    Stands in for RAG-over-vendor-guide + grounded extraction. Same code path
    for every vendor -- the ONLY per-vendor thing is which doc gets retrieved."""

    def __init__(self, vendor_docs: dict[str, str]):
        # vendor_docs: {vendor: raw_guide_text}
        self.docs = vendor_docs
        self._obs, self._rem, self._enum = {}, {}, {}
        for vendor, text in vendor_docs.items():
            self._parse(vendor, text)

    def _parse(self, vendor, text):
        prov = f"{vendor} command guide"
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("OBSERVE "):
                # OBSERVE <intent> :: <cmd> :: <method> :: <spec>
                body = line[len("OBSERVE "):]
                intent, cmd, method, spec = [x.strip() for x in body.split("::")]
                self._obs[(vendor, intent)] = ObservationCapability(
                    vendor, intent, cmd, method, spec, prov)
            elif line.startswith("REMEDIATE "):
                body = line[len("REMEDIATE "):]
                param, tmpl = [x.strip() for x in body.split("::", 1)]
                self._rem[(vendor, param)] = RemediationCapability(
                    vendor, param, tmpl.replace("\\n", "\n"), prov)
            elif line.startswith("ENUMERATE "):
                body = line[len("ENUMERATE "):]
                rel, cmd = [x.strip() for x in body.split("::", 1)]
                self._enum[(vendor, rel)] = (cmd, prov)

    def resolve_observe(self, vendor, read_intent):
        cap = self._obs.get((vendor, read_intent))
        if cap is None:
            # In production: fall through to MCP/NETCONF, then grounded-AI.
            # Here we surface the gap honestly instead of guessing a command.
            raise KeyError(
                f"no observation capability for ({vendor}, {read_intent}). "
                f"Feed the {vendor} guide covering this parameter -- do not add code.")
        return cap

    def resolve_remediate(self, vendor, param):
        cap = self._rem.get((vendor, param))
        if cap is None:
            raise KeyError(f"no remediation capability for ({vendor}, {param})")
        return cap

    def resolve_enumerate(self, vendor, relationship_type):
        e = self._enum.get((vendor, relationship_type))
        if e is None:
            raise KeyError(f"no enumerate command for ({vendor}, {relationship_type})")
        return e
