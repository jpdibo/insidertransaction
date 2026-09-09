from __future__ import annotations

import html
import io
import json
import re
from datetime import datetime
from typing import Any

from pypdf import PdfReader

from .fixture_json import ParseError
from .newsweb_json import _compact_english_form, _english_forms


PARSER_VERSION = "denmark-oam-detail-v3"
DETAIL_ROOT = "https://appft.gold.extension.gopublic.dk/api/9217fa13-5d9a-46c6-9921-69ee7e6cfaf6/details"


def _sections(payload: dict) -> dict[str, dict[str, list[dict]]]:
    result = {}
    for section in payload.get("sections", []):
        values: dict[str, list[dict]] = {}
        for element in section.get("elements", []):
            key = element.get("key", {}).get("name", "")
            values.setdefault(key, []).append(element.get("value", {}))
        result[section.get("heading", "")] = values
    return result


def _attachment_text(filename: str, data: bytes) -> str | None:
    lower = filename.lower()
    try:
        if re.search(r"\.pdf(?:\s*\(|$)", lower):
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise ParseError("encrypted Denmark OAM attachment requires review")
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if re.search(r"\.html?(?:\s*\(|$)", lower):
            page = data.decode("utf-8", errors="strict")
            return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).replace("\xa0", " ").split())
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"Denmark OAM attachment extraction failed: {exc}") from exc
    return None


def _fallback_form(message: dict, text: str, issuer: str, lei: str | None, party_hint: str) -> dict | None:
    compact = " ".join(text.split())
    if not re.search(r"Details of the person discharging managerial responsibilities", compact, re.IGNORECASE):
        return None
    party = re.search(r"1\.?\s*Details of the person.*?a\)\s*Name\s+(.+?)\s+2\.?\s*Reason", compact, re.IGNORECASE)
    role = re.search(r"a\)\s*Position\s*/\s*status\s+(.+?)\s+b\)\s*Initial", compact, re.IGNORECASE)
    nature = re.search(r"b\)\s*Nature of the transaction\s+(.+?)\s+c\)\s*Price", compact, re.IGNORECASE)
    isin = re.search(r"\b([A-Z]{2}[A-Z0-9]{10})\b", compact)
    trade_date = re.search(r"(?:e\)|64)\s*Date of the transaction\s+(\d{2}-\d{2}-\d{4}|\d{4}-\d{2}-\d{2})", compact, re.IGNORECASE)
    venue = re.search(r"f\)\s*Place of the transaction\s+(.+?)(?:\s+About\s|$)", compact, re.IGNORECASE)
    quantity = re.search(r"Total number of shares:\s*([\d,.]+)\s*shares", compact, re.IGNORECASE)
    consideration = re.search(r"Total (?:purchase|sales?) price:\s*([A-Z]{3})\s*([\d,.]+)", compact, re.IGNORECASE)
    detail = re.search(r"Price\(s\)\s+Volume\s*\(s\).*?\b(DKK|EUR|SEK|NOK|USD|GBP|CHF)\s+([\d,.]+)\s+([\d,.]+)", compact, re.IGNORECASE)
    if not all((role, nature, trade_date)) or (not quantity and not detail):
        return None
    nature_raw = nature.group(1).strip()
    action = "disposal" if re.search(r"sale|disposal", nature_raw, re.IGNORECASE) else "acquisition" if re.search(r"purchase|acquisition", nature_raw, re.IGNORECASE) else "other"
    raw_date = trade_date.group(1)
    parsed_date = datetime.strptime(raw_date, "%d-%m-%Y").date().isoformat() if raw_date[2] == "-" else raw_date
    quantity_raw = quantity.group(1) if quantity else detail.group(3)
    quantity_value = quantity_raw.replace(",", "")
    currency = consideration.group(1) if consideration else detail.group(1).upper() if detail else None
    consideration_raw = consideration.group(2).replace(",", "") if consideration else None
    price_raw = detail.group(2) if detail else None
    price_value = price_raw.replace(",", "") if price_raw else None
    role_raw = role.group(1).strip()
    is_pca = bool(re.search(r"relative to|closely (?:associated|related)", role_raw, re.IGNORECASE))
    party_name = party.group(1).strip() if party else party_hint
    related = re.search(r"(?:relative to|closely associated with)\s+(.+?)(?:\s*\(|$)", role_raw, re.IGNORECASE)
    if not related:
        related = re.search(r"CEO and board member,\s*(.+?),\s*is also", role_raw, re.IGNORECASE)
    return {
        "source_locator": f"announcement-{message['messageId']}-form-1", "notification_status": "initial",
        "issuer": {"name_raw": issuer, "lei_raw": lei},
        "transacting_party": {"name_raw": party_name, "party_type": "natural_person", "status_raw": role_raw,
                              "pdmr_or_pca": "pca" if is_pca else "pdmr",
                              "related_pdmr_name_raw": related.group(1).strip() if related else None,
                              "identity_resolution_status": "unresolved"},
        "quality_issues": ["detail_prices_not_normalized_from_misaligned_pdf_table"] if not detail else [],
        "transaction_groups": [{
            "group_locator": "transaction-1", "event_key": "transaction-1",
            "instrument": {"name_raw": "Shares", "isin_raw": isin.group(1) if isin else None, "instrument_type": "ordinary_share"},
            "nature_raw": nature_raw, "action": action, "mechanism": "unknown", "consideration": "cash_paid_received" if consideration else "unknown",
            "investment_discretion": "unknown", "exposure_effect": "increase" if action == "acquisition" else "decrease" if action == "disposal" else "unknown",
            "trade_date": parsed_date, "trade_date_precision": "day", "venue_raw": venue.group(1).strip() if venue else None,
            "aggregation_reconciliation": "detail_rows_retained" if detail else "aggregate_only", "eligible_own_money_signal": False,
            "signal_exclusion_reason": "investment_discretion_unresolved" if detail else "detail_fill_table_not_normalized",
            "rows": [{"row_locator": "detail-row-1" if detail else "aggregate-row-1", "representation": "individual" if detail else "aggregate",
                      "price_raw": f"{currency} {price_raw}" if price_raw else None,
                      "price_amount_reported": price_value, "price_currency_normalized": currency, "quote_unit_scale": "1",
                      "quantity_raw": quantity_raw, "quantity": quantity_value, "quantity_unit": "shares",
                      "consideration_reported": consideration_raw, "consideration_currency": currency}],
        }],
    }


def _fallback_danish(message: dict, text: str, party_hint: str) -> dict | None:
    compact = " ".join(text.split())
    if "Nærmere oplysninger om personen med ledelsesansvar" not in compact:
        return None
    structured_party = re.search(r"1\.\s*Nærmere oplysninger.*?a\)\s*Navn\s+(.+?)\s+2\.\s*Årsag", compact, re.IGNORECASE)
    structured_role = re.search(r"a\)\s*Stilling/titel\s+(.+?)\s*b\)\s*Første", compact, re.IGNORECASE)
    structured_issuer = re.search(r"3\.\s*Nærmere oplysninger.*?a\)\s*Navn\s+(.+?)\s*b\)\s*LEI-kode\s+([A-Z0-9]{20})", compact, re.IGNORECASE)
    structured_isin = re.search(r"Identifikationskode\s+([A-Z]{2}[A-Z0-9]{10})", compact, re.IGNORECASE)
    structured_nature = re.search(r"Transaktionens art\s+(.+?)(?:\s+\d[\d .]*\d|\s+d\) Aggregerede)", compact, re.IGNORECASE)
    structured_aggregate = re.search(r"Aggregeret mængde\s+-\s+Pris\s+([\d.]+)\s*stk\.\s+([\d.]+)\s+(DKK|EUR|SEK|NOK)", compact, re.IGNORECASE)
    structured_date = re.search(r"Dato for transaktionen\s+(\d{2}-\d{2}-\d{4})", compact, re.IGNORECASE)
    if all((structured_party, structured_role, structured_issuer, structured_isin, structured_nature, structured_aggregate, structured_date)):
        party_name = structured_party.group(1).strip()
        role_raw = structured_role.group(1).strip()
        nature_raw = structured_nature.group(1).strip()
        action = "acquisition" if re.search(r"køb|erhvervelse", nature_raw, re.IGNORECASE) else "disposal" if re.search(r"salg|afståelse", nature_raw, re.IGNORECASE) else "other"
        quantity_raw, consideration_raw, currency = structured_aggregate.groups()
        related = re.search(r"(?:direktør|director)\s+(.+)$", party_name, re.IGNORECASE)
        return {
            "source_locator": f"announcement-{message['messageId']}-form-1", "notification_status": "initial",
            "issuer": {"name_raw": structured_issuer.group(1).strip(), "lei_raw": structured_issuer.group(2)},
            "transacting_party": {"name_raw": party_name, "party_type": "legal_entity" if re.search(r"\b(ApS|A/S)\b", party_name) else "natural_person",
                                  "status_raw": role_raw, "pdmr_or_pca": "pca" if related else "pdmr",
                                  "related_pdmr_name_raw": related.group(1).strip() if related else None,
                                  "identity_resolution_status": "unresolved"},
            "quality_issues": ["detail_prices_not_normalized_from_misaligned_pdf_table"],
            "transaction_groups": [{
                "group_locator": "transaction-1", "event_key": "transaction-1",
                "instrument": {"name_raw": "Shares", "isin_raw": structured_isin.group(1), "instrument_type": "ordinary_share"},
                "nature_raw": nature_raw, "action": action, "mechanism": "unknown", "consideration": "cash_paid_received",
                "investment_discretion": "unknown", "exposure_effect": "increase" if action == "acquisition" else "decrease" if action == "disposal" else "unknown",
                "trade_date": datetime.strptime(structured_date.group(1), "%d-%m-%Y").date().isoformat(), "trade_date_precision": "day",
                "venue_raw": "XCSE" if re.search(r"Sted for transaktionen\s+XCSE", compact, re.IGNORECASE) else None,
                "venue_mic": "XCSE" if re.search(r"Sted for transaktionen\s+XCSE", compact, re.IGNORECASE) else None,
                "aggregation_reconciliation": "aggregate_only", "eligible_own_money_signal": False,
                "signal_exclusion_reason": "detail_fill_table_not_normalized",
                "rows": [{"row_locator": "aggregate-row-1", "representation": "aggregate", "price_raw": None,
                          "price_amount_reported": None, "price_currency_normalized": currency, "quote_unit_scale": "1",
                          "quantity_raw": quantity_raw, "quantity": quantity_raw.replace(".", ""), "quantity_unit": "shares",
                          "consideration_reported": consideration_raw.replace(".", ""), "consideration_currency": currency}],
            }],
        }
    issuer = re.search(r"Nærmere oplysninger om\s*udstederen.*?([A-ZÆØÅ][A-Za-zÆØÅæøå0-9 .-]+?)\s+([A-Z0-9]{20})\s+Nærmere oplysninger om transaktionen", compact, re.IGNORECASE)
    isin = re.search(r"(DK[A-Z0-9]{10})", compact)
    price_quantity = re.search(r"([\d.]+,\d+)\s+(DKK|EUR|SEK|NOK|USD|GBP|CHF)\s+([\d.]+)\b", compact)
    trade_date = re.search(r"(\d{2}-\d{2}-\d{4})", compact)
    nature = re.search(r"(Salg|Køb|Erhvervelse|Afståelse)", compact, re.IGNORECASE)
    if not all((issuer, isin, price_quantity, trade_date, nature)):
        return None
    nature_raw = nature.group(1)
    action = "disposal" if nature_raw.lower() in {"salg", "afståelse"} else "acquisition"
    price_raw, currency, quantity_raw = price_quantity.groups()
    instrument_match = re.search(r"Nærmere oplysninger om transaktionen.*?a\)\s*(.+?)\s+" + re.escape(isin.group(1)), compact, re.IGNORECASE)
    role_match = re.search(r"Årsag til indberetningen\s+(.+?)\s+Nærmere oplysninger om\s*udstederen", compact, re.IGNORECASE)
    return {
        "source_locator": f"announcement-{message['messageId']}-form-1", "notification_status": "initial",
        "issuer": {"name_raw": issuer.group(1).strip(), "lei_raw": issuer.group(2)},
        "transacting_party": {"name_raw": party_hint, "party_type": "natural_person",
                              "status_raw": role_match.group(1).strip() if role_match else "",
                              "pdmr_or_pca": "pdmr", "identity_resolution_status": "unresolved"},
        "quality_issues": [],
        "transaction_groups": [{
            "group_locator": "transaction-1", "event_key": "transaction-1",
            "instrument": {"name_raw": instrument_match.group(1).strip() if instrument_match else "Unresolved instrument",
                           "isin_raw": isin.group(1), "instrument_type": "other"},
            "nature_raw": nature_raw, "action": action, "mechanism": "unknown", "consideration": "cash_paid_received",
            "investment_discretion": "unknown", "exposure_effect": "decrease" if action == "disposal" else "increase",
            "trade_date": datetime.strptime(trade_date.group(1), "%d-%m-%Y").date().isoformat(), "trade_date_precision": "day",
            "venue_raw": "Nasdaq OMX Copenhagen" if "Nasdaq OMX Copenhagen" in compact else None,
            "venue_mic": "XCSE" if "Nasdaq OMX Copenhagen" in compact else None,
            "aggregation_reconciliation": "detail_rows_retained", "eligible_own_money_signal": False,
            "signal_exclusion_reason": "instrument_outside_default_equity",
            "rows": [{"row_locator": "detail-row-1", "representation": "individual",
                      "price_raw": f"{price_raw} {currency}", "price_amount_reported": price_raw.replace(".", "").replace(",", "."),
                      "price_currency_normalized": currency, "quote_unit_scale": "1", "quantity_raw": quantity_raw,
                      "quantity": quantity_raw.replace(".", ""), "quantity_unit": None, "consideration_currency": currency}],
        }],
    }


def parse(data: bytes, attachments: list[tuple[str, bytes]] | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError("Denmark OAM detail is not JSON") from exc
    sections = _sections(payload)
    notification = sections.get("Notification", {})
    time = sections.get("Time", {})
    issuer_section = sections.get("Issuer", {})
    party_section = sections.get("Manager or related party", {})
    def value(section: dict[str, list[dict]], key: str) -> str:
        items = section.get(key, [])
        return str(items[0].get("value", "")).strip() if items else ""
    native_id = value(notification, "Announcement ID")
    issuer = value(issuer_section, "Company")
    lei = value(issuer_section, "LEI code") or None
    party_hint = value(party_section, "Manager or related party")
    published = value(time, "Published")
    if not native_id or not issuer or not party_hint or not published:
        raise ParseError("Denmark OAM detail fields missing")
    message = {"messageId": native_id, "publishedTime": datetime.strptime(published, "%d-%m-%Y %H:%M:%S").isoformat(),
               "body": payload.get("heading", ""), "correctionForMessageId": None}
    filings = None
    for filename, content in attachments or []:
        text = _attachment_text(filename, content)
        if not text:
            continue
        filings = _english_forms(message, text)
        if not filings:
            compact = _compact_english_form(message, text)
            filings = [compact] if compact else None
        if not filings:
            fallback = _fallback_form(message, text, issuer, lei, party_hint)
            filings = [fallback] if fallback else None
        if not filings:
            fallback = _fallback_danish(message, text, party_hint)
            filings = [fallback] if fallback else None
        if filings:
            break
    if not filings:
        raise ParseError("Denmark OAM transaction form not parsed")
    correction = bool(re.search(r"correction|korrektion", payload.get("heading", ""), re.IGNORECASE))
    for filing in filings:
        filing["issuer"]["name_raw"] = filing["issuer"].get("name_raw") or issuer
        filing["issuer"]["lei_raw"] = filing["issuer"].get("lei_raw") or lei
        filing["notification_status"] = "correction" if correction else "initial"
        if correction:
            filing.setdefault("quality_issues", []).append("correction_parent_not_machine_readable")
        filing.setdefault("quality_issues", []).append("issuer_announcement_scope_not_private_regulator_notifications")
    return {"schema_version": "1.0", "fixture_kind": "real",
            "source": {"native_record_id": native_id, "url": f"{DETAIL_ROOT}/{native_id}", "published_at": message["publishedTime"]},
            "filings": filings}
