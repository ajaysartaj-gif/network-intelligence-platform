"""
core/knowledge/parsers/docx_parser.py
======================================
Extract plain text from a Word document — paragraphs and table cells, in
document order — so vendor config guides / customer docs shared as .docx
ingest the same as any other document.
"""
from __future__ import annotations

from typing import Optional


def extract(path: str) -> Optional[str]:
    from docx import Document  # local import: optional dependency (python-docx)

    doc = Document(path)
    parts = []
    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text.strip())
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = "\n".join(parts)
    return text or None
