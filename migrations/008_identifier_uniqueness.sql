DELETE FROM issuer_identifiers
WHERE scheme = 'LEI' AND value NOT GLOB '[A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9]';

DELETE FROM instrument_identifiers
WHERE scheme = 'ISIN' AND value NOT GLOB '[A-Z][A-Z][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9][A-Z0-9]';

DELETE FROM issuer_identifiers
WHERE id NOT IN (
    SELECT MIN(id) FROM issuer_identifiers
    GROUP BY scheme, value, COALESCE(valid_from, '')
);

DELETE FROM instrument_identifiers
WHERE id NOT IN (
    SELECT MIN(id) FROM instrument_identifiers
    GROUP BY scheme, value, COALESCE(valid_from, '')
);

CREATE UNIQUE INDEX idx_issuer_identifiers_identity
ON issuer_identifiers(scheme, value, COALESCE(valid_from, ''));

CREATE UNIQUE INDEX idx_instrument_identifiers_identity
ON instrument_identifiers(scheme, value, COALESCE(valid_from, ''));
