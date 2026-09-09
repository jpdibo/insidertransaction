from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


ROOT = "https://www.unternehmensregister.de"


def _search_rows(body: bytes, fallback_date: str | None = None) -> tuple[list[DiscoveredRecord], set[int]]:
    try:
        page = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransportError("Unternehmensregister search response is not UTF-8") from exc
    if "Suchergebnis" not in page or "publicationCategory" not in page:
        raise TransportError("Unternehmensregister search markers missing")
    records = []
    links = list(re.finditer(r'<a\b[^>]*data-testid="normal-pub"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.DOTALL | re.IGNORECASE))
    for index, link in enumerate(links):
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", link.group(2))).split())
        if "Führungsaufgaben wahrnehmen" not in title and "persons discharging managerial responsibilities" not in title.lower():
            continue
        href = html.unescape(link.group(1))
        payload = parse_qs(urlparse(href).query).get("payload", [""])[0]
        following = page[link.end():links[index + 1].start() if index + 1 < len(links) else link.end() + 2000]
        date_match = re.search(r"Datum:\s*(\d{2}\.\d{2}\.\d{4})", html.unescape(re.sub(r"<[^>]+>", " ", following)))
        if not payload or (not date_match and not fallback_date):
            raise TransportError("Unternehmensregister publication identity or date missing")
        published = f"{date_match.group(1)[6:]}-{date_match.group(1)[3:5]}-{date_match.group(1)[:2]}" if date_match else fallback_date
        native_id = "ureg_" + hashlib.sha256(payload.encode("ascii")).hexdigest()[:32]
        records.append(DiscoveredRecord(native_id, f"{ROOT}/de/printView?{urlencode({'payload': payload})}", metadata={"published_date": published}))
    offsets = set()
    for href in re.findall(r'href="([^"]*[?&]from=[^"&]+[^"]*)"', page, re.IGNORECASE):
        try:
            value = int(parse_qs(urlparse(html.unescape(href)).query).get("from", ["0"])[0])
        except ValueError:
            continue
        if value >= 0:
            offsets.add(value)
    return records, offsets


def _job_number(body: bytes) -> str:
    match = re.search(rb'\\?"jobNumber\\?":\\?"([0-9]+)\\?"', body)
    if not match:
        raise TransportError("Unternehmensregister stable publication identity missing")
    return match.group(1).decode("ascii")


class UnternehmensregisterAdapter:
    version = "unternehmensregister-v2"
    host = "www.unternehmensregister.de"

    def __init__(self, *, timeout: float = 30, retries: int = 2):
        self.client = HttpClient(timeout=timeout, retries=retries)
        self._prefetched: dict[str, bytes] = {}

    def _token(self) -> str:
        response = self.client.request(f"{ROOT}/api/search-token", expected_host=self.host)
        try:
            token = json.loads(response.body)["token"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise TransportError("Unternehmensregister search-token contract changed") from exc
        if not isinstance(token, str) or len(token) < 40:
            raise TransportError("Unternehmensregister search token missing")
        return token

    def probe(self) -> dict[str, str]:
        return {"status": "ok", "token": "available" if self._token() else "missing"}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None = None) -> list[DiscoveredRecord]:
        del cursor
        start, end = date.fromisoformat(interval_from), date.fromisoformat(interval_to)
        discovered: dict[str, DiscoveredRecord] = {}
        while start <= end:
            token = self._token()
            base = {"companyName": "", "publicationCategory": "80", "sourceDateFrom": start.isoformat(),
                    "sourceDateTo": start.isoformat(), "drilldownFilter": "21", "companyFederalState": "",
                    "searchToken": token, "formType": "CAPITAL_MARKET"}
            pending, visited = {0}, set()
            while pending:
                offset = min(pending)
                pending.remove(offset)
                if offset in visited:
                    continue
                query = dict(base)
                if offset:
                    query["from"] = str(offset)
                body = self.client.request(f"{ROOT}/de/suche?{urlencode(query)}", expected_host=self.host).body
                rows, offsets = _search_rows(body, start.isoformat())
                for record in rows:
                    body = self.fetch(record)
                    native_id = "ureg_job_" + _job_number(body)
                    stable_record = DiscoveredRecord(native_id, record.url, metadata=record.metadata)
                    if native_id in discovered and discovered[native_id].url != stable_record.url:
                        raise TransportError(f"Unternehmensregister duplicate job number: {native_id}")
                    discovered[native_id] = stable_record
                    self._prefetched[native_id] = body
                visited.add(offset)
                pending.update(value for value in offsets if value not in visited)
                if len(visited) > 1000:
                    raise TransportError("Unternehmensregister pagination exceeded safety limit")
            start += timedelta(days=1)
        return sorted(discovered.values(), key=lambda record: record.native_record_id)

    def fetch(self, record: DiscoveredRecord) -> bytes:
        prefetched = self._prefetched.pop(record.native_record_id, None)
        if prefetched is not None:
            return prefetched
        body = self.client.request(record.url, expected_host=self.host).body
        visible = html.unescape(body.decode("utf-8", errors="strict"))
        if "Angaben zum Geschäft" not in visible and "Details of the transaction" not in visible:
            raise TransportError("Unternehmensregister PDMR detail markers missing")
        return body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        return []
