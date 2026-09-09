CREATE TABLE jurisdictions (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    regime_family TEXT NOT NULL
);

CREATE TABLE rule_versions (
    id INTEGER PRIMARY KEY,
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    annual_threshold_decimal TEXT,
    threshold_currency TEXT,
    legal_source_url TEXT NOT NULL,
    verified_at TEXT,
    CHECK (effective_to IS NULL OR effective_to > effective_from),
    UNIQUE (jurisdiction_code, effective_from)
);

CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    jurisdiction_code TEXT NOT NULL REFERENCES jurisdictions(code),
    name TEXT NOT NULL,
    public_url TEXT NOT NULL,
    submission_url TEXT,
    adapter TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('discovered','publication_route_confirmed','sample_verified','adapter_tested','backfill_partial','live_verified','degraded','blocked','out_of_scope')),
    required INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0,1)),
    rights_status TEXT NOT NULL,
    last_verified_at TEXT
);

CREATE TABLE source_versions (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    effective_from TEXT NOT NULL,
    capabilities_json TEXT NOT NULL,
    UNIQUE(source_id, version)
);

CREATE TABLE issuers (
    id TEXT PRIMARY KEY,
    legal_name TEXT NOT NULL,
    domicile_code TEXT REFERENCES jurisdictions(code),
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE issuer_identifiers (
    id INTEGER PRIMARY KEY,
    issuer_id TEXT NOT NULL REFERENCES issuers(id),
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    evidence_url TEXT,
    UNIQUE(scheme, value, valid_from)
);
CREATE TABLE issuer_aliases (
    id INTEGER PRIMARY KEY,
    issuer_id TEXT NOT NULL REFERENCES issuers(id),
    name TEXT NOT NULL,
    language TEXT,
    valid_from TEXT,
    valid_to TEXT,
    evidence_url TEXT
);

CREATE TABLE instruments (
    id TEXT PRIMARY KEY,
    issuer_id TEXT REFERENCES issuers(id),
    instrument_class TEXT NOT NULL,
    name_raw TEXT NOT NULL,
    share_class TEXT,
    intrinsic_currency TEXT,
    status TEXT NOT NULL DEFAULT 'active'
);
CREATE TABLE instrument_identifiers (
    id INTEGER PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    UNIQUE(scheme, value, valid_from)
);
CREATE TABLE listings (
    id INTEGER PRIMARY KEY,
    instrument_id TEXT NOT NULL REFERENCES instruments(id),
    mic TEXT,
    ticker TEXT,
    quote_currency TEXT,
    quote_unit_scale TEXT,
    valid_from TEXT,
    valid_to TEXT,
    is_primary INTEGER CHECK(is_primary IN (0,1))
);

CREATE TABLE parties (
    id TEXT PRIMARY KEY,
    party_type TEXT NOT NULL CHECK(party_type IN ('natural_person','legal_entity','trust','arrangement','anonymous_role','unresolved')),
    canonical_name TEXT,
    identity_status TEXT NOT NULL
);
CREATE TABLE party_aliases (
    id INTEGER PRIMARY KEY,
    party_id TEXT NOT NULL REFERENCES parties(id),
    name_raw TEXT NOT NULL,
    source_id TEXT REFERENCES sources(source_id),
    UNIQUE(party_id, name_raw, source_id)
);
CREATE TABLE issuer_roles (
    id INTEGER PRIMARY KEY,
    party_id TEXT NOT NULL REFERENCES parties(id),
    issuer_id TEXT NOT NULL REFERENCES issuers(id),
    raw_title TEXT,
    normalized_role TEXT,
    pdmr_or_pca TEXT NOT NULL CHECK(pdmr_or_pca IN ('pdmr','pca','anonymous','unknown')),
    valid_from TEXT,
    valid_to TEXT,
    evidence_url TEXT
);
CREATE TABLE party_relationships (
    id INTEGER PRIMARY KEY,
    from_party_id TEXT NOT NULL REFERENCES parties(id),
    to_party_id TEXT NOT NULL REFERENCES parties(id),
    issuer_id TEXT REFERENCES issuers(id),
    relationship_type TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    evidence_url TEXT,
    review_state TEXT NOT NULL
);

CREATE TABLE ingestion_runs (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    code_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    report_path TEXT
);
CREATE TABLE run_tasks (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES ingestion_runs(id),
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    target_from TEXT,
    target_to TEXT,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    UNIQUE(run_id, source_id)
);
CREATE TABLE source_checkpoints (
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    mode TEXT NOT NULL,
    covered_through TEXT,
    cursor TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(source_id, mode)
);

CREATE TABLE source_records (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    native_record_id TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    published_at TEXT,
    published_date TEXT,
    source_updated_at TEXT,
    status TEXT NOT NULL,
    UNIQUE(source_id, native_record_id)
);
CREATE TABLE fetch_attempts (
    id INTEGER PRIMARY KEY,
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    run_id TEXT REFERENCES ingestion_runs(id),
    attempted_at TEXT NOT NULL,
    http_status INTEGER,
    disposition TEXT NOT NULL,
    error TEXT
);
CREATE TABLE raw_objects (
    sha256 TEXT PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    encoding TEXT,
    size_bytes INTEGER NOT NULL CHECK(size_bytes >= 0),
    first_retrieved_at TEXT NOT NULL
);
CREATE TABLE document_versions (
    id INTEGER PRIMARY KEY,
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    raw_sha256 TEXT NOT NULL REFERENCES raw_objects(sha256),
    version_ordinal INTEGER NOT NULL,
    retrieved_at TEXT NOT NULL,
    parser_hint TEXT,
    UNIQUE(source_record_id, raw_sha256),
    UNIQUE(source_record_id, version_ordinal)
);
CREATE TABLE attachments (
    id INTEGER PRIMARY KEY,
    parent_document_version_id INTEGER NOT NULL REFERENCES document_versions(id),
    document_version_id INTEGER REFERENCES document_versions(id),
    url TEXT NOT NULL,
    original_filename TEXT,
    status TEXT NOT NULL
);

CREATE TABLE extraction_runs (
    id INTEGER PRIMARY KEY,
    document_version_id INTEGER NOT NULL REFERENCES document_versions(id),
    parser_version TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    input_manifest_hash TEXT NOT NULL,
    normalized_hash TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    UNIQUE(document_version_id, parser_version, config_hash, input_manifest_hash)
);
CREATE TABLE filings (
    id TEXT PRIMARY KEY,
    issuer_id TEXT REFERENCES issuers(id),
    source_scoped_reference TEXT,
    current_version_id INTEGER
);
CREATE TABLE filing_versions (
    id INTEGER PRIMARY KEY,
    filing_id TEXT NOT NULL REFERENCES filings(id),
    version_number INTEGER NOT NULL,
    notification_status TEXT NOT NULL,
    amends_reference TEXT,
    source_locator TEXT NOT NULL,
    issuer_received_at TEXT,
    accepted_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(filing_id, version_number),
    UNIQUE(filing_id, content_hash)
);
CREATE TABLE filing_publications (
    filing_version_id INTEGER NOT NULL REFERENCES filing_versions(id),
    source_record_id INTEGER NOT NULL REFERENCES source_records(id),
    publication_rank INTEGER NOT NULL,
    confidence TEXT NOT NULL,
    PRIMARY KEY(filing_version_id, source_record_id)
);
CREATE TABLE transaction_groups (
    id INTEGER PRIMARY KEY,
    filing_version_id INTEGER NOT NULL REFERENCES filing_versions(id),
    group_locator TEXT NOT NULL,
    party_id TEXT REFERENCES parties(id),
    related_pdmr_party_id TEXT REFERENCES parties(id),
    instrument_id TEXT REFERENCES instruments(id),
    nature_raw TEXT NOT NULL,
    action TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    consideration_type TEXT NOT NULL,
    investment_discretion TEXT NOT NULL,
    exposure_effect TEXT NOT NULL,
    trade_date TEXT,
    trade_date_precision TEXT NOT NULL,
    venue_raw TEXT,
    venue_mic TEXT,
    reconciliation_status TEXT NOT NULL,
    eligible_own_money_signal INTEGER NOT NULL CHECK(eligible_own_money_signal IN (0,1)),
    signal_exclusion_reason TEXT,
    UNIQUE(filing_version_id, group_locator)
);
CREATE TABLE reported_transaction_rows (
    id INTEGER PRIMARY KEY,
    transaction_group_id INTEGER NOT NULL REFERENCES transaction_groups(id),
    row_locator TEXT NOT NULL,
    occurrence_ordinal INTEGER NOT NULL,
    representation TEXT NOT NULL CHECK(representation IN ('individual','aggregate')),
    selected_for_analytics INTEGER NOT NULL CHECK(selected_for_analytics IN (0,1)),
    price_raw TEXT,
    price_amount_decimal TEXT,
    price_currency TEXT,
    quote_unit_scale_decimal TEXT,
    price_per_unit_decimal TEXT,
    quantity_raw TEXT,
    quantity_decimal TEXT,
    quantity_unit TEXT,
    consideration_reported_decimal TEXT,
    consideration_derived_decimal TEXT,
    consideration_currency TEXT,
    derivation TEXT,
    UNIQUE(transaction_group_id, row_locator, occurrence_ordinal)
);
CREATE TABLE economic_events (
    id TEXT PRIMARY KEY,
    current_version_id INTEGER,
    event_kind TEXT NOT NULL
);
CREATE TABLE event_versions (
    id INTEGER PRIMARY KEY,
    economic_event_id TEXT NOT NULL REFERENCES economic_events(id),
    version_number INTEGER NOT NULL,
    filing_version_id INTEGER NOT NULL REFERENCES filing_versions(id),
    transaction_group_id INTEGER NOT NULL REFERENCES transaction_groups(id),
    accepted_content_hash TEXT NOT NULL,
    valid_from TEXT NOT NULL,
    superseded_at TEXT,
    UNIQUE(economic_event_id, version_number),
    UNIQUE(economic_event_id, accepted_content_hash)
);
CREATE TABLE event_evidence (
    event_version_id INTEGER NOT NULL REFERENCES event_versions(id),
    reported_row_id INTEGER NOT NULL REFERENCES reported_transaction_rows(id),
    evidence_role TEXT NOT NULL,
    PRIMARY KEY(event_version_id, reported_row_id)
);
CREATE TABLE field_provenance (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reported','derived','corrected','missing','not_reported','not_applicable','redacted','ambiguous','parse_failed','not_yet_enriched')),
    document_version_id INTEGER REFERENCES document_versions(id),
    locator TEXT,
    original_text TEXT,
    derivation TEXT
);
CREATE TABLE quality_issues (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    details TEXT
);
CREATE TABLE review_decisions (
    id INTEGER PRIMARY KEY,
    decision_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    evidence TEXT NOT NULL,
    decided_at TEXT NOT NULL,
    supersedes_id INTEGER REFERENCES review_decisions(id)
);
CREATE TABLE outbox_events (
    id INTEGER PRIMARY KEY,
    idempotency_key TEXT NOT NULL UNIQUE,
    economic_event_id TEXT NOT NULL REFERENCES economic_events(id),
    event_version_id INTEGER NOT NULL REFERENCES event_versions(id),
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'dry_run'
);
CREATE TABLE coverage_intervals (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    covered_from TEXT,
    covered_to TEXT,
    state TEXT NOT NULL,
    evidence TEXT,
    UNIQUE(source_id, covered_from, covered_to)
);
CREATE TABLE source_health_snapshots (
    id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(source_id),
    observed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    newest_publication_at TEXT,
    details TEXT
);

CREATE INDEX idx_records_publication ON source_records(published_at, published_date);
CREATE INDEX idx_records_source_native ON source_records(source_id, native_record_id);
CREATE INDEX idx_groups_trade_date ON transaction_groups(trade_date, action);
CREATE INDEX idx_groups_party_date ON transaction_groups(party_id, trade_date);
CREATE INDEX idx_filing_issuer ON filings(issuer_id);
CREATE INDEX idx_quality_queue ON quality_issues(status, severity);
CREATE INDEX idx_rows_group_selected ON reported_transaction_rows(transaction_group_id, selected_for_analytics);

CREATE VIEW current_events AS
SELECT e.id AS event_id, ev.id AS event_version_id, ev.version_number,
       f.id AS filing_id, fv.notification_status, i.legal_name AS issuer_name,
       p.canonical_name AS party_name, p.party_type, ir.instrument_class,
       tg.action, tg.mechanism, tg.consideration_type, tg.trade_date,
       tg.eligible_own_money_signal, sr.published_at, sr.published_date,
       s.source_id, s.jurisdiction_code, tg.id AS transaction_group_id
FROM economic_events e
JOIN event_versions ev ON ev.id = e.current_version_id
JOIN filing_versions fv ON fv.id = ev.filing_version_id
JOIN filings f ON f.id = fv.filing_id
LEFT JOIN issuers i ON i.id = f.issuer_id
JOIN transaction_groups tg ON tg.id = ev.transaction_group_id
LEFT JOIN parties p ON p.id = tg.party_id
LEFT JOIN instruments ir ON ir.id = tg.instrument_id
JOIN filing_publications fp ON fp.filing_version_id = fv.id AND fp.publication_rank = 1
JOIN source_records sr ON sr.id = fp.source_record_id
JOIN sources s ON s.source_id = sr.source_id;
