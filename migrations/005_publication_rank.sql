UPDATE filing_publications
SET publication_rank = (
    SELECT ranked.position
    FROM (
        SELECT rowid AS target_rowid,
               ROW_NUMBER() OVER (PARTITION BY filing_version_id ORDER BY source_record_id) AS position
        FROM filing_publications
    ) AS ranked
    WHERE ranked.target_rowid = filing_publications.rowid
);

CREATE UNIQUE INDEX idx_filing_publication_rank
ON filing_publications(filing_version_id, publication_rank);
