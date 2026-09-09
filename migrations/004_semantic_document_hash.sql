ALTER TABLE document_versions ADD COLUMN semantic_sha256 TEXT;
CREATE UNIQUE INDEX idx_document_semantic_version
ON document_versions(source_record_id, semantic_sha256)
WHERE semantic_sha256 IS NOT NULL;
