from __future__ import annotations

import json
from datetime import date, timedelta
from urllib.parse import quote, urlencode

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


API = "https://bdif.amf-france.org/back/api/v1"


def _search_payload(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportError("AMF search response is not valid JSON") from exc
    if not isinstance(payload.get("result"), list) or not isinstance(payload.get("total"), int):
        raise TransportError("AMF search response contract changed")
    return payload


class AmfAdapter:
    version = "amf-bdif-v1"
    host = "bdif.amf-france.org"

    def __init__(self, *, timeout: float = 30, retries: int = 2):
        self.client = HttpClient(timeout=timeout, retries=retries)

    def probe(self) -> dict[str, str]:
        url = f"{API}/informations?TypesInformation=DD&From=0&Size=1"
        payload = _search_payload(self.client.request(url, expected_host=self.host).body)
        return {"status": "ok", "total_capped": str(payload["total"])}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None = None) -> list[DiscoveredRecord]:
        del cursor
        start = date.fromisoformat(interval_from)
        end = date.fromisoformat(interval_to)
        records: dict[str, DiscoveredRecord] = {}
        while start <= end:
            date_from = f"{start.isoformat()}T00:00:00.000Z"
            date_to = f"{start.isoformat()}T23:59:59.999Z"
            offset = 0
            expected_total: int | None = None
            while True:
                query = urlencode({"DateDebut": date_from, "DateFin": date_to, "TypesInformation": "DD", "From": offset, "Size": 100})
                payload = _search_payload(self.client.request(f"{API}/informations?{query}", expected_host=self.host).body)
                if payload["total"] >= 10000:
                    raise TransportError(f"AMF single-day result cap reached for {start.isoformat()}")
                if expected_total is None:
                    expected_total = payload["total"]
                elif payload["total"] != expected_total:
                    raise TransportError(f"AMF result count changed during pagination for {start.isoformat()}")
                for item in payload["result"]:
                    number = str(item.get("numero") or "")
                    documents = [document for document in item.get("documents", []) if document.get("accessible") and str(document.get("path", "")).lower().endswith(".pdf")]
                    if not number or not documents:
                        raise TransportError("AMF disclosure identity or accessible PDF missing")
                    path = str(documents[0]["path"])
                    url = f"{API}/documents/{'/'.join(quote(part, safe='') for part in path.split('/'))}"
                    records[number] = DiscoveredRecord(number, url, metadata={"published_date": str(item.get("datePublication") or "")[:10]})
                offset += len(payload["result"])
                if offset >= expected_total:
                    break
                if not payload["result"]:
                    raise TransportError(f"AMF pagination ended early for {start.isoformat()}")
            start += timedelta(days=1)
        return sorted(records.values(), key=lambda record: record.native_record_id)

    def fetch(self, record: DiscoveredRecord) -> bytes:
        body = self.client.request(record.url, expected_host=self.host).body
        if not body.startswith(b"%PDF-"):
            raise TransportError("AMF document is not a PDF")
        return body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        return []
