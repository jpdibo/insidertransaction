from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ingestion.fixture import FixtureAdapter
from ingestion.bafin import BafinAdapter
from ingestion.newsweb import NewsWebAdapter
from ingestion.sweden_fi import SwedenFiAdapter
from ingestion.six import SixAdapter
from ingestion.amf import AmfAdapter
from ingestion.unternehmensregister import UnternehmensregisterAdapter
from ingestion.nl_afm import NlAfmAdapter
from ingestion.denmark_oam import DenmarkOamAdapter
from parsers.fixture_json import PARSER_VERSION, ParseError, canonical_json, content_hash, parse
from parsers.bafin_html import PARSER_VERSION as BAFIN_PARSER_VERSION, parse as parse_bafin
from parsers.newsweb_json import PARSER_VERSION as NEWSWEB_PARSER_VERSION, parse as parse_newsweb
from parsers.sweden_fi_html import PARSER_VERSION as SWEDEN_PARSER_VERSION, parse as parse_sweden
from parsers.six_json import PARSER_VERSION as SIX_PARSER_VERSION, parse as parse_six
from parsers.amf_pdf import PARSER_VERSION as AMF_PARSER_VERSION, parse as parse_amf
from parsers.unternehmensregister_html import PARSER_VERSION as UREG_PARSER_VERSION, parse as parse_ureg
from parsers.nl_afm_html import PARSER_VERSION as NL_AFM_PARSER_VERSION, parse as parse_nl_afm
from parsers.denmark_oam_json import PARSER_VERSION as DK_OAM_PARSER_VERSION, parse as parse_denmark_oam

from . import __version__
from .config import config_hash
from .db import transaction
from .numbers import canonical_decimal, multiply
from .storage import store_raw


@dataclass
class SourceResult:
    source_id: str
    state: str = "accepted"
    discovered: int = 0
    unchanged: int = 0
    accepted: int = 0
    amended: int = 0
    quarantined: int = 0
    error: str | None = None


@dataclass
class DailyResult:
    run_id: str
    status: str
    cutoff: str
    sources: list[SourceResult] = field(default_factory=list)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def recover_abandoned_runs(connection: sqlite3.Connection) -> int:
    rows = connection.execute("SELECT id FROM ingestion_runs WHERE status='running'").fetchall()
    if not rows:
        return 0
    recovered_at = utc_now()
    with transaction(connection):
        connection.execute(
            "UPDATE run_tasks SET state='interrupted',error=COALESCE(error,'abandoned run recovered after writer-lock acquisition') "
            "WHERE state='running' AND run_id IN (SELECT id FROM ingestion_runs WHERE status='running')"
        )
        connection.execute(
            "UPDATE ingestion_runs SET status='interrupted',finished_at=? WHERE status='running'", (recovered_at,)
        )
    return len(rows)


def reconcile_cross_source_duplicates(connection: sqlite3.Connection, *, dry_run: bool = False) -> int:
    candidates = connection.execute(
        "WITH current_events AS ("
        "SELECT e.id AS event_id,ev.accepted_content_hash,("
        "SELECT MIN(sr.source_id) FROM filing_publications fp "
        "JOIN source_records sr ON sr.id=fp.source_record_id WHERE fp.filing_version_id=ev.filing_version_id"
        ") AS source_id FROM economic_events e JOIN event_versions ev ON ev.id=e.current_version_id) "
        "SELECT a.event_id AS left_event_id,b.event_id AS right_event_id,a.source_id AS left_source,b.source_id AS right_source "
        "FROM current_events a JOIN current_events b ON a.event_id<b.event_id "
        "AND a.accepted_content_hash=b.accepted_content_hash AND a.source_id<>b.source_id"
    ).fetchall()
    if dry_run or not candidates:
        return len(candidates)
    now = utc_now()
    with transaction(connection):
        for row in candidates:
            connection.execute(
                "INSERT OR IGNORE INTO event_links(left_event_id,right_event_id,link_type,confidence,review_state,evidence_json,created_at) "
                "VALUES(?,?,'potential_duplicate','exact_normalized_content','pending',?,?)",
                (row["left_event_id"], row["right_event_id"], json.dumps({
                    "left_source": row["left_source"], "right_source": row["right_source"],
                    "basis": "accepted_content_hash",
                }, sort_keys=True), now),
            )
    return len(candidates)


def seed_registry(connection: sqlite3.Connection, config: dict[str, Any], config_digest: str) -> None:
    with transaction(connection):
        for jurisdiction in config["jurisdictions"]:
            connection.execute(
                "INSERT INTO jurisdictions(code,name,regime_family) VALUES(?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET name=excluded.name, regime_family=excluded.regime_family",
                (jurisdiction["code"], jurisdiction["name"], jurisdiction["regime_family"]),
            )
        for rule in config.get("rules", []):
            connection.execute(
                "INSERT OR IGNORE INTO rule_versions(jurisdiction_code,effective_from,effective_to,annual_threshold_decimal,threshold_currency,legal_source_url,verified_at) VALUES(?,?,?,?,?,?,?)",
                (rule["jurisdiction"], rule["effective_from"], rule.get("effective_to"), rule.get("annual_threshold_decimal"),
                 rule.get("threshold_currency"), rule["legal_source_url"], rule.get("verified_at")),
            )
        for source in config["sources"]:
            connection.execute(
                "INSERT INTO sources(source_id,jurisdiction_code,name,public_url,submission_url,adapter,status,required,rights_status,last_verified_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
                "name=excluded.name,public_url=excluded.public_url,submission_url=excluded.submission_url,adapter=excluded.adapter,"
                "status=excluded.status,required=excluded.required,rights_status=excluded.rights_status,last_verified_at=excluded.last_verified_at",
                (source["source_id"], source["jurisdiction"], source["name"], source["public_url"],
                 source.get("submission_url"), source["adapter"], source["status"], int(source.get("required", False)),
                 source["rights_status"], source.get("last_verified_at")),
            )
            connection.execute(
                "INSERT OR IGNORE INTO source_versions(source_id,version,config_hash,effective_from,capabilities_json) VALUES(?,?,?,?,?)",
                (source["source_id"], source["version"], config_digest, config["effective_from"],
                 json.dumps(source.get("capabilities", {}), sort_keys=True)),
            )


def _stable_id(prefix: str, *parts: str) -> str:
    value = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(value).hexdigest()[:24]}"


def _upsert_source_document(
    connection: sqlite3.Connection, run_id: str, source: dict[str, Any], payload: dict[str, Any],
    data: bytes, raw_root: Path, parser_version: str, suffix: str = ".json", mime_type: str = "application/json",
) -> tuple[int, int, bool]:
    source_meta = payload["source"]
    digest, relative, size = store_raw(data, raw_root, suffix)
    if source["source_id"] == "nl_afm_mar19":
        try:
            metadata = source_meta.get("metadata", {})
            normalized = parse_nl_afm(data, {"native_record_id": source_meta["native_record_id"],
                                             "url": source_meta["url"], **metadata})
            semantic_digest = hashlib.sha256(canonical_json(normalized["filings"])).hexdigest()
        except ParseError:
            semantic_digest = digest
    else:
        try:
            decoded = json.loads(data)
            semantic_content = decoded["data"] if isinstance(decoded, dict) and "data" in decoded and "header" in decoded else decoded
            semantic_digest = hashlib.sha256(canonical_json(semantic_content)).hexdigest()
        except (UnicodeDecodeError, json.JSONDecodeError):
            if source["source_id"] == "de_unternehmensregister_archive":
                page = data.decode("utf-8")
                page = re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.DOTALL | re.IGNORECASE)
                visible = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).replace("\xa0", " ").split())
                semantic_digest = hashlib.sha256(visible.encode("utf-8")).hexdigest()
            else:
                semantic_digest = digest
    now = utc_now()
    with transaction(connection):
        connection.execute(
            "INSERT INTO source_records(source_id,native_record_id,canonical_url,published_at,published_date,source_updated_at,status,metadata_json) "
            "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_id,native_record_id) DO UPDATE SET canonical_url=excluded.canonical_url, "
            "source_updated_at=excluded.source_updated_at,status=excluded.status,metadata_json=excluded.metadata_json",
            (source["source_id"], source_meta["native_record_id"], source_meta["url"], source_meta.get("published_at"),
             source_meta.get("published_date"), source_meta.get("source_updated_at"), "fetched",
             json.dumps(source_meta.get("metadata", {}), sort_keys=True)),
        )
        record_id = connection.execute(
            "SELECT id FROM source_records WHERE source_id=? AND native_record_id=?",
            (source["source_id"], source_meta["native_record_id"]),
        ).fetchone()["id"]
        connection.execute(
            "INSERT OR IGNORE INTO raw_objects(sha256,relative_path,mime_type,encoding,size_bytes,first_retrieved_at) VALUES(?,?,?,?,?,?)",
            (digest, relative, mime_type, "utf-8", size, now),
        )
        existing = connection.execute(
            "SELECT id,semantic_sha256 FROM document_versions WHERE source_record_id=? AND semantic_sha256=? ORDER BY id LIMIT 1",
            (record_id, semantic_digest),
        ).fetchone()
        if not existing:
            existing = connection.execute(
                "SELECT id,semantic_sha256 FROM document_versions WHERE source_record_id=? AND raw_sha256=? ORDER BY id LIMIT 1",
                (record_id, digest),
            ).fetchone()
            if existing and existing["semantic_sha256"] != semantic_digest:
                connection.execute("UPDATE document_versions SET semantic_sha256=? WHERE id=?", (semantic_digest, existing["id"]))
        unchanged = existing is not None
        if existing:
            document_id = existing["id"]
        else:
            ordinal = connection.execute(
                "SELECT COALESCE(MAX(version_ordinal),0)+1 AS n FROM document_versions WHERE source_record_id=?", (record_id,)
            ).fetchone()["n"]
            cursor = connection.execute(
                "INSERT INTO document_versions(source_record_id,raw_sha256,version_ordinal,retrieved_at,parser_hint,semantic_sha256) VALUES(?,?,?,?,?,?)",
                (record_id, digest, ordinal, now, parser_version, semantic_digest),
            )
            document_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO fetch_attempts(source_record_id,run_id,attempted_at,http_status,disposition) VALUES(?,?,?,?,?)",
            (record_id, run_id, now, 200, "unchanged" if unchanged else "stored"),
        )
    return record_id, document_id, unchanged


def _party(connection: sqlite3.Connection, source_id: str, filing_ref: str, party: dict[str, Any]) -> str:
    if party["party_type"] == "anonymous_role":
        party_id = _stable_id("anon", source_id, filing_ref, party.get("status_raw", "anonymous"))
        canonical_name = None
    else:
        party_id = _stable_id("party", source_id, filing_ref, party["name_raw"])
        canonical_name = party["name_raw"]
    connection.execute(
        "INSERT INTO parties(id,party_type,canonical_name,identity_status) VALUES(?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET party_type=excluded.party_type, "
        "canonical_name=COALESCE(parties.canonical_name,excluded.canonical_name)",
        (party_id, party["party_type"], canonical_name, party.get("identity_resolution_status", "unresolved")),
    )
    connection.execute(
        "INSERT OR IGNORE INTO party_aliases(party_id,name_raw,source_id) VALUES(?,?,?)",
        (party_id, party.get("name_raw", party.get("status_raw", "Anonymous disclosed role")), source_id),
    )
    return party_id


def _accept_payload(
    connection: sqlite3.Connection, source: dict[str, Any], record_id: int, document_id: int,
    payload: dict[str, Any], manifest_hash: str, parser_version: str,
) -> tuple[int, int]:
    accepted = amended = 0
    now = utc_now()
    extraction_hash = content_hash(payload["filings"])
    with transaction(connection):
        connection.execute(
            "INSERT OR IGNORE INTO extraction_runs(document_version_id,parser_version,config_hash,input_manifest_hash,normalized_hash,status,started_at,finished_at) "
            "VALUES(?,?,?,?,?,'accepted',?,?)",
            (document_id, parser_version, source["version"], manifest_hash, extraction_hash, now, now),
        )
        for filing in sorted(payload["filings"], key=lambda value: value["source_locator"]):
            issuer = filing["issuer"]
            lei = issuer.get("lei_raw") if re.fullmatch(r"[A-Z0-9]{20}", issuer.get("lei_raw") or "") else None
            issuer_key = lei or issuer["name_raw"]
            issuer_id = _stable_id("issuer", issuer_key)
            connection.execute(
                "INSERT OR IGNORE INTO issuers(id,legal_name,domicile_code,status) VALUES(?,?,?,'active')",
                (issuer_id, issuer["name_raw"], source["jurisdiction"]),
            )
            if lei:
                connection.execute(
                    "INSERT OR IGNORE INTO issuer_identifiers(issuer_id,scheme,value,evidence_url) VALUES(?,'LEI',?,?)",
                    (issuer_id, lei, payload["source"]["url"]),
                )
            filing_reference = filing.get("native_notification_reference")
            amends_reference = filing.get("amends_native_reference")
            filing_id = None
            if amends_reference:
                original = connection.execute(
                    "SELECT fv.filing_id FROM filing_versions fv "
                    "JOIN filing_publications fp ON fp.filing_version_id=fv.id "
                    "JOIN source_records sr ON sr.id=fp.source_record_id "
                    "WHERE sr.source_id=? AND sr.native_record_id=? ORDER BY fv.id LIMIT 1",
                    (source["source_id"], amends_reference),
                ).fetchone()
                filing_id = original["filing_id"] if original else None
            if filing_id is None and not amends_reference:
                later_correction = connection.execute(
                    "SELECT fv.filing_id FROM filing_versions fv JOIN filings f ON f.id=fv.filing_id "
                    "WHERE fv.amends_reference=? AND f.id IN ("
                    "SELECT fv2.filing_id FROM filing_versions fv2 JOIN filing_publications fp ON fp.filing_version_id=fv2.id "
                    "JOIN source_records sr ON sr.id=fp.source_record_id WHERE sr.source_id=?) "
                    "ORDER BY fv.id LIMIT 1",
                    (payload["source"]["native_record_id"], source["source_id"]),
                ).fetchone()
                filing_id = later_correction["filing_id"] if later_correction else None
            if filing_id is None:
                identity_reference = filing_reference or amends_reference
                filing_id = _stable_id("filing", source["source_id"], identity_reference) if identity_reference else _stable_id(
                    "filing", source["source_id"], payload["source"]["native_record_id"], filing["source_locator"]
                )
            filing_hash = content_hash(filing)
            connection.execute(
                "INSERT OR IGNORE INTO filings(id,issuer_id,source_scoped_reference) VALUES(?,?,?)",
                (filing_id, issuer_id, filing["source_locator"]),
            )
            existing = connection.execute(
                "SELECT id FROM filing_versions WHERE filing_id=? AND content_hash=?", (filing_id, filing_hash)
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE filing_versions SET issuer_name_raw=COALESCE(issuer_name_raw,?) WHERE id=?",
                    (issuer["name_raw"], existing["id"]),
                )
                for group in filing["transaction_groups"]:
                    connection.execute(
                        "UPDATE transaction_groups SET instrument_name_raw=COALESCE(instrument_name_raw,?),"
                        "underlying_isin_raw=COALESCE(underlying_isin_raw,?) "
                        "WHERE filing_version_id=? AND group_locator=?",
                        (group["instrument"]["name_raw"], group["instrument"].get("underlying_isin_raw"),
                         existing["id"], group["group_locator"]),
                    )
                publication_rank = connection.execute(
                    "SELECT COALESCE(MAX(publication_rank),0)+1 FROM filing_publications WHERE filing_version_id=?",
                    (existing["id"],),
                ).fetchone()[0]
                connection.execute(
                    "INSERT OR IGNORE INTO filing_publications(filing_version_id,source_record_id,publication_rank,confidence) VALUES(?,?,?,'native')",
                    (existing["id"], record_id, publication_rank),
                )
                continue
            current_filing = connection.execute(
                "SELECT fv.notification_status FROM filings f LEFT JOIN filing_versions fv ON fv.id=f.current_version_id WHERE f.id=?",
                (filing_id,),
            ).fetchone()
            candidate_is_correction = filing["notification_status"] in {"amended", "correction", "corrected"}
            current_is_correction = bool(current_filing and current_filing["notification_status"] in {"amended", "correction", "corrected"})
            promote_current = not current_filing or current_filing["notification_status"] is None or candidate_is_correction or not current_is_correction
            version_number = connection.execute(
                "SELECT COALESCE(MAX(version_number),0)+1 AS n FROM filing_versions WHERE filing_id=?", (filing_id,)
            ).fetchone()["n"]
            cursor = connection.execute(
                "INSERT INTO filing_versions(filing_id,version_number,notification_status,amends_reference,source_locator,issuer_received_at,accepted_at,content_hash,issuer_name_raw) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (filing_id, version_number, filing["notification_status"], filing.get("amends_native_reference"),
                 filing["source_locator"], filing.get("issuer_received_at"), now, filing_hash, issuer["name_raw"]),
            )
            filing_version_id = cursor.lastrowid
            if promote_current:
                connection.execute("UPDATE filings SET current_version_id=? WHERE id=?", (filing_version_id, filing_id))
            connection.execute(
                "INSERT INTO filing_publications(filing_version_id,source_record_id,publication_rank,confidence) VALUES(?,?,1,'native')",
                (filing_version_id, record_id),
            )
            for issue in filing.get("quality_issues", []):
                code = issue.split(":", 1)[0]
                connection.execute(
                    "INSERT INTO quality_issues(entity_type,entity_id,code,severity,status,details) VALUES('filing_version',?,?,'warning','open',?)",
                    (str(filing_version_id), code, issue),
                )
            party_id = _party(connection, source["source_id"], filing_id, filing["transacting_party"])
            related_party_id = None
            if filing["transacting_party"].get("related_pdmr_name_raw"):
                related_party_id = _party(connection, source["source_id"], filing_id + ":related", {
                    "name_raw": filing["transacting_party"]["related_pdmr_name_raw"], "party_type": "natural_person",
                    "identity_resolution_status": "unresolved",
                })
            connection.execute(
                "INSERT OR IGNORE INTO issuer_roles(party_id,issuer_id,raw_title,normalized_role,pdmr_or_pca,evidence_url) VALUES(?,?,?,?,?,?)",
                (party_id, issuer_id, filing["transacting_party"].get("status_raw"),
                 filing["transacting_party"].get("role_normalized"), filing["transacting_party"].get("pdmr_or_pca", "unknown"),
                 payload["source"]["url"]),
            )
            if related_party_id:
                connection.execute(
                    "INSERT OR IGNORE INTO party_relationships(from_party_id,to_party_id,issuer_id,relationship_type,evidence_url,review_state) VALUES(?,?,?,?,?,'reported')",
                    (party_id, related_party_id, issuer_id, "pca_of", payload["source"]["url"]),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO issuer_roles(party_id,issuer_id,raw_title,normalized_role,pdmr_or_pca,evidence_url) VALUES(?,?,?,?, 'pdmr',?)",
                    (related_party_id, issuer_id, filing["transacting_party"].get("related_pdmr_role_raw"),
                     filing["transacting_party"].get("related_pdmr_role_normalized"), payload["source"]["url"]),
                )
            seen_event_ids: set[str] = set()
            for group in sorted(filing["transaction_groups"], key=lambda value: value["group_locator"]):
                instrument = group["instrument"]
                isin = instrument.get("isin_raw") if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{10}", instrument.get("isin_raw") or "") else None
                instrument_key = isin or (issuer_id + ":" + instrument["name_raw"])
                instrument_id = _stable_id("instrument", instrument_key)
                connection.execute(
                    "INSERT INTO instruments(id,issuer_id,instrument_class,name_raw,intrinsic_currency,status) VALUES(?,?,?,?,?,'active') "
                    "ON CONFLICT(id) DO UPDATE SET instrument_class=excluded.instrument_class,name_raw=excluded.name_raw,"
                    "intrinsic_currency=COALESCE(excluded.intrinsic_currency,instruments.intrinsic_currency)",
                    (instrument_id, issuer_id, instrument["instrument_type"], instrument["name_raw"], instrument.get("currency")),
                )
                if isin:
                    connection.execute(
                        "INSERT OR IGNORE INTO instrument_identifiers(instrument_id,scheme,value) VALUES(?,'ISIN',?)",
                        (instrument_id, isin),
                    )
                cursor = connection.execute(
                    "INSERT INTO transaction_groups(filing_version_id,group_locator,party_id,related_pdmr_party_id,instrument_id,instrument_name_raw,underlying_isin_raw,nature_raw,action,mechanism,consideration_type,investment_discretion,exposure_effect,trade_date,trade_date_precision,venue_raw,venue_mic,reconciliation_status,eligible_own_money_signal,signal_exclusion_reason) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (filing_version_id, group["group_locator"], party_id, related_party_id, instrument_id, instrument["name_raw"], instrument.get("underlying_isin_raw"), group["nature_raw"],
                      group["action"], group.get("mechanism", "unknown"), group.get("consideration", "unknown"),
                     group.get("investment_discretion", "unknown"), group.get("exposure_effect", "unknown"), group.get("trade_date"),
                     group.get("trade_date_precision", "unknown"), group.get("venue_raw"), group.get("venue_mic"),
                     group.get("aggregation_reconciliation", "not_applicable"), int(group.get("eligible_own_money_signal", False)),
                     group.get("signal_exclusion_reason")),
                )
                group_id = cursor.lastrowid
                selected = "individual" if any(row["representation"] == "individual" for row in group["rows"]) else "aggregate"
                row_ids = []
                for ordinal, row in enumerate(group["rows"], 1):
                    quantity = canonical_decimal(row["quantity"]) if row.get("quantity") is not None else None
                    price = canonical_decimal(row["price_amount_reported"]) if row.get("price_amount_reported") is not None else None
                    scale = canonical_decimal(row.get("quote_unit_scale", "1")) if price is not None else None
                    normalized_price = multiply(price, scale) if price is not None else None
                    price_currency = row.get("price_currency_normalized")
                    consideration_currency = row.get("consideration_currency")
                    compatible_currency = price_currency is not None and price_currency == consideration_currency
                    derived = multiply(quantity, price, scale) if quantity is not None and price is not None and compatible_currency else None
                    row_cursor = connection.execute(
                        "INSERT INTO reported_transaction_rows(transaction_group_id,row_locator,occurrence_ordinal,representation,selected_for_analytics,price_raw,price_amount_decimal,price_currency,quote_unit_scale_decimal,price_per_unit_decimal,quantity_raw,quantity_decimal,quantity_unit,consideration_reported_decimal,consideration_derived_decimal,consideration_currency,derivation) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (group_id, row["row_locator"], ordinal, row["representation"], int(row["representation"] == selected),
                         row.get("price_raw"), price, price_currency, scale, normalized_price,
                         row.get("quantity_raw"), quantity, row.get("quantity_unit"), row.get("consideration_reported"),
                         derived, consideration_currency, row.get("consideration_derivation")),
                    )
                    row_ids.append(row_cursor.lastrowid)
                    for field_name, original_text, status in (
                        ("quantity_decimal", row.get("quantity_raw"), "reported" if row.get("quantity") is not None else "not_reported"),
                        ("price_amount_decimal", row.get("price_raw"), "reported" if row.get("price_amount_reported") is not None else "not_reported"),
                        ("consideration_derived_decimal", None, "derived" if derived is not None else "not_yet_enriched"),
                    ):
                        connection.execute(
                            "INSERT INTO field_provenance(entity_type,entity_id,field_name,status,document_version_id,locator,original_text,derivation) VALUES('reported_row',?,?,?,?,?,?,?)",
                            (str(row_cursor.lastrowid), field_name, status, document_id, row["row_locator"], original_text,
                             row.get("consideration_derivation") if field_name == "consideration_derived_decimal" else None),
                        )
                event_key = group.get("event_key") or group["group_locator"]
                event_id = _stable_id("event", source["source_id"], filing_id, event_key)
                seen_event_ids.add(event_id)
                connection.execute("INSERT OR IGNORE INTO economic_events(id,event_kind) VALUES(?,'reported_group')", (event_id,))
                event_hash = content_hash({"filing": filing_hash, "group": group})
                event_version_number = connection.execute(
                    "SELECT COALESCE(MAX(version_number),0)+1 AS n FROM event_versions WHERE economic_event_id=?", (event_id,)
                ).fetchone()["n"]
                previous = connection.execute("SELECT current_version_id FROM economic_events WHERE id=?", (event_id,)).fetchone()
                if promote_current and previous and previous["current_version_id"]:
                    connection.execute("UPDATE event_versions SET superseded_at=? WHERE id=?", (now, previous["current_version_id"]))
                    amended += 1
                ev_cursor = connection.execute(
                    "INSERT INTO event_versions(economic_event_id,version_number,filing_version_id,transaction_group_id,accepted_content_hash,valid_from) VALUES(?,?,?,?,?,?)",
                    (event_id, event_version_number, filing_version_id, group_id, event_hash, now),
                )
                event_version_id = ev_cursor.lastrowid
                if promote_current:
                    connection.execute(
                        "UPDATE economic_events SET current_version_id=?,retracted_at=NULL,retraction_reason=NULL WHERE id=?",
                        (event_version_id, event_id),
                    )
                for row_id in row_ids:
                    connection.execute(
                        "INSERT INTO event_evidence(event_version_id,reported_row_id,evidence_role) VALUES(?,?,'reported')",
                        (event_version_id, row_id),
                    )
                if promote_current:
                    connection.execute(
                        "INSERT OR IGNORE INTO outbox_events(idempotency_key,economic_event_id,event_version_id,kind,payload_json,status) VALUES(?,?,?,?,?,'dry_run')",
                        (f"{event_id}:v{event_version_number}", event_id, event_version_id,
                         "correction" if previous and previous["current_version_id"] else "new_event",
                         canonical_json({"event_id": event_id, "version": event_version_number}).decode("utf-8")),
                    )
                accepted += 1
            if promote_current:
                stale_events = connection.execute(
                    "SELECT e.id,e.current_version_id,ev.version_number FROM economic_events e "
                    "JOIN event_versions ev ON ev.id=e.current_version_id JOIN filing_versions fv ON fv.id=ev.filing_version_id "
                    "WHERE fv.filing_id=?",
                    (filing_id,),
                ).fetchall()
                for stale in stale_events:
                    if stale["id"] in seen_event_ids:
                        continue
                    connection.execute("UPDATE event_versions SET superseded_at=? WHERE id=?", (now, stale["current_version_id"]))
                    connection.execute(
                        "UPDATE economic_events SET current_version_id=NULL,retracted_at=?,retraction_reason='absent_from_reparse' WHERE id=?",
                        (now, stale["id"]),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO outbox_events(idempotency_key,economic_event_id,event_version_id,kind,payload_json,status) "
                        "VALUES(?,?,?,?,?,'dry_run')",
                        (f"{stale['id']}:v{stale['version_number']}:retraction", stale["id"], stale["current_version_id"],
                         "retraction", canonical_json({"event_id": stale["id"], "reason": "absent_from_reparse"}).decode("utf-8")),
                    )
    return accepted, amended


def _store_attachment(connection: sqlite3.Connection, run_id: str, source: dict[str, Any], parent_document_id: int,
                      attachment, adapter: NewsWebAdapter, raw_root: Path) -> tuple[str, bytes]:
    existing_link = connection.execute(
        "SELECT a.original_filename,ro.relative_path FROM attachments a "
        "JOIN document_versions dv ON dv.id=a.document_version_id JOIN raw_objects ro ON ro.sha256=dv.raw_sha256 "
        "WHERE a.parent_document_version_id=? AND a.url=? AND a.status='fetched'",
        (parent_document_id, attachment.url),
    ).fetchone()
    if existing_link:
        return existing_link["original_filename"], (raw_root / existing_link["relative_path"]).read_bytes()
    data, mime, filename = adapter.fetch_attachment(attachment)
    suffix = Path(filename).suffix.lower() or ".bin"
    digest, relative, size = store_raw(data, raw_root, suffix)
    now = utc_now()
    with transaction(connection):
        connection.execute(
            "INSERT INTO source_records(source_id,native_record_id,canonical_url,status) VALUES(?,?,?,'fetched') "
            "ON CONFLICT(source_id,native_record_id) DO UPDATE SET canonical_url=excluded.canonical_url,status='fetched'",
            (source["source_id"], attachment.native_record_id, attachment.url),
        )
        attachment_record_id = connection.execute(
            "SELECT id FROM source_records WHERE source_id=? AND native_record_id=?",
            (source["source_id"], attachment.native_record_id),
        ).fetchone()["id"]
        connection.execute(
            "INSERT OR IGNORE INTO raw_objects(sha256,relative_path,mime_type,size_bytes,first_retrieved_at) VALUES(?,?,?,?,?)",
            (digest, relative, mime, size, now),
        )
        existing = connection.execute(
            "SELECT id FROM document_versions WHERE source_record_id=? AND raw_sha256=?", (attachment_record_id, digest)
        ).fetchone()
        if existing:
            attachment_document_id = existing["id"]
        else:
            ordinal = connection.execute(
                "SELECT COALESCE(MAX(version_ordinal),0)+1 FROM document_versions WHERE source_record_id=?", (attachment_record_id,)
            ).fetchone()[0]
            attachment_document_id = connection.execute(
                "INSERT INTO document_versions(source_record_id,raw_sha256,version_ordinal,retrieved_at,parser_hint) VALUES(?,?,?,?,NULL)",
                (attachment_record_id, digest, ordinal, now),
            ).lastrowid
        connection.execute(
            "INSERT OR IGNORE INTO attachments(parent_document_version_id,document_version_id,url,original_filename,status) VALUES(?,?,?,?, 'fetched')",
            (parent_document_id, attachment_document_id, attachment.url, filename),
        )
        connection.execute(
            "INSERT INTO fetch_attempts(source_record_id,run_id,attempted_at,http_status,disposition) VALUES(?,?,?,200,'stored')",
            (attachment_record_id, run_id, now),
        )
    return filename, data


def run_daily(
    connection: sqlite3.Connection, config: dict[str, Any], config_path: Path, raw_root: Path,
    reports_root: Path, cutoff: str, source_filter: set[str] | None = None, *, mode: str = "daily",
) -> DailyResult:
    run_id = f"run_{uuid.uuid4().hex}"
    started = utc_now()
    digest = config_hash(config_path)
    cutoff_date = cutoff[:10]
    connection.execute(
        "INSERT INTO ingestion_runs(id,mode,started_at,cutoff_at,status,code_version,config_hash) VALUES(?,?,?,?,?,?,?)",
        (run_id, mode, started, cutoff, "running", __version__, digest),
    )
    connection.commit()
    results: list[SourceResult] = []
    enabled = [source for source in config["sources"] if source.get("backfill_enabled" if mode == "backfill" else "daily_enabled")]
    if source_filter:
        enabled = [source for source in enabled if source["source_id"] in source_filter]
    for source in sorted(enabled, key=lambda item: item["source_id"]):
        result = SourceResult(source["source_id"])
        results.append(result)
        previous = connection.execute(
            "SELECT covered_through FROM source_checkpoints WHERE source_id=? AND mode=?", (source["source_id"], mode)
        ).fetchone()
        if mode == "backfill":
            interval_from_date = date.fromisoformat(previous["covered_through"]) + timedelta(days=1) if previous and previous["covered_through"] else date.fromisoformat(source.get("backfill_start_date", source.get("start_date", cutoff_date)))
            interval_to_date = min(date.fromisoformat(cutoff_date), interval_from_date + timedelta(days=source.get("backfill_window_days", 7) - 1))
            interval_from, interval_to = interval_from_date.isoformat(), interval_to_date.isoformat()
        else:
            interval_from = (date.fromisoformat(previous["covered_through"]) - timedelta(days=source.get("overlap_days", 7))).isoformat() if previous and previous["covered_through"] else source.get("start_date", cutoff_date)
            interval_to = cutoff_date
        connection.execute(
            "INSERT INTO run_tasks(run_id,source_id,state,attempts,target_from,target_to) VALUES(?,?,'running',1,?,?)",
            (run_id, source["source_id"], interval_from, interval_to),
        )
        connection.commit()
        try:
            if source["adapter"] == "fixture_json":
                adapter = FixtureAdapter(Path(source["fixture_path"]))
            elif source["adapter"] == "newsweb_live":
                adapter = NewsWebAdapter(timeout=source.get("timeout_seconds", 20), retries=source.get("retries", 2))
            elif source["adapter"] == "sweden_fi_live":
                adapter = SwedenFiAdapter(timeout=source.get("timeout_seconds", 20), retries=source.get("retries", 2),
                                           request_delay=source.get("request_delay_seconds", 0.15),
                                           search_request_delay=source.get("search_request_delay_seconds"))
            elif source["adapter"] == "bafin_live":
                adapter = BafinAdapter(timeout=source.get("timeout_seconds", 20), retries=source.get("retries", 2),
                                       request_delay=source.get("request_delay_seconds", 0.2))
            elif source["adapter"] == "six_live":
                adapter = SixAdapter(timeout=source.get("timeout_seconds", 20), retries=source.get("retries", 2))
            elif source["adapter"] == "amf_live":
                adapter = AmfAdapter(timeout=source.get("timeout_seconds", 30), retries=source.get("retries", 2))
            elif source["adapter"] == "unternehmensregister_live":
                adapter = UnternehmensregisterAdapter(timeout=source.get("timeout_seconds", 30), retries=source.get("retries", 2))
            elif source["adapter"] == "nl_afm_live":
                adapter = NlAfmAdapter(timeout=source.get("timeout_seconds", 30), retries=source.get("retries", 2))
            elif source["adapter"] == "denmark_oam_live":
                adapter = DenmarkOamAdapter(timeout=source.get("timeout_seconds", 30), retries=source.get("retries", 2))
            else:
                raise RuntimeError(f"adapter not implemented: {source['adapter']}")
            records = adapter.discover(interval_from, interval_to, None)
            result.discovered = len(records)
            for record in records:
                record_id = None
                document_id = None
                parser_version = None
                try:
                    expected_parser_version = SWEDEN_PARSER_VERSION if source.get("parser") == "sweden_fi_html" else BAFIN_PARSER_VERSION if source.get("parser") == "bafin_html" else SIX_PARSER_VERSION if source.get("parser") == "six_json" else AMF_PARSER_VERSION if source.get("parser") == "amf_pdf" else UREG_PARSER_VERSION if source.get("parser") == "unternehmensregister_html" else NL_AFM_PARSER_VERSION if source.get("parser") == "nl_afm_html" else DK_OAM_PARSER_VERSION if source.get("parser") == "denmark_oam_json" else NEWSWEB_PARSER_VERSION if source.get("parser") == "newsweb_json" else PARSER_VERSION
                    if source.get("capabilities", {}).get("immutable_version_ids"):
                        accepted_version = connection.execute(
                            "SELECT 1 FROM source_records sr JOIN document_versions dv ON dv.source_record_id=sr.id "
                            "JOIN extraction_runs er ON er.document_version_id=dv.id "
                            "WHERE sr.source_id=? AND sr.native_record_id=? AND er.parser_version=? AND er.status='accepted' LIMIT 1",
                            (source["source_id"], record.native_record_id, expected_parser_version),
                        ).fetchone()
                        if accepted_version:
                            result.unchanged += 1
                            continue
                    data = adapter.fetch(record)
                    parser_name = source.get("parser", "fixture_json")
                    if parser_name == "newsweb_json":
                        message = json.loads(data)["data"]["message"]
                        preliminary = {"source": {
                            "native_record_id": str(message["messageId"]),
                            "url": f"https://newsweb.oslobors.no/message/{message['messageId']}",
                            "published_at": message["publishedTime"], "source_updated_at": None,
                        }}
                        payload = None
                        parser_version = NEWSWEB_PARSER_VERSION
                        suffix, mime_type = ".json", "application/json"
                    elif parser_name == "sweden_fi_html":
                        metadata = record.metadata or {}
                        preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url,
                                                   "published_date": metadata.get("published_date")}}
                        payload = None
                        parser_version = SWEDEN_PARSER_VERSION
                        suffix, mime_type = ".html", "text/html"
                    elif parser_name == "bafin_html":
                        metadata = record.metadata or {}
                        preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url,
                                                   "published_date": metadata.get("published_date")}}
                        payload = None
                        parser_version = BAFIN_PARSER_VERSION
                        suffix, mime_type = ".html", "text/html"
                    elif parser_name == "six_json":
                        metadata = record.metadata or {}
                        preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url,
                                                   "published_date": metadata.get("published_date")}}
                        payload = None
                        parser_version = SIX_PARSER_VERSION
                        suffix, mime_type = ".json", "application/json"
                    elif parser_name == "amf_pdf":
                        metadata = record.metadata or {}
                        preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url,
                                                   "published_date": metadata.get("published_date")}}
                        payload = None
                        parser_version = AMF_PARSER_VERSION
                        suffix, mime_type = ".pdf", "application/pdf"
                    elif parser_name == "unternehmensregister_html":
                        metadata = record.metadata or {}
                        preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url,
                                                   "published_date": metadata.get("published_date")}}
                        payload = None
                        parser_version = UREG_PARSER_VERSION
                        suffix, mime_type = ".html", "text/html"
                    elif parser_name == "nl_afm_html":
                        metadata = record.metadata or {}
                        preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url,
                                                   "metadata": metadata}}
                        payload = None
                        parser_version = NL_AFM_PARSER_VERSION
                        suffix, mime_type = ".html", "text/html"
                    elif parser_name == "denmark_oam_json":
                        metadata = record.metadata or {}
                        preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url,
                                                   "published_at": metadata.get("published_at")}}
                        payload = None
                        parser_version = DK_OAM_PARSER_VERSION
                        suffix, mime_type = ".json", "application/json"
                    else:
                        try:
                            preliminary = json.loads(data)
                        except (UnicodeDecodeError, json.JSONDecodeError):
                            preliminary = {"source": {"native_record_id": record.native_record_id, "url": record.url}}
                        payload = None
                        parser_version = PARSER_VERSION
                        suffix, mime_type = ".json", "application/json"
                    record_id, document_id, unchanged = _upsert_source_document(
                        connection, run_id, source, preliminary, data, raw_root, parser_version, suffix, mime_type
                    )
                    if unchanged:
                        result.unchanged += 1
                        disposition = connection.execute(
                            "SELECT status FROM extraction_runs WHERE document_version_id=? AND parser_version=? "
                            "ORDER BY id DESC LIMIT 1", (document_id, parser_version),
                        ).fetchone()
                        if disposition and disposition["status"] == "accepted":
                            with transaction(connection):
                                connection.execute(
                                    "UPDATE quality_issues SET status='resolved' WHERE entity_type='source_record' "
                                    "AND entity_id=? AND code='parse_failed' AND status='open'",
                                    (str(record_id),),
                                )
                            continue
                        if disposition and disposition["status"] == "quarantined":
                            result.state = "quarantined"
                            result.quarantined += 1
                            continue
                    attachment_inputs = []
                    if source["adapter"] in {"newsweb_live", "denmark_oam_live"}:
                        for attachment in adapter.enumerate_attachments(record, data):
                            attachment_inputs.append(_store_attachment(connection, run_id, source, document_id, attachment, adapter, raw_root))
                    if parser_name == "newsweb_json":
                        payload = parse_newsweb(data, attachment_inputs)
                    elif parser_name == "sweden_fi_html":
                        payload = parse_sweden(data, record.metadata or {})
                    elif parser_name == "bafin_html":
                        payload = parse_bafin(data, {"native_record_id": record.native_record_id, **(record.metadata or {})})
                    elif parser_name == "six_json":
                        payload = parse_six(data)
                    elif parser_name == "amf_pdf":
                        payload = parse_amf(data)
                    elif parser_name == "unternehmensregister_html":
                        payload = parse_ureg(data, {"native_record_id": record.native_record_id, "url": record.url, **(record.metadata or {})})
                    elif parser_name == "nl_afm_html":
                        payload = parse_nl_afm(data, {"native_record_id": record.native_record_id, "url": record.url, **(record.metadata or {})})
                    elif parser_name == "denmark_oam_json":
                        payload = parse_denmark_oam(data, attachment_inputs)
                    else:
                        payload = payload or parse(data)
                    accepted, amended = _accept_payload(connection, source, record_id, document_id, payload, digest, parser_version)
                    with transaction(connection):
                        connection.execute(
                            "UPDATE quality_issues SET status='resolved' WHERE entity_type='source_record' "
                            "AND entity_id=? AND code='parse_failed' AND status='open'",
                            (str(record_id),),
                        )
                    result.accepted += accepted
                    result.amended += amended
                except ParseError as exc:
                    result.state = "quarantined"
                    result.quarantined += 1
                    result.error = f"{result.error}; {record.native_record_id}: {exc}" if result.error else f"{record.native_record_id}: {exc}"
                    if record_id is not None:
                        with transaction(connection):
                            if document_id is not None and parser_version is not None:
                                connection.execute(
                                    "INSERT OR IGNORE INTO extraction_runs(document_version_id,parser_version,config_hash,input_manifest_hash,status,started_at,finished_at) "
                                    "VALUES(?,?,?,?, 'quarantined',?,?)",
                                    (document_id, parser_version, source["version"], digest, utc_now(), utc_now()),
                                )
                            connection.execute(
                                "INSERT INTO quality_issues(entity_type,entity_id,code,severity,status,details) VALUES('source_record',?,'parse_failed','error','open',?)",
                                (str(record_id), str(exc)),
                            )
            with transaction(connection):
                connection.execute(
                    "INSERT INTO source_checkpoints(source_id,mode,covered_through,updated_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(source_id,mode) DO UPDATE SET covered_through=excluded.covered_through,updated_at=excluded.updated_at",
                    (source["source_id"], mode, interval_to, utc_now()),
                )
                connection.execute(
                    "UPDATE run_tasks SET state=?,discovered_count=?,accepted_count=?,error=? WHERE run_id=? AND source_id=?",
                    (result.state, result.discovered, result.accepted, result.error, run_id, source["source_id"]),
                )
                connection.execute(
                    "INSERT INTO source_health_snapshots(source_id,observed_at,status,details) VALUES(?,?,?,?)",
                    (source["source_id"], utc_now(), "healthy" if result.state == "accepted" else "degraded",
                     json.dumps({"discovered": result.discovered, "quarantined": result.quarantined})),
                )
        except (OSError, ValueError, ParseError, RuntimeError) as exc:
            result.state = "quarantined" if isinstance(exc, ParseError) else "failed"
            result.quarantined = int(isinstance(exc, ParseError))
            result.error = str(exc)
            with transaction(connection):
                connection.execute(
                    "UPDATE run_tasks SET state=?,error=? WHERE run_id=? AND source_id=?",
                    (result.state, result.error, run_id, source["source_id"]),
                )
                connection.execute(
                    "INSERT INTO source_health_snapshots(source_id,observed_at,status,details) VALUES(?,?,?,?)",
                    (source["source_id"], utc_now(), "degraded", result.error),
                )
    status = "success" if all(result.state == "accepted" for result in results) else "partial_failure"
    finished = utc_now()
    reports_root.mkdir(parents=True, exist_ok=True)
    report_path = reports_root / f"{run_id}.json"
    report = {"run_id": run_id, "started_at": started, "finished_at": finished, "cutoff": cutoff, "status": status,
              "sources": [result.__dict__ for result in results]}
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    markdown_path = reports_root / f"{run_id}.md"
    lines = [f"# Daily run {run_id}", "", f"Status: **{status}**", f"Cutoff: `{cutoff}`", "", "| Source | State | Discovered | Unchanged | Accepted | Amended | Quarantined | Error |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    lines.extend(f"| {item.source_id} | {item.state} | {item.discovered} | {item.unchanged} | {item.accepted} | {item.amended} | {item.quarantined} | {item.error or ''} |" for item in results)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    connection.execute(
        "UPDATE ingestion_runs SET finished_at=?,status=?,report_path=? WHERE id=?",
        (finished, status, report_path.as_posix(), run_id),
    )
    connection.commit()
    return DailyResult(run_id, status, cutoff, results)


def reparse_saved(connection: sqlite3.Connection, config: dict[str, Any], config_path: Path, raw_root: Path,
                  source_filter: set[str] | None = None, dry_run: bool = False) -> dict[str, Any]:
    digest = config_hash(config_path)
    configured = {source["source_id"]: source for source in config["sources"]}
    supported_parsers = {"newsweb_json", "sweden_fi_html", "bafin_html", "six_json", "amf_pdf", "unternehmensregister_html", "nl_afm_html", "denmark_oam_json"}
    selected = source_filter or {source_id for source_id, source in configured.items() if source.get("parser") in supported_parsers}
    outcome = {"documents": 0, "accepted": 0, "amended": 0, "quarantined": 0, "errors": []}
    for source_id in sorted(selected):
        source = configured.get(source_id)
        if not source or source.get("parser") not in supported_parsers:
            continue
        records = connection.execute(
            "SELECT sr.id AS record_id,sr.native_record_id,sr.canonical_url,sr.published_at,sr.published_date,sr.metadata_json,"
            "dv.id AS document_id,dv.parser_hint,ro.relative_path FROM source_records sr "
            "JOIN document_versions dv ON dv.source_record_id=sr.id JOIN raw_objects ro ON ro.sha256=dv.raw_sha256 "
            "WHERE sr.source_id=? AND sr.native_record_id NOT LIKE '%:attachment:%' "
            "AND dv.version_ordinal=(SELECT MAX(dv2.version_ordinal) FROM document_versions dv2 WHERE dv2.source_record_id=sr.id) "
            "ORDER BY sr.native_record_id", (source_id,),
        ).fetchall()
        for record in records:
            outcome["documents"] += 1
            if dry_run:
                continue
            data = (raw_root / record["relative_path"]).read_bytes()
            try:
                if source["parser"] == "newsweb_json":
                    attachment_rows = connection.execute(
                        "SELECT a.original_filename,ro.relative_path FROM attachments a "
                        "JOIN document_versions adv ON adv.id=a.document_version_id JOIN raw_objects ro ON ro.sha256=adv.raw_sha256 "
                        "WHERE a.parent_document_version_id=? ORDER BY a.id", (record["document_id"],),
                    ).fetchall()
                    attachment_inputs = [(row["original_filename"], (raw_root / row["relative_path"]).read_bytes()) for row in attachment_rows]
                    payload = parse_newsweb(data, attachment_inputs)
                    parser_version = NEWSWEB_PARSER_VERSION
                elif source["parser"] == "denmark_oam_json":
                    attachment_rows = connection.execute(
                        "SELECT a.original_filename,ro.relative_path FROM attachments a "
                        "JOIN document_versions adv ON adv.id=a.document_version_id JOIN raw_objects ro ON ro.sha256=adv.raw_sha256 "
                        "WHERE a.parent_document_version_id=? ORDER BY a.id", (record["document_id"],),
                    ).fetchall()
                    attachment_inputs = [(row["original_filename"], (raw_root / row["relative_path"]).read_bytes()) for row in attachment_rows]
                    payload = parse_denmark_oam(data, attachment_inputs)
                    parser_version = DK_OAM_PARSER_VERSION
                elif source["parser"] == "sweden_fi_html":
                    payload = parse_sweden(data, {"report_version": record["native_record_id"], "url": record["canonical_url"],
                                                  "published_date": record["published_date"]})
                    parser_version = SWEDEN_PARSER_VERSION
                elif source["parser"] == "six_json":
                    payload = parse_six(data)
                    parser_version = SIX_PARSER_VERSION
                elif source["parser"] == "amf_pdf":
                    payload = parse_amf(data)
                    parser_version = AMF_PARSER_VERSION
                elif source["parser"] == "unternehmensregister_html":
                    payload = parse_ureg(data, {"native_record_id": record["native_record_id"], "url": record["canonical_url"], "published_date": record["published_date"]})
                    parser_version = UREG_PARSER_VERSION
                elif source["parser"] == "nl_afm_html":
                    metadata = json.loads(record["metadata_json"])
                    payload = parse_nl_afm(data, {"native_record_id": record["native_record_id"], "url": record["canonical_url"], **metadata})
                    parser_version = NL_AFM_PARSER_VERSION
                else:
                    melding_id, party_id = record["native_record_id"].split(":", 1)
                    payload = parse_bafin(data, {"native_record_id": record["native_record_id"], "meldung_id": melding_id,
                                                 "party_id": party_id, "url": record["canonical_url"],
                                                 "activated_at": record["published_date"] or ""})
                    parser_version = BAFIN_PARSER_VERSION
                accepted, amended = _accept_payload(connection, source, record["record_id"], record["document_id"], payload, digest, parser_version)
                with transaction(connection):
                    connection.execute(
                        "UPDATE quality_issues SET status='resolved' WHERE entity_type='source_record' "
                        "AND entity_id=? AND code='parse_failed' AND status='open'",
                        (str(record["record_id"]),),
                    )
                outcome["accepted"] += accepted
                outcome["amended"] += amended
            except (ParseError, OSError, ValueError) as exc:
                outcome["quarantined"] += 1
                outcome["errors"].append(f"{source_id}/{record['native_record_id']}: {exc}")
    return outcome
