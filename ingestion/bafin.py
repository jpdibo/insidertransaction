from __future__ import annotations

import html
import re
import time
from datetime import date, datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


ROOT = "https://portal.mvp.bafin.de/database/DealingsInfo/"


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def _table(page: str, table_id: str) -> str | None:
    match = re.search(rf'<table\b[^>]*\bid=["\']{re.escape(table_id)}["\'][^>]*>(.*?)</table>', page,
                      re.DOTALL | re.IGNORECASE)
    return match.group(1) if match else None


def _search_rows(body: bytes) -> tuple[list[dict[str, str]], list[str]]:
    try:
        page = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransportError("BaFin search response is not UTF-8") from exc
    visible = html.unescape(page)
    if "Auswahl Emittent" not in visible or 'id="sucheForm"' not in page:
        raise TransportError("BaFin search markers missing; possible challenge or layout change")
    table = _table(page, "emittent")
    if table is None:
        if "Keine Ergebnisse" in visible:
            return [], []
        raise TransportError("BaFin search table missing")
    tbody = re.search(r"<tbody>(.*?)</tbody>", table, re.DOTALL | re.IGNORECASE)
    if not tbody:
        raise TransportError("BaFin search table body missing")
    rows = []
    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.DOTALL | re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE)
        link = re.search(r'href=["\']([^"\']*ergebnisListe\.do[^"\']+)["\']', row_html, re.IGNORECASE)
        if len(cells) != 10 or not link:
            raise TransportError("BaFin search result row schema changed")
        values = [_text(cell) for cell in cells]
        query = parse_qs(urlparse(html.unescape(link.group(1))).query)
        if not query.get("meldungId") or not query.get("emittentBafinId"):
            raise TransportError("BaFin notification identity missing")
        rows.append({
            "issuer": values[0], "issuer_bafin_id": values[1], "isin": values[2], "party": values[3],
            "position": values[4], "instrument": values[5], "nature": values[6], "trade_date": values[7],
            "venue": values[8], "activated_at": values[9], "meldung_id": query["meldungId"][0],
            "published_date": datetime.strptime(values[9][:10], "%d.%m.%Y").date().isoformat(),
            "party_list_url": urljoin(ROOT, html.unescape(link.group(1))),
        })
    pagination = re.search(r'<div\b[^>]*class=["\'][^"\']*pagelinks[^"\']*["\'][^>]*>(.*?)</div>', page,
                           re.DOTALL | re.IGNORECASE)
    links = re.findall(r'href=["\']([^"\']*sucheForm\.do[^"\']+)["\']', pagination.group(1), re.IGNORECASE) if pagination else []
    return rows, [urljoin(ROOT, html.unescape(link)) for link in links]


def _party_detail_links(body: bytes, expected_meldung_id: str, expected_issuer_id: str) -> list[tuple[str, str]]:
    try:
        page = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransportError("BaFin party response is not UTF-8") from exc
    if "Auswahl Meldepflichtiger" not in html.unescape(page):
        raise TransportError("BaFin party-list markers missing")
    table = _table(page, "meldepflichtiger")
    if table is None:
        raise TransportError("BaFin party-list table missing")
    links = []
    for href in re.findall(r'href=["\']([^"\']*transaktionListe\.do[^"\']+)["\']', table, re.IGNORECASE):
        decoded = html.unescape(href)
        query = parse_qs(urlparse(decoded).query)
        if query.get("meldungId") != [expected_meldung_id] or query.get("emittentBafinId") != [expected_issuer_id] or not query.get("meldepflichtigerId"):
            raise TransportError("BaFin detail identity mismatch")
        clean_query = urlencode({
            "cmd": "loadTransaktionenAction", "meldungId": expected_meldung_id,
            "emittentBafinId": expected_issuer_id, "meldepflichtigerId": query["meldepflichtigerId"][0],
        })
        links.append((query["meldepflichtigerId"][0], f"{ROOT}transaktionListe.do?{clean_query}"))
    if not links:
        raise TransportError("BaFin party-list contains no transaction detail")
    return links


class BafinAdapter:
    version = "bafin-live-v1"
    host = "portal.mvp.bafin.de"

    def __init__(self, *, timeout: float = 20, retries: int = 2, request_delay: float = 0.2):
        self.client = HttpClient(timeout=timeout, retries=retries)
        self.request_delay = request_delay

    @staticmethod
    def _date(value: str) -> str:
        return date.fromisoformat(value).strftime("%d.%m.%Y")

    def _search_url(self, interval_from: str, interval_to: str) -> str:
        return f"{ROOT}sucheForm.do?{urlencode({'zeitraum': '3', 'zeitraumVon': self._date(interval_from), 'zeitraumBis': self._date(interval_to), 'emittentButton': 'Suche Emittent'})}"

    def probe(self) -> dict[str, str]:
        today = date.today().isoformat()
        response = self.client.request(self._search_url(today, today), expected_host=self.host)
        rows, _ = _search_rows(response.body)
        return {"status": "ok", "checked_date": today, "result_rows": str(len(rows))}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None) -> list[DiscoveredRecord]:
        pending = [self._search_url(interval_from, interval_to)]
        visited: set[str] = set()
        notifications: dict[str, dict[str, str]] = {}
        while pending:
            url = pending.pop(0)
            if url in visited:
                continue
            visited.add(url)
            response = self.client.request(url, expected_host=self.host)
            rows, page_links = _search_rows(response.body)
            for row in rows:
                key = row["meldung_id"]
                previous = notifications.get(key)
                if previous and previous != row:
                    raise TransportError(f"BaFin notification {key} has conflicting search rows")
                notifications[key] = row
            pending.extend(link for link in page_links if link not in visited)

        records = []
        for melding_id, row in sorted(notifications.items(), key=lambda item: (item[1]["activated_at"], item[0])):
            time.sleep(self.request_delay)
            party_page = self.client.request(row["party_list_url"], expected_host=self.host)
            details = _party_detail_links(party_page.body, melding_id, row["issuer_bafin_id"])
            for party_id, detail_url in details:
                metadata = dict(row)
                metadata.update({"party_id": party_id, "url": detail_url})
                records.append(DiscoveredRecord(f"{melding_id}:{party_id}", detail_url, metadata=metadata))
        return records

    def fetch(self, record: DiscoveredRecord) -> bytes:
        time.sleep(self.request_delay)
        response = self.client.request(record.url, expected_host=self.host)
        page = response.body.decode("utf-8", errors="strict")
        visible = html.unescape(page)
        if "Angaben zum Geschäft/zu den Geschäften" not in visible or 'id="transaktion"' not in page:
            raise TransportError("BaFin transaction-detail markers missing; possible challenge or layout change")
        melding_id, party_id = record.native_record_id.split(":", 1)
        if f"meldungId={melding_id}" not in visible or f"meldepflichtigerId={party_id}" not in visible:
            raise TransportError("BaFin transaction-detail identity mismatch")
        return response.body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        return []
