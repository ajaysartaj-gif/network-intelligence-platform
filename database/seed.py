from database.database import SessionLocal, engine
from database.models import *

Base.metadata.create_all(bind=engine)

db = SessionLocal()

# =========================================================
# DEVICES
# =========================================================

devices = [

    Device(
        hostname="DEL-CORE-01",
        ip_address="10.1.1.1",
        vendor="Cisco",
        model="ASR1001-X",
        role="Core Router",
        site="Delhi DC",
        os_version="IOS-XE 17.9",
        status="online",
        latitude=28.6139,
        longitude=77.2090,
    ),

    Device(
        hostname="MUM-CORE-01",
        ip_address="10.2.1.1",
        vendor="Juniper",
        model="MX480",
        role="Core Router",
        site="Mumbai DC",
        os_version="Junos 22.1",
        status="online",
        latitude=19.0760,
        longitude=72.8777,
    ),

    Device(
        hostname="BLR-FW-01",
        ip_address="10.3.1.1",
        vendor="Palo Alto",
        model="PA-5220",
        role="Firewall",
        site="Bangalore DC",
        os_version="PAN-OS 11",
        status="degraded",
        latitude=12.9716,
        longitude=77.5946,
    ),
]

db.add_all(devices)

# =========================================================
# BGP PEERS
# =========================================================

bgp = [

    BGPPeer(
        local_device="DEL-CORE-01",
        peer_ip="192.168.100.1",
        peer_asn="65002",
        state="Established",
        prefixes_received=850000,
        flaps=0,
    ),

    BGPPeer(
        local_device="MUM-CORE-01",
        peer_ip="192.168.200.1",
        peer_asn="65003",
        state="Idle",
        prefixes_received=0,
        flaps=17,
    ),
]

db.add_all(bgp)

# =========================================================
# INCIDENTS
# =========================================================

incidents = [

    Incident(
        title="BGP Flapping Mumbai WAN",
        severity="critical",
        status="active",
        assigned_to="Ajay",
        affected_service="MPLS WAN",
        description="Repeated BGP resets observed on WAN edge router.",
    ),

    Incident(
        title="High CPU Firewall",
        severity="major",
        status="investigating",
        assigned_to="NOC Team",
        affected_service="Internet Edge",
        description="Firewall CPU utilization above 90%.",
    ),
]

db.add_all(incidents)

# =========================================================
# ALERTS
# =========================================================

alerts = [

    Alert(
        device="MUM-CORE-01",
        alert_type="BGP",
        severity="critical",
        message="BGP peer down",
    ),

    Alert(
        device="BLR-FW-01",
        alert_type="CPU",
        severity="major",
        message="CPU exceeded 95%",
    ),
]

db.add_all(alerts)

# =========================================================
# KNOWLEDGE BASE
# =========================================================

docs = [

    KnowledgeDocument(
        title="BGP Troubleshooting Guide",
        vendor="Cisco",
        protocol="BGP",
        content=\"\"\"
Check BGP neighbor state.
Verify reachability.
Validate ASN configuration.
Inspect route advertisements.
Check flap counters.
\"\"\",
    ),

    KnowledgeDocument(
        title="Firewall High CPU RCA",
        vendor="Palo Alto",
        protocol="Security",
        content=\"\"\"
Inspect session table.
Review threat logs.
Check SSL decryption load.
Validate policy hit count.
\"\"\",
    ),
]

db.add_all(docs)

db.commit()

print(\"Database seeded successfully\")
