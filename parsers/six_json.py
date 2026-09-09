from __future__ import annotations

import json
from datetime import datetime

from parsers.fixture_json import ParseError


PARSER_VERSION = "six-management-v2"

SECURITIES = {
    "2": ("Conversion rights", "convertible"),
    "4": ("Call options", "option"),
    "5": ("Put options", "option"),
    "6": ("Bearer shares", "ordinary_share"),
    "7": ("Registered shares", "ordinary_share"),
    "99": ("Other securities", "other"),
}
ROLES = {
    "1": "Executive board member / senior management",
    "2": "Non-executive board member",
    "3": "Sponsor / founding shareholder of the SPAC",
}


def parse(data: bytes) -> dict:
    try:
        payload = json.loads(data, parse_float=str)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError("SIX response is not valid JSON") from exc
    items = payload.get("itemList")
    if payload.get("status") != "Ok" or payload.get("totalCount") != 1 or not isinstance(items, list) or len(items) != 1:
        raise ParseError("SIX detail response contract changed")
    item = items[0]
    required = ("notificationId", "notificationSubmitter", "transactionDate", "buySellIndicator", "securityTypeCode")
    if any(item.get(field) in (None, "") for field in required):
        raise ParseError("SIX detail response lacks required fields")
    notification_id = str(item["notificationId"])
    date_raw = str(item["transactionDate"])
    try:
        trade_date = datetime.strptime(date_raw, "%Y%m%d").date().isoformat()
    except ValueError as exc:
        raise ParseError("SIX transaction date is invalid") from exc
    action_code = str(item["buySellIndicator"])
    action = {"1": "acquisition", "2": "disposal", "3": "grant"}.get(action_code, "other")
    nature = {"1": "Purchase", "2": "Sale", "3": "Granting/Writing"}.get(action_code, f"Code {action_code}")
    security_name, instrument_type = SECURITIES.get(str(item["securityTypeCode"]), (f"Security code {item['securityTypeCode']}", "other"))
    description = str(item.get("securityDescription") or "").strip()
    instrument_name = f"{security_name}: {description}" if description else security_name
    related_code = str(item.get("obligorRelatedPartyInd") or "")
    role = ROLES.get(str(item.get("obligorFunctionCode") or ""), "Undisclosed management role")
    is_related = related_code in {"I", "L"}
    correctee = str(item.get("correcteeId") or "")
    source_url = f"https://www.ser-ag.com/sheldon/management_transactions/v1/overview.json?notificationId={notification_id}"
    return {
        "schema_version": "1.0",
        "source": {"native_record_id": notification_id, "url": source_url, "published_date": trade_date},
        "filings": [{
            "source_locator": notification_id,
            "native_notification_reference": correctee or notification_id,
            "notification_status": "correction" if correctee else "initial",
            "amends_native_reference": correctee or None,
            "issuer": {"name_raw": str(item["notificationSubmitter"]), "lei_raw": None},
            "transacting_party": {
                "party_type": "anonymous_role", "status_raw": role,
                "pdmr_or_pca": "pca" if is_related else "anonymous",
                "identity_resolution_status": "unavailable_by_regime",
            },
            "transaction_groups": [{
                "group_locator": notification_id, "event_key": notification_id,
                "instrument": {"name_raw": instrument_name, "isin_raw": item.get("ISIN") or None, "instrument_type": instrument_type},
                "nature_raw": nature, "action": action,
                "mechanism": "unknown", "consideration": "unknown",
                "investment_discretion": "unavailable_by_regime", "exposure_effect": "increase" if action == "acquisition" else "decrease" if action == "disposal" else "unknown",
                "trade_date": trade_date, "trade_date_precision": "day", "venue_raw": "SIX Swiss Exchange" if item.get("swxListed") == "T" else None,
                "venue_mic": "XSWX" if item.get("swxListed") == "T" else None,
                "aggregation_reconciliation": "not_applicable", "eligible_own_money_signal": False,
                "signal_exclusion_reason": "party_identity_unavailable_by_regime",
                "rows": [{
                    "row_locator": f"{notification_id}-row-1", "representation": "aggregate",
                    "price_raw": str(item.get("transactionAmountPerSecurityCHF")) if item.get("transactionAmountPerSecurityCHF") is not None else None,
                    "price_amount_reported": item.get("transactionAmountPerSecurityCHF"), "price_currency_normalized": "CHF",
                    "quote_unit_scale": "1", "quantity_raw": str(item.get("transactionSize")) if item.get("transactionSize") is not None else None,
                    "quantity": item.get("transactionSize"), "quantity_unit": "securities",
                    "consideration_reported": item.get("transactionAmountCHF"), "consideration_currency": "CHF",
                }],
            }],
        }],
    }
