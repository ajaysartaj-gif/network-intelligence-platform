import random
from datetime import datetime, timedelta
from typing import List

from database.database import create_db, get_session
from database.models import ChangeRequest, ComplianceRule, Device, Incident, NetworkLink, Telemetry


def _device_samples() -> List[dict]:
    return [
        {
            "hostname": "DEL-CORE-01",
            "ip_address": "10.1.0.1",
            "vendor": "Cisco",
            "model": "IOS-XR",
            "role": "Core Router",
            "site": "DEL",
            "os_version": "7.5.3",
            "status": "healthy",
        },
        {
            "hostname": "MUM-EDGE-01",
            "ip_address": "10.1.1.1",
            "vendor": "Juniper",
            "model": "MX480",
            "role": "Edge Router",
            "site": "MUM",
            "os_version": "20.4R3",
            "status": "warning",
        },
        {
            "hostname": "BLR-FW-01",
            "ip_address": "10.1.2.1",
            "vendor": "Fortinet",
            "model": "FortiGate-600C",
            "role": "Firewall",
            "site": "BLR",
            "os_version": "7.2.0",
            "status": "critical",
        },
        {
            "hostname": "HYD-LEAF-02",
            "ip_address": "10.1.3.2",
            "vendor": "Arista",
            "model": "7280R",
            "role": "Leaf Switch",
            "site": "HYD",
            "os_version": "4.29.2F",
            "status": "healthy",
        },
    ]


def _incident_samples() -> List[dict]:
    return [
        {
            "title": "BGP neighbor flapping on MUM-EDGE-01",
            "severity": "high",
            "status": "investigating",
            "assigned_to": "noc-team",
            "affected_service": "WAN Transit",
            "description": "BGP session to upstream provider is unstable and causing route withdraws.",
        },
        {
            "title": "Firewall policy mismatch on BLR-FW-01",
            "severity": "critical",
            "status": "mitigating",
            "assigned_to": "security-team",
            "affected_service": "Internet Egress",
            "description": "Duplicate policy entries detected with conflicting source NAT behavior.",
        },
    ]


def _telemetry_samples(device_ids: List[int]) -> List[dict]:
    samples: List[dict] = []
    base_time = datetime.utcnow()
    for device_id in device_ids:
        samples.extend(
            [
                {
                    "device_id": device_id,
                    "timestamp": base_time - timedelta(minutes=idx * 5),
                    "metric_name": "cpu",
                    "value": random.uniform(28.0, 92.0),
                    "unit": "%",
                    "tags": "performance",
                }
                for idx in range(3)
            ]
        )
        samples.extend(
            [
                {
                    "device_id": device_id,
                    "timestamp": base_time - timedelta(minutes=idx * 5),
                    "metric_name": "memory",
                    "value": random.uniform(34.0, 88.0),
                    "unit": "%",
                    "tags": "performance",
                }
                for idx in range(3)
            ]
        )
    return samples


def _compliance_rules() -> List[dict]:
    return [
        {
            "name": "password-encryption",
            "description": "Ensure password encryption is enabled for management access.",
            "vendor": None,
            "severity": "high",
            "enabled": True,
        },
        {
            "name": "ssh-only-management",
            "description": "Management plane must use SSH only.",
            "vendor": None,
            "severity": "medium",
            "enabled": True,
        },
        {
            "name": "ntp-servers",
            "description": "Devices must have at least one NTP server configured.",
            "vendor": None,
            "severity": "low",
            "enabled": True,
        },
    ]


def _network_links() -> List[dict]:
    return [
        {
            "source_device": "DEL-CORE-01",
            "destination_device": "MUM-EDGE-01",
            "link_type": "mpls",
            "status": "up",
            "bandwidth_mbps": 1000.0,
        },
        {
            "source_device": "DEL-CORE-01",
            "destination_device": "HYD-LEAF-02",
            "link_type": "evpn",
            "status": "up",
            "bandwidth_mbps": 1000.0,
        },
        {
            "source_device": "BLR-FW-01",
            "destination_device": "MUM-EDGE-01",
            "link_type": "internet",
            "status": "warning",
            "bandwidth_mbps": 500.0,
        },
    ]


def seed_database() -> bool:
    create_db()
    with get_session() as session:
        if session.query(Device).count() > 0:
            return True

        devices = [Device(**entry) for entry in _device_samples()]
        session.add_all(devices)
        session.flush()

        device_ids = [device.id for device in devices]
        telemetries = [Telemetry(**entry) for entry in _telemetry_samples(device_ids)]
        session.add_all(telemetries)

        incidents = [Incident(**entry) for entry in _incident_samples()]
        session.add_all(incidents)

        rules = [ComplianceRule(**entry) for entry in _compliance_rules()]
        session.add_all(rules)

        changes = [
            ChangeRequest(
                title="Upgrade MUM-EDGE-01 routing policy",
                status="planning",
                risk="medium",
                implementation_date=(datetime.utcnow() + timedelta(days=2)).isoformat(),
                engineer="netops",
            ),
            ChangeRequest(
                title="BLR-FW-01 HA failover test",
                status="scheduled",
                risk="low",
                implementation_date=(datetime.utcnow() + timedelta(days=5)).isoformat(),
                engineer="security",
            ),
        ]
        session.add_all(changes)

        links = [NetworkLink(**entry) for entry in _network_links()]
        session.add_all(links)

        session.commit()

    return True
