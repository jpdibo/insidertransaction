from __future__ import annotations

import json
from pathlib import Path

from .base import DiscoveredRecord


class FixtureAdapter:
    version = "fixture-v1"

    def __init__(self, root: Path):
        self.root = root

    def probe(self) -> dict[str, str]:
        return {"status": "ok" if self.root.is_dir() else "missing", "path": str(self.root)}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None) -> list[DiscoveredRecord]:
        records = []
        for path in sorted(self.root.glob("*.json"), key=lambda item: item.name):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "source" in payload:
                source = payload["source"]
                native_id = source["native_record_id"]
                url = source["url"]
                published = source.get("published_at", source.get("published_date", ""))[:10]
            else:
                message = payload["data"]["message"]
                native_id = str(message["messageId"])
                url = f"https://newsweb.oslobors.no/message/{native_id}"
                published = message["publishedTime"][:10]
            if interval_from <= published <= interval_to:
                records.append(DiscoveredRecord(native_id, url, path))
        return records

    def fetch(self, record: DiscoveredRecord) -> bytes:
        if record.path is None:
            raise ValueError("fixture record has no local path")
        return record.path.read_bytes()

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        return []
