from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlencode

from .base import DiscoveredRecord
from .http import HttpClient, TransportError


ROOT = "https://www.afm.nl"
REGISTER_TYPE = "0ee836dc-5520-459d-bcf4-a4a689de6614"
DETAIL = ROOT + "/en/sector/registers/meldingenregisters/transacties-leidinggevenden-mar19-/details"


def _local(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _xml_records(body: bytes) -> list[DiscoveredRecord]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise TransportError("AFM Netherlands export is not valid XML") from exc
    if _local(root) != "register" or root.attrib.get("name") != "transacties-leidinggevenden-mar19-":
        raise TransportError("AFM Netherlands export markers missing")
    records: dict[str, DiscoveredRecord] = {}
    for row in root:
        if _local(row) != "vermelding":
            continue
        fields = {_local(item): " ".join((item.text or "").split()) for item in row}
        native_id = fields.get("meldingid", "")
        date_raw = fields.get("transactiedatum", "")
        if not native_id or not date_raw:
            raise TransportError("AFM Netherlands notification identity or date missing")
        try:
            trade_date = datetime.strptime(date_raw, "%m/%d/%Y %I:%M:%S %p").date().isoformat()
        except ValueError as exc:
            raise TransportError(f"AFM Netherlands transaction date changed: {date_raw}") from exc
        metadata = {
            "transaction_date": trade_date,
            "related_pdmr_name": fields.get("nauwgelieerdaan") or None,
            "issuer_name": fields.get("uitgevendeinstelling") or None,
            "party_name": fields.get("meldingsplichtige") or None,
        }
        record = DiscoveredRecord(native_id, DETAIL + "?" + urlencode({"id": native_id}), metadata=metadata)
        existing = records.get(native_id)
        if existing and existing.metadata != metadata:
            raise TransportError(f"AFM Netherlands conflicting duplicate notification: {native_id}")
        records[native_id] = record
    return sorted(records.values(), key=lambda item: item.native_record_id)


class NlAfmAdapter:
    version = "nl-afm-mar19-v1"
    host = "www.afm.nl"

    def __init__(self, *, timeout: float = 30, retries: int = 2):
        self.client = HttpClient(timeout=timeout, retries=retries)

    def probe(self) -> dict[str, str]:
        return {"status": "ok", "export": "available" if self.discover("2026-09-01", "2026-09-01", None) else "empty"}

    def discover(self, interval_from: str, interval_to: str, cursor: str | None = None) -> list[DiscoveredRecord]:
        del cursor
        start = datetime.strptime(interval_from, "%Y-%m-%d").strftime("%d-%m-%Y")
        end = datetime.strptime(interval_to, "%Y-%m-%d").strftime("%d-%m-%Y")
        query = urlencode({"DateFrom": start, "DateTill": end, "type": REGISTER_TYPE, "format": "xml"})
        body = self.client.request(f"{ROOT}/export.aspx?{query}", expected_host=self.host).body
        return _xml_records(body)

    def fetch(self, record: DiscoveredRecord) -> bytes:
        body = self.client.request(record.url, expected_host=self.host).body
        visible = body.decode("utf-8", errors="strict")
        if "Position/Status" not in visible or ">Transactions<" not in visible or record.native_record_id not in visible:
            raise TransportError("AFM Netherlands detail markers missing")
        return body

    def enumerate_attachments(self, record: DiscoveredRecord, data: bytes) -> list[DiscoveredRecord]:
        return []
