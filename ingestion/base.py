from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class DiscoveredRecord:
    native_record_id: str
    url: str
    path: Path | None = None
    metadata: dict[str, Any] | None = None


class SourceAdapter(Protocol):
    version: str

    def probe(self) -> dict[str, str]: ...
    def discover(self, interval_from: str, interval_to: str, cursor: str | None) -> list[DiscoveredRecord]: ...
    def fetch(self, record: DiscoveredRecord) -> bytes: ...
    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]: ...
