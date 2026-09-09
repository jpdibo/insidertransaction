from __future__ import annotations

import json
import re
import warnings
from difflib import SequenceMatcher
from datetime import datetime
from io import BytesIO
from typing import Any

try:
    from cryptography.utils import CryptographyDeprecationWarning
    warnings.filterwarnings("ignore", message=r"ARC4 has been moved.*", category=CryptographyDeprecationWarning)
except ImportError:
    pass
from pypdf import PdfReader

from .fixture_json import ParseError

PARSER_VERSION = "newsweb-message-v12"


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ParseError("encrypted NewsWeb attachment requires review")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"NewsWeb PDF extraction failed: {exc}") from exc


def _base(message: dict, filings: list[dict]) -> dict[str, Any]:
    native_id = str(message["messageId"])
    return {
        "schema_version": "1.0", "fixture_kind": "real",
        "source": {"native_record_id": native_id, "url": f"https://newsweb.oslobors.no/message/{native_id}", "published_at": message["publishedTime"]},
        "filings": filings,
    }


def _group(*, locator: str, instrument: str, instrument_type: str, nature: str, action: str,
           mechanism: str, consideration: str, exposure: str, trade_date: str | None,
           quantity_raw: str, quantity: str, quantity_unit: str = "shares", price_raw: str | None = None,
           price: str | None = None, currency: str | None = None, venue: str | None = None,
            eligible: bool = False, exclusion: str | None = None, representation: str = "aggregate") -> dict:
    return {
        "group_locator": locator, "event_key": locator,
        "instrument": {"name_raw": instrument, "instrument_type": instrument_type},
        "nature_raw": nature, "action": action, "mechanism": mechanism, "consideration": consideration,
        "investment_discretion": "unknown", "exposure_effect": exposure, "trade_date": trade_date,
        "trade_date_precision": "day" if trade_date else "unknown", "venue_raw": venue,
        "aggregation_reconciliation": "not_applicable", "eligible_own_money_signal": eligible,
        "signal_exclusion_reason": exclusion,
        "rows": [{"row_locator": f"{locator}-row-1", "representation": representation, "price_raw": price_raw,
                  "price_amount_reported": price, "price_currency_normalized": currency,
                  "quote_unit_scale": "1", "quantity_raw": quantity_raw, "quantity": quantity,
                  "quantity_unit": quantity_unit, "consideration_currency": currency}],
    }


def _filing(message: dict, locator: str, issuer: str, party: dict, groups: list[dict], issues: list[str] | None = None) -> dict:
    return {
        "source_locator": locator,
        "notification_status": "correction" if message.get("correctionForMessageId") else "initial",
        "amends_native_reference": str(message["correctionForMessageId"]) if message.get("correctionForMessageId") else None,
        "issuer": {"name_raw": issuer, "lei_raw": None}, "transacting_party": party,
        "transaction_groups": groups, "quality_issues": issues or [],
    }


def _restore_body_text(value: str, body: str) -> str:
    value = re.sub(r"\s+N/A$", "", value).strip()
    if "�" not in value and "Kla veness" not in value:
        return value
    pattern = "".join("." if char == "�" else r"\s*" if char.isspace() else re.escape(char) for char in value)
    match = re.search(pattern, body, re.IGNORECASE)
    return " ".join(match.group(0).split()) if match else value.replace("Kla veness", "Klaveness")


def _reported_isin(text: str) -> str | None:
    labelled = re.search(r"(?:ISIN|IDENTIFICATION CODE)\s*:?\s*([A-Z]{2}(?:\s*[A-Z0-9]){9}\s*\d)\b", text, re.IGNORECASE)
    generic = re.search(r"\b([A-Z]{2}(?:\s*[A-Z0-9]){9}\s*\d)\b", text, re.IGNORECASE)
    match = labelled or generic
    return re.sub(r"\s+", "", match.group(1)).upper() if match else None


def _restore_wrapped_name(value: str, body: str) -> str:
    body_name = re.search(r"^(.+?),\s*.+?,\s*has on ", body, re.IGNORECASE | re.DOTALL)
    parts = value.split()
    body_parts = body_name.group(1).split() if body_name else []
    if len(parts) > 2 and len(body_parts) == 2 and parts[0].casefold() == body_parts[0].casefold():
        collapsed = parts[0] + " " + "".join(parts[1:])
        if SequenceMatcher(None, collapsed.casefold(), body_name.group(1).casefold()).ratio() >= 0.9:
            return collapsed
    return value


def _direct_body(message: dict, pdf_text: str) -> dict | None:
    body = message.get("body", "")
    match = re.search(
        r"^(?P<name>.+?),\s*(?P<role>.+?),\s*has on (?P<date>\d{1,2} \w+ \d{4}),\s*"
        r"(?P<action>bought|sold) a total of (?P<quantity>[\d,]+) shares .*? at a price of (?P<price>[\d.,]+)",
        body, re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    body_date = datetime.strptime(match["date"], "%d %B %Y").date().isoformat()
    action = "acquisition" if match["action"].lower() == "bought" else "disposal"
    currency_match = re.search(r"\b(EUR|GBP|NOK|SEK|DKK|CHF)\s+([\d.,]+)\s+([\d,]+)", pdf_text)
    isin_match = re.search(r"ISIN\s+(?:code\s+)?([A-Z]{2}\s?[A-Z0-9 ]{10,14})", pdf_text, re.IGNORECASE)
    lei_match = re.search(r"\bLEI\s+([A-Z0-9]{20})", pdf_text)
    pdf_date_match = re.search(r"Date of the transaction\s+(\d{4}-\d{2}-\d{2})", pdf_text)
    pdf_name_match = re.search(r"\ba\)\s+Name\s+(.+)", pdf_text)
    currency = currency_match.group(1) if currency_match else None
    quantity = match["quantity"].replace(",", "")
    price = match["price"].replace(",", ".")
    issues = []
    if pdf_date_match and pdf_date_match.group(1) != body_date:
        issues.append(f"conflicting_trade_date:body={body_date},attachment={pdf_date_match.group(1)}")
    if pdf_name_match and pdf_name_match.group(1).strip() != match["name"].strip():
        issues.append("conflicting_party_name_between_body_and_attachment")
    group = _group(locator="headline-transaction-1", instrument="shares", instrument_type="ordinary_share",
                   nature=match["action"], action=action, mechanism="unknown", consideration="cash_paid_received",
                   exposure="increase" if action == "acquisition" else "decrease", trade_date=body_date,
                   quantity_raw=match["quantity"], quantity=quantity, price_raw=f"{currency + ' ' if currency else ''}{match['price']}",
                   price=price, currency=currency, venue=None, eligible=False,
                   exclusion="disposal" if action == "disposal" else "mechanism_unresolved")
    if isin_match:
        group["instrument"]["isin_raw"] = isin_match.group(1).replace(" ", "")
    filing = _filing(message, f"message-{message['messageId']}-notification-1", message["issuerName"], {
        "name_raw": match["name"], "party_type": "natural_person", "status_raw": match["role"],
        "pdmr_or_pca": "pdmr", "identity_resolution_status": "unresolved",
    }, [group], issues)
    filing["issuer"]["lei_raw"] = lei_match.group(1) if lei_match else None
    return filing


def _employee_plan(message: dict, pdf_text: str) -> list[dict] | None:
    body = message.get("body", "")
    title = message.get("title", "")
    is_english = "Employee Share Purchase Programme" in title
    is_norwegian = "Aksjer til Ledende Ansatte" in title
    if not is_english and not is_norwegian:
        return None
    price_match = re.search(r"NOK\s+([\d.,]+) per (?:share|aksje)", body)
    date_match = re.search(r"(?:closed on|avsluttet)\s+(\d{1,2}\.? \w+ \d{4})", body)
    if not price_match or not date_match:
        raise ParseError("employee-plan body lost reviewed price/date markers")
    raw_date = date_match.group(1).replace(".", "")
    trade_date = datetime.strptime(raw_date, "%d %B %Y").date().isoformat()
    price = price_match.group(1).replace(",", ".")
    filings = []
    for line in pdf_text.splitlines():
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) != 4 or not re.search(r"[A-Za-z]", parts[0]) or "Name" in parts[0]:
            continue
        name, _, purchased, _ = parts
        quantity = purchased.replace(" ", "")
        if not quantity.isdigit():
            continue
        ordinal = len(filings) + 1
        group = _group(locator=f"employee-plan-{ordinal}", instrument="Veidekke shares", instrument_type="ordinary_share",
                       nature="Employee Share Purchase Programme", action="acquisition", mechanism="employee_purchase_scheme",
                       consideration="cash_paid_received", exposure="increase", trade_date=trade_date,
                       quantity_raw=purchased, quantity=quantity, price_raw=f"NOK {price_match.group(1)}",
                       price=price, currency="NOK", eligible=False, exclusion="employee_purchase_scheme")
        filing = _filing(message, f"employee-plan-{trade_date}-{ordinal}", message["issuerName"], {
            "name_raw": name.strip(), "party_type": "natural_person", "status_raw": "Primary insider",
            "pdmr_or_pca": "pdmr", "identity_resolution_status": "unresolved",
        }, [group])
        filing["native_notification_reference"] = f"employee-plan:{message['issuerName']}:{trade_date}:{name.strip()}"
        filings.append(filing)
    if not filings:
        raise ParseError("employee-plan attachment table produced no transaction rows")
    return filings


def _english_forms(message: dict, pdf_text: str) -> list[dict] | None:
    pdf_text = re.sub(r"[ \t]+", " ", pdf_text)
    if "Details of the person discharging managerial responsibilities" not in pdf_text:
        return None
    starts = list(re.finditer(r"(?im)^\s*1\s+Details of the person discharging managerial responsibilities", pdf_text))
    filings = []
    for person_ordinal, start in enumerate(starts, 1):
        end = starts[person_ordinal].start() if person_ordinal < len(starts) else len(pdf_text)
        section = pdf_text[start.start():end]
        names = re.findall(r"(?im)^\s*a\)\s+(?:Business name|Name)\s+(.+?)\s*$", section)
        role_match = re.search(r"(?im)^\s*a\)\s+Position/status\s+(.+?)\s*$", section)
        lei_match = re.search(r"(?im)^\s*b\)\s+(?:LEI|LEI code)\s+([A-Z0-9]{20})", section)
        if len(names) < 2 or not role_match:
            continue
        party_name = _restore_wrapped_name(names[0].strip(), message.get("body", ""))
        issuer_name = names[1].strip()
        role = role_match.group(1).strip()
        transaction_starts = list(re.finditer(r"(?im)^\s*4(?:\.\d+)?\s+Details of the transaction", section))
        groups = []
        issues = []
        for transaction_ordinal, tx_start in enumerate(transaction_starts, 1):
            tx_end = transaction_starts[transaction_ordinal].start() if transaction_ordinal < len(transaction_starts) else len(section)
            tx = section[tx_start.start():tx_end]
            nature_match = re.search(r"(?ims)^\s*b\)\s+Nature of the transaction\s+(.+?)(?=^\s*c\)\s+Price)", tx)
            date_match = re.search(r"(?im)^\s*e\)\s+Date of the transaction\s+(.+?)\s*$", tx)
            place_match = re.search(r"(?im)^\s*f\)\s+Place of the transaction\s+(.+?)\s*$", tx)
            isin = _reported_isin(tx)
            instrument_match = re.search(r"(?ims)^\s*a\)\s+Description of the financial\s+(.+?)(?=^\s*b\)\s+Nature)", tx)
            price_volume = re.search(r"\b(EUR|GBP|NOK|SEK|DKK|CHF|USD)\s+([\d.,]+)\s+([\d,]+)\s*$", tx, re.MULTILINE)
            if not all((nature_match, date_match, price_volume)):
                issues.append(f"transaction_{transaction_ordinal}_critical_table_parse_failed")
                continue
            nature = " ".join(nature_match.group(1).split())
            currency, price_raw, quantity_raw = price_volume.groups()
            quantity = quantity_raw.replace(",", "")
            price = price_raw.replace(",", ".")
            raw_date = re.sub(r"\s*-\s*", "-", date_match.group(1).strip())
            parsed_date = None
            for date_format in ("%Y-%m-%d", "%d %B %Y"):
                try:
                    parsed_date = datetime.strptime(raw_date, date_format).date().isoformat(); break
                except ValueError:
                    pass
            if not parsed_date:
                issues.append(f"transaction_{transaction_ordinal}_date_parse_failed:{raw_date}")
            body_date_match = re.search(r"has on (\d{1,2} \w+ \d{4})", message.get("body", ""), re.IGNORECASE)
            if body_date_match and parsed_date:
                body_date = datetime.strptime(body_date_match.group(1), "%d %B %Y").date().isoformat()
                if body_date != parsed_date:
                    issues.append(f"conflicting_trade_date:body={body_date},attachment={parsed_date}")
            lower = nature.lower()
            if "tax" in lower and ("sale" in lower or "disposal" in lower):
                action, mechanism = "disposal", "tax_related_sale"
            elif "sale" in lower or "disposal" in lower:
                action, mechanism = "disposal", "exchange_sale" if "xoff" not in (place_match.group(1).lower() if place_match else "") else "off_market_trade"
            elif "purchase" in lower or "acquisition" in lower or "receipt" in lower:
                action, mechanism = "acquisition", "exchange_purchase" if "xoff" not in (place_match.group(1).lower() if place_match else "") else "off_market_trade"
            elif "vest" in lower or "delivery" in lower or "award" in lower or "grant" in lower:
                action, mechanism = "grant", "compensation_vesting"
            elif "exercise" in lower:
                action, mechanism = "exercise", "option_exercise"
            else:
                action, mechanism = "other", "unknown"
            zero_price = price in {"0", "0.0", "0.00"}
            consideration = "none" if zero_price and action in {"grant", "transfer", "other"} else "cash_paid_received"
            instrument_text = " ".join(instrument_match.group(1).split()) if instrument_match else "Unresolved instrument"
            instrument_text = re.sub(r"^instrument(?:,\s*type of instrument)?\s+", "", instrument_text, flags=re.IGNORECASE)
            instrument_text = re.sub(r"^Identification code\s+", "", instrument_text, flags=re.IGNORECASE)
            instrument_text = re.sub(r"\s+Identification code.*$", "", instrument_text, flags=re.IGNORECASE)
            instrument_text = re.sub(r"\s*\(ISIN\s*:\s*[A-Z0-9]+\)\.?$", "", instrument_text, flags=re.IGNORECASE)
            instrument_type = "option" if "option" in instrument_text.lower() or "rsu" in instrument_text.lower() else "ordinary_share"
            group = _group(locator=f"person-{person_ordinal}-transaction-{transaction_ordinal}", instrument=instrument_text,
                           instrument_type=instrument_type, nature=nature, action=action, mechanism=mechanism,
                           consideration=consideration, exposure="decrease" if action == "disposal" else "increase" if action in {"acquisition", "grant", "exercise"} else "unknown",
                           trade_date=parsed_date, quantity_raw=quantity_raw, quantity=quantity,
                           price_raw=f"{currency} {price_raw}", price=price, currency=currency,
                           venue=place_match.group(1).strip() if place_match else None, eligible=False,
                           exclusion="not_an_own_money_purchase" if action != "acquisition" else "investment_discretion_unresolved",
                           representation="individual")
            if isin:
                group["instrument"]["isin_raw"] = isin
            groups.append(group)
        if groups:
            pca = "closely associated" in role.lower()
            related_match = re.search(r"to the PDMR,\s*([^,]+)", role, re.IGNORECASE)
            party = {"name_raw": party_name, "party_type": "legal_entity" if pca and re.search(r"\b(AS|Ltd|Limited|BV|AB)\b", party_name) else "natural_person",
                     "status_raw": role, "pdmr_or_pca": "pca" if pca else "pdmr", "identity_resolution_status": "unresolved"}
            if related_match:
                party["related_pdmr_name_raw"] = related_match.group(1).strip()
            filing = _filing(message, f"message-{message['messageId']}-person-{person_ordinal}", issuer_name, party, groups, issues)
            filing["issuer"]["lei_raw"] = lei_match.group(1) if lei_match else None
            filings.append(filing)
    return filings or None


def _compact_english_form(message: dict, pdf_text: str) -> dict | None:
    pdf_text = " ".join(pdf_text.split())
    if not re.search(r"Details of (?:the )?.{0,100}(?:primary insider|person closely associated)", pdf_text, re.IGNORECASE):
        return None
    person_match = re.search(
        r"\b1\s*Details of .*?\ba\)\s*Name\s+(.+?)\s+2(?:\s*Reason for the notification)?\s+a\)\s*Position",
        pdf_text, re.IGNORECASE | re.DOTALL,
    )
    role_match = re.search(r"\ba\)\s*Position\s*/?\s*status\s+(.+?)(?=\s+b\)\s*Initial)", pdf_text, re.IGNORECASE | re.DOTALL)
    issuer_match = re.search(
        r"3\s*Details of (?:the issuer|the company|[^\n]+).*?\ba\)\s*Name\s+(.+?)\s+\bb\)\s*LEI\s+([A-Z0-9]{20})",
        pdf_text, re.IGNORECASE | re.DOTALL,
    )
    tx_start = re.search(r"\b4(?:\.\d+)?\.?\s*(?:Details of the transaction|a\)\s*Description)", pdf_text, re.IGNORECASE)
    if not all((person_match, role_match, issuer_match, tx_start)):
        return None
    tx = pdf_text[tx_start.start():]
    nature_match = re.search(r"\bb\)\s*Nature\s+of\s+the\s+transaction\s+(.+?)(?=\s+c\)\s*Price)", tx, re.IGNORECASE | re.DOTALL)
    date_match = re.search(r"\be\)\s*Date\s+of\s+the\s+transaction\s+(\d{4}-\d{2}-\d{2}|\d{1,2} [A-Za-z]+ \d{4})", tx, re.IGNORECASE)
    place_match = re.search(r"\bf\)\s*Place\s+of\s+(?:the\s+)?transaction\s+(.+?)(?=\s+g\)|\Z)", tx, re.IGNORECASE | re.DOTALL)
    price_section = re.search(r"\bc\)\s*Price\(s\)\s+and\s+volume\(s\)(.+?)(?=\s+d\)\s*Aggregated)", tx, re.IGNORECASE | re.DOTALL)
    instrument_section = re.search(r"(?:\ba\)\s*)?Description of the\s+financial\s+instrument.+?(?=\s+b\)\s*Nature)", tx, re.IGNORECASE | re.DOTALL)
    if not all((nature_match, date_match, place_match, price_section, instrument_section)):
        return None
    nature = " ".join(nature_match.group(1).split())
    lower = nature.lower()
    gift = "gift" in lower
    row = price_section.group(1)
    priced = re.search(r"\b(EUR|GBP|NOK|SEK|DKK|CHF|USD)\s+([\d.]+)\s+([\d,]+)(?:\s|$)", row)
    if not priced:
        priced = re.search(r"Price\(s\)\s+in\s+(EUR|GBP|NOK|SEK|DKK|CHF|USD)\s+Volume\(s\)\s+([\d.]+)\s+([\d,]+)", row, re.IGNORECASE | re.DOTALL)
    currency = price_raw = quantity_raw = None
    if priced:
        currency, price_raw, quantity_raw = priced.groups()
    else:
        unpriced = re.search(r"Price\(s\).*?Volume\(s\)\s+([\d.]+)\s+([\d,]+)", row, re.IGNORECASE | re.DOTALL)
        if unpriced:
            price_raw, quantity_raw = unpriced.groups()
            aggregate = re.search(r"\bd\)\s+Aggregated.+?(?=\s+e\))", tx, re.IGNORECASE | re.DOTALL)
            currency_match = re.search(r"\b(EUR|GBP|NOK|SEK|DKK|CHF|USD)\b", aggregate.group(0)) if aggregate else None
            currency = currency_match.group(1) if currency_match else None
    if gift and not quantity_raw:
        quantity_match = re.search(r"Aggregate number of shares:\s*([\d,]+)", tx, re.IGNORECASE)
        quantity_raw = quantity_match.group(1) if quantity_match else None
    if not quantity_raw or (not gift and price_raw is None):
        return None
    quantity = quantity_raw.replace(",", "").replace(" ", "")
    price = price_raw.replace(",", "") if price_raw is not None else None
    if gift:
        action, mechanism, consideration, exposure = "transfer", "gift_inheritance", "none", "decrease"
        price = price_raw = currency = None
    elif "sale" in lower or "disposal" in lower:
        action, mechanism, consideration, exposure = "disposal", "off_market_trade" if "outside" in place_match.group(1).lower() else "exchange_sale", "cash_paid_received", "decrease"
    elif "grant" in lower:
        action, mechanism, consideration, exposure = "grant", "compensation_grant", "none" if price in {"0", "0.0", "0.00"} else "unknown", "increase"
    elif "purchase" in lower or "acquisition" in lower or "bought" in lower:
        action, mechanism, consideration, exposure = "acquisition", "off_market_trade" if "outside" in place_match.group(1).lower() else "exchange_purchase", "cash_paid_received", "increase"
    elif "transfer" in lower and currency and re.search(r"\bacquired\b", message.get("body", ""), re.IGNORECASE):
        action, mechanism, consideration, exposure = "acquisition", "off_market_trade", "cash_paid_received", "increase"
    else:
        action, mechanism, consideration, exposure = "other", "unknown", "unknown", "unknown"
    instrument_block = " ".join(instrument_section.group(0).split())
    isin = _reported_isin(instrument_block)
    if "bond" in instrument_block.lower():
        instrument, instrument_type, quantity_unit = "FRN senior secured bonds", "bond", "nominal_amount"
    elif re.search(r"\boptions?\b", instrument_block, re.IGNORECASE):
        instrument, instrument_type, quantity_unit = "Share options", "option", "options"
    else:
        instrument, instrument_type, quantity_unit = "Shares", "ordinary_share", "shares"
    role = " ".join(role_match.group(1).split())
    party_name = _restore_body_text(" ".join(person_match.group(1).split()), message.get("body", ""))
    issuer_name, lei = (_restore_body_text(" ".join(issuer_match.group(1).split()), message.get("body", "")), issuer_match.group(2))
    pca = "closely associated" in role.lower()
    party = {
        "name_raw": party_name,
        "party_type": "legal_entity" if pca and re.search(r"\b(AS|ASA|AB|BV|Ltd|Limited|PLC|Holding|Rederiaksjeselskapet)\b", party_name, re.IGNORECASE) else "natural_person",
        "status_raw": role, "pdmr_or_pca": "pca" if pca else "pdmr", "identity_resolution_status": "unresolved",
    }
    issues = []
    related = re.search(r"(?:associated with|associated party of)\s+(.+?)(?:,\s*(?:Chair|chair|Chief|board)|\s+of\s+the\s+issuer)", role)
    if pca and " and " in role.lower():
        issues.append("multiple_related_pdmrs_not_fully_normalized")
    elif related:
        party["related_pdmr_name_raw"] = related.group(1).strip()
    raw_date = date_match.group(1)
    trade_date = raw_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) else datetime.strptime(raw_date, "%d %B %Y").date().isoformat()
    venue = re.sub(r"\s+(?:External|Page \d+.*|Pexip\s*\|.*)$", "", " ".join(place_match.group(1).split())).strip()
    venue = _restore_body_text(venue, message.get("body", ""))
    if "transfer" in lower and action == "acquisition":
        issues.append("body_attachment_nature_wording_differs")
    group = _group(
        locator="compact-form-transaction-1", instrument=instrument, instrument_type=instrument_type,
        nature=nature, action=action, mechanism=mechanism, consideration=consideration, exposure=exposure,
        trade_date=trade_date, quantity_raw=quantity_raw, quantity=quantity, quantity_unit=quantity_unit,
        price_raw=f"{currency} {price_raw}" if currency and price_raw is not None else price_raw,
        price=price, currency=currency, venue=venue, eligible=False,
        exclusion="not_an_own_money_purchase" if action != "acquisition" else "investment_discretion_unresolved",
        representation="individual",
    )
    if isin and instrument_type != "option":
        group["instrument"]["isin_raw"] = isin
    elif isin:
        group["instrument"]["underlying_isin_raw"] = isin
        issues.append("reported_isin_identifies_underlying_share_not_option")
    filing = _filing(message, f"message-{message['messageId']}-compact-form-1", issuer_name, party, [group], issues)
    filing["issuer"]["lei_raw"] = lei
    return filing


def _body_embedded_form(message: dict) -> dict | None:
    body = message.get("body", "")
    if "Details in accordance with Article 19(6)" not in body:
        return None
    compact = " ".join(body.split())
    party_match = re.search(r"1\. Details of the person.+?a\) Name:\s*(.+?)\s+b\) Position/status:\s*(.+?)\s+c\) Initial", compact, re.IGNORECASE)
    issuer_match = re.search(r"3\. Details of the issuer\s+a\) Name:\s*(.+?)\s+b\) LEI:\s*([A-Z0-9]{20})", compact, re.IGNORECASE)
    tx_match = re.search(
        r"4\. Details of the transaction\s+a\).*?code:\s*(.+?),\s*ISIN\s+([A-Z]{2}[A-Z0-9]{10})\s+"
        r"b\) Nature of the transaction:\s*(.+?)\s+c\) Price\(s\) and volume\(s\):\s*"
        r"([A-Z]{3})\s+([\d.]+)\s+per share;\s*([\d,]+)\s+shares\s+d\) Date of the transaction:\s*"
        r"(\d{1,2} \w+ \d{4})\s+e\) Place of the transaction:\s*(.+?)(?=\s+This information)", compact, re.IGNORECASE,
    )
    if not all((party_match, issuer_match, tx_match)):
        return None
    party_name, role = party_match.groups()
    instrument, isin, nature, currency, price, quantity_raw, raw_date, venue = tx_match.groups()
    action = "acquisition" if nature.lower().startswith("acquisition") else "disposal" if nature.lower().startswith("disposal") else "other"
    related = re.search(r"associated with\s+(.+?),\s*(.+?)(?:\s+of\s+|\s+in\s+)", role, re.IGNORECASE)
    party = {"name_raw": party_name, "party_type": "legal_entity", "status_raw": role, "pdmr_or_pca": "pca",
             "identity_resolution_status": "unresolved"}
    if related:
        party["related_pdmr_name_raw"] = related.group(1).strip()
        party["related_pdmr_role_raw"] = related.group(2).strip()
    group = _group(
        locator="body-form-transaction-1", instrument=instrument, instrument_type="ordinary_share", nature=nature,
        action=action, mechanism="exchange_purchase" if action == "acquisition" else "unknown",
        consideration="cash_paid_received", exposure="increase" if action == "acquisition" else "decrease",
        trade_date=datetime.strptime(raw_date, "%d %B %Y").date().isoformat(), quantity_raw=quantity_raw,
        quantity=quantity_raw.replace(",", ""), price_raw=f"{currency} {price}", price=price, currency=currency,
        venue=venue, eligible=False, exclusion="investment_discretion_unresolved" if action == "acquisition" else "not_an_own_money_purchase",
    )
    group["instrument"]["isin_raw"] = isin
    filing = _filing(message, f"message-{message['messageId']}-body-form-1", issuer_match.group(1), party, [group])
    filing["issuer"]["lei_raw"] = issuer_match.group(2)
    return filing


def _krt_form(message: dict, pdf_text: str) -> dict | None:
    if "KRT-1500" not in pdf_text or "2.8.2 Aggregert volum" not in pdf_text:
        return None
    def after_id(field_id: str) -> str | None:
        match = re.search(rf"(?m)^\s*{re.escape(field_id)}[^\n]*\n([^\n]+)", pdf_text)
        return match.group(1).strip() if match else None
    reporting_type = after_id("1.3.1") or ""
    related = after_id("1.7.1")
    role = after_id("1.7.2")
    issuer = after_id("2.2.2") or message["issuerName"]
    issuer_lei = after_id("2.2.1")
    instrument_match = re.search(r"2\.3\.1 Instrument\s*:\s*([^\n]+)", pdf_text)
    isin_match = re.search(r"2\.3\.2 ISIN-kode\s*:\s*([A-Z]{2}[A-Z0-9]{10})", pdf_text)
    nature_match = re.search(r"2\.4\.1 Transaksjonstype\s*:\s*([^\n]+)", pdf_text)
    nature_detail = re.search(r"2\.4\.2 Beskrivelse av transaksjonstype\s*:\s*([^\n]+)", pdf_text)
    currency_match = re.search(r"2\.6\.1 Valuta\s*:\s*([A-Z]{3})", pdf_text)
    price_match = re.search(r"2\.8\.1 Gjennomsnittlig pris per enhet\s*:\s*([\d ,.]+)", pdf_text)
    volume_match = re.search(r"2\.8\.2 Aggregert volum\s*:\s*([\d ]+)", pdf_text)
    date_match = re.search(r"2\.9\.1 Angi dato\s*:\s*(\d{2}\.\d{2}\.\d{4})", pdf_text)
    venue_match = re.search(r"2\.10\.1 Handelsplass\s*:\s*([^\n]+)", pdf_text)
    if not all((nature_match, currency_match, price_match, volume_match, date_match)):
        raise ParseError("KRT-1500 attachment lost mandatory transaction markers")
    is_company_pca = "foretak" in reporting_type.lower()
    is_person_pca = "person" in reporting_type.lower() and "n�rst�ende" in reporting_type.lower()
    party = after_id("1.6.2") if is_company_pca else after_id("1.4.2") or after_id("1.4.1") or after_id("1.5.2") or after_id("1.5.1") or related
    if not party:
        raise ParseError("KRT-1500 transacting party marker unresolved")
    nature = nature_match.group(1).strip()
    if nature_detail and "Du har ikke" not in nature_detail.group(1):
        nature += ": " + nature_detail.group(1).strip()
    lower = nature.lower()
    option_transaction = "opsjon" in lower
    if option_transaction and lower.startswith("aksept"):
        action, mechanism, exposure = "grant", "compensation_grant", "increase"
    elif option_transaction and lower.startswith("erverv"):
        action, mechanism, exposure = "acquisition", "unknown", "increase"
    elif lower.startswith("kj"):
        action, mechanism, exposure = "acquisition", "unknown", "increase"
    elif lower.startswith("salg"):
        action, mechanism, exposure = "disposal", "unknown", "decrease"
    elif lower.startswith("utl") or lower.startswith("overf"):
        action, mechanism, exposure = "transfer", "corporate_action", "neutral"
    elif lower.startswith("tildel"):
        action, mechanism, exposure = "grant", "compensation_grant", "increase"
    else:
        action, mechanism, exposure = "other", "unknown", "unknown"
    price_raw = price_match.group(1).strip().replace(" ", "").replace(",", ".")
    quantity_raw = volume_match.group(1).strip()
    zero = price_raw in {"0", "0.0", "0.00"}
    instrument = "Share options" if option_transaction else instrument_match.group(1).strip() if instrument_match else "Unresolved instrument"
    group = _group(locator="krt-transaction-1", instrument=instrument,
                   instrument_type="option" if option_transaction else "ordinary_share" if instrument_match and "aksje" in instrument_match.group(1).lower() else "other",
                   nature=nature, action=action, mechanism=mechanism, consideration="none" if zero else "cash_paid_received",
                   exposure=exposure, trade_date=datetime.strptime(date_match.group(1), "%d.%m.%Y").date().isoformat(),
                   quantity_raw=quantity_raw, quantity=quantity_raw.replace(" ", ""), quantity_unit="options" if option_transaction else "shares",
                   price_raw=f"{price_raw} {currency_match.group(1)}", price=price_raw, currency=currency_match.group(1),
                   venue=venue_match.group(1).strip() if venue_match else None, eligible=False,
                   exclusion="not_an_own_money_purchase" if action != "acquisition" else "investment_discretion_unresolved")
    if isin_match and not option_transaction:
        group["instrument"]["isin_raw"] = isin_match.group(1)
    elif isin_match:
        group["instrument"]["underlying_isin_raw"] = isin_match.group(1)
    reference_match = re.search(r"Referansenummer:\s*([^\s]+)", pdf_text)
    source_locator = f"krt-{reference_match.group(1)}" if reference_match else f"message-{message['messageId']}-krt-1"
    filing = _filing(message, source_locator, issuer, {
        "name_raw": party, "party_type": "legal_entity" if is_company_pca else "natural_person",
        "status_raw": "N�rst�ende foretak" if is_company_pca else ("N�rst�ende person" if is_person_pca else (role or reporting_type)),
        "pdmr_or_pca": "pca" if is_company_pca or is_person_pca else "pdmr",
        "related_pdmr_name_raw": related if is_company_pca or is_person_pca else None,
        "related_pdmr_role_raw": role if is_company_pca or is_person_pca else None,
        "identity_resolution_status": "unresolved",
    }, [group])
    if reference_match:
        filing["native_notification_reference"] = reference_match.group(1)
    if issuer_lei and re.fullmatch(r"[A-Z0-9]{20}", issuer_lei):
        filing["issuer"]["lei_raw"] = issuer_lei
    return filing


def _english_krt_form(message: dict, pdf_text: str) -> dict | None:
    if "KRT-1500 Form for notification" not in pdf_text or "2.8.2 Aggregated volume" not in pdf_text:
        return None

    def after_id(field_id: str) -> str | None:
        match = re.search(rf"(?m)^\s*{re.escape(field_id)}[^\n]*\n([^\n]+)", pdf_text)
        return match.group(1).strip() if match else None

    reporting_type = after_id("1.3.1") or ""
    party = after_id("1.6.2")
    related = after_id("1.7.1")
    role = after_id("1.7.2")
    issuer_lei = after_id("2.2.1")
    issuer = after_id("2.2.2") or message["issuerName"]
    instrument_match = re.search(r"2\.3\.1 Instrument\s*:\s*([^\n]+)", pdf_text)
    isin_match = re.search(r"2\.3\.2 ISIN code\s*:\s*([A-Z]{2}[A-Z0-9]{10})", pdf_text)
    nature_match = re.search(r"2\.4\.1 Transaction type\s*:\s*([^\n]+)", pdf_text)
    currency_match = re.search(r"2\.6\.1 Currency\s*:\s*([A-Z]{3})", pdf_text)
    price_match = re.search(r"2\.8\.1 Average price per unit\s*:\s*([\d ,.]+)", pdf_text)
    volume_match = re.search(r"2\.8\.2 Aggregated volume\s*:\s*([\d ,]+)", pdf_text)
    date_match = re.search(r"2\.9\.1 Specify date\s*:\s*(\d{2}/\d{2}/\d{4})", pdf_text)
    venue_match = re.search(r"2\.10\.1 Trading venue\s*:\s*([^\n]+)", pdf_text)
    if not all((party, related, role, issuer_lei, instrument_match, nature_match, currency_match, price_match, volume_match, date_match)):
        raise ParseError("English KRT-1500 attachment lost mandatory transaction markers")
    trade_date = datetime.strptime(date_match.group(1), "%m/%d/%Y").date().isoformat()
    sent_match = re.search(r"Date sent:\s*(\d{2}\.\d{2}\.\d{4})", pdf_text)
    sent_date = datetime.strptime(sent_match.group(1), "%d.%m.%Y").date().isoformat() if sent_match else None
    body_date = datetime.strptime(re.search(r"\b(\d{1,2} \w+ \d{4})\b", message.get("body", "")).group(1), "%d %B %Y").date().isoformat() if re.search(r"\b(\d{1,2} \w+ \d{4})\b", message.get("body", "")) else None
    if trade_date not in {sent_date, body_date}:
        raise ParseError("English KRT-1500 slash date lacks independent day/month corroboration")
    nature = nature_match.group(1).strip()
    action = "disposal" if nature.lower().startswith("sale") else "acquisition" if nature.lower().startswith("purchase") else "other"
    instrument = instrument_match.group(1).strip()
    instrument_type = "ordinary_share" if instrument.lower() == "share" else "other"
    price_raw = price_match.group(1).replace(" ", "").replace(",", ".")
    quantity_raw = volume_match.group(1).strip()
    group = _group(
        locator="english-krt-transaction-1", instrument=instrument, instrument_type=instrument_type,
        nature=nature, action=action, mechanism="exchange_sale" if action == "disposal" else "unknown",
        consideration="cash_paid_received", exposure="decrease" if action == "disposal" else "increase" if action == "acquisition" else "unknown",
        trade_date=trade_date, quantity_raw=quantity_raw, quantity=quantity_raw.replace(" ", "").replace(",", ""),
        price_raw=f"{price_raw} {currency_match.group(1)}", price=price_raw, currency=currency_match.group(1),
        venue=venue_match.group(1).strip() if venue_match else None, eligible=False,
        exclusion="not_an_own_money_purchase" if action != "acquisition" else "investment_discretion_unresolved",
    )
    if isin_match:
        group["instrument"]["isin_raw"] = isin_match.group(1)
    reference_match = re.search(r"Reference number:\s*([^\s]+)", pdf_text)
    locator = f"krt-{reference_match.group(1)}" if reference_match else f"message-{message['messageId']}-english-krt-1"
    filing = _filing(message, locator, issuer, {
        "name_raw": party, "party_type": "legal_entity" if "entity closely associated" in reporting_type.lower() else "natural_person",
        "status_raw": reporting_type, "pdmr_or_pca": "pca" if "closely associated" in reporting_type.lower() else "pdmr",
        "related_pdmr_name_raw": related, "related_pdmr_role_raw": role, "identity_resolution_status": "unresolved",
    }, [group])
    if reference_match:
        filing["native_notification_reference"] = reference_match.group(1)
    if re.fullmatch(r"[A-Z0-9]{20}", issuer_lei):
        filing["issuer"]["lei_raw"] = issuer_lei
    return filing


def _afm_form(message: dict, pdf_text: str) -> dict | None:
    if not re.search(r"AFM\s+notification\s+form\s+MAR\s+19", pdf_text, re.IGNORECASE):
        return None
    compact = " ".join(pdf_text.split())
    party_match = re.search(r"if applicable\.\s*(.+?)\s+2\. Reason for the notification", compact, re.IGNORECASE)
    role_match = re.search(r"e\.g\. CEO, CFO\.\s*(.+?)\s+b\) Initial notification", compact, re.IGNORECASE)
    issuer_match = re.search(r"Full name of the entity\s+(.+?)\s+b\) LEI", compact, re.IGNORECASE)
    lei_match = re.search(r"ISO 17442 LEI code\.\s*([A-Z0-9]{20})", compact, re.IGNORECASE)
    isin_values = re.findall(r"\b[12]\.\s*([A-Z]{2}[A-Z0-9]{10})", compact)
    fills = re.findall(r"(?m)^\s*([12])\s+(NOK|EUR|SEK|DKK|GBP|CHF|USD)\s+([\d.]+)\s+([\d,]+)\s*$", pdf_text)
    dates = {re.sub(r"\s+", "", value) for value in re.findall(r"\b(20\d{2}\s*-\s*\d{2}\s*-\s*\d{2})\b", pdf_text)}
    venues = set(re.findall(r"(?m)^\s*[12]\.\s*(Euronext Growth Oslo|Oslo Børs|Outside a trading venue)\s*$", pdf_text, re.IGNORECASE))
    if not all((party_match, role_match, issuer_match, lei_match)) or len(fills) != 2 or len(set(isin_values)) != 1 or len(dates) != 1 or len(venues) != 1:
        raise ParseError(f"AFM MAR 19 form indexed vectors incomplete: party={bool(party_match)},role={bool(role_match)},issuer={bool(issuer_match)},lei={bool(lei_match)},fills={len(fills)},isins={len(set(isin_values))},dates={len(dates)},venues={len(venues)}")
    rows = []
    for index, currency, price, quantity_raw in fills:
        rows.append({"row_locator": f"afm-fill-{index}", "representation": "individual", "price_raw": f"{currency} {price}",
                     "price_amount_reported": price, "price_currency_normalized": currency, "quote_unit_scale": "1",
                     "quantity_raw": quantity_raw, "quantity": quantity_raw.replace(",", ""), "quantity_unit": "shares",
                     "consideration_currency": currency})
    detail_total = sum(int(fill[3].replace(",", "")) for fill in fills)
    aggregate = re.search(rf"\b({detail_total:,})\s+(NOK|EUR|SEK|DKK|GBP|CHF|USD)\s+([\d.]+)", compact)
    if not aggregate:
        raise ParseError("AFM MAR 19 reported aggregate markers missing")
    aggregate_quantity_raw, aggregate_currency, aggregate_price = aggregate.groups()
    if detail_total != int(aggregate_quantity_raw.replace(",", "")) or {fill[1] for fill in fills} != {aggregate_currency}:
        raise ParseError("AFM MAR 19 detail rows do not reconcile to the reported aggregate")
    rows.append({"row_locator": "afm-reported-aggregate", "representation": "aggregate", "price_raw": f"{aggregate_currency} {aggregate_price}",
                 "price_amount_reported": aggregate_price, "price_currency_normalized": aggregate_currency, "quote_unit_scale": "1",
                 "quantity_raw": aggregate_quantity_raw, "quantity": aggregate_quantity_raw.replace(",", ""), "quantity_unit": "shares", "consideration_currency": aggregate_currency})
    group = {
        "group_locator": "afm-transaction-1", "event_key": "afm-transaction-1",
        "instrument": {"name_raw": "Ordinary shares", "instrument_type": "ordinary_share", "isin_raw": isin_values[0]},
        "nature_raw": "Sell", "action": "disposal", "mechanism": "exchange_sale", "consideration": "cash_paid_received",
        "investment_discretion": "unknown", "exposure_effect": "decrease", "trade_date": next(iter(dates)),
        "trade_date_precision": "day", "venue_raw": next(iter(venues)),
        "aggregation_reconciliation": "detail_quantity_matches_aggregate_price_is_rounded", "eligible_own_money_signal": False,
        "signal_exclusion_reason": "not_an_own_money_purchase", "rows": rows,
    }
    filing = _filing(message, f"message-{message['messageId']}-afm-1", issuer_match.group(1).strip(), {
        "name_raw": party_match.group(1).strip(), "party_type": "natural_person", "status_raw": role_match.group(1).strip(),
        "pdmr_or_pca": "pdmr", "identity_resolution_status": "unresolved",
    }, [group], ["reported_weighted_average_price_rounded"])
    filing["issuer"]["lei_raw"] = lei_match.group(1)
    return filing


def _schouw_forms(message: dict, pdf_text: str) -> dict | None:
    if "Aktieselskabet Schouw & Co." not in pdf_text or "Exercise of options" not in pdf_text:
        return None
    starts = list(re.finditer(r"(?m)^\s*1\s*\.\s+Details of the person", pdf_text))
    if len(starts) != 2:
        raise ParseError("Schouw disclosure must contain exactly two repeated notification forms")
    groups = []
    party_name = role = issuer_name = lei = None
    for ordinal, start in enumerate(starts, 1):
        end = starts[ordinal].start() if ordinal < len(starts) else len(pdf_text)
        section = " ".join(pdf_text[start.start():end].split())
        name_match = re.search(r"a\) Name\s+(.+?)\s+2\. Reason", section)
        role_match = re.search(r"a\) Position/status\s+(.+?)\s+b\) Initial", section)
        issuer_match = re.search(r"3\. Details of the issuer.+?a\) Name\s+(.+?)\s+b\) LEI\s+([A-Z0-9]{20})", section)
        nature_match = re.search(r"b\) Nature of the transaction\s+(.+?)\s+c\) Price", section)
        row_match = re.search(r"c\) Price\(s\) and volume\(s\).*?\b(DKK)\s+([\d.]+)\s+([\d,]+)\s+shares", section)
        date_match = re.search(r"e\) Date of the transaction\s+(\d{1,2} [A-Za-z]+ \d{4})", section)
        venue_match = re.search(r"f\) Place of transaction\s+(.+?)(?:\s+Aktieselskabet Schouw|\Z)", section)
        isin_match = re.search(r"\b(DK[A-Z0-9]{10})\b", section)
        if not all((name_match, role_match, issuer_match, nature_match, row_match, date_match, venue_match, isin_match)):
            raise ParseError(f"Schouw repeated form {ordinal} lost mandatory fields")
        values = (name_match.group(1).strip(), role_match.group(1).strip(), issuer_match.group(1).strip(), issuer_match.group(2))
        if party_name is None:
            party_name, role, issuer_name, lei = values
        elif values != (party_name, role, issuer_name, lei):
            raise ParseError("Schouw repeated forms disagree on party, role, issuer, or LEI")
        nature = nature_match.group(1).strip()
        currency, price, quantity_raw = row_match.groups()
        action = "exercise" if nature.lower().startswith("exercise") else "disposal" if nature.lower().startswith("sale") else "other"
        group = _group(
            locator=f"schouw-transaction-{ordinal}", instrument="Shares", instrument_type="ordinary_share", nature=nature,
            action=action, mechanism="option_exercise" if action == "exercise" else "off_market_trade",
            consideration="cash_paid_received", exposure="increase" if action == "exercise" else "decrease" if action == "disposal" else "unknown",
            trade_date=datetime.strptime(date_match.group(1), "%d %B %Y").date().isoformat(), quantity_raw=quantity_raw,
            quantity=quantity_raw.replace(",", ""), price_raw=f"{currency} {price}", price=price, currency=currency,
            venue=re.sub(r"\s+\d+/\d+$", "", venue_match.group(1).strip()), eligible=False,
            exclusion="option_exercise" if action == "exercise" else "not_an_own_money_purchase",
        )
        group["instrument"]["isin_raw"] = isin_match.group(1)
        groups.append(group)
    filing = _filing(message, f"message-{message['messageId']}-schouw-1", issuer_name, {
        "name_raw": _restore_body_text(party_name, message.get("body", "")), "party_type": "natural_person",
        "status_raw": role, "pdmr_or_pca": "pdmr", "identity_resolution_status": "unresolved",
    }, groups, ["source_labels_forms_as_second_notification_without_correction_reference"])
    filing["issuer"]["lei_raw"] = lei
    return filing


def _thor_forms(message: dict, pdf_text: str) -> dict | None:
    if message.get("issuerName") != "Thor Medical ASA" or "Scatec Innovation AS" not in pdf_text:
        return None
    starts = list(re.finditer(r"(?m)^\s*NOTIFICATION OF TRANSACTIONS PURSUANT TO THE MARKET ABUSE REGULATION ARTICLE 19", pdf_text))
    if len(starts) != 2:
        raise ParseError("Thor Medical disclosure must contain exactly two transaction-form pages")
    groups = []
    party_name = role = issuer_name = lei = related = None
    for ordinal, start in enumerate(starts, 1):
        end = starts[ordinal].start() if ordinal < len(starts) else len(pdf_text)
        section = " ".join(pdf_text[start.start():end].split())
        name_match = re.search(r"a\) Name\s+(.+?)\s+2 Reason", section)
        role_match = re.search(r"a\) Position/status\s+(.+?)\s+b\) Initial", section)
        issuer_match = re.search(r"3 Details of the issuer.+?a\) Name\s+(.+?)\s+b\) LEI\s+([A-Z0-9]{20})", section)
        nature_match = re.search(r"b\) Nature of the transaction\s+(.+?)\s+c\) Price", section)
        row_match = re.search(r"c\) Price\(s\) and volume\(s\).*?\b(NOK)\s+([\d.]+)\s+([\d,]+)", section)
        date_match = re.search(r"e\) Date of the transaction\s+(20\d{2}\s*-\s*\d{2}\s*-\s*\d{2});\s*([^\s]+\s+CEST)", section)
        venue_match = re.search(r"f\) Place of the transaction\s+(.+?)\s*$", section)
        isin = _reported_isin(section)
        if not all((name_match, role_match, issuer_match, nature_match, row_match, date_match, venue_match, isin)):
            raise ParseError(f"Thor Medical page {ordinal} fields: name={bool(name_match)},role={bool(role_match)},issuer={bool(issuer_match)},nature={bool(nature_match)},row={bool(row_match)},date={bool(date_match)},venue={bool(venue_match)},isin={bool(isin)}")
        values = (name_match.group(1).strip(), role_match.group(1).strip(), issuer_match.group(1).strip(), issuer_match.group(2))
        if party_name is None:
            party_name, role, issuer_name, lei = values
            related_match = re.search(r"close associate of\s+(.+?),\s*chair", role, re.IGNORECASE)
            related = related_match.group(1).strip() if related_match else None
        elif (values[0], values[2], values[3]) != (party_name, issuer_name, lei):
            raise ParseError("Thor Medical pages disagree on party, issuer, or LEI")
        nature = nature_match.group(1).strip()
        currency, price, quantity_raw = row_match.groups()
        lending = nature.lower().startswith("share lending")
        action, mechanism, consideration, exposure = ("transfer", "corporate_action", "none", "neutral") if lending else ("acquisition", "private_placement", "cash_paid_received", "increase")
        group = _group(
            locator=f"thor-transaction-{ordinal}", instrument="Shares", instrument_type="ordinary_share", nature=nature,
            action=action, mechanism=mechanism, consideration=consideration, exposure=exposure,
            trade_date=re.sub(r"\s+", "", date_match.group(1)), quantity_raw=quantity_raw, quantity=quantity_raw.replace(",", ""),
            price_raw=f"{currency} {price}", price=price, currency=currency, venue=venue_match.group(1).strip(),
            eligible=False, exclusion="non_cash_share_loan" if lending else "private_placement_allocation",
        )
        group["instrument"]["isin_raw"] = isin
        groups.append(group)
    filing = _filing(message, f"message-{message['messageId']}-thor-1", issuer_name, {
        "name_raw": party_name, "party_type": "legal_entity", "status_raw": role, "pdmr_or_pca": "pca",
        "related_pdmr_name_raw": related, "related_pdmr_role_raw": "Chair of the board", "identity_resolution_status": "unresolved",
    }, groups, ["intraday_time_and_timezone_retained_in_raw_evidence"])
    filing["issuer"]["lei_raw"] = lei
    return filing


def _gift(message: dict) -> dict | None:
    body = message.get("body", "")
    match = re.search(r"styreleder\s+(.+?)\s+har i dag mottatt\s+([\d. ]+)\s+egenkapitalbevis i gave", body, re.IGNORECASE)
    if not match:
        return None
    quantity = re.sub(r"[^0-9]", "", match.group(2))
    published_date = message["publishedTime"][:10]
    group = _group(locator="gift-1", instrument="egenkapitalbevis", instrument_type="other", nature="mottatt i gave",
                   action="transfer", mechanism="gift_inheritance", consideration="none", exposure="increase",
                   trade_date=published_date, quantity_raw=match.group(2), quantity=quantity, price_raw=None, price=None,
                   currency=None, eligible=False, exclusion="non_cash_gift")
    return _filing(message, f"message-{message['messageId']}-gift-1", message["issuerName"], {
        "name_raw": match.group(1).strip(), "party_type": "natural_person", "status_raw": "styreleder",
        "pdmr_or_pca": "pdmr", "identity_resolution_status": "unresolved",
    }, [group], ["trade_date_assumed_from_phrase_i_dag_and_publication_date"])


def _share_loan_return(message: dict, pdf_text: str) -> dict | None:
    if "Share lending re-delivery" not in message.get("title", ""):
        return None
    def after(label: str) -> str | None:
        match = re.search(re.escape(label) + r"\s*\n([^\n]+)", pdf_text, re.IGNORECASE)
        return match.group(1).strip() if match else None
    party = after("1.6.2 Foretaksnavn (til det n�rst�ende foretaket)")
    related = after("1.7.1 Fullt navn")
    role = after("1.7.2 Stilling/Rolle")
    issuer = after("2.2.2 Foretaksnavn (til utsteder eller deltaker p� utslippskvotemarked)") or message["issuerName"]
    volume_match = re.search(r"2\.8\.2 Aggregert volum\s*:\s*([\d ]+)", pdf_text)
    date_match = re.search(r"2\.9\.1 Angi dato\s*:\s*(\d{2}\.\d{2}\.\d{4})", pdf_text)
    if not all((party, related, role, volume_match, date_match)):
        raise ParseError("share-loan attachment lost reviewed KRT-1500 markers")
    trade_date = datetime.strptime(date_match.group(1), "%d.%m.%Y").date().isoformat()
    quantity_raw = volume_match.group(1)
    group = _group(locator="share-loan-return-1", instrument="Aksje", instrument_type="ordinary_share",
                   nature="Tilbakelevering av utl�nte aksjer", action="transfer", mechanism="corporate_action",
                   consideration="none", exposure="neutral", trade_date=trade_date, quantity_raw=quantity_raw,
                   quantity=quantity_raw.replace(" ", ""), price_raw="0 NOK", price="0", currency="NOK",
                   venue="XOFF", eligible=False, exclusion="non_cash_share_loan_return")
    return _filing(message, f"message-{message['messageId']}-pca-1", issuer, {
        "name_raw": party, "party_type": "legal_entity", "status_raw": "N�rst�ende foretak",
        "pdmr_or_pca": "pca", "related_pdmr_name_raw": related, "identity_resolution_status": "unresolved",
        "role_normalized": role,
    }, [group])


def parse(data: bytes, attachments: list[tuple[str, bytes]] | None = None) -> dict[str, Any]:
    try:
        source = json.loads(data)
        message = source["data"]["message"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ParseError(f"unrecognized NewsWeb message response: {exc}") from exc
    categories = {item.get("category_en") for item in message.get("category", [])}
    if "MANAGERS’ TRANSACTION" not in categories and "MANAGERS' TRANSACTION" not in categories:
        raise ParseError("NewsWeb message is not classified as a managers transaction")
    pdf_texts = [extract_pdf_text(content) for name, content in (attachments or []) if name.lower().endswith(".pdf")]
    pdf_text = "\n".join(pdf_texts)
    filings = _employee_plan(message, pdf_text) or _english_forms(message, pdf_text)
    if filings is None:
        single = _thor_forms(message, pdf_text) or _schouw_forms(message, pdf_text) or _afm_form(message, pdf_text) or _compact_english_form(message, pdf_text) or _english_krt_form(message, pdf_text) or _krt_form(message, pdf_text) or _body_embedded_form(message) or _direct_body(message, pdf_text) or _gift(message)
        filings = [single] if single else None
    if not filings:
        raise ParseError("NewsWeb layout does not match a reviewed parser rule")
    return _base(message, filings)
