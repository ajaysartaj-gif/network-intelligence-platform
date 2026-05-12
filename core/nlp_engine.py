import re
<<<<<<< HEAD
from typing import Dict, List
=======
from typing import Dict, List, Tuple
>>>>>>> 5cb6d67eba2e3f48a4a6ba132b7fab89cc51e00a

VENDORS = [
    "cisco",
    "juniper",
    "arista",
    "paloalto",
    "fortinet",
    "aruba",
    "nokia",
    "huawei",
    "versa",
    "vmware",
]

PROTOCOLS = [
    "bgp",
    "ospf",
    "eigrp",
    "isis",
    "mpls",
    "evpn",
    "vxlan",
    "ospfv3",
    "tcp",
    "udp",
    "netconf",
    "restconf",
    "snmp",
]

INTENT_PATTERNS = {
    "troubleshoot": [r"trouble", r"issue", r"down", r"fail", r"problem"],
    "audit": [r"audit", r"compliance", r"review", r"policy"],
    "configure": [r"configure", r"setup", r"provision", r"deploy"],
    "monitor": [r"monitor", r"observe", r"metrics", r"telemetry"],
    "change": [r"change", r"update", r"modify", r"upgrade"],
}

DEVICE_KEYWORDS = [
    "router",
    "switch",
    "firewall",
    "load balancer",
    "edge",
    "core",
    "leaf",
    "spine",
    "controller",
]

NETWORK_TERMS = [
    "fabric",
    "topology",
    "link",
    "segment",
    "route",
    "path",
    "latency",
    "throughput",
    "packet loss",
    "jitter",
]


class NLPEngine:
    """Basic network NLP engine for enterprise network intent and entity detection."""

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-zA-Z0-9\s-]", " ", text).strip().lower()

    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        normalized = self._normalize(text)
        tokens = normalized.split()
        devices = [token.upper() for token in tokens if re.match(r"^[A-Z0-9-]+$", token) and any(char.isdigit() for char in token)]
        vendors = [vendor.title() for vendor in VENDORS if vendor in normalized]
        protocols = [protocol.upper() for protocol in PROTOCOLS if protocol in normalized]
        roles = [word for word in DEVICE_KEYWORDS if word in normalized]
        sites = [word.upper() for word in tokens if word.endswith("hq") or word.endswith("dc") or word.startswith("site")]

        return {
            "devices": list(dict.fromkeys(devices)),
            "vendors": list(dict.fromkeys(vendors)),
            "protocols": list(dict.fromkeys(protocols)),
            "roles": list(dict.fromkeys(roles)),
            "sites": list(dict.fromkeys(sites)),
        }

    def detect_intent(self, text: str) -> str:
        normalized = self._normalize(text)
        for intent, patterns in INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, normalized):
                    return intent
        return "informational"

    def parse_network_keywords(self, text: str) -> Dict[str, List[str]]:
        normalized = self._normalize(text)
        found = [term for term in NETWORK_TERMS if term in normalized]
        return {
            "keywords": list(dict.fromkeys(found)),
            "mentions": normalized.split(),
        }

    def extract_device_vendor_protocol(self, text: str) -> Dict[str, List[str]]:
        entities = self.extract_entities(text)
        if not entities["vendors"] and "juniper" in text.lower():
            entities["vendors"].append("Juniper")

        return {
            "devices": entities["devices"],
            "vendors": entities["vendors"],
            "protocols": entities["protocols"],
        }


def analyze_text(text: str) -> Dict[str, object]:
    engine = NLPEngine()
    return {
        "intent": engine.detect_intent(text),
        "entities": engine.extract_entities(text),
        "keywords": engine.parse_network_keywords(text),
        "device_vendor_protocol": engine.extract_device_vendor_protocol(text),
    }
