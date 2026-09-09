# European Insider Transactions

Private research-pilot launch candidate for disclosed PDMR/PCA and Swiss management transactions. It uses one local SQLite database, immutable content-addressed evidence, deterministic Python parsers, and a server-rendered analyst feed. It does not imply illegal insider dealing and does not infer sentiment from acquisition/disposal labels.

## Tested State

- Conda environment `short_selling`: CPython 3.10.18, SQLite 3.50.3, `pypdf` 3.17.4; Windows.
- Fifty-one system and adapter-contract tests pass on 09 September 2026.
- Official adapters cover Norway NewsWeb, Sweden FI, Switzerland SIX, Germany BaFin and Unternehmensregister, France AMF, Netherlands AFM, and Denmark OAM.
- Discovery counts, immutable evidence, stable source identities, exact decimals, PCA relationships, revisions, retractions and aggregate/detail reconciliation are retained where the source supports them. Unsupported or incomplete evidence is quarantined.
- Six synthetic events exercise required edge cases and are visibly sourced from `offline_fixture_corpus`; they are excluded from production coverage claims.
- The local canonical database contains 383 current events: 377 official events across seven jurisdictions and six synthetic controls. See `docs/country_history.md` for the step-by-step jurisdiction ledger.

## Commands

```powershell
$python = "C:\Users\jpdib\anaconda3\envs\short_selling\python.exe"
& $python -m pip install -e .
& $python -m insider_tracker init-db
& $python -m insider_tracker daily
& $python -m unittest discover -v
& $python -m insider_tracker web --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. Set `INSIDER_TRACKER_TOKEN` to require a bearer token. The daily command works with the interface closed and creates a SQLite online backup plus copied raw evidence.

Other commands: `probe`, `backfill --cutoff ...`, `reparse`, `reconcile`, `rebuild-metrics`, `retry-quarantine`, `audit-sample`, `show-coverage`, `backup`, and `restore BUNDLE DESTINATION`. Maintenance hooks are lock-safe; accepted metrics are rebuilt transactionally.

## Storage

- Canonical database: `data/insiders.sqlite3`
- Immutable evidence: `data/raw/<hash-prefix>/<sha256>.<ext>`
- Daily reports: `data/reports/`
- Consistent bundles: `data/backups/`

The SQLite file must remain on persistent local disk, not a network or cloud-sync folder. Remote users access HTTP(S), never the database file.

## Limitations

The source registry covers 17 jurisdictions, but ten have no implemented retrieval adapter. NewsWeb and several other sources use observed public web-application calls rather than supported APIs. Norway has two records quarantined for missing authoritative evidence, Sweden FI throttles long result sets, Denmark has one missing-form announcement, and Finland/UK automation requires permission or licensing. Historical coverage and independent 50-observation reviews remain incomplete. See `docs/launch_checklist.md`.
