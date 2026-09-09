from __future__ import annotations

import html
import re
from datetime import date, datetime

from .fixture_json import ParseError


PARSER_VERSION = "unternehmensregister-html-v6"


def _visible(data: bytes) -> str:
    try:
        page = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("Unternehmensregister detail is not UTF-8") from exc
    page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.DOTALL | re.IGNORECASE)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).replace("\xa0", " ").split())


def _field(pattern: str, text: str, name: str, *, required: bool = True) -> str | None:
    match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if match:
        return " ".join(match.group(1).split())
    if required:
        raise ParseError(f"Unternehmensregister field missing: {name}")
    return None


def parse(data: bytes, metadata: dict) -> dict:
    text = _visible(data)
    english = "Details of the person discharging managerial responsibilities" in text
    numbered_english = english and "Position / status" in text
    if numbered_english:
        first_name = _field(r"First name:\s*(.*?)\s+Last name\(s\):", text, "first name")
        last_name = _field(r"Last name\(s\):\s*(.*?)\s+2\. Reason for the notification", text, "last name")
        party = f"{first_name} {last_name}"
        role = _field(r"Position / status\s+Position:\s*(.*?)\s+b\) Initial notification", text, "role")
        status = "Amendment" if re.search(r"b\) Amendment", text, re.IGNORECASE) else "Initial notification"
        issuer_section = _field(r"3\. Details of the issuer.*?a\) Name\s+(.*?)\s+4\. Details of the transaction", text, "issuer section")
        issuer = _field(r"^(.*?)\s+b\) LEI", issuer_section, "issuer")
        lei = _field(r"b\) LEI\s+([A-Z0-9]{20})", issuer_section, "LEI", required=False)
        instrument = _field(r"a\) Description of the financial instrument.*?Type:\s*(.*?)\s+ISIN:", text, "instrument")
        isin = _field(r"ISIN:\s*([A-Z]{2}[A-Z0-9]{10})", text, "ISIN", required=False)
        nature = _field(r"b\) Nature of the transaction\s+(.*?)\s+c\) Price", text, "nature")
        date_raw = _field(r"e\) Date of the transaction\s+(\d{4}-\d{2}-\d{2})", text, "trade date")
        trade_date = date.fromisoformat(date_raw).isoformat()
        venue = _field(r"f\) Place of the transaction\s+(.*?)(?:\s+\d{2}\.\d{2}\.\d{4}\s+The DGAP|\s+Further information|\s+Information about mandatory publication|$)", text, "venue")
        aggregate = re.search(r"d\) Aggregated information\s+Price\s+Aggregated volume\s+(.+?\b[A-Z]{3})\s+(.+?\b[A-Z]{3})\s+e\) Date", text, re.IGNORECASE)
        aggregate_price_raw, aggregate_quantity_raw = aggregate.groups() if aggregate else (None, None)
    else:
        party = _field(r"Details of the person.*?Name:\s*(.*?)\s+Reason for the notification" if english else r"Angaben zu den Personen.*?Name:\s*(.*?)\s+Grund der Meldung", text, "party")
        role = _field(r"Position/status:\s*(.*?)\s+b\) Initial notification/\s*Amendment" if english else r"Position/Status:\s*(.*?)\s+b\) Erstmeldung/Berichtigung", text, "role")
        status = _field(r"Initial notification/\s*Amendment:\s*(.*?)\s+Details of issuer" if english else r"Erstmeldung/Berichtigung:\s*(.*?)\s+Angaben zum Emittenten", text, "status")
        issuer_section = _field(r"Details of issuer\s+Name:\s*(.*?)\s+Details of the transaction" if english else r"Angaben zum Emittenten\s+Name:\s*(.*?)\s+Angaben zum Geschäft", text, "issuer section")
        issuer = _field(r"^(.*?)\s+(?:Address:|Country:|LEI:)" if english else r"^(.*?)\s+(?:Adresse:|Staat:|LEI:)", issuer_section, "issuer")
        lei = _field(r"LEI:\s*([A-Z0-9]{20})", issuer_section, "LEI", required=False)
        instrument = _field(r"Type of instrument:\s*(.*?)\s+Identification code:" if english else r"Art des Instruments:\s*(.*?)\s+Kennung:", text, "instrument")
        isin = _field(r"Identification code:\s*([A-Z]{2}[A-Z0-9]{10})" if english else r"Kennung:\s*([A-Z]{2}[A-Z0-9]{10})", text, "ISIN", required=False)
        nature = _field(r"b\) Nature of the transaction:\s*(.*?)\s+c\) Price" if english else r"b\) Art des Geschäfts:\s*(.*?)\s+c\) Preis", text, "nature")
        date_raw = _field(r"e\) Date of the transaction:\s*(\d{2}\.\d{2}\.\d{4})" if english else r"e\) Datum des Geschäfts:\s*(\d{2}\.\d{2}\.\d{4})", text, "trade date")
        trade_date = datetime.strptime(date_raw, "%d.%m.%Y").date().isoformat()
        venue = _field(r"f\) Place of the transaction:\s*(.*?)\s+(?:Further information|Information about mandatory publication)" if english else r"f\) Ort des Geschäfts:\s*(.*?)\s+(?:Weitere Angaben|Angaben zur Pflichtmitteilung)", text, "venue")
        aggregate_quantity_raw = _field(r"Aggregated volume:\s*(.*?)\s+Price:" if english else r"Aggregiertes Volumen:\s*(.*?)\s+Preis:", text, "aggregate quantity", required=False)
        aggregate_price_raw = _field(r"Aggregated volume:.*?Price:\s*(.*?)\s+e\) Date" if english else r"Aggregiertes Volumen:.*?Preis:\s*(.*?)\s+e\) Datum", text, "aggregate price", required=False)
    def decimal_value(value: str | None) -> str | None:
        if not value or "nicht bezifferbar" in value.lower():
            return None
        match = re.search(r"[-+]?\d[\d .]*(?:,\d+)?", value)
        return match.group(0).replace(" ", "").replace(".", "").replace(",", ".") if match else None
    quantity = decimal_value(aggregate_quantity_raw)
    price = decimal_value(aggregate_price_raw)
    currency_match = re.search(r"\b(EUR|USD|GBP|CHF|SEK|NOK|DKK)\b", aggregate_price_raw or "")
    currency = currency_match.group(1) if currency_match else None
    ambiguous_aggregate = bool(re.search(r"\b(EUR|USD|GBP|CHF|SEK|NOK|DKK)\b", aggregate_quantity_raw or ""))
    if ambiguous_aggregate:
        quantity = None
        price = None
    if re.search(r"Schenkung|Gift", nature, re.IGNORECASE):
        action = "gift"
    elif re.search(r"Gewährung|Zuteilung|Begebung|Grant", nature, re.IGNORECASE):
        action = "grant"
    elif re.search(r"\b(?:Verkauf|Veräußerung|Sale|Disposal)\b", nature, re.IGNORECASE):
        action = "disposal"
    elif re.search(r"\b(?:Kauf|Erwerb|Purchase|Acquisition)\b", nature, re.IGNORECASE):
        action = "acquisition"
    else:
        action = "other"
    entity_pattern = r"\b(?:AG|Aktiengesellschaft|GmbH|SE|KG|OHG|UG|Ltd|Limited|PLC|S\.A\.?|B\.V\.?|PTE\.?)\b"
    party_type = "legal_entity" if re.search(entity_pattern, party, re.IGNORECASE) else "natural_person"
    is_pca = bool(re.search(r"enger?\s+Beziehung|closely associated", role, re.IGNORECASE))
    underlying_match = re.search(r"\bunderlying\b.*?\bISIN\s*:?[ ]*([A-Z]{2}[A-Z0-9]{10})", text, re.IGNORECASE)
    underlying_isin = underlying_match.group(1) if underlying_match else None
    mic_match = re.search(r"\bMIC\s*:\s*([A-Z0-9]{4})\b", venue, re.IGNORECASE)
    venue_mic = mic_match.group(1).upper() if mic_match else None
    reference = metadata["native_record_id"]
    exposure = "increase" if action == "acquisition" or (action == "gift" and re.search(r"\b(?:erhalten|Zugang)\b", nature, re.IGNORECASE)) else "decrease" if action == "disposal" or (action == "gift" and re.search(r"Schenkung.*\ban\b", nature, re.IGNORECASE)) else "unknown"
    return {"schema_version": "1.0", "source": {"native_record_id": reference, "url": metadata["url"], "published_date": metadata.get("published_date")},
            "filings": [{"source_locator": reference, "notification_status": "correction" if re.search(r"Berichtigung|Amendment", status, re.IGNORECASE) else "initial",
                         "issuer": {"name_raw": issuer, "lei_raw": lei},
                          "transacting_party": {"name_raw": party, "party_type": party_type, "status_raw": role,
                                                "pdmr_or_pca": "pca" if is_pca else "pdmr", "identity_resolution_status": "unresolved"},
                         "quality_issues": ["archive_aggregate_labels_semantically_ambiguous"] if ambiguous_aggregate else [],
                         "transaction_groups": [{"group_locator": "transaction-1", "event_key": "transaction-1",
                                                 "instrument": {"name_raw": instrument, "isin_raw": isin, "underlying_isin_raw": underlying_isin,
                                                                "instrument_type": "ordinary_share" if re.search(r"Aktie|Share", instrument, re.IGNORECASE) else "other"},
                                                 "nature_raw": nature, "action": action, "mechanism": "unknown", "consideration": "unknown",
                                                 "investment_discretion": "unknown", "exposure_effect": exposure,
                                                 "trade_date": trade_date, "trade_date_precision": "day", "venue_raw": venue,
                                                 "venue_mic": venue_mic,
                                                 "aggregation_reconciliation": "aggregate_only", "eligible_own_money_signal": False,
                                                 "signal_exclusion_reason": "archive_aggregate_only",
                                                 "rows": [{"row_locator": "aggregate-row-1", "representation": "aggregate", "price_raw": aggregate_price_raw,
                                                           "price_amount_reported": price, "price_currency_normalized": currency, "quote_unit_scale": "1",
                                                           "quantity_raw": aggregate_quantity_raw, "quantity": quantity, "quantity_unit": None,
                                                           "consideration_currency": currency}]}]}]}
