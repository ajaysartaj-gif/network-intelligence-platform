"""
GatewayDeviceAdapter — bridges strategies.mismatch.MismatchStrategy onto the
LIVE Universal Vendor Adapter Framework (core.vendor.VendorGateway), instead of
the offline adapters.generic.GenericAdapter + adapters.transport.MockTransport
pair the dead pipeline was built and tested against.

Design constraint (Volume 7 §4 — "no parallel runtimes"): this class contains
no vendor or protocol logic of its own. It only maps between two abstractions
that already exist in the repository:

    adapters.base.DeviceAdapter          (what MismatchStrategy expects)
    core.vendor.gateway.VendorGateway    (what the rest of the engine already uses)

Everything vendor-specific still lives exactly where it lived before this file
existed: inside core/vendor/adapters/*.py. Adding a vendor here still means
adding/extending one of those adapters, not touching this bridge or the engine.

Known scope limits (documented rather than silently guessed around, per this
platform's own "declare unavailable, never guess" principle):

  * Relationship enumeration is driven by the gateway's GET_NEIGHBORS operation.
    When a real topology graph is supplied (see core.topology.knowledge_graph_bridge,
    built from CDP/LLDP discovery), interface pairing is exact — the graph edge's
    metadata carries the real local/remote interface names, resolving multi-homed
    topologies correctly. Without one (discovery unavailable, netmiko missing,
    or the caller didn't pass a graph), pairing falls back to a conservative
    heuristic (see _infer_remote_interface): unambiguous only when a device has
    exactly one protocol-enabled interface. In that fallback case, topologies the
    heuristic can't resolve are skipped rather than paired incorrectly.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from adapters.base import DeviceAdapter, Endpoint, ParameterValue, RelationshipInstance
from knowledge.normalize import normalize

logger = logging.getLogger(__name__)

# read_intent (semantic, vendor-neutral, as declared in the corpus/KP) ->
# the NormalizedObject attribute key the live gateway adapters already expose
# via GET_INTERFACE_DETAILS. Extending this dict is how a NEW semantic
# parameter becomes readable — no adapter/engine code changes required as
# long as the vendor adapter's parse_output already emits the attribute.
READ_INTENT_ATTR = {
    "ospf_area_id": "area",
    "ospf_hello_interval": "hello",
    "ospf_dead_interval": "dead",
    "interface_mtu": "mtu",
    "ospf_network_type": "network_type",
    "ospf_router_id": "router_id",
    "ospf_auth": "auth",
    "ospf_network_mask": "network_mask",
    # HSRP's 6 corpus/hsrp_pairing.txt parameters were declared from day
    # one but had ZERO entries here — every one was structurally
    # unreadable regardless of adapter support. hsrp_group_number/priority
    # were already emitted by the existing "show standby brief" parser
    # (attrs "grp"/"prio"); the other 4 needed cisco_ios_like.py's new
    # verbose "show standby" parsing (see its GET_INTERFACE_DETAILS branch)
    # to be readable at all.
    "hsrp_group_number": "grp",
    "hsrp_priority": "prio",
    "hsrp_virtual_ip": "virtual_ip",
    "hsrp_version": "version",
    "hsrp_auth": "auth",
    "hsrp_timers": "timers",
    # Auto-drafted corpus/vrrp_pairing.txt params — keyed by their
    # read_intent field, which the drafter named distinctly from the
    # param's own `name` (e.g. name="advertisement_interval",
    # read_intent="master_election"). "show vrrp brief"'s Time column was
    # previously matched-but-discarded; now captured as "adv_interval".
    "master_election": "adv_interval",
    "master_reclaim": "preempt_enabled",
}

# relationship_type (as declared in the corpus/KP) -> the gateway Operation
# protocol parameter used to collect neighbors/interfaces for it.
RELATIONSHIP_PROTOCOL = {
    "mpls_l3vpn_peering": "mpls_l3vpn",
    "vxlan_evpn_peering": "vxlan_evpn",
    "pim_neighbor": "multicast_pim",
    "eigrp_adjacency": "eigrp",
    "vrrp_pairing": "vrrp",
    "ospf_adjacency": "ospf",
    "hsrp_pairing": "hsrp",
}

# relationship_type -> read_intent used to derive a remediation config template
# name on the gateway side (see _INTENT_FOR_PARAM below for the full mapping).
_INTENT_FOR_PARAM = {
    "ospf_hello_interval": "set_ospf_hello_interval",
    "ospf_dead_interval": "set_ospf_dead_interval",
    "interface_mtu": "set_interface_mtu",
    "ospf_network_type": "set_ospf_network_type",
    # Reuses the existing enable_ospf_on_interface / fix_duplicate_router_id
    # Cisco recipes (core.knowledge.compiler.protocol_registry) — a
    # Mismatch-Investigation-detected area or router-id violation previously
    # had no remediation mapping at all here and silently produced no fix.
    "ospf_area_id": "enable_ospf_on_interface",
    "ospf_router_id": "fix_duplicate_router_id",
    # hsrp_group_number and hsrp_timers are deliberately absent — see the
    # recipes' own docstring in protocol_registry.py for why (renumbering a
    # group isn't a single safe command; timers are one packed string this
    # template substitution can't split back into two positions).
    "hsrp_priority": "set_hsrp_priority",
    "hsrp_virtual_ip": "set_hsrp_virtual_ip",
    "hsrp_auth": "set_hsrp_auth",
    "hsrp_version": "set_hsrp_version",
    # advertisement_interval reuses a new dedicated recipe; preempt_setting
    # reuses the SAME enable_vrrp_preempt intent the compiled Backup
    # signature already uses — both fixes are the identical command
    # regardless of which path (FSM signature vs. Mismatch Investigation)
    # detected the problem.
    "advertisement_interval": "set_vrrp_advertisement_interval",
    "preempt_setting": "enable_vrrp_preempt",
}


class GatewayDeviceAdapter(DeviceAdapter):
    """One instance per investigation. Talks to whichever devices/vendors the
    gateway resolves adapters for — this class never checks vendor identity."""

    vendor = "gateway-backed"

    def __init__(self, gateway: Any, ip_to_device: Dict[str, Any], relationship_type: str,
                 topology_graph: Any = None):
        self.gateway = gateway
        self._ip_to_dev = ip_to_device
        self.relationship_type = relationship_type
        self._protocol = RELATIONSHIP_PROTOCOL.get(relationship_type, "")
        self._nbr_cache: Dict[str, list] = {}
        self._iface_cache: Dict[str, Dict[str, Any]] = {}
        self._rid_map: Optional[Dict[str, str]] = None
        # Real CDP/LLDP-derived adjacency (core.topology.knowledge_graph_bridge),
        # if the caller built one. When present, interface pairing is exact
        # instead of heuristic — see module docstring.
        self.topology_graph = topology_graph

    # ── internal: cached, gateway-backed reads ──────────────────────────────
    def _neighbors(self, device_ip: str) -> list:
        if device_ip in self._nbr_cache:
            return self._nbr_cache[device_ip]
        from core.vendor.operations import Op, Operation
        device = self._ip_to_dev.get(device_ip)
        objs: list = []
        if device is not None and self._protocol:
            objs, _err = self.gateway.collect(
                device, Operation(Op.GET_NEIGHBORS, {"protocol": self._protocol}))
        self._nbr_cache[device_ip] = objs or []
        return self._nbr_cache[device_ip]

    def _interfaces(self, device_ip: str) -> Dict[str, Any]:
        if device_ip in self._iface_cache:
            return self._iface_cache[device_ip]
        from core.vendor.operations import Op, Operation
        device = self._ip_to_dev.get(device_ip)
        objs: list = []
        if device is not None and self._protocol:
            objs, _err = self.gateway.collect(
                device, Operation(Op.GET_INTERFACE_DETAILS, {"protocol": self._protocol}))
        # MERGE, not overwrite: the adapter legitimately returns MULTIPLE
        # NormalizedObjects for the SAME interface id — one per command
        # (e.g. "show ip ospf interface" for area/hello/dead, "show
        # interface" for hardware mtu, "show running-config interface X"
        # for an ip_mtu override). A naive {o.id: o} comprehension keeps
        # only whichever object happens to be last and silently discards
        # every attribute the others carried.
        by_iface: Dict[str, Dict[str, Any]] = {}
        for o in (objs or []):
            if getattr(o, "type", "") != "interface":
                continue
            by_iface.setdefault(o.id, {}).update(o.attributes)
        self._iface_cache[device_ip] = by_iface
        return by_iface

    def _ospf_interfaces(self, device_ip: str) -> Dict[str, Any]:
        """Interfaces on this device that are actually running the protocol
        under investigation (have a neighbor_count attribute at all)."""
        return {k: v for k, v in self._interfaces(device_ip).items()
                if v.get("neighbor_count") is not None}

    def _infer_local_interface(self, device_ip: str, nbr: Any = None) -> Optional[str]:
        """Which local interface this neighbor was seen on.

        Prefers the EXACT interface the protocol's own neighbor table
        already reports for THIS specific neighbor (e.g. OSPF's "show ip
        ospf neighbor" trailing Interface column, captured by
        _OSPF_NEIGHBOR_PARSER's extra_attrs) when the caller has that
        neighbor object in hand. This resolves a multi-homed device (more
        than one protocol-enabled interface — real routers with several
        neighbors on different links, not just the single-link MVP case)
        exactly, without needing real CDP/LLDP topology discovery at all.
        Before this, a device with >1 OSPF interface always fell through to
        the single-interface heuristic below and got skipped entirely —
        silently disabling the whole Mismatch Investigation for exactly the
        multi-neighbor routers most likely to need it.

        Falls back to the single-protocol-interface heuristic (unambiguous
        only when the device has exactly one) when no per-neighbor
        interface is available — e.g. a protocol whose neighbor-table
        parser doesn't capture it yet, or no neighbor object was passed."""
        if nbr is not None:
            iface = nbr.get("interface")
            if iface:
                return iface
        ifaces = self._ospf_interfaces(device_ip)
        return next(iter(ifaces)) if len(ifaces) == 1 else None

    def _infer_remote_interface(self, remote_ip: str, local_ip: Optional[str] = None,
                               rid_map: Optional[Dict[str, str]] = None) -> Optional[str]:
        """Same idea as _infer_local_interface, but for the far end: finds
        the remote device's OWN neighbor entry that points back to
        `local_ip` (via the router-id map) and reads THAT neighbor's own
        interface attribute — resolving the remote side exactly for a
        multi-homed remote device too, not just the near side.

        Falls back to the single-interface heuristic when `local_ip`/
        `rid_map` aren't supplied, or the remote neighbor table doesn't
        capture a per-neighbor interface. See module docstring for the
        documented limitation that remains in that fallback case."""
        if local_ip is not None and rid_map is not None:
            for nbr in self._neighbors(remote_ip):
                neighbor_id = getattr(nbr, "id", "")
                if rid_map.get(neighbor_id, neighbor_id) == local_ip:
                    iface = nbr.get("interface")
                    if iface:
                        return iface
                    break
        ifaces = self._ospf_interfaces(remote_ip)
        return next(iter(ifaces)) if len(ifaces) == 1 else None

    def _router_id_to_device_ip(self) -> Dict[str, str]:
        """Neighbor objects identify the far end by protocol router-id (that's
        what 'show ip/ospf ... neighbor' reports), which is generally NOT the
        same string as the device's management/SSH IP used as this engine's
        device key. Build router_id -> device_ip once from each approved
        device's own interface attributes (already fetched for read_parameter,
        so this adds no extra round trip), so a neighbor entry can be resolved
        back to an approved device without assuming the two identifiers match."""
        if self._rid_map is not None:
            return self._rid_map
        rid_map: Dict[str, str] = {}
        for dev_ip in self._ip_to_dev.keys():
            for iface_obj in self._interfaces(dev_ip).values():
                rid = iface_obj.get("router_id")
                if rid:
                    rid_map[rid] = dev_ip
                    break
        self._rid_map = rid_map
        return rid_map

    def _real_interface_pair(self, local_ip: str, remote_ip: str) -> Optional[tuple]:
        """Exact pairing from real CDP/LLDP discovery, if a topology graph was
        supplied. Returns (local_interface, remote_interface) or None if the
        graph doesn't have this edge (e.g. discovery failed for this pair, or
        no graph was passed) — callers fall back to the heuristic in that case."""
        if self.topology_graph is None:
            return None
        try:
            from core.topology.knowledge_graph_bridge import neighbor_interfaces
        except Exception:
            return None
        pair = neighbor_interfaces(self.topology_graph, local_ip, remote_ip)
        if not pair or not pair[0] or not pair[1]:
            return None
        return pair

    # ── DeviceAdapter interface ──────────────────────────────────────────────
    def enumerate_relationship(self, relationship_type: str,
                               enumerate_intent: str) -> List[RelationshipInstance]:
        instances: List[RelationshipInstance] = []
        seen_pairs = set()
        rid_map = self._router_id_to_device_ip()
        for local_ip in self._ip_to_dev.keys():
            for nbr in self._neighbors(local_ip):
                neighbor_id = getattr(nbr, "id", "")
                remote_ip = rid_map.get(neighbor_id, neighbor_id)
                if not remote_ip or remote_ip not in self._ip_to_dev:
                    continue  # far end isn't an approved/known device -> skip, don't guess
                pair_key = tuple(sorted((local_ip, remote_ip)))
                if pair_key in seen_pairs:
                    continue
                real_pair = self._real_interface_pair(local_ip, remote_ip)
                if real_pair:
                    local_ctx, remote_ctx = real_pair
                else:
                    local_ctx = self._infer_local_interface(local_ip, nbr=nbr)
                    remote_ctx = self._infer_remote_interface(
                        remote_ip, local_ip=local_ip, rid_map=rid_map)
                if not local_ctx or not remote_ctx:
                    logger.info(
                        "Mismatch investigation: skipping %s<->%s — interface pairing "
                        "is ambiguous (multi-homed?) and no topology graph resolved it.",
                        local_ip, remote_ip)
                    continue
                seen_pairs.add(pair_key)
                instances.append(RelationshipInstance(
                    key=f"{local_ip}:{local_ctx}<->{remote_ip}:{remote_ctx}",
                    local=Endpoint(device=local_ip, context=local_ctx),
                    remote=Endpoint(device=remote_ip, context=remote_ctx),
                    observed_state=str(nbr.get("state", "")),
                ))
        return instances

    def read_parameter(self, endpoint: Endpoint, read_intent: str) -> ParameterValue:
        attr = READ_INTENT_ATTR.get(read_intent)
        if attr is None:
            return ParameterValue(value=None, raw="", available=False)
        iface_obj = self._interfaces(endpoint.device).get(endpoint.context)
        if iface_obj is None:
            return ParameterValue(value=None, raw="", available=False)
        # "interface_mtu" means the IP MTU OSPF's DBD exchange actually
        # checks — a distinct, independently-configurable value (`ip mtu
        # <n>`) from the interface's underlying L2/hardware MTU (the "mtu"
        # attr, from `show interface`). Prefer the explicit ip_mtu override
        # when the adapter reported one; the hardware MTU is only a
        # legitimate stand-in when no override exists (Cisco IOS: ip mtu
        # defaults to the interface MTU).
        if read_intent == "interface_mtu" and iface_obj.get("ip_mtu") is not None:
            raw = iface_obj.get("ip_mtu")
        else:
            raw = iface_obj.get(attr)
        if raw is None:
            return ParameterValue(value=None, raw="", available=False)
        value = normalize(read_intent, raw)
        return ParameterValue(value=value, raw=str(raw), available=value is not None)

    def generate_remediation(self, endpoint: Endpoint, param_name: str,
                             target_value: str) -> str:
        intent_name = _INTENT_FOR_PARAM.get(param_name)
        device = self._ip_to_dev.get(endpoint.device)
        if not intent_name or device is None:
            return f"! no gateway-resolved remediation for ({param_name}) on {endpoint.device}"
        from core.vendor.operations import RemediationIntent
        # Recipes render via named placeholders ("{area}", "{router_id}",
        # ...), not a generic "{value}" — READ_INTENT_ATTR already gives us
        # the right placeholder name for this param (it's the same
        # attribute name the recipe's own defaults dict uses), so pass
        # target_value under that key too. Without this, an area/router-id
        # fix silently rendered its recipe's DEFAULT ("area 0") instead of
        # the actual value this violation needs.
        placeholder = READ_INTENT_ATTR.get(param_name, "value")
        # For HSRP/VRRP, endpoint.context is the SAME "iface:group"
        # composite _HSRP_STANDBY_PARSER's id_template produces (a device
        # can run multiple groups per interface) — passing it as
        # neighbor_ip too lets render_remediation_fix's existing
        # fhrp_iface/fhrp_group split (already used by add_hsrp_preempt)
        # resolve correctly here as well, instead of falling back to its
        # "group 1" default regardless of the real group number. A no-op
        # for OSPF/BGP, whose bare interface-name context has no colon to
        # split.
        intent = RemediationIntent(
            name=intent_name,
            params={"protocol": self._protocol, "interface": endpoint.context,
                    "neighbor_ip": endpoint.context,
                    "value": target_value, placeholder: target_value},
            target_device=endpoint.device,
            rationale=f"Align {param_name} to {target_value} (Mismatch Investigation)",
        )
        plan = self.gateway.remediate(device, intent)
        if not plan or not plan.supported or not plan.fix_commands:
            return f"! adapter declined remediation for ({param_name}) on {endpoint.device}"
        return "\n".join(plan.fix_commands)
