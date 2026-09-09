from __future__ import annotations

import io
import re
from datetime import datetime

from pypdf import PdfReader

from parsers.fixture_json import ParseError


PARSER_VERSION = "amf-bdif-pdf-v4"


def _field(pattern: str, text: str, *, required: bool = True) -> str | None:
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return " ".join(match.group(1).split())
    if required:
        raise ParseError(f"AMF PDF field missing: {pattern.split(':', 1)[0]}")
    return None


def _number(value: str) -> str:
    return value.replace(" ", "").replace(",", ".")


def _parse_text(text: str) -> dict:
    reference_match = re.search(r"\b(20\d{2}DD\d+)\b", text)
    header_isin_match = re.search(r"\b([A-Z]{2}[A-Z0-9]{10})\b", text)
    english_at = text.find("Individual notification")
    if english_at >= 0:
        text = text[english_at:]
    if not reference_match:
        raise ParseError("AMF notification reference missing")
    reference = reference_match.group(1)
    party_block = _field(r"PERSON CLOSELY ASSOCIATED\s*:\s*(.*?)\s*INITIAL NOTIFICATION", text)
    issuer_name = _field(r"DETAILS OF THE ISSUER\s+NAME\s*:\s*(.*?)\s+LEI\s*:", text)
    lei_raw = _field(r"\bLEI\s*:\s*([A-Z0-9]+)", text, required=False)
    lei = lei_raw if lei_raw and re.fullmatch(r"[A-Z0-9]{20}", lei_raw) else None
    status_raw = _field(r"INITIAL NOTIFICATION\s*/\s*AMENDMENT\s*:\s*(.*?)\s+DETAILS OF THE ISSUER", text)
    is_correction = "amend" in status_raw.lower() or "modification" in status_raw.lower()
    normalized_party = party_block.lower().replace("�", "e")
    is_pca = "closely associated" in normalized_party or "personne morale liee" in normalized_party or "personne etroitement liee" in normalized_party
    party_name = re.split(r"\s+(?:legal person|natural person|person) closely associated", party_block, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    if not party_name:
        party_name = party_block
    sections = re.split(r"DETAIL OF THE TRANSACTION(?:\s+\d+)?", text, flags=re.IGNORECASE)[1:]
    groups = []
    month_formats = ("%d %B %Y", "%d %b %Y")
    for ordinal, section in enumerate(sections, 1):
        full_section = section
        section = section.split("DATE OF RECEIPT OF THE NOTIFICATION", 1)[0]
        date_raw = _field(r"DATE OF THE TRANSACTION\s*:\s*(.*?)\s+PLACE OF THE TRANSACTION", section)
        trade_date = None
        for date_format in month_formats:
            try:
                trade_date = datetime.strptime(date_raw, date_format).date().isoformat()
                break
            except ValueError:
                pass
        if trade_date is None:
            raise ParseError(f"AMF transaction date is invalid: {date_raw}")
        venue = _field(r"PLACE OF THE TRANSACTION\s*:\s*(.*?)\s+NATURE OF THE TRANSACTION", section)
        nature = _field(r"NATURE OF THE TRANSACTION\s*:\s*(.*?)\s+DESCRIPTION OF THE FINANCIAL INSTRUMENT", section)
        instrument_name = _field(r"DESCRIPTION OF THE FINANCIAL INSTRUMENT[^:]*:\s*(.*?)\s+(?:IDENTIFICATION CODE|DETAILED OPERATION INFORMATION)", section)
        isin = _field(r"IDENTIFICATION CODE\s*:\s*([A-Z]{2}[A-Z0-9]{10})", section, required=False) or (header_isin_match.group(1) if header_isin_match else None)
        effective_acquisition = re.search(r"acquisitions? effectives?|effective acquisitions?", full_section, re.IGNORECASE)
        action = "acquisition" if re.search(r"acquisition|purchase|subscription", nature, re.IGNORECASE) or effective_acquisition else "disposal" if re.search(r"sale|disposal|cession", nature, re.IGNORECASE) else "grant" if re.search(r"grant|allocation", nature, re.IGNORECASE) else "other"
        instrument_type = "option" if "option" in instrument_name.lower() else "ordinary_share" if "share" in instrument_name.lower() or "action" in instrument_name.lower() else "other"
        detail = _field(r"DETAILED OPERATION INFORMATION\s+(.*?)\s+AGGREGATED INFORMATION", section)
        rows = []
        for row_ordinal, match in enumerate(re.finditer(r"PRICE(?: UNIT)?\s*:\s*([\d .,]+)\s+([A-Za-z]+)\s+VOLUME\s*:\s*([\d .,]+)", detail, re.IGNORECASE), 1):
            price, currency_raw, quantity = match.groups()
            currency = "EUR" if currency_raw.lower() in {"euro", "eur"} else currency_raw.upper()
            rows.append({"row_locator": f"transaction-{ordinal}-detail-{row_ordinal}", "representation": "individual",
                         "price_raw": f"{price.strip()} {currency_raw}", "price_amount_reported": _number(price),
                         "price_currency_normalized": currency, "quote_unit_scale": "1", "quantity_raw": quantity.strip(),
                         "quantity": _number(quantity), "quantity_unit": "securities", "consideration_currency": currency})
        aggregate = re.search(r"AGGREGATED INFORMATION\s+PRICE\s*:\s*([\d .,]+)\s+([A-Za-z]+)\s+AGGREGATED VOLUME\s*:\s*([\d .,]+)", section, re.DOTALL | re.IGNORECASE)
        if aggregate:
            price, currency_raw, quantity = aggregate.groups()
            currency = "EUR" if currency_raw.lower() in {"euro", "eur"} else currency_raw.upper()
            if re.search(r"correspondent.*?prix.*?volume agr[ée]g", full_section, re.DOTALL | re.IGNORECASE):
                rows = []
            rows.append({"row_locator": f"transaction-{ordinal}-aggregate", "representation": "aggregate",
                         "price_raw": f"{price.strip()} {currency_raw}", "price_amount_reported": _number(price),
                         "price_currency_normalized": currency, "quote_unit_scale": "1", "quantity_raw": quantity.strip(),
                         "quantity": _number(quantity), "quantity_unit": "securities", "consideration_currency": currency})
        if not rows:
            raise ParseError(f"AMF transaction {ordinal} has no price/volume rows")
        groups.append({"group_locator": f"transaction-{ordinal}", "event_key": f"transaction-{ordinal}",
                       "instrument": {"name_raw": instrument_name, "isin_raw": isin, "instrument_type": instrument_type},
                       "nature_raw": nature, "action": action, "mechanism": "unknown", "consideration": "cash_paid_received",
                       "investment_discretion": "unknown", "exposure_effect": "increase" if action == "acquisition" else "decrease" if action == "disposal" else "unknown",
                       "trade_date": trade_date, "trade_date_precision": "day", "venue_raw": venue,
                       "venue_mic": "XPAR" if "euronext paris" in venue.lower() else None,
                       "aggregation_reconciliation": "detail_rows_retained", "eligible_own_money_signal": False,
                       "signal_exclusion_reason": "investment_discretion_and_mechanism_unresolved", "rows": rows})
    if not groups:
        raise ParseError("AMF PDF contains no transaction sections")
    url = f"https://bdif.amf-france.org/back/api/v1/informations/{reference}"
    return {"schema_version": "1.0", "source": {"native_record_id": reference, "url": url}, "filings": [{
        "source_locator": reference, "native_notification_reference": reference,
        "notification_status": "correction" if is_correction else "initial", "issuer": {"name_raw": issuer_name, "lei_raw": lei},
        "transacting_party": {"name_raw": party_name, "party_type": "legal_entity" if is_pca and re.search(r"\b(SA|SAS|SARL|SC|SOCIETE|HOLDING)\b", party_name, re.IGNORECASE) else "natural_person",
                              "status_raw": party_block, "pdmr_or_pca": "pca" if is_pca else "pdmr", "identity_resolution_status": "unresolved"},
        "transaction_groups": groups, "quality_issues": ["invalid_lei: published LEI does not have 20 characters"] if lei_raw and not lei else [],
    }]}


def parse(data: bytes) -> dict:
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)
    except Exception as exc:
        raise ParseError(f"AMF PDF extraction failed: {exc}") from exc
    return _parse_text(text)
