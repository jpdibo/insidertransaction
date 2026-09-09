# Validation Report

Validation updated: 09 September 2026. Host: Windows. Runtime: Conda `short_selling`, CPython 3.10.18, SQLite 3.50.3, pypdf 3.17.4. Result: **57 passed, 0 failed, 0 skipped**.

## Executed Commands

```powershell
& "C:\Users\jpdib\anaconda3\envs\short_selling\python.exe" -m pip install -e .
& "C:\Users\jpdib\anaconda3\envs\short_selling\python.exe" -m compileall -q insider_tracker ingestion parsers tests
& "C:\Users\jpdib\anaconda3\envs\short_selling\python.exe" -m unittest discover -v
& "C:\Users\jpdib\anaconda3\envs\short_selling\python.exe" -m insider_tracker daily --config "C:\insider_sales\config\sources.yaml" --database "C:\insider_sales\data\insiders.sqlite3" --raw-root "C:\insider_sales\data\raw"
```

Final Conda test output on 09 September 2026 ended with `Ran 57 tests` and `OK`. Compilation emitted no errors. Regression coverage includes correction/retraction ordering, lock ownership races, role-classification replay, nullable-identifier uniqueness, cross-source links, UTC scheduling, multilingual source layouts, deterministic audits, SIX amendment semantics, BaFin aggregate-only and explicit-explanation handling, German archive option/entity/PCA/gift handling, AFM exact transaction-type grouping, NewsWeb ISIN/option/venue handling, Sweden daily partitioning, and AMF comment-based aggregate/acquisition semantics.

Saved-byte NewsWeb reprocessing recovered 15 of those 17 quarantined documents and produced 17 current events: standard MAR purchases/sales, a non-cash gift, a bond disposal with nominal volume, an option grant without assigning the underlying-share ISIN to the option, English KRT-1500, an AFM two-fill disclosure with its rounded aggregate retained but unselected, Schouw option exercise plus sale, and Thor Medical private-placement allocation plus a neutral share-lending transfer. A final offline replay checked all 38 documents, created no new versions, and retained only `681380` (referenced forms absent) and `681718` (transaction date unresolved) as quarantines.

The BaFin recent-register adapter was expanded with bounded one-day windows covering 18-20 and 25-31 August plus 01-09 September 2026. It contains 53 current events and 84 reported monetary rows. All quantities remain explicitly null because the public register labels monetary consideration as `Volumen` and does not publish unit quantity in these details. One disclosure publishes only aggregate price and monetary volume; that row is retained as aggregate without inferred quantity. The independent audit passes 50/50 events and all 81 selected rows in that sample.

Canonical database checks after German archive expansion and saved-byte correction replay: integrity `ok`; 0 foreign-key violations; 499 current events; 863 event versions; 521 source records and 970 immutable raw objects. Current-event sources: Switzerland 53, Germany BaFin 53, Germany archive 93, Denmark 6, France 61, Netherlands 62, Norway 52, Sweden 113 and synthetic controls 6. No contradictory role classifications remain for the same party, issuer and raw title.

The Unternehmensregister archive route was expanded across publication dates 19-23 December 2016. It retained 93 explicit PDMR publications with zero quarantines. Stable identity comes from each detail's official `jobNumber`; opaque search payloads are intentionally not identifiers because they change on every query. German, English and numbered layouts retain filing-language names, entity/PCA roles, whole-word actions, option underlyings and MICs. Legacy aggregate labels that attach currency to both values remain raw-only, normalized quantity/price are null, and all archive aggregate rows are excluded from analytics. Independent evidence review passes 50/50. Eleven bilingual pairs and one correction candidate remain separate because the archive exposes no authoritative parent/equivalence identifier.

The Netherlands AFM route was validated for transaction date 1 September 2026 using the official filtered XML export and HTML details. It discovered 18 stable `meldingid` notifications and produced 19 current transaction groups after reconciling one two-fill notification to its official aggregate. The sample contains 20 detail rows, 19 retained/unselected aggregate rows, one PCA legal entity with persisted related-PDMR metadata, zero null quantities and zero quarantines. Final network replay returned 18 unchanged; final saved-byte reparse returned zero changes. AFM does not expose correction lineage, so every filing carries an explicit correction-semantics quality warning.

The Denmark Finanstilsynet OAM route was tested on publication dates 6-8 September 2026. Seven stable announcements and their official attachments were retained; six transaction events parse across English PCA, English aggregate-only and column-scrambled Danish forms. The 8 September slice repeated with three unchanged. Announcement `300014006` remains quarantined because its public package contains only an issuer cover notice and a regulator receipt referencing private submission `300014005`, not the Article 19 transaction form. Correction `300014007` separately publishes the actual form and is accepted. This source remains adapter-tested and disabled from daily scheduling.

## Covered Gates

| Test | Outcome |
|---|---|
| Same saved bytes replay | Stable event/version/hash/outbox counts; archive live replay returned 27 unchanged |
| Netherlands AFM replay | 18 stable IDs unchanged; 20 fills reconciled into 19 groups with official aggregates unselected |
| Denmark OAM bounded sample | 6 of 7 announcements accepted; 1 evidence-incomplete package retained/quarantined |
| Exact decimals `2`, `10`, `0.123456789123456789` | Exact round trip and Decimal numeric ordering |
| 10,000 at 245.50 GBX | GBP 24,550 with `0.01` quote scale |
| Two fills plus aggregate | Details total 3,000; aggregate retained and unselected |
| Correction | Same event, prior version superseded, correction outbox entry |
| Anonymous Swiss role | Null canonical name; disclosure-scoped anonymous ID |
| PCA legal entity | Party and related PDMR remain separate |
| Exercise and tax sale | Distinct actions; neither becomes own-money purchase |
| Unknown layout | Raw bytes retained; source task quarantined; no event |
| Unknown currency | Price retained; no derived consideration |
| Writer overlap | Second lock acquisition raises explicit busy result |
| Crash recovery | Abandoned runs/tasks finalize as interrupted after exclusive lock acquisition |
| Correction ordering | Correction remains current when the original arrives later |
| Reparse removal | Missing corrected groups are retracted while old versions remain auditable |
| Cross-source duplicates | Exact normalized candidates are linked for review and never silently merged |
| Scheduler | Real UTF-16 Windows XML, UTC boundary, IgnoreNew, installed task Ready |
| Backup/restore | Online snapshot, raw hashes, integrity and FK checks pass |
| Web/API/CSV | WSGI routes return successfully; date-only UI has no invented midnight |

The interface was opened with Playwright against `data/insiders.sqlite3`; the feed showed the real Instabank event and synthetic cases, and browser console errors were zero after the favicon/date fixes.

## Real Sample

NewsWeb message `681721`, source URL `https://newsweb.oslobors.no/message/681721`, was inspected on 07 September 2026. Captured response fixture SHA-256: `5628c8261141b6a5445f3b2d6455cb326843182a178c90ccab43fd5b0dbe03b4` (1,273 bytes). Manually checked fields: issuer Instabank ASA; party Janne Perlesentbakken; deputy employee board representative; sale; 37,556 shares; reported price 4.97; trade date 04 September 2026; publication `2026-09-07T06:14:40.529Z`; one attachment. Currency and attachment fields are unresolved and excluded from derived value.

The original message remains in the real corpus, now with its PDF attachment. The attachment supplies NOK, LEI, ISIN and value while conflicting with the headline on trade date/name; the current accepted version exposes the conflict rather than inventing certainty.

## Not Passed / Not Run

- No adapter satisfies every production-readiness gate, including stable long-run retrieval and resolved use/redistribution rights; seven sources now independently pass 50 observations.
- Live discovery and stable repeat ingestion are demonstrated for Norway, Sweden, Germany BaFin and Unternehmensregister, Switzerland, France and Netherlands. The installed scheduler has fired automatically and through a manual Task Scheduler launch; all sources completed in run `run_b8885a5dcd7d44d491dd3f31b3c177a2`, with controlled overall exit code 2 solely for a retained Norway evidence quarantine. Real correction-before-original, process termination injection and OCR extraction remain untested.
- Independent evidence review passed 50/50 current events for France, Sweden, Netherlands, Norway, Switzerland, BaFin and Unternehmensregister after correcting every initially identified discrepancy. Detailed reviewer decisions remain in ignored local CSV manifests; aggregate evidence is recorded in `docs/audit_results.md`.
- The Windows task is installed and `Ready`; automatic and manual Task Scheduler executions have both been observed.
- Commercial redistribution and feed rights remain unresolved for every source.
- PostgreSQL dependency scan over Python/TOML/SQL/JSON/XML returned no matches.

These are launch blockers, not passes. Current status is a tested private engineering vertical slice, not dependable 17-country operation.
