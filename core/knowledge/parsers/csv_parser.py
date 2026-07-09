"""
core/knowledge/parsers/csv_parser.py
=====================================
Flatten a CSV file (exported inventories, ACL tables, VLAN/VRF mappings)
into readable "col=value" lines so row-level facts are embeddable text
rather than opaque delimited data.
"""
from __future__ import annotations

import csv
from typing import Optional


def extract(path: str) -> Optional[str]:
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        lines = []
        for row in reader:
            pairs = [f"{k}={v}" for k, v in row.items() if k and (v or "").strip()]
            if pairs:
                lines.append(", ".join(pairs))
    text = "\n".join(lines)
    return text or None
