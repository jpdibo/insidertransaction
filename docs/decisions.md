# Decisions

- SQLite 3 only through standard-library `sqlite3`; no ORM, database server, container or queue.
- JSON-compatible YAML permits a versioned `sources.yaml` without a YAML runtime dependency.
- Standard-library WSGI keeps deployment to one Python process and one scheduled command.
- Decimals are normalized strings and calculated with `Decimal`; SQLite never calculates canonical money.
- Stable IDs derive from source-scoped evidence keys; identical economics are not a deduplication key.
- Detailed rows win analytical selection over matching aggregates; both remain stored.
- Synthetic fixtures use an `out_of_scope` source and never count toward country coverage.
- Observed browser requests are not called documented APIs.
- The Windows scheduler is installed on the confirmed persistent pilot host; automatic and manual Task Scheduler launches are verified.
