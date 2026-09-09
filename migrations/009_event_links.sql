CREATE TABLE event_links (
    id INTEGER PRIMARY KEY,
    left_event_id TEXT NOT NULL REFERENCES economic_events(id),
    right_event_id TEXT NOT NULL REFERENCES economic_events(id),
    link_type TEXT NOT NULL,
    confidence TEXT NOT NULL,
    review_state TEXT NOT NULL,
    evidence_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    CHECK(left_event_id < right_event_id),
    UNIQUE(left_event_id, right_event_id, link_type)
);

CREATE INDEX idx_event_links_right ON event_links(right_event_id);
