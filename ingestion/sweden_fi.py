from __future__ import annotations

import html
import math
import re
import time
from datetime import date, timedelta
from urllib.parse import urlencode, urljoin

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def _search_rows(body: bytes) -> tuple[int, list[dict]]:
    try:
        page = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TransportError("FI search response is not UTF-8") from exc
    visible = html.unescape(page)
    if "Transaktionsdatum" not in visible or "badge badge-info" not in page:
        raise TransportError("FI search response markers missing; possible challenge or layout change")
    count_match = re.search(r'class="badge badge-info">\s*([\d ]+)\s*</span>', page)
    if not count_match:
        raise TransportError("FI search result count missing")
    total = int(count_match.group(1).replace(" ", ""))
    if total and "Rapportsammanst" not in visible:
        raise TransportError("FI result links missing; possible challenge or layout change")
    body_match = re.search(r"<tbody>(.*?)</tbody>", page, re.DOTALL | re.IGNORECASE)
    rows = []
    if body_match:
        for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", body_match.group(1), re.DOTALL | re.IGNORECASE):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE)
            link = re.search(r'href="([^"]*Rapportsammanst[^\"]+)"', row_html, re.IGNORECASE)
            if len(cells) != 16 or not link:
                raise TransportError("FI result row schema changed")
            values = [_text(cell) for cell in cells]
            report_match = re.search(r"/Index/([A-Z0-9]+-\d+)", html.unescape(link.group(1)), re.IGNORECASE)
            if not report_match:
                raise TransportError("FI result detail identity missing")
            rows.append({
                "report_version": report_match.group(1).upper(), "href": html.unescape(link.group(1)),
                "published_date": values[0], "issuer": values[1], "pdmr": values[2], "role": values[3],
                "is_pca": values[4] == "Ja", "nature": values[5], "instrument": values[6],
                "instrument_type": values[7], "isin": values[8], "trade_date": values[9],
                "quantity": values[10], "quantity_unit": values[11], "price": values[12],
                "currency": values[13], "status": values[14],
            })
    return total, rows


class SwedenFiAdapter:
    version = "sweden-fi-live-v2"
    host = "marknadssok.fi.se"
    root = f"https://{host}"
    search_path = "/Publiceringsklient/sv-SE/Search/Search"
    page_path = "/Publiceringsklient/sv-SE/Search/Search/Insyn"

    def __init__(self, *, timeout: float = 20, retries: int = 2, request_delay: float = 0.15,
                 search_request_delay: float | None = None):
        self.client = HttpClient(timeout=timeout, retries=retries)
        self.request_delay = request_delay
        self.search_request_delay = request_delay if search_request_delay is None else search_request_delay

    def _params(self, interval_from: str, interval_to: str, page: int, paging: bool) -> dict[str, str]:
        values = {"SearchFunctionType": "Insyn", "Utgivare": "", "PersonILedandeStällningNamn": "",
                  "Transaktionsdatum.From": "", "Transaktionsdatum.To": "", "Publiceringsdatum.From": interval_from,
                  "Publiceringsdatum.To": interval_to, "button": "search", "Page": str(page)}
        if paging:
            values["paging"] = "True"
            values["page"] = str(page)
        return values

    def _page(self, interval_from: str, interval_to: str, page: int) -> tuple[int, list[dict]]:
        path = self.search_path if page == 1 else self.page_path
        response = self.client.request(f"{self.root}{path}?{urlencode(self._params(interval_from, interval_to, page, page > 1))}", expected_host=self.host)
        return _search_rows(response.body)

    def probe(self) -> dict[str, str]:
        today = date.today().isoformat()
        count, _ = self._page(today, today, 1)
        return {"status": "ok", "checked_date": today, "result_rows": str(count)}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None) -> list[DiscoveredRecord]:
        start = date.fromisoformat(interval_from)
        end = date.fromisoformat(interval_to)
        rows = []
        current = start
        search_requests = 0
        while current <= end:
            day = current.isoformat()
            if search_requests:
                time.sleep(self.search_request_delay)
            total, day_rows = self._page(day, day, 1)
            search_requests += 1
            for page in range(2, math.ceil(total / 10) + 1):
                time.sleep(self.search_request_delay)
                page_total, page_rows = self._page(day, day, page)
                search_requests += 1
                if page_total != total:
                    raise TransportError("FI result count changed during pagination")
                day_rows.extend(page_rows)
            if len(day_rows) != total:
                raise TransportError(f"FI pagination incomplete for {day}: expected {total}, received {len(day_rows)}")
            rows.extend(day_rows)
            current += timedelta(days=1)
        by_report: dict[str, dict] = {}
        for row in rows:
            entry = by_report.setdefault(row["report_version"], {"published_date": row["published_date"], "search_rows": []})
            entry["search_rows"].append(row)
        records = []
        for report, values in sorted(by_report.items()):
            url = urljoin(self.root, values["search_rows"][0]["href"])
            values["report_version"] = report
            values["url"] = url
            records.append(DiscoveredRecord(report, url, metadata=values))
        return records

    def fetch(self, record: DiscoveredRecord) -> bytes:
        time.sleep(self.request_delay)
        response = self.client.request(record.url, expected_host=self.host)
        text = response.body.decode("utf-8", errors="strict")
        if "Rapportsammanställning" not in html.unescape(text) or "Transaktionsdetaljer" not in html.unescape(text):
            if "Ingen rapportering hittades" in html.unescape(text):
                raise TransportError(f"FI report disappeared: {record.native_record_id}")
            raise TransportError("FI detail markers missing; possible challenge or layout change")
        return response.body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        return []
