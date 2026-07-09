"""
core/knowledge/parsers
=======================
Universal format parser — turns a file on disk into plain text ready for
chunking/embedding, regardless of source format (PDF, DOCX, JSON, YAML,
XML, CSV, HTML). Plain-text formats (.md/.txt/.cfg/...) don't need a
parser at all and are read directly by the ingestion pipeline.

Each extractor takes a path and returns text, or None/raises if the file
can't be read. A missing optional dependency (pypdf, python-docx, PyYAML,
bs4) raises ImportError, which callers should catch and skip that file
without failing the whole batch.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Dict, Optional, Set

from core.knowledge.parsers import (
    csv_parser,
    docx_parser,
    html_parser,
    pdf_parser,
    structured_parser,
)

logger = logging.getLogger("NetBrain.Knowledge.Parsers")

_EXT_MAP: Dict[str, Callable[[str], Optional[str]]] = {
    ".pdf":  pdf_parser.extract,
    ".docx": docx_parser.extract,
    ".csv":  csv_parser.extract,
    ".html": html_parser.extract,
    ".htm":  html_parser.extract,
    ".json": structured_parser.extract_json,
    ".yaml": structured_parser.extract_yaml,
    ".yml":  structured_parser.extract_yaml,
    ".xml":  structured_parser.extract_xml,
}


def supported_extensions() -> Set[str]:
    """File extensions this package can parse (lowercase, with dot)."""
    return set(_EXT_MAP.keys())


def extract_text(path: str) -> Optional[str]:
    """
    Dispatch to the right extractor by file extension. Returns None if the
    extension is unsupported, the file is empty, or the required optional
    dependency isn't installed (logged, not raised, so batch ingestion
    keeps going).
    """
    ext = os.path.splitext(path)[1].lower()
    fn = _EXT_MAP.get(ext)
    if fn is None:
        return None
    try:
        return fn(path)
    except ImportError as exc:
        logger.warning(f"Parser for '{ext}' unavailable ({exc}) — skipping {path}")
        return None
    except Exception as exc:
        logger.warning(f"Failed to parse {path}: {exc}")
        return None


__all__ = ["extract_text", "supported_extensions"]
