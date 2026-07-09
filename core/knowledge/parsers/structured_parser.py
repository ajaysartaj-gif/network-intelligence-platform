"""
core/knowledge/parsers/structured_parser.py
============================================
Flatten JSON / YAML / XML (YANG-model exports, OpenConfig payloads,
structured configs, REST API responses) into readable "path: value" lines.
Embedding a flattened path preserves the semantic structure (e.g.
"interfaces.Gi0/1.mtu: 1500") that a raw dump of braces/tags would bury.
"""
from __future__ import annotations

import json
from typing import Any, List, Optional


def _flatten(obj: Any, prefix: str, out: List[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten(v, f"{prefix}[{i}]", out)
    else:
        if obj is not None and str(obj).strip() != "":
            out.append(f"{prefix}: {obj}")


def _flatten_to_text(obj: Any) -> Optional[str]:
    lines: List[str] = []
    _flatten(obj, "", lines)
    return "\n".join(lines) or None


def extract_json(path: str) -> Optional[str]:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = json.load(f)
    return _flatten_to_text(data)


def extract_yaml(path: str) -> Optional[str]:
    import yaml  # local import: optional dependency (PyYAML)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        data = yaml.safe_load(f)
    return _flatten_to_text(data)


def _elem_to_dict(elem) -> Any:
    children = list(elem)
    node: dict = {}
    if elem.attrib:
        node.update({f"@{k}": v for k, v in elem.attrib.items()})
    if children:
        for child in children:
            child_val = _elem_to_dict(child)
            if child.tag in node:
                existing = node[child.tag]
                if isinstance(existing, list):
                    existing.append(child_val)
                else:
                    node[child.tag] = [existing, child_val]
            else:
                node[child.tag] = child_val
        text = (elem.text or "").strip()
        if text:
            node["#text"] = text
        return node
    text = (elem.text or "").strip()
    if node:
        if text:
            node["#text"] = text
        return node
    return text


def extract_xml(path: str) -> Optional[str]:
    import xml.etree.ElementTree as ET  # stdlib

    tree = ET.parse(path)
    root = tree.getroot()
    data = {root.tag: _elem_to_dict(root)}
    return _flatten_to_text(data)
