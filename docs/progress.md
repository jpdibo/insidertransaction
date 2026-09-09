# Progress And Resume

## Implemented And Tested

Migration ledger/schema through 011, source registry, immutable raw storage, official adapters for seven jurisdictions, deterministic HTML/JSON/PDF/XML parsers, persisted discovery metadata, exact decimals, PCA relationships, anonymous roles, semantic document hashes, filing/event revisions and retractions, cross-source duplicate links, row reconciliation, dry-run outbox, ownership-safe writer lock, abandoned-run recovery, checkpoints, reports, online backup/restore, web/API/CSV, installed Conda scheduler and 46 passing tests. The canonical database has 322 current events. Netherlands has 41 current events after the first scheduled run. Denmark contributed six events from seven announcements; `300014006` is evidence-incomplete and remains quarantined. Norway has 52 current events after recovering `681853`; only `681380` and `681718` remain quarantined for missing authoritative evidence.

## Priority Queue

1. Obtain missing notification forms for NewsWeb `681380` and a defensible transaction date for `681718`; independently audit at least 50 Norway observations. The other 15 former quarantines are recovered and repeat-stable.
2. Independently check 50 Sweden observations and expand backfill under FI throttling limits; aggregate/detail reconciliation is complete for the saved sample.
3. Independently audit 50 BaFin observations and broaden the Unternehmensregister archive sample beyond 19 December 2016.
4. Define reviewed bilingual-event linking for separate German/English archive publications; never silently merge them.
5. Independently audit the Netherlands AFM sample and correction behavior; broaden Denmark OAM layouts and resolve missing form `300014006` if evidence appears.
6. Obtain written Nasdaq permission/licensing before automating Finland; Finnish OAM/Nasdaq public terms currently prohibit capture.
7. Establish an approved UK PIP/RIS contract; use FCA NSM only for archive reconciliation.

Resume with `python -m unittest discover -v`, inspect `docs/country_history.md` and `docs/launch_checklist.md`, and never promote a status without transaction-level evidence and repeat ingestion.
