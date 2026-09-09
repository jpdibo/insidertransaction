from __future__ import annotations

import hashlib
import json
from typing import Any

PARSER_VERSION = "fixture-json-v1"
ALLOWED_ACTIONS = {
    "acquisition", "disposal", "grant", "exercise", "conversion", "transfer",
    "pledge", "release", "lapse", "cancellation", "other", "unknown",
}


class ParseError(ValueError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def parse(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"invalid UTF-8 JSON: {exc}") from exc
    if payload.get("schema_version") != "1.0":
        raise ParseError("unknown fixture layout/schema version")
    if payload.get("fixture_kind") not in {"synthetic", "real"}:
        raise ParseError("fixture_kind must be synthetic or real")
    if not isinstance(payload.get("filings"), list) or not payload["filings"]:
        raise ParseError("at least one filing is required")
    for filing in payload["filings"]:
        for field in ("source_locator", "notification_status", "issuer", "transacting_party"):
            if field not in filing:
                raise ParseError(f"filing missing {field}")
        if not filing.get("transaction_groups"):
            raise ParseError("filing has no transaction_groups")
        for group in filing["transaction_groups"]:
            if group.get("action") not in ALLOWED_ACTIONS:
                raise ParseError(f"unsupported action: {group.get('action')}")
            if not group.get("rows"):
                raise ParseError("transaction group has no rows")
    return payload
