"""Tests for the Universal Vendor Adapter Framework and its engine integration."""
import json
import re
import sys
import types
from pathlib import Path

sys.modules.setdefault("streamlit", types.ModuleType("streamlit"))
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.vendor import (
    VendorGateway, discover_adapters, all_adapters, register, VendorAdapter,
    Operation, Op, RemediationIntent, DeviceProbe, VendorProfile, NormalizedError,
    ErrorClass, obj, ObjectType,
)
from core.troubleshooting import TroubleshootingEngine, TSConfig, ResolutionStatus


class Dev:
    def __init__(self, ip, descr):
        self.ip, self.hostname, self.device_type = ip, "R", "generic"
        self._descr = descr


def _gw():
    return VendorGateway(send=lambda d, cmds: {c: "2.2.2.2   0   EXSTART" for c in cmds},
                         hint_provider=lambda d: {"sys_descr": d._descr})


def test_ios_ip_mtu_ignores_mere_mention_in_description():
    """Regression: the ip_mtu stanza regex used to search the WHOLE interface
    body unanchored, so a "description ... ip mtu 9999 ..." line (or a
    negated "no ip mtu 9999") was misread as a real override. Anchoring to
    the start of a config line (after indentation) fixes this."""
    from core.vendor.adapters.cisco_ios_like import IosLikeAdapter

    adapter = IosLikeAdapter()
    profile = VendorProfile(vendor="ios-like", os="ios-like", version="", confidence=0.9,
                            capabilities=[], attributes={"ip": "10.0.0.1"})
    cfg = (
        "interface GigabitEthernet0/0\n"
        " description reference: legacy ip mtu 9999 config, do not reuse\n"
        " ip address 10.0.0.3 255.255.255.0\n"
        " ip mtu 1300\n"
    )
    objs = adapter.parse_output(
        Operation(Op.GET_INTERFACE_DETAILS, {"protocol": "ospf"}),
        {"show running-config | section ^interface": cfg}, profile)
    merged = {}
    for o in objs:
        merged.setdefault(o.id, {}).update(o.attributes)
    assert merged["GigabitEthernet0/0"]["ip_mtu"] == "1300"
    print("[ip_mtu] description mention ignored, real override captured: PASS")


def test_auto_discovery_registers_adapters():
    discover_adapters(force=True)
    names = {a.name for a in all_adapters()}
    assert {"generic-cli", "ios-like", "junos-like"} <= names
    print("[1] adapter auto-discovery: PASS")


def test_detection_routes_by_device_and_falls_back():
    gw = _gw()
    a_ios, _ = gw.resolve(Dev("1.1.1.1", "Cisco IOS Software 15.2"))
    a_jun, _ = gw.resolve(Dev("2.2.2.2", "Juniper JUNOS mx480"))
    a_unk, _ = gw.resolve(Dev("3.3.3.3", "FutureVendor NOS 9"))
    assert a_ios.name == "ios-like" and a_jun.name == "junos-like"
    assert a_unk.name == "generic-cli"          # unknown → generic fallback, never crash
    print("[2] detection + generic fallback: PASS")


def test_same_operation_different_vendor_commands():
    gw = _gw()
    op = Operation(Op.GET_NEIGHBORS, {"protocol": "ospf"})
    ios, pi = gw.resolve(Dev("1.1.1.1", "cisco ios"))
    jun, pj = gw.resolve(Dev("2.2.2.2", "juniper junos"))
    assert ios.build_command(op, pi) != jun.build_command(op, pj)
    print("[3] one operation → vendor-specific commands: PASS")


def test_same_intent_different_vendor_config_with_rollback():
    gw = _gw()
    intent = RemediationIntent("set_protocol_network_point_to_point",
                               {"protocol": "ospf", "interface": "Gi0/0"})
    p_ios = gw.remediate(Dev("1.1.1.1", "cisco ios"), intent)
    p_jun = gw.remediate(Dev("2.2.2.2", "juniper junos"), intent)
    assert p_ios.fix_commands and p_jun.fix_commands
    assert p_ios.fix_commands != p_jun.fix_commands
    assert p_ios.rollback_commands and p_jun.rollback_commands   # rollback ALWAYS accompanies fix
    print("[4] one intent → vendor config + rollback: PASS")


def test_error_normalization():
    gw = _gw()
    e = gw.translate_error(Dev("1.1.1.1", "cisco ios"), "% Invalid input detected")
    assert e.error_class == ErrorClass.CLI
    print("[5] vendor error → normalized error: PASS")


def test_adding_a_new_vendor_requires_no_core_change():
    """Define a brand-new adapter at runtime; it must work with zero framework/engine edits."""
    @register
    class FutureFabricAdapter(VendorAdapter):
        name = "future-fabric"
        priority = 99

        def detect(self, probe):
            blob = " ".join(str(v) for v in probe.hints.values()).lower()
            return VendorProfile(vendor="future", confidence=0.95 if "futurefabric" in blob else 0.0,
                                 attributes={"ip": getattr(probe.device, "ip", "")})

        def capabilities(self, profile):
            return ["cloud", "telemetry", "some_future_capability"]

        def build_command(self, operation, profile):
            return [f"api:get/{operation.name}"]

        def parse_output(self, operation, raw, profile):
            return [obj(ObjectType.NEIGHBOR, device=profile.attributes.get("ip", ""),
                        id="peer1", state="up")]

        def build_fix(self, intent, profile):
            return [f"api:apply/{intent.name}"]

        def build_rollback(self, intent, profile):
            return [f"api:revert/{intent.name}"]

        def translate_error(self, raw_error):
            return NormalizedError(ErrorClass.API, raw_error)

    gw = _gw()
    a, _ = gw.resolve(Dev("9.9.9.9", "FutureFabric controller v1"))
    assert a.name == "future-fabric"                 # picked purely by detection confidence
    objs, err = gw.collect(Dev("9.9.9.9", "FutureFabric controller v1"),
                           Operation(Op.GET_NEIGHBORS, {"protocol": "ospf"}))
    assert err is None and objs and objs[0].type == "neighbor"
    print("[6] new vendor via one adapter, no core change: PASS")


def test_no_vendor_names_in_engine_or_framework_core():
    """The engine and framework core must contain NO vendor conditionals/names.
    Vendor tokens are allowed ONLY inside the adapters/ plug-in directory."""
    vendor_tokens = ["cisco", "juniper", "arista", "nokia", "huawei", "junos",
                     "ios-xe", "eos", "fortinet", "palo alto"]
    core_files = list((ROOT / "core" / "vendor").glob("*.py")) + \
                 list((ROOT / "core" / "troubleshooting").glob("*.py"))
    offenders = []
    for f in core_files:
        text = f.read_text(encoding="utf-8", errors="ignore").lower()
        for tok in vendor_tokens:
            if tok in text:
                offenders.append(f"{f.name}:{tok}")
    assert not offenders, f"vendor tokens leaked into core: {offenders}"
    print("[7] zero vendor names in engine/framework core: PASS")


def test_engine_uses_gateway_end_to_end():
    """Engine reasons on normalized objects and remediates via intent; the vendor
    fix comes entirely from the adapter."""
    def ai(prompt: str) -> str:
        if "Restate this network troubleshooting" in prompt:
            return "Determine why OSPF adjacency is stuck."
        if "candidate ROOT CAUSES" in prompt:
            return json.dumps([
                {"statement": "MTU mismatch between OSPF neighbors", "prior": 0.3},
                {"statement": "OSPF timer mismatch", "prior": 0.2}])
        if "normalized diagnostic OPERATION" in prompt:
            already = ""
            m = re.search(r"ALREADY COLLECTED[^\n]*\n([^\n]*)", prompt)
            if m:
                already = m.group(1)
            cands = [{"device": "all", "operation": Op.GET_NEIGHBORS, "params": {"protocol": "ospf"}, "value": 0.9},
                     {"device": "all", "operation": Op.GET_INTERFACE_DETAILS, "params": {}, "value": 0.8},
                     {"device": "all", "operation": Op.GET_ROUTING_INFORMATION, "params": {}, "value": 0.7}]
            cands = [c for c in cands if c["operation"] not in already]
            return json.dumps(cands[:3])
        if "Interpret this device output" in prompt:
            mtu = re.search(r"\[(hyp_[0-9a-f]+)\]\s*MTU mismatch", prompt)
            impacts = []
            if mtu:
                impacts.append({"hypothesis_id": mtu.group(1), "effect": "support",
                                "weight": 0.5, "reason": "EXSTART indicates MTU"})
            tim = re.search(r"\[(hyp_[0-9a-f]+)\]\s*OSPF timer", prompt)
            if tim:
                impacts.append({"hypothesis_id": tim.group(1), "effect": "contradict",
                                "weight": 0.5, "reason": "timers fine"})
            return json.dumps({"facts": [{"subject": "ospf.neighbor", "attribute": "state",
                                          "value": "EXSTART"}], "impacts": impacts})
        if "VENDOR-NEUTRAL" in prompt:
            return json.dumps({"name": "ignore_protocol_mtu",
                               "params": {"protocol": "ospf", "interface": "Gi0/0"},
                               "rationale": "MTU mismatch keeps OSPF in EXSTART."})
        return ""

    devices = [Dev("10.0.0.1", "Cisco IOS Software 15.2"),
               Dev("10.0.0.2", "Cisco IOS Software 15.2"),
               Dev("10.0.0.3", "Cisco IOS Software 15.2")]
    gw = VendorGateway(send=lambda d, cmds: {c: "2.2.2.2   0   EXSTART" for c in cmds},
                       hint_provider=lambda d: {"sys_descr": d._descr})
    eng = TroubleshootingEngine(ai_call=ai, devices=devices, gateway=gw,
                                config=TSConfig(max_steps=5))
    report = eng.run("why is OSPF stuck")
    s = report.session
    assert s.status == ResolutionStatus.RESOLVED_PENDING_APPROVAL, s.status
    # the fix is VENDOR syntax produced by the ios-like adapter from the neutral intent
    assert s.fix and any("mtu-ignore" in c for c in s.fix.config_commands), s.fix.config_commands
    assert s.fix.rollback_commands                       # rollback always present
    # engine collected NORMALIZED objects (neighbor facts), not raw CLI
    assert any(o.subject.startswith("ospf") for o in s.observations)
    print("[8] engine end-to-end via gateway (normalized + intent-driven fix): PASS")


if __name__ == "__main__":
    test_auto_discovery_registers_adapters()
    test_detection_routes_by_device_and_falls_back()
    test_same_operation_different_vendor_commands()
    test_same_intent_different_vendor_config_with_rollback()
    test_error_normalization()
    test_adding_a_new_vendor_requires_no_core_change()
    test_no_vendor_names_in_engine_or_framework_core()
    test_engine_uses_gateway_end_to_end()
    print("\nALL VENDOR-FRAMEWORK TESTS PASSED")
