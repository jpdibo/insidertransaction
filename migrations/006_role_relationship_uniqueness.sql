DELETE FROM issuer_roles
WHERE id NOT IN (
    SELECT MIN(id)
    FROM issuer_roles
    GROUP BY party_id, issuer_id, COALESCE(raw_title, ''), COALESCE(normalized_role, ''), pdmr_or_pca,
             COALESCE(valid_from, ''), COALESCE(valid_to, ''), COALESCE(evidence_url, '')
);

DELETE FROM party_relationships
WHERE id NOT IN (
    SELECT MIN(id)
    FROM party_relationships
    GROUP BY from_party_id, to_party_id, COALESCE(issuer_id, ''), relationship_type,
             COALESCE(valid_from, ''), COALESCE(valid_to, ''), COALESCE(evidence_url, ''), review_state
);

CREATE UNIQUE INDEX idx_issuer_roles_evidence_unique
ON issuer_roles(party_id, issuer_id, COALESCE(raw_title, ''), COALESCE(normalized_role, ''), pdmr_or_pca,
                COALESCE(valid_from, ''), COALESCE(valid_to, ''), COALESCE(evidence_url, ''));

CREATE UNIQUE INDEX idx_party_relationships_evidence_unique
ON party_relationships(from_party_id, to_party_id, COALESCE(issuer_id, ''), relationship_type,
                       COALESCE(valid_from, ''), COALESCE(valid_to, ''), COALESCE(evidence_url, ''), review_state);
