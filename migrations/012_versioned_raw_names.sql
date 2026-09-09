ALTER TABLE filing_versions ADD COLUMN issuer_name_raw TEXT;
ALTER TABLE transaction_groups ADD COLUMN instrument_name_raw TEXT;

DROP VIEW current_events;
CREATE VIEW current_events AS
SELECT e.id AS event_id, ev.id AS event_version_id, ev.version_number,
       f.id AS filing_id, fv.notification_status, COALESCE(fv.issuer_name_raw, i.legal_name) AS issuer_name,
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
