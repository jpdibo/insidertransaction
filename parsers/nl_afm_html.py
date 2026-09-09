from __future__ import annotations

import html
import re
from datetime import date
from typing import Any

from .fixture_json import ParseError


PARSER_VERSION = "nl-afm-detail-v3"


def _text(fragment: str) -> str:
    fragment = re.sub(r'<span\b[^>]*class="[^"]*cc-mobile-title[^"]*"[^>]*>.*?</span>', "", fragment, flags=re.DOTALL | re.IGNORECASE)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def _decimal(raw: str) -> str | None:
    value = raw.strip()
    if not value or value in {"-", "n.v.t."}:
        return None
    if not re.fullmatch(r"[-+]?\d[\d.]*,\d+|[-+]?\d+", value):
        raise ParseError(f"AFM Netherlands decimal changed: {raw}")
    return value.replace(".", "").replace(",", ".")


def _action(value: str) -> tuple[str, str]:
    lower = value.lower()
    if any(word in lower for word in ("vervreemding", "verkoop", "disposal", "sale")):
        return "disposal", "decrease"
    if any(word in lower for word in ("verwerving", "aankoop", "acquisition", "purchase")):
        return "acquisition", "increase"
    if any(word in lower for word in ("toekenning", "grant")):
        return "grant", "increase"
    return "other", "unknown"


def _instrument(value: str) -> str:
    lower = value.lower()
    if "gewoon aandeel" in lower or "ordinary share" in lower:
        return "ordinary_share"
    if "certificaat" in lower or "depositary receipt" in lower:
        return "depositary_receipt"
    if "optie" in lower or "option" in lower:
        return "option"
    if "obligatie" in lower or "bond" in lower:
        return "bond"
    return "other"


def _fields(page: str) -> dict[str, str]:
    result = {}
    pattern = re.compile(r'cc-em--detail-list__label[^>]*>(.*?)</span>\s*<span\b[^>]*class="[^"]*cc-em--detail-list__value[^"]*"[^>]*>\s*<span>(.*?)</span>', re.DOTALL | re.IGNORECASE)
    for label, value in pattern.findall(page):
        result[_text(label)] = _text(value)
    return result


def _table(page: str, title: str, expected: int) -> list[list[str]]:
    match = re.search(rf'<h2\b[^>]*>{re.escape(title)}</h2>.*?<table\b[^>]*>(.*?)</table>', page, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ParseError(f"AFM Netherlands {title.lower()} table missing")
    body = re.search(r"<tbody>(.*?)</tbody>", match.group(1), re.DOTALL | re.IGNORECASE)
    if not body:
        raise ParseError(f"AFM Netherlands {title.lower()} table body missing")
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body.group(1), re.DOTALL | re.IGNORECASE):
        cells = [_text(cell) for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.DOTALL | re.IGNORECASE)]
        if len(cells) != expected:
            raise ParseError(f"AFM Netherlands {title.lower()} row schema changed")
        rows.append(cells)
    return rows


def parse(data: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        page = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("AFM Netherlands detail is not UTF-8") from exc
    if "Position/Status" not in page or ">Transactions<" not in page:
        raise ParseError("AFM Netherlands detail layout markers missing")
    fields = _fields(page)
    required = ("Notifiable", "Issuing institution", "Position/Status", "Transaction")
    if any(not fields.get(name) for name in required):
        raise ParseError("AFM Netherlands party/issuer fields missing")
    trade_date = metadata.get("transaction_date")
    if not trade_date:
        month = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "mei": 5, "jun": 6, "jul": 7,
                 "aug": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12}
        match = re.fullmatch(r"(\d{2})\s+([A-Za-z]{3})\s+(\d{4})", fields["Transaction"])
        if not match or match.group(2).lower() not in month:
            raise ParseError("AFM Netherlands transaction date changed")
        trade_date = date(int(match.group(3)), month[match.group(2).lower()], int(match.group(1))).isoformat()
    groups = []
    for ordinal, cells in enumerate(_table(page, "Transactions", 9), 1):
        instrument_raw, isin, category, transaction_type, option_program, venue, price_raw, quantity_raw, currency = cells
        action, exposure = _action(category or transaction_type)
        instrument_type = _instrument(instrument_raw)
        group = {
            "group_locator": f"transaction-{ordinal}", "event_key": f"transaction-{ordinal}",
            "instrument": {"name_raw": instrument_raw, "isin_raw": isin or None, "instrument_type": instrument_type},
            "nature_raw": f"{category} / {transaction_type}", "action": action,
            "mechanism": "employee_purchase_scheme" if option_program.lower() in {"ja", "yes"} else "unknown",
            "consideration": "cash_paid_received", "investment_discretion": "unknown", "exposure_effect": exposure,
            "trade_date": trade_date, "trade_date_precision": "day", "venue_raw": venue or None,
            "venue_mic": "XAMS" if "EURONEXT AMSTERDAM" in venue.upper() else None,
            "aggregation_reconciliation": "detail_rows_retained", "eligible_own_money_signal": False,
            "signal_exclusion_reason": "instrument_outside_default_equity" if instrument_type != "ordinary_share" else "investment_discretion_and_mechanism_unresolved",
            "rows": [{"row_locator": f"detail-row-{ordinal}", "representation": "individual",
                      "price_raw": f"{price_raw} {currency}" if currency else price_raw,
                      "price_amount_reported": _decimal(price_raw), "price_currency_normalized": currency or None,
                      "quote_unit_scale": "1", "quantity_raw": quantity_raw, "quantity": _decimal(quantity_raw),
                      "quantity_unit": None, "consideration_currency": currency or None}],
        }
        groups.append(group)
    for ordinal, cells in enumerate(_table(page, "Aggregated information", 8), 1):
        instrument_raw, isin, category, transaction_type, venue, price_raw, quantity_raw, currency = cells
        action, _ = _action(category or transaction_type)
        matches = [group for group in groups if group["instrument"].get("isin_raw") == (isin or None)
                   and group["action"] == action and group["nature_raw"] == f"{category} / {transaction_type}"
                   and (group.get("venue_raw") or "") == venue]
        if not matches:
            continue
        target = matches[0]
        for extra in matches[1:]:
            target["rows"].extend(extra["rows"])
            groups.remove(extra)
        target["rows"].append({"row_locator": f"aggregate-row-{ordinal}", "representation": "aggregate",
                                   "price_raw": f"{price_raw} {currency}" if currency else price_raw,
                                   "price_amount_reported": _decimal(price_raw), "price_currency_normalized": currency or None,
                                   "quote_unit_scale": "1", "quantity_raw": quantity_raw, "quantity": _decimal(quantity_raw),
                                   "quantity_unit": None, "consideration_currency": currency or None})
        target["aggregation_reconciliation"] = "official_aggregate_retained"
    if not groups:
        raise ParseError("AFM Netherlands transaction rows missing")
    related_name = metadata.get("related_pdmr_name")
    party_name = fields["Notifiable"]
    is_pca = bool(related_name)
    filing = {
        "source_locator": metadata["native_record_id"], "native_notification_reference": metadata["native_record_id"],
        "notification_status": "initial", "issuer": {"name_raw": fields["Issuing institution"], "lei_raw": fields.get("LEI") or None},
        "transacting_party": {"name_raw": party_name,
                              "party_type": "legal_entity" if is_pca and re.search(r"(?:N\.V\.|B\.V\.|Ltd|Limited|SA|SE)\s*$", party_name, re.IGNORECASE) else "natural_person",
                              "status_raw": fields["Position/Status"], "pdmr_or_pca": "pca" if is_pca else "pdmr",
                              "related_pdmr_name_raw": related_name, "related_pdmr_role_raw": fields["Position/Status"] if is_pca else None,
                              "identity_resolution_status": "unresolved"},
        "transaction_groups": groups,
        "quality_issues": ["afm_correction_semantics_not_published"],
    }
    return {"schema_version": "1.0", "fixture_kind": "real",
            "source": {"native_record_id": metadata["native_record_id"], "url": metadata["url"]}, "filings": [filing]}
