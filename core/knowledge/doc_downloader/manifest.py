"""
core/knowledge/doc_downloader/manifest.py
==========================================
Idempotent, JSON-file-backed record of every document already downloaded —
same "safe to call on every run, content-hash dedup" contract already used
throughout this codebase (core.troubleshooting.strategies.live_retriever.
ensure_corpus_ingested, core.knowledge.enterprise.pipelines.
ensure_general_corpus_ingested). Keyed by source_url, not local path, since
a source can legitimately be re-classified/moved without re-downloading it.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass
class ManifestEntry:
    source_url: str
    vendor: str
    doc_type: str
    title: str
    local_path: str
    sha256: str
    fetched_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DownloadManifest:
    """One manifest file per root download directory (pdf_downloads/.manifest.json)."""

    def __init__(self, root: str):
        self.root = root
        self.path = os.path.join(root, ".manifest.json")
        self._entries: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._entries = json.load(f) or {}
            except Exception:
                self._entries = {}

    def _save(self) -> None:
        os.makedirs(self.root, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._entries, f, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def has(self, source_url: str) -> bool:
        return source_url in self._entries

    def get(self, source_url: str) -> Optional[ManifestEntry]:
        raw = self._entries.get(source_url)
        return ManifestEntry(**raw) if raw else None

    def record(self, entry: ManifestEntry) -> None:
        self._entries[entry.source_url] = asdict(entry)
        self._save()

    def __len__(self) -> int:
        return len(self._entries)

    def by_vendor(self, vendor: str) -> Dict[str, dict]:
        return {k: v for k, v in self._entries.items() if v.get("vendor") == vendor}
