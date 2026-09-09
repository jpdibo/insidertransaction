# Operations

## Daily Run

The Windows Task Scheduler definition at `scheduler/InsiderTrackerDaily.xml` is installed as `InsiderTrackerDaily`; it runs the `short_selling` Conda interpreter every calendar day at 06:00 UTC with `StartWhenAvailable`. Automatic firing and a manual Task Scheduler launch have been observed. Exit code 2 means the pipeline completed with an explicit source quarantine or failure; inspect the matching `data/reports/run_*.json` rather than treating it as a process crash.

The daily process acquires `data/lock`, migrates and validates configuration, resumes from source checkpoints with overlap, stores raw bytes atomically, parses outside write transactions, commits accepted facts and dry-run alert outbox entries, writes JSON/Markdown reports, creates an online SQLite backup, copies every referenced raw object, and releases the lock. Exit `0` is success, `2` partial failure and `3` writer overlap.

## Recovery

- Source outage: leave its checkpoint unchanged, inspect `run_tasks` and health snapshots, keep healthy sources enabled.
- Website redesign or HTTP 200 challenge: retain bytes, quarantine, mark degraded, add a reviewed parser fixture; never auto-repair.
- Unit error: disable affected analytics, add a corrected parser version, replay saved bytes and issue correction outbox rows.
- False merge: append a review decision and split stable events/identities; never delete evidence.
- Duplicate inflation: inspect source-native IDs, publication links, row occurrence ordinals and selected representation.
- Bulk correction: back up, replay a bounded source/date range, verify current and prior versions, then rebuild metrics.
- Database recovery: `python -m insider_tracker restore BUNDLE EMPTY_DIR`; verify integrity, foreign keys and raw hashes before replacing service paths.
- Alert retraction: outbox uses event/version keys; enqueue a correction/retraction referencing the prior version. Delivery remains dry-run.
- Parser rollback: retain old parser code/config/reference artifacts with the backup manifest, restore and replay frozen bytes.

Backups use `sqlite3.Connection.backup`, not live file copying. Raw objects are immutable and copied into each bundle. Keep bundles on separately configured encrypted storage in production; retention target is 7 daily, 4 weekly and 12 monthly bundles after measured sizing.

The app is localhost-only by default. Set `INSIDER_TRACKER_TOKEN`; use TLS at a reverse proxy for remote access, least-privilege OS ACLs, encrypted disk/backups, and never share the SQLite file over a network mount.
