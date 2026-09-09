INSERT OR IGNORE INTO issuer_roles(party_id, issuer_id, raw_title, normalized_role, pdmr_or_pca, evidence_url)
SELECT pr.to_party_id, pr.issuer_id, NULL, NULL, 'pdmr', pr.evidence_url
FROM party_relationships pr
WHERE pr.issuer_id IS NOT NULL
  AND NOT EXISTS (
      SELECT 1 FROM issuer_roles ir
      WHERE ir.party_id = pr.to_party_id AND ir.issuer_id = pr.issuer_id
  );
