from __future__ import annotations

import csv
import hashlib
from pathlib import Path


def create_audit_sample(connection, source_id: str, size: int, output: Path) -> int:
    if size < 1:
        raise ValueError("audit sample size must be positive")
    rows = connection.execute(
        "SELECT DISTINCT e.id AS event_id,sr.native_record_id,sr.canonical_url,ro.sha256 AS raw_sha256,"
        "COALESCE(fv.issuer_name_raw,iss.legal_name) AS issuer_name,p.canonical_name AS party_name,tg.action,tg.nature_raw,tg.trade_date,"
        "tg.venue_raw,COALESCE(tg.instrument_name_raw,i.name_raw) AS instrument_name,ii.value AS isin,tg.underlying_isin_raw,rr.representation,rr.price_raw,"
        "rr.price_amount_decimal,rr.price_currency,rr.quantity_raw,rr.quantity_decimal,rr.quantity_unit "
        "FROM economic_events e JOIN event_versions ev ON ev.id=e.current_version_id "
        "JOIN filing_versions fv ON fv.id=ev.filing_version_id JOIN filings f ON f.id=fv.filing_id "
        "JOIN filing_publications fp ON fp.filing_version_id=fv.id AND fp.publication_rank=1 JOIN source_records sr ON sr.id=fp.source_record_id "
        "JOIN document_versions dv ON dv.source_record_id=sr.id AND dv.version_ordinal=(SELECT MAX(x.version_ordinal) FROM document_versions x WHERE x.source_record_id=sr.id) "
        "JOIN raw_objects ro ON ro.sha256=dv.raw_sha256 JOIN issuers iss ON iss.id=f.issuer_id "
        "JOIN transaction_groups tg ON tg.id=ev.transaction_group_id LEFT JOIN parties p ON p.id=tg.party_id "
        "LEFT JOIN instruments i ON i.id=tg.instrument_id LEFT JOIN instrument_identifiers ii ON ii.instrument_id=i.id AND ii.scheme='ISIN' "
        "JOIN reported_transaction_rows rr ON rr.transaction_group_id=tg.id AND rr.selected_for_analytics=1 "
        "WHERE sr.source_id=? ORDER BY e.id,rr.id",
        (source_id,),
    ).fetchall()
    events = {}
    for row in rows:
        item = dict(row)
        event = events.setdefault(item["event_id"], {key: item[key] for key in (
            "event_id", "native_record_id", "canonical_url", "raw_sha256", "issuer_name", "party_name",
            "action", "nature_raw", "trade_date", "venue_raw", "instrument_name", "isin", "underlying_isin_raw",
        )})
        values = " | ".join(str(item[key] or "") for key in (
            "representation", "price_raw", "price_amount_decimal", "price_currency", "quantity_raw",
            "quantity_decimal", "quantity_unit",
        ))
        event["selected_rows"] = f"{event.get('selected_rows', '')} || {values}".strip(" |")
    selected = sorted(events.values(), key=lambda item: hashlib.sha256(f"{source_id}:{item['event_id']}".encode()).hexdigest())[:size]
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "source_id", "event_id", "native_record_id", "canonical_url", "raw_sha256", "issuer_name",
        "party_name", "action", "nature_raw", "trade_date", "venue_raw", "instrument_name", "isin", "underlying_isin_raw",
        "selected_rows", "decision", "notes",
    ]
    with output.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in selected:
            writer.writerow({"source_id": source_id, **item, "decision": "", "notes": ""})
    return len(selected)
