"""
GenericAdapter -- ONE adapter class for every vendor, forever.

It holds no commands, no regexes, no fix templates. It composes:
  transport  : run a command / fetch structured data  (thin, vendor wire only)
  resolver   : (vendor, read_intent) -> how to read; (vendor, param) -> how to fix
  normalizer : raw vendor value -> canonical world-model value

read_parameter = resolve how-to-read  ->  transport runs it  ->  extract  ->  normalize
Adding Juniper touched THIS file zero times. It required a Junos guide doc + a
Junos transport binding. That is the whole point.
"""
from __future__ import annotations
from .base import DeviceAdapter, Endpoint, RelationshipInstance, ParameterValue
from knowledge.capability import apply_extraction
from knowledge.normalize import normalize


class GenericAdapter(DeviceAdapter):
    def __init__(self, vendor, transport, resolver, topology, device):
        self.vendor = vendor
        self.transport = transport      # bound to `device`
        self.resolver = resolver
        self.topology = topology         # discovery result (DeviceDiscoveryEngine)
        self.device = device

    def enumerate_relationship(self, relationship_type, enumerate_intent):
        # The enumerate COMMAND is resolved from the vendor guide (not hardcoded)...
        cmd, _prov = self.resolver.resolve_enumerate(self.vendor, relationship_type)
        # ...the PAIRING of far ends comes from topology/CDP/LLDP (discovery), which
        # is legitimately its own engine, not per-protocol hardcoding.
        out = []
        for dev, data in self.topology.items():
            for nb in data.get("neighbors", []):
                out.append(RelationshipInstance(
                    key=f"{dev}:{nb['local_if']}<->{nb['remote_dev']}:{nb['remote_if']}",
                    local=Endpoint(dev, nb["local_if"]),
                    remote=Endpoint(nb["remote_dev"], nb["remote_if"]),
                    observed_state=nb["state"]))
        return out

    def read_parameter(self, endpoint, read_intent):
        try:
            cap = self.resolver.resolve_observe(self.vendor, read_intent)
        except KeyError:
            # capability genuinely not known for this vendor -> declare unavailable,
            # never guess a command. The strategy skips this parameter.
            return ParameterValue(value=None, raw="", available=False)
        raw = self.transport.run(cap.command.format(ctx=endpoint.context),
                                 endpoint.context)
        extracted = apply_extraction(cap, raw)
        value = normalize(read_intent, extracted)          # -> world-model space
        raw_str = raw if isinstance(raw, str) else str(raw)
        return ParameterValue(value=value, raw=raw_str.strip(),
                              available=extracted is not None)

    def generate_remediation(self, endpoint, param_name, target_value):
        try:
            cap = self.resolver.resolve_remediate(self.vendor, param_name)
        except KeyError:
            return f"! no doc-resolved remediation for ({self.vendor}, {param_name})"
        cfg = self.topology[endpoint.device]["ifcfg"][endpoint.context]
        return cap.template.format(ctx=endpoint.context, val=target_value,
                                   area=cfg.get("area", ""))
