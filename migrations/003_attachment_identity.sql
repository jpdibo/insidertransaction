CREATE UNIQUE INDEX idx_attachments_parent_url
ON attachments(parent_document_version_id, url);
