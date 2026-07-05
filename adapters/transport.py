"""
Transport = the ONLY legitimately vendor-specific code, and it is tiny and
protocol-agnostic. Its whole job: open a session to a box and run an arbitrary
command string (or fetch a YANG subtree). It knows NOTHING about OSPF, hello
intervals, or issues. It does not grow when you add protocols -- only when you
add a fundamentally new wire protocol (CLI-over-SSH vs NETCONF).

In production this is one Netmiko client (Netmiko already abstracts 100+ platforms
behind a `device_type` string -- that is DATA, auto-discoverable by your
DeviceDiscoveryEngine) plus one ncclient/PyEZ client for NETCONF. So "new vendor"
is picking an existing transport + a device_type string, not writing command tables.

This mock renders realistic per-platform output from a scenario so the resolver +
generic adapter can be driven offline. Swap `run()` for a live session unchanged.
"""
from __future__ import annotations


def _mask(prefix):
    bits = ("1" * int(prefix)).ljust(32, "0")
    return ".".join(str(int(bits[i:i + 8], 2)) for i in range(0, 32, 8))


class MockTransport:
    def __init__(self, platform: str, ifcfg: dict):
        self.platform = platform
        self.ifcfg = ifcfg          # {interface: {cfg...}} for this one device

    def run(self, command: str, ctx: str = ""):
        cfg = self.ifcfg[ctx]
        cfg = {**cfg, "mask": _mask(cfg["prefix"])}
        if self.platform == "cisco_ios":
            return self._ios(command, ctx, cfg)
        if self.platform == "juniper_junos":
            return self._junos(command, ctx, cfg)
        raise ValueError(self.platform)

    # --- Cisco IOS CLI ------------------------------------------------------
    def _ios(self, command, ctx, cfg):
        if "ospf interface" in command:
            return (
                f"{ctx} is up, line protocol is up\n"
                f"  Internet Address {cfg['ip']}/{cfg['prefix']}, Netmask {cfg['mask']}, Area {cfg['area']}\n"
                f"  Router ID {cfg['rid']}, Network Type {cfg['ntype']}, Cost 1\n"
                f"  Hello {cfg['hello']}, Dead {cfg['dead']}, Retransmit 5\n"
                f"  Authentication {cfg['auth']}\n"
            )
        if "show interface" in command or "show ip interface" in command:
            return f"{ctx} is up\n  MTU {cfg['mtu']} bytes, BW 1000000 Kbit\n"
        return f"% unrecognized: {command}"

    # --- Juniper Junos CLI (extensive) --------------------------------------
    def _junos(self, command, ctx, cfg):
        if "ospf interface" in command:
            return (
                f"{ctx} is up\n"
                f"  Area {cfg['area']}, Type {cfg['ntype']}\n"
                f"  Address {cfg['ip']}, Mask {cfg['mask']}, MTU {cfg['mtu']}\n"
                f"  Router ID {cfg['rid']}\n"
                f"  Hello {cfg['hello']}, Dead {cfg['dead']}, ReXmit 5\n"
                f"  Auth type {cfg['auth']}\n"
            )
        return f"error: unrecognized command: {command}"


class MockNetconfTransport(MockTransport):
    """Illustrates the structured path: returns a dict, not screen-scrape text.
    A `structured` ObservationCapability reads a field path -- zero regex."""
    def run(self, command, ctx=""):
        cfg = self.ifcfg[ctx]
        return {"ospf-interface": {
            "hello-interval": cfg["hello"], "dead-interval": cfg["dead"],
            "area-id": cfg["area"], "mtu": cfg["mtu"]}}
