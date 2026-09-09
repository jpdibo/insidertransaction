from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .fixture_json import ParseError

PARSER_VERSION = "sweden-fi-detail-v5"


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("\xa0", " ").split())


def _fields(page: str) -> dict[str, str]:
    result = {}
    pattern = re.compile(r'<div class="col-sm-4 text-right">(.*?)</div>\s*<div class="col-sm-6">(.*?)</div>', re.DOTALL | re.IGNORECASE)
    for label, value in pattern.findall(page):
        result[_text(label)] = _text(value)
    return result


def _action(nature: str) -> tuple[str, str]:
    nature_lower = nature.lower()
    if nature_lower.startswith("förvärv"):
        return "acquisition", "increase"
    if nature_lower.startswith("avyttring"):
        return "disposal", "decrease"
    if nature_lower.startswith("tilldelning"):
        return "grant", "increase"
    return "other", "unknown"


def parse(data: bytes, metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        page = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("FI detail is not UTF-8") from exc
    visible = html.unescape(page)
    if "Rapportsammanställning" not in visible or "Transaktionsdetaljer" not in visible:
        raise ParseError("FI detail layout markers missing")
    fields = _fields(page)
    required = ("Namn på anmälningsskyldig", "Person i ledande ställning", "Namn på emittent")
    if any(not fields.get(name) for name in required):
        raise ParseError("FI party/issuer fields missing")
    table_match = re.search(r"Transaktionsdetaljer.*?<table[^>]*>(.*?)</table>", visible, re.DOTALL | re.IGNORECASE)
    if not table_match:
        raise ParseError("FI transaction table missing")
    body_match = re.search(r"<tbody>(.*?)</tbody>", table_match.group(1), re.DOTALL | re.IGNORECASE)
    if not body_match:
        raise ParseError("FI transaction table body missing")
    groups = []
    for ordinal, row_html in enumerate(re.findall(r"<tr[^>]*>(.*?)</tr>", body_match.group(1), re.DOTALL | re.IGNORECASE), 1):
        raw_cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE)
        if len(raw_cells) != 11:
            raise ParseError("FI transaction row schema changed")
        cells = [_text(cell) for cell in raw_cells]
        instrument_type_raw, instrument_name, isin, nature, _, quantity_raw, quantity_unit, price_raw, currency, trade_date, venue = cells
        action, exposure = _action(nature)
        instrument_lower = instrument_type_raw.lower()
        if instrument_lower == "aktie":
            instrument_type = "ordinary_share"
        elif "teckningsoption" in instrument_lower:
            instrument_type = "warrant"
        elif "option" in instrument_lower:
            instrument_type = "option"
        elif "obligation" in instrument_lower:
            instrument_type = "bond"
        elif "rätt" in instrument_lower:
            instrument_type = "right"
        else:
            instrument_type = "other"
        quantity = quantity_raw.replace(" ", "")
        price = price_raw.replace(" ", "").replace(",", ".")
        option_program = "checked" in raw_cells[4].lower()
        mechanism = "employee_purchase_scheme" if option_program and action == "acquisition" else "compensation_grant" if option_program and action == "grant" else "unknown"
        zero = price in {"0", "0.0", "0.00"}
        group = {
            "group_locator": f"transaction-{ordinal}", "event_key": f"transaction-{ordinal}",
            "instrument": {"name_raw": instrument_name, "isin_raw": isin or None, "instrument_type": instrument_type},
            "nature_raw": nature, "action": action, "mechanism": mechanism,
            "consideration": "none" if zero and action == "grant" else "cash_paid_received",
            "investment_discretion": "unknown", "exposure_effect": exposure,
            "trade_date": trade_date or None, "trade_date_precision": "day" if trade_date else "unknown",
            "venue_raw": venue or None, "aggregation_reconciliation": "detail_rows_retained",
            "eligible_own_money_signal": False,
            "signal_exclusion_reason": "instrument_outside_default_equity" if instrument_type != "ordinary_share" else "investment_discretion_and_mechanism_unresolved",
            "rows": [{"row_locator": f"detail-row-{ordinal}", "representation": "individual", "price_raw": f"{price_raw} {currency}" if currency else price_raw,
                      "price_amount_reported": price or None, "price_currency_normalized": currency or None, "quote_unit_scale": "1",
                      "quantity_raw": quantity_raw, "quantity": quantity or None, "quantity_unit": quantity_unit or None,
                      "consideration_currency": currency or None}],
        }
        groups.append(group)
    quality_issues = []
    aggregate_table = re.search(r"Aggregeringar.*?<table[^>]*>(.*?)</table>", visible, re.DOTALL | re.IGNORECASE)
    if aggregate_table:
        aggregate_body = re.search(r"<tbody>(.*?)</tbody>", aggregate_table.group(1), re.DOTALL | re.IGNORECASE)
        if not aggregate_body:
            raise ParseError("FI aggregate table body missing")
        for aggregate_ordinal, row_html in enumerate(re.findall(r"<tr[^>]*>(.*?)</tr>", aggregate_body.group(1), re.DOTALL | re.IGNORECASE), 1):
            cells = [_text(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE)]
            if len(cells) != 7:
                raise ParseError("FI aggregate row schema changed")
            instrument_name, isin, nature, trade_date, venue, volume_raw, weighted_raw = cells
            action, _ = _action(nature)
            volume_match = re.fullmatch(r"(.+?)\s*\((.+)\)", volume_raw)
            price_match = re.fullmatch(r"(.+?)\s+([A-Z]{3})", weighted_raw)
            if not volume_match or not price_match:
                raise ParseError("FI aggregate price or volume format changed")
            aggregate_quantity = volume_match.group(1).replace(" ", "").replace(",", ".")
            aggregate_price = price_match.group(1).replace(" ", "").replace(",", ".")
            aggregate_currency = price_match.group(2)
            matches = [group for group in groups if group["instrument"].get("isin_raw") == (isin or None) and group["action"] == action
                       and group["trade_date"] == trade_date and (group.get("venue_raw") or "") == venue]
            if not matches:
                quality_issues.append(f"aggregate_without_details:{aggregate_ordinal}")
                continue
            exact_matches = [group for group in matches if any(
                row["representation"] == "individual" and row.get("quantity") == aggregate_quantity
                and row.get("price_amount_reported") == aggregate_price for row in group["rows"]
            )]
            if exact_matches:
                matches = exact_matches[:1]
            target = matches[0]
            for extra in matches[1:]:
                target["rows"].extend(extra["rows"])
                groups.remove(extra)
            target["rows"].append({"row_locator": f"aggregate-row-{aggregate_ordinal}", "representation": "aggregate",
                                   "price_raw": weighted_raw, "price_amount_reported": aggregate_price,
                                   "price_currency_normalized": aggregate_currency, "quote_unit_scale": "1",
                                   "quantity_raw": volume_raw, "quantity": aggregate_quantity,
                                   "quantity_unit": volume_match.group(2), "consideration_currency": aggregate_currency})
            try:
                detail_rows = [row for row in target["rows"] if row["representation"] == "individual"]
                detail_quantity = sum((Decimal(row["quantity"]) for row in detail_rows), Decimal(0))
                weighted_price = sum((Decimal(row["quantity"]) * Decimal(row["price_amount_reported"]) for row in detail_rows), Decimal(0)) / detail_quantity
                precision = Decimal(1).scaleb(-len(aggregate_price.partition(".")[2]))
                reconciled = detail_quantity == Decimal(aggregate_quantity) and weighted_price.quantize(precision, rounding=ROUND_HALF_UP) == Decimal(aggregate_price)
            except (InvalidOperation, ZeroDivisionError, TypeError):
                reconciled = False
            target["aggregation_reconciliation"] = "matches_details" if reconciled else "mismatch"
            if not reconciled:
                quality_issues.append(f"aggregate_detail_mismatch:{aggregate_ordinal}")
    report_version = metadata["report_version"]
    base_report, version = report_version.rsplit("-", 1)
    is_pca = fields.get("Närstående") == "Ja"
    correction = fields.get("Korrigering") == "Ja"
    filing = {
        "source_locator": base_report, "native_notification_reference": base_report,
        "notification_status": "amended" if correction else "initial",
        "amends_native_reference": f"{base_report}-{int(version)-1}" if correction and int(version) > 1 else None,
        "issuer": {"name_raw": fields["Namn på emittent"], "lei_raw": fields.get("Emittentens LEI-kod") or None},
        "transacting_party": {
            "name_raw": fields["Namn på anmälningsskyldig"], "party_type": "legal_entity" if is_pca and re.search(r"\b(AB|HB|KB|AS|Oy|ApS|SA|SGPS|GmbH|Ltd|Limited|Aktiebolag|Aktiebolaget)\b", fields["Namn på anmälningsskyldig"], re.IGNORECASE) else "natural_person",
            "status_raw": fields.get("Befattning för person i ledande ställning", ""), "pdmr_or_pca": "pca" if is_pca else "pdmr",
            "related_pdmr_name_raw": fields["Person i ledande ställning"] if is_pca else None,
            "related_pdmr_role_raw": fields.get("Befattning för person i ledande ställning") if is_pca else None,
            "identity_resolution_status": "unresolved",
        },
        "transaction_groups": groups,
        "quality_issues": quality_issues,
    }
    return {"schema_version": "1.0", "fixture_kind": "real",
            "source": {"native_record_id": report_version, "url": metadata["url"], "published_date": metadata["published_date"]},
            "filings": [filing]}
