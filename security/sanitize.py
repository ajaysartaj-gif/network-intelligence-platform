"""Input/output sanitization to prevent XSS."""

import html
import re
from typing import Optional


def sanitize_markdown(text: str) -> str:
    """Escape HTML in markdown to prevent XSS."""
    if not text:
        return text

    # Escape HTML tags
    text = html.escape(text)

    # Preserve safe markdown syntax
    text = text.replace("&lt;strong&gt;", "<strong>")
    text = text.replace("&lt;/strong&gt;", "</strong>")
    text = text.replace("&lt;em&gt;", "<em>")
    text = text.replace("&lt;/em&gt;", "</em>")

    return text


def sanitize_hostname(hostname: str) -> str:
    """Validate and sanitize hostname."""
    if not hostname or len(hostname) > 128:
        raise ValueError("Invalid hostname length")

    if not re.match(r"^[A-Z0-9][-A-Z0-9._]*[A-Z0-9]$", hostname, re.I):
        raise ValueError(f"Invalid hostname format: {hostname}")

    return hostname


def sanitize_ip(ip: str) -> str:
    """Validate IPv4 address."""
    parts = ip.split(".")
    if len(parts) != 4:
        raise ValueError(f"Invalid IP: {ip}")

    for part in parts:
        try:
            n = int(part)
            if n < 0 or n > 255:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError(f"Invalid IP octet: {part}")

    return ip


def sanitize_vlan(vlan_id: str) -> int:
    """Validate VLAN ID (1-4094)."""
    try:
        vlan = int(vlan_id)
        if vlan < 1 or vlan > 4094:
            raise ValueError()
        return vlan
    except (ValueError, TypeError):
        raise ValueError(f"Invalid VLAN ID: {vlan_id}")
