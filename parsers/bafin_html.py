from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

from .fixture_json import ParseError

PARSER_VERSION = "bafin-detail-v2"


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def _table(page: str, table_id: str) -> str:
    match = re.search(rf'<table\b[^>]*\bid=["\']{re.escape(table_id)}["\'][^>]*>(.*?)</table>', page,
                      re.DOTALL | re.IGNORECASE)
    if not match:
        raise ParseError(f"BaFin table {table_id} missing")
    return match.group(1)


def _table_tail(page: str, table_id: str) -> str:
    match = re.search(rf'<table\b[^>]*\bid=["\']{re.escape(table_id)}["\'][^>]*>', page, re.IGNORECASE)
    if not match:
        raise ParseError(f"BaFin table {table_id} missing")
    return page[match.end():]


def _pairs(table: str) -> dict[str, str]:
    result = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, re.DOTALL | re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)
        if len(cells) >= 2:
            result[_text(cells[0]).rstrip(":")] = _text(cells[1])
    return result


def _decimal(value: str) -> str:
    return value.replace(".", "").replace(" ", "").replace(",", ".")


def _money(value: str) -> tuple[str | None, str | None]:
    match = re.fullmatch(r"([+-]?[\d., ]+)\s+([A-Z]{3})", value.strip())
    if not match:
        return None, None
    return _decimal(match.group(1)), match.group(2)


def _date(value: str) -> str | None:
    if not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return datetime.fromisoformat(value.strip()[:10]).date().isoformat()


def parse(data: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        page = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("BaFin detail is not UTF-8") from exc
    visible = html.unescape(page)
    if "Angaben zum Geschäft/zu den Geschäften" not in visible or "Preis(e)und Volumen" not in visible:
        raise ParseError("BaFin detail layout markers missing")

    person = _pairs(_table(page, "1"))
    reason = _pairs(_table(page, "2"))
    issuer_table = _table(page, "3")
    issuer_values = [_text(value) for value in re.findall(r"<td[^>]*>(.*?)</td>", issuer_table, re.DOTALL | re.IGNORECASE)]
    if len(issuer_values) < 2:
        raise ParseError("BaFin issuer name or LEI missing")
    issuer_name, lei = issuer_values[0], issuer_values[1]

    transaction = _table(page, "4")
    transaction_pairs = _pairs(transaction)
    instrument_raw = transaction_pairs.get("Art", "")
    isin = transaction_pairs.get("ISIN", "")
    nature_match = re.search(r"b\)\s*Art des Geschäfts\s*</th>\s*</tr>\s*<tr[^>]*>\s*<td[^>]*>(.*?)</td>", transaction,
                             re.DOTALL | re.IGNORECASE)
    if not nature_match:
        raise ParseError("BaFin transaction nature missing")
    nature = _text(nature_match.group(1))
    explanation_match = re.search(r"Erläuterung\s*</th>\s*</tr>\s*<tr[^>]*>\s*<td[^>]*>(.*?)</td>", transaction,
                                  re.DOTALL | re.IGNORECASE)
    explanation = _text(explanation_match.group(1)) if explanation_match else ""

    # This table contains a nested table in its footer, so a non-greedy closing-tag match would truncate it.
    transaktion = _table_tail(page, "transaktion")

    def footer_value(label: str) -> str | None:
        match = re.search(rf"<td[^>]*>\s*{label}:?\s*</td>\s*<td[^>]*>(.*?)</td>", transaktion,
                          re.DOTALL | re.IGNORECASE)
        return _text(match.group(1)) if match else None

    tbody = re.search(r"<tbody>(.*?)</tbody>", transaktion, re.DOTALL | re.IGNORECASE)
    if not tbody:
        raise ParseError("BaFin price/volume rows missing")
    rows = []
    row_currencies = set()
    for ordinal, row_html in enumerate(re.findall(r"<tr[^>]*>(.*?)</tr>", tbody.group(1), re.DOTALL | re.IGNORECASE), 1):
        cells = [_text(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE)]
        if len(cells) != 2:
            raise ParseError("BaFin price/volume row schema changed")
        if not cells[0] and not cells[1]:
            continue
        price, price_currency = _money(cells[0])
        volume, volume_currency = _money(cells[1])
        if not price or not volume or price_currency != volume_currency:
            raise ParseError("BaFin price/volume currency or number is invalid")
        row_currencies.add(price_currency)
        rows.append({
            "row_locator": f"price-volume-{ordinal}", "representation": "individual",
            "price_raw": cells[0], "price_amount_reported": price, "price_currency_normalized": price_currency,
            "quote_unit_scale": "1", "quantity_raw": None, "quantity": None, "quantity_unit": None,
            "consideration_reported": volume, "consideration_currency": volume_currency,
            "consideration_derivation": "reported_monetary_volume",
        })

    aggregate_only = not rows
    if aggregate_only:
        aggregate_price = footer_value("Preis") or ""
        aggregate_volume = footer_value("Aggregiertes Volumen") or ""
        price, price_currency = _money(aggregate_price)
        volume, volume_currency = _money(aggregate_volume)
        if not price or not volume or price_currency != volume_currency:
            raise ParseError("BaFin aggregate-only price/volume currency or number is invalid")
        row_currencies.add(price_currency)
        rows.append({
            "row_locator": "aggregate-price-volume", "representation": "aggregate",
            "price_raw": aggregate_price, "price_amount_reported": price, "price_currency_normalized": price_currency,
            "quote_unit_scale": "1", "quantity_raw": None, "quantity": None, "quantity_unit": None,
            "consideration_reported": volume, "consideration_currency": volume_currency,
            "consideration_derivation": "reported_monetary_volume",
        })

    trade_date = _date(metadata.get("trade_date", ""))
    date_match = re.search(r"e\)\s*Datum des Geschäfts\s*</th>\s*</tr>\s*<tr[^>]*>\s*<td[^>]*>(.*?)</td>", transaktion,
                           re.DOTALL | re.IGNORECASE)
    detail_date = _date(_text(date_match.group(1))) if date_match else None
    if trade_date and detail_date and trade_date != detail_date:
        raise ParseError("BaFin search/detail trade dates disagree")
    trade_date = detail_date or trade_date
    mic = footer_value("MIC")
    venue = footer_value("Name") or metadata.get("venue") or None

    nature_lower = nature.lower()
    explanation_lower = explanation.lower()
    if nature_lower in {"kauf", "erwerb"}:
        action, exposure = "acquisition", "increase"
    elif nature_lower in {"verkauf", "veräußerung"}:
        action, exposure = "disposal", "decrease"
    elif nature_lower == "schenkung":
        action, exposure = "gift", "unknown"
    elif nature_lower == "sonstiges" and "schenkung" in explanation_lower:
        action, exposure = "gift", "unknown"
    elif nature_lower == "sonstiges" and re.match(r"(?:kauf|erwerb)\b", explanation_lower):
        action, exposure = "acquisition", "increase"
    elif nature_lower == "sonstiges" and re.match(r"(?:verkauf\b|einräumung\s*\(verkauf\))", explanation_lower):
        action, exposure = "disposal", "decrease"
    else:
        action, exposure = "other", "unknown"
    instrument_lower = instrument_raw.lower()
    instrument_type = "ordinary_share" if instrument_lower == "aktie" else "bond" if any(value in instrument_lower for value in ("schuldverschreibung", "anleihe", "obligation")) else "option" if "option" in instrument_lower else "other"
    position = reason.get("Position", metadata.get("position", ""))
    is_pca = "enger beziehung" in position.lower()
    first_name, last_name, title = person.get("Vorname", ""), person.get("Nachname", ""), person.get("Titel", "")
    party_name = " ".join(value for value in (title, first_name, last_name) if value)
    if not party_name:
        raise ParseError("BaFin transacting party name missing")
    entity_pattern = r"\b(AG|GmbH|SE|KG|OHG|UG|Ltd|Limited|PLC|S\.A|B\.V|PTE)(?:\.|\b)"
    party_type = "legal_entity" if is_pca and re.search(entity_pattern, party_name, re.IGNORECASE) else "natural_person"
    melding_id = str(metadata["meldung_id"])
    activated = metadata.get("activated_at", "")
    published_date = _date(activated[:10])
    eligible = action == "acquisition" and instrument_type == "ordinary_share"
    group = {
        "group_locator": "transaction-1", "event_key": "transaction-1",
        "instrument": {"name_raw": instrument_raw or "Unspecified instrument", "isin_raw": isin or None,
                       "instrument_type": instrument_type, "currency": next(iter(row_currencies)) if len(row_currencies) == 1 else None},
        "nature_raw": f"{nature}: {explanation}" if explanation else nature, "action": action, "mechanism": "open_market" if nature_lower in {"kauf", "verkauf"} else "unknown",
        "consideration": "cash_paid_received", "investment_discretion": "unknown", "exposure_effect": exposure,
        "trade_date": trade_date, "trade_date_precision": "day" if trade_date else "unknown", "venue_raw": venue,
        "venue_mic": mic, "aggregation_reconciliation": "aggregate_only_monetary_volume_without_quantity" if aggregate_only else "reported_monetary_volume_without_quantity",
        "eligible_own_money_signal": eligible,
        "signal_exclusion_reason": None if eligible else "instrument_or_transaction_outside_default_purchase_signal",
        "rows": rows,
    }
    filing = {
        "source_locator": melding_id, "native_notification_reference": melding_id, "notification_status": "initial",
        "issuer": {"name_raw": issuer_name, "lei_raw": lei or None},
        "transacting_party": {"name_raw": party_name, "party_type": party_type, "status_raw": position,
                              "pdmr_or_pca": "pca" if is_pca else "pdmr", "identity_resolution_status": "unresolved"},
        "transaction_groups": [group], "quality_issues": ["quantity_not_published_by_bafin_register"],
    }
    return {"schema_version": "1.0", "fixture_kind": "real",
            "source": {"native_record_id": metadata["native_record_id"], "url": metadata["url"],
                       "published_date": published_date}, "filings": [filing]}
