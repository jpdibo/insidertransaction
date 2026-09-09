from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import urlencode

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


class NewsWebAdapter:
    version = "newsweb-live-v1"
    host = "api3.oslo.oslobors.no"
    base = f"https://{host}/v1/newsreader"

    def __init__(self, *, timeout: float = 20, retries: int = 2):
        self.client = HttpClient(timeout=timeout, retries=retries)

    def probe(self) -> dict[str, str]:
        today = date.today().isoformat()
        self._search(today, today)
        return {"status": "ok", "checked_date": today}

    def _search(self, interval_from: str, interval_to: str) -> dict:
        query = urlencode({
            "category": "1102", "issuer": "", "fromDate": interval_from,
            "toDate": interval_to, "market": "", "messageTitle": "",
        })
        payload = self.client.json(f"{self.base}/list?{query}", method="POST", expected_host=self.host)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("messages"), list) or not isinstance(data.get("overflow"), bool):
            raise TransportError("NewsWeb list schema changed")
        return data

    def _complete_search(self, interval_from: date, interval_to: date) -> list[dict]:
        data = self._search(interval_from.isoformat(), interval_to.isoformat())
        if not data["overflow"]:
            return data["messages"]
        if interval_from == interval_to:
            raise TransportError(f"NewsWeb single-day result overflow on {interval_from}; cannot prove completeness")
        midpoint = interval_from + timedelta(days=(interval_to - interval_from).days // 2)
        return self._complete_search(interval_from, midpoint) + self._complete_search(midpoint + timedelta(days=1), interval_to)

    def discover(self, interval_from: str, interval_to: str, cursor: str | None) -> list[DiscoveredRecord]:
        messages = self._complete_search(date.fromisoformat(interval_from), date.fromisoformat(interval_to))
        by_id: dict[int, dict] = {}
        for message in messages:
            message_id = message.get("messageId")
            if not isinstance(message_id, int) or not message.get("publishedTime"):
                raise TransportError("NewsWeb list item schema changed")
            by_id[message_id] = message
        return [
            DiscoveredRecord(str(message_id), f"https://newsweb.oslobors.no/message/{message_id}", metadata=message)
            for message_id, message in sorted(by_id.items(), key=lambda item: (item[1]["publishedTime"], item[0]))
        ]

    def fetch(self, record: DiscoveredRecord) -> bytes:
        query = urlencode({"messageId": record.native_record_id})
        response = self.client.request(f"{self.base}/message?{query}", method="POST", expected_host=self.host)
        payload = self.client.parse_json(response)
        message = payload.get("data", {}).get("message")
        if not isinstance(message, dict) or str(message.get("messageId")) != record.native_record_id:
            raise TransportError("NewsWeb message schema or identity mismatch")
        if message.get("numbAttachments") != len(message.get("attachments", [])):
            raise TransportError("NewsWeb attachment count mismatch")
        return response.body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        message = json.loads(data)["data"]["message"]
        return [DiscoveredRecord(
            f"{record.native_record_id}:attachment:{item['id']}",
            f"{self.base}/attachment?{urlencode({'messageId': record.native_record_id, 'attachmentId': item['id']})}",
            metadata={"message_id": record.native_record_id, "attachment_id": item["id"], "filename": item["name"]},
        ) for item in message["attachments"]]

    def fetch_attachment(self, record: DiscoveredRecord) -> tuple[bytes, str, str]:
        response = self.client.request(record.url, method="GET", expected_host=self.host)
        filename = str((record.metadata or {}).get("filename", "attachment.bin"))
        if len(response.body) > 20 * 1024 * 1024:
            raise TransportError("NewsWeb attachment exceeds 20 MiB limit")
        if filename.lower().endswith(".pdf"):
            if not response.body.startswith(b"%PDF-"):
                raise TransportError("NewsWeb PDF attachment has invalid magic bytes")
            mime = "application/pdf"
        else:
            if response.body.lstrip().lower().startswith((b"<!doctype html", b"<html")):
                raise TransportError("NewsWeb attachment is an HTML error/challenge page")
            mime = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        return response.body, mime, filename
