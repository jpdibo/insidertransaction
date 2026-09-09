from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


HOST = "appft.gold.extension.gopublic.dk"
ROOT = f"https://{HOST}/api/9217fa13-5d9a-46c6-9921-69ee7e6cfaf6"
ATTACHMENT_HOST = "saegressprod.blob.core.windows.net"


def _json(body: bytes, marker: str) -> dict:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportError(f"Denmark OAM {marker} response is not JSON") from exc
    if not isinstance(payload, dict):
        raise TransportError(f"Denmark OAM {marker} schema changed")
    return payload


class DenmarkOamAdapter:
    version = "denmark-oam-v1"
    host = HOST

    def __init__(self, *, timeout: float = 30, retries: int = 2):
        self.client = HttpClient(timeout=timeout, retries=retries)

    def probe(self) -> dict[str, str]:
        return {"status": "ok", "search": "available" if self.discover("2026-09-08", "2026-09-08", None) else "empty"}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None = None) -> list[DiscoveredRecord]:
        del cursor
        records: dict[str, DiscoveredRecord] = {}
        page = 1
        while True:
            request = {"query": "", "filters": [
                {"type": "dropdown", "key": "CategoryFilter", "options": ["RelatedPartyTransactions"]},
                {"type": "daterange", "key": "PublicationDateFilter", "min": interval_from, "max": interval_to},
            ], "page": page, "pageSize": 100}
            response = self.client.request(f"{ROOT}/search", method="POST", expected_host=self.host,
                                           json_body=request, headers={"Accept-Language": "en-US"})
            payload = _json(response.body, "search")
            paging, data = payload.get("paging"), payload.get("data")
            rows = data.get("rows") if isinstance(data, dict) else None
            if not isinstance(paging, dict) or not isinstance(rows, list) or paging.get("page") != page:
                raise TransportError("Denmark OAM search paging schema changed")
            for row in rows:
                native_id = str(row.get("id", ""))
                published_raw = row.get("PublicationDateColumn", "")
                if not native_id.isdigit() or not published_raw:
                    raise TransportError("Denmark OAM announcement identity or date missing")
                published_at = datetime.strptime(published_raw, "%d-%m-%Y %H:%M:%S").isoformat()
                record = DiscoveredRecord(native_id, f"{ROOT}/details/{native_id}", metadata={"published_at": published_at})
                if native_id in records and records[native_id] != record:
                    raise TransportError(f"Denmark OAM conflicting duplicate announcement: {native_id}")
                records[native_id] = record
            total_count = int(paging.get("totalCount", -1))
            total_pages = int(paging.get("totalPages", -1))
            if total_count < 0 or total_pages < 1 or page > total_pages:
                raise TransportError("Denmark OAM search count invalid")
            if page == total_pages:
                if len(records) != total_count:
                    raise TransportError(f"Denmark OAM completeness mismatch: expected {total_count}, got {len(records)}")
                break
            page += 1
        return sorted(records.values(), key=lambda item: item.native_record_id)

    def fetch(self, record: DiscoveredRecord) -> bytes:
        body = self.client.request(record.url, expected_host=self.host, headers={"Accept-Language": "en-US"}).body
        payload = _json(body, "detail")
        if not payload.get("sections") or record.native_record_id not in body.decode("utf-8", errors="replace"):
            raise TransportError("Denmark OAM detail markers or identity missing")
        return body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        payload = _json(data, "detail")
        attachments = []
        for section in payload.get("sections", []):
            for element in section.get("elements", []):
                value = element.get("value", {})
                if value.get("type") != "link" or not value.get("url"):
                    continue
                url = value["url"]
                if urlparse(url).hostname != ATTACHMENT_HOST:
                    raise TransportError(f"Denmark OAM unexpected attachment host: {url}")
                identity = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
                attachments.append(DiscoveredRecord(f"{record.native_record_id}:attachment:{identity}", url,
                                                     metadata={"filename": value.get("title") or PurePosixPath(urlparse(url).path).name}))
        if not attachments:
            raise TransportError(f"Denmark OAM announcement has no documents: {record.native_record_id}")
        return attachments

    def fetch_attachment(self, record: DiscoveredRecord) -> tuple[bytes, str, str]:
        response = self.client.request(record.url, expected_host=ATTACHMENT_HOST)
        filename = str((record.metadata or {}).get("filename", "attachment.bin"))
        lower = filename.lower()
        if lower.endswith(".pdf"):
            if not response.body.startswith(b"%PDF-"):
                raise TransportError("Denmark OAM PDF attachment has invalid magic bytes")
            mime = "application/pdf"
        elif lower.endswith((".html", ".htm")):
            if not response.body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise TransportError("Denmark OAM HTML attachment has invalid markers")
            mime = "text/html"
        else:
            mime = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        if len(response.body) > 20 * 1024 * 1024:
            raise TransportError("Denmark OAM attachment exceeds 20 MiB limit")
        return response.body, mime, filename
