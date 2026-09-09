# Progress And Resume

## Implemented And Tested

Migration ledger/schema through 013, source registry, immutable raw storage, official adapters for seven jurisdictions, deterministic HTML/JSON/PDF/XML parsers, persisted discovery metadata, filing/group raw names and option-underlying identifiers, exact decimals, PCA relationships, anonymous roles, semantic document hashes, filing/event revisions and retractions, cross-source duplicate links, row reconciliation, dry-run outbox, ownership-safe writer lock, abandoned-run recovery, checkpoints, reports, online backup/restore, web/API/CSV, installed Conda scheduler and 51 passing tests. The canonical database has 383 current events. Netherlands has 62 current events from 53 notifications. Denmark contributed six events from seven announcements; `300014006` is evidence-incomplete and remains quarantined. Norway has 52 current events; only `681380` and `681718` remain quarantined for missing authoritative evidence. Sweden has 113 current events after count-checked, daily-partitioned retrieval completed under measured FI pacing. Independent evidence audits pass 50/50 for France, Sweden, Netherlands and Norway.

## Priority Queue

1. Obtain missing notification forms for NewsWeb `681380` and a defensible transaction date for `681718`; the accepted Norway set independently passes 50/50.
2. Expand Sweden backfill under the measured FI pacing limits; its independent 50-observation audit and aggregate/detail reconciliation are complete.
3. Independently audit 50 BaFin observations and broaden the Unternehmensregister archive sample beyond 19 December 2016.
4. Define reviewed bilingual-event linking for separate German/English archive publications; never silently merge them.
5. Determine Netherlands correction/removal behavior; its independent audit passes 50/50. Resolve Denmark form `300014006` only if new authoritative evidence appears.
6. Obtain written Nasdaq permission/licensing before automating Finland; Finnish OAM/Nasdaq public terms currently prohibit capture.
7. Establish an approved UK PIP/RIS contract; use FCA NSM only for archive reconciliation.

Resume with `python -m unittest discover -v`, inspect `docs/country_history.md` and `docs/launch_checklist.md`, and never promote a status without transaction-level evidence and repeat ingestion.
