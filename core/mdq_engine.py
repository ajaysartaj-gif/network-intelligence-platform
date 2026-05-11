from dataclasses import dataclass
from typing import List


@dataclass
class DeviceResult:
    hostname: str
    ip: str
    status: str
    output: str
    vendor: str = "Cisco"
    role: str = "Router"
    site: str = "HQ"
    command: str = "show version"


NETMIKO_OK = False


def run_query(query: str, devices=None) -> List[DeviceResult]:

    if devices is None:
        devices = []

    results = []

    for device in devices:

        results.append(
            DeviceResult(
                hostname=device.get("hostname", "unknown"),
                ip=device.get("ip", "0.0.0.0"),
                status="ok",
                output=f"Simulated output for query: {query}",
                vendor=device.get("vendor", "Cisco"),
                role=device.get("role", "Router"),
                site=device.get("site", "HQ"),
                command=query,
            )
        )

    return results


def build_synthesis_prompt(query: str, results: List[DeviceResult]) -> str:

    device_sections = []

    for r in results:

        section = (
            f"Device: {r.hostname}\n"
            f"Status: {r.status}\n"
            f"{r.output}"
        )

        device_sections.append(section)

    device_context = "\n\n".join(device_sections)

    ok_count = sum(
        1 for r in results
        if r.status == "ok"
    )

    return (
        f'Multi-device query: "{query}"\n'
        f'{len(results)} devices queried '
        f'({ok_count} successful):\n\n'
        f'{device_context}'
    )
