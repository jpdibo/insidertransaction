from __future__ import annotations

import json
from datetime import date
from urllib.parse import urlencode

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


ROOT = "https://www.ser-ag.com/sheldon/management_transactions/v1/overview.json"


def _payload(body: bytes) -> dict:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportError("SIX response is not valid JSON") from exc
    if value.get("status") != "Ok" or not isinstance(value.get("itemList"), list) or not isinstance(value.get("totalCount"), int):
        raise TransportError("SIX response contract changed")
    return value


class SixAdapter:
    version = "six-management-v1"
    host = "www.ser-ag.com"

    def __init__(self, *, timeout: float = 20, retries: int = 2):
        self.client = HttpClient(timeout=timeout, retries=retries)

    @staticmethod
    def _compact_date(value: str) -> str:
        return date.fromisoformat(value).strftime("%Y%m%d")

    def probe(self) -> dict[str, str]:
        response = self.client.request(f"{ROOT}?pageSize=1&pageNumber=0", expected_host=self.host)
        payload = _payload(response.body)
        return {"status": "ok", "total": str(payload["totalCount"])}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None = None) -> list[DiscoveredRecord]:
        del cursor
        page_size = 100
        page = 0
        discovered: dict[str, DiscoveredRecord] = {}
        expected_total: int | None = None
        while True:
            query = urlencode({
                "pageSize": page_size, "pageNumber": page, "sortAttribute": "byDate",
                "fromDate": self._compact_date(interval_from), "toDate": self._compact_date(interval_to),
            })
            payload = _payload(self.client.request(f"{ROOT}?{query}", expected_host=self.host).body)
            if expected_total is None:
                expected_total = payload["totalCount"]
            elif payload["totalCount"] != expected_total:
                raise TransportError("SIX result count changed during pagination")
            for item in payload["itemList"]:
                notification_id = str(item.get("notificationId") or "")
                transaction_date = str(item.get("transactionDate") or "")
                if not notification_id or len(transaction_date) != 8:
                    raise TransportError("SIX notification identity or transaction date missing")
                url = f"{ROOT}?{urlencode({'notificationId': notification_id})}"
                discovered[notification_id] = DiscoveredRecord(
                    notification_id, url, metadata={"published_date": f"{transaction_date[:4]}-{transaction_date[4:6]}-{transaction_date[6:]}"}
                )
            if len(discovered) >= expected_total or not payload["itemList"]:
                break
            page += 1
        if len(discovered) != expected_total:
            raise TransportError(f"SIX pagination incomplete: expected {expected_total}, found {len(discovered)}")
        return sorted(discovered.values(), key=lambda record: record.native_record_id)

    def fetch(self, record: DiscoveredRecord) -> bytes:
        response = self.client.request(record.url, expected_host=self.host)
        payload = _payload(response.body)
        if payload["totalCount"] != 1 or len(payload["itemList"]) != 1 or str(payload["itemList"][0].get("notificationId")) != record.native_record_id:
            raise TransportError("SIX detail identity mismatch")
        return response.body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        return []
