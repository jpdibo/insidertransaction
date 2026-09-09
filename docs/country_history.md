# Country Implementation History

This ledger records what was done for each of the 17 in-scope jurisdictions. Dates are evidence or implementation dates, not claims of production readiness. Live databases, raw documents, backups and audit worksheets stay local and are intentionally excluded from Git because they contain source evidence and personal data.

## Austria (AT)

- 2026-09-07: Registered OeKB issuer/OAM as the primary candidate route.
- 2026-09-07: Recorded pre-MAR FMA archive evidence and separated the publication route from submission systems.
- Current state: `publication_route_confirmed`; no adapter or transaction-level sample.
- Next gate: identify the exact Article 19 category, stable IDs, history and varied current samples.

## Belgium (BE)

- 2026-09-07: Registered the FSMA transaction search as the primary dedicated register.
- Current state: `publication_route_confirmed`; no adapter or transaction-level sample.
- Next gate: verify search/export contracts, correction timestamps, pagination and history.

## Switzerland (CH)

- 2026-09-08: Identified SIX overview and issuer JSON endpoints from the production UI.
- 2026-09-08: Verified date, paging, transaction, security, management-role and related-party code meanings.
- 2026-09-08: Implemented `ingestion/six.py` and `parsers/six_json.py`.
- 2026-09-08: Ingested 36 anonymous-party events and repeated with 36 unchanged and zero quarantines.
- 2026-09-09: Enabled one-day historical backfill, but the 25 August request timed out twice across all configured retries; no checkpoint advanced.
- 2026-09-09: Retried after endpoint recovery and accepted 17 events for 25 August, reaching 53 with zero quarantines.
- 2026-09-09: Independent review initially passed 49/50. Corrected `correcteeId` amendment semantics, replayed all 53 saved details, expanded audit fields, and passed 50/50.
- Current state: `live_verified`; three-year public retention and redistribution rights remain constraints.
- Next gate: demonstrate stable repeat retrieval over a longer interval and resolve reuse terms.

## Germany (DE)

- 2026-09-08: Implemented and repeat-tested the BaFin recent-register adapter and HTML parser.
- 2026-09-08: Accepted 20 BaFin events with 28 price/monetary-volume rows. Unit quantity remains null because BaFin does not publish it in those details.
- 2026-09-08: Implemented the Unternehmensregister archive search using `publicationCategory=80`, daily windows and `printView` details.
- 2026-09-08: Replaced unstable encrypted search-payload IDs with stable detail `jobNumber` identities.
- 2026-09-08: Added German, English and numbered Article 19 archive layouts and corrected `Verkauf` classification.
- 2026-09-08: Validated 27 archive publications on 2016-12-19 with a final 27-unchanged replay and zero quarantines.
- 2026-09-09: Enabled one-day BaFin backfill and accepted 13 additional events from 25-27 August, reaching 33. The 28 August window then timed out twice without checkpoint advancement.
- 2026-09-09: Recovered the endpoint, expanded BaFin backward through 18-20 August, and reached 53 accepted events.
- 2026-09-09: Retained an aggregate-only monetary disclosure without inferring quantity. Independent review initially passed 39/50; explicit `Sonstiges` explanations and duplicate audit rows were corrected, saved evidence was replayed, and the final audit passed 50/50 across 81 selected rows.
- 2026-09-09: Expanded the archive through 23 December 2016, reaching 93 publications with zero quarantines.
- 2026-09-09: Archive review initially passed 19/50. Corrected filing-language instrument names, whole-word option actions, legal-entity/PCA roles, explicit gift direction, underlying ISINs, MICs and obsolete contradictory role rows; final independent review passed 50/50.
- 2026-09-09: Identified 11 defensible bilingual pairs and one standalone correction candidate. They remain separate and unlinked because the archive publishes no machine-readable parent or equivalent-publication identifiers.
- Current state: BaFin `adapter_tested`; archive `sample_verified`. Ambiguous legacy aggregate labels remain raw-only and excluded from analytics.
- Next gate: continue bounded archive dates and link publications only if authoritative identifiers become available.

## Denmark (DK)

- 2026-09-08: Researched Finanstilsynet OAM and Nasdaq; selected the official OAM as primary and Nasdaq as permission-gated reconciliation.
- 2026-09-08: Identified the OAM JSON POST search, 100-row paging limit, stable numeric announcement IDs, details and official attachment host.
- 2026-09-08: Added JSON request-body support, `ingestion/denmark_oam.py` and `parsers/denmark_oam_json.py`.
- 2026-09-08: Added English PCA, English aggregate-only and column-scrambled Danish form handling.
- 2026-09-08: Retained seven announcements from 2026-09-06 through 2026-09-08 and accepted six transaction events.
- 2026-09-08: Kept `300014006` quarantined because its public package omits the transaction form; correction `300014007` separately includes and parses the form.
- 2026-09-08: Repeated the 2026-09-08 slice with three unchanged.
- 2026-09-09: Advanced bounded coverage through 9 September. The 8 September slice replayed three unchanged, 9 September had zero records, and live `300014006` remained byte-identical with no added form.
- Current state: `adapter_tested`, disabled from daily scheduling while the sample has an evidence gap.
- Next gate: broaden dates/layouts and obtain the missing public form only if authoritative evidence appears.

## Spain (ES)

- 2026-09-07: Registered CNMV issuer search as the candidate public route.
- Current state: `discovered`; no complete global date-ordered route.
- Next gate: identify stable discovery, current/legacy split, details and corrections.

## Finland (FI)

- 2026-09-08: Verified Finnish OAM category 66, CSRF search, stable disclosure IDs and attachment routes.
- 2026-09-08: Measured 25,558 category records from July 2016 through 2026-09-08.
- 2026-09-08: Reconciled a bounded OAM/Nasdaq interval; Nasdaq-only Tallink records correctly belonged to the Estonian home state.
- 2026-09-08: Confirmed First North is outside Finnish OAM scope.
- Current state: `blocked`; Nasdaq terms prohibit automated/manual capture and extraction without written approval.
- Next gate: obtain written Nasdaq permission or a licensed feed.

## France (FR)

- 2026-09-08: Identified the AMF BDIF information API and its 10,000-result cap.
- 2026-09-08: Implemented mandatory daily partitioning, exact count checks, PDF retrieval and bilingual PDF parsing.
- 2026-09-08: Added detailed-fill retention, unselected aggregates, PCA handling and malformed-LEI quality policy.
- 2026-09-08: Accepted 43 repeat-stable PDFs producing 61 current transaction events with zero quarantines.
- 2026-09-09: Generated deterministic 50-event audit worksheet `data/reports/audit_fr_amf_bdif_50.csv` locally.
- 2026-09-09: Independent PDF review initially found two discrepancies. Added comment-based aggregate/effective-acquisition handling, reparsed saved evidence, and passed the repeated audit 50/50.
- Current state: `live_verified`.
- Next gate: complete and record the independent 50-observation review and validate real correction linkage.

## United Kingdom (GB)

- 2026-09-07: Verified FCA NSM storage scope, corrections/history behavior and delayed publication role.
- 2026-09-08: Confirmed prompt discovery requires an approved PIP/RIS; NSM is archive reconciliation only.
- Current state: `publication_route_confirmed`, automation permission/licensing blocked.
- Next gate: contract with an approved PIP/RIS and obtain FCA NSM automation permission.

## Greece (GR)

- 2026-09-07: Registered the ATHEX transaction-notification page.
- Current state: `publication_route_confirmed`; no adapter.
- Next gate: validate Greek/English transaction samples, identifiers, pagination and archive continuity.

## Ireland (IE)

- 2026-09-07: Registered the Central Bank of Ireland CSM as the candidate storage mechanism.
- Current state: `discovered`; transaction discovery and market-segment completeness are unverified.
- Next gate: establish the Article 19 category, stable detail contract and history.

## Italy (IT)

- 2026-09-07: Registered CONSOB internal-dealing and issuer dissemination candidates.
- Current state: `discovered`; public access remains technically unresolved.
- Next gate: validate CONSOB access and eMarket/1INFO issuer routing without bypassing controls.

## Netherlands (NL)

- 2026-09-08: Identified AFM's unpaginated filtered XML export and stable `meldingid` detail identity.
- 2026-09-08: Implemented `ingestion/nl_afm.py`, `parsers/nl_afm_html.py` and persisted discovery metadata via migration 011.
- 2026-09-08: Added Dutch localized decimal parsing, PCA linkage and detail/aggregate reconciliation.
- 2026-09-08: Validated 18 notifications producing 19 groups, 20 detail rows and 19 retained aggregates; final replay returned 18 unchanged.
- 2026-09-09: The manually launched scheduled daily run discovered 33 notifications and accepted 22 additional events without an AFM error.
- 2026-09-09: Bounded backfill through 27 August expanded the sample to 53 notifications and 62 events. Independent review found two issues; exact transaction-type aggregate matching and versioned raw-name replay corrected both, and the repeated audit passed 50/50.
- Current state: `live_verified` and daily-enabled. AFM does not publish correction lineage.
- Next gate: reach and independently review 50 observations, then establish removal/correction policy.

## Norway (NO)

- 2026-09-07: Implemented the observed NewsWeb announcement endpoint, attachment capture and reviewed KRT/MAR parser families.
- 2026-09-08: Reprocessed 38 saved documents and recovered 15 of 17 original quarantines.
- 2026-09-08: Kept `681380` quarantined because referenced forms are absent and `681718` quarantined because the authoritative transaction date is absent.
- 2026-09-09: Scheduled daily execution discovered new notification `681853`; its complete PDF exposed a no-space label extraction layout.
- 2026-09-09: Extended the compact MAR parser for that exact layout and accepted `681853` from saved evidence.
- 2026-09-09: Independent review of 50 accepted events initially found 16 issues. General fixes covered bilingual publication joins, event-specific names, anchored/spaced ISINs, attachment dates, option units/underlyings, row representation, instrument boundaries and venue footers; two repeated reviews reached 50/50.
- Current state: `adapter_tested`; two evidence-incomplete quarantines remain.
- Next gate: obtain authoritative missing evidence and expand to at least 50 independently reviewed observations.

## Poland (PL)

- 2026-09-07: Registered GPW ESPI/EBI as the candidate announcement route.
- Current state: `publication_route_confirmed`; no adapter.
- Next gate: validate main/NewConnect feeds, Article 19 category, attachments and rights.

## Portugal (PT)

- 2026-09-07: Registered CMVM SDI as the candidate document system.
- Current state: `discovered`; JavaScript retrieval contract remains unresolved.
- Next gate: establish stable search/detail identities, transaction category and history.

## Sweden (SE)

- 2026-09-07: Implemented FI search/detail ingestion with immutable report-version IDs.
- 2026-09-08: Added independent one-day historical backfill windows to respect FI throttling.
- 2026-09-08: Implemented aggregate/detail grouping and checks for summed quantity and rounded weighted price.
- 2026-09-08: Reparsed 61 saved report versions into 73 current groups with matching official aggregates and zero parser quarantines.
- 2026-09-09: Generated deterministic 50-event audit worksheet `data/reports/audit_se_fi_insyn_50.csv` locally.
- 2026-09-09: Scheduled daily execution reached page 9 before FI closed the connection; the source failed explicitly without advancing silently.
- 2026-09-09: Measured separate FI search and detail request windows, partitioned discovery by publication date, accepted the legitimate zero-result page shape, and configured eight-second search/four-second detail pacing.
- 2026-09-09: Completed a live source run with 76 report versions, zero quarantines and 26 newly accepted groups; Sweden reached 113 current groups, of which 111 match official aggregates and two are detail-only.
- 2026-09-09: Independent HTML review initially found three filing-specific name discrepancies. Migration 012 preserved issuer/instrument raw names per filing/group; saved-evidence replay and repeated review then passed 50/50.
- Current state: `adapter_tested`; source throttling remains operationally significant.
- Next gate: complete the 50-observation review and add resumable/reduced-pressure paging for daily retrieval.

## Cross-Country Milestones

- 2026-09-07: Created the SQLite-only canonical model, immutable raw store, migrations, reports, backup/restore and local web/API/CSV interface.
- 2026-09-08: Added migrations 008-010 for identifier uniqueness, event links and retractions; hardened locking, crash recovery and correction ordering.
- 2026-09-08: Installed Windows Task Scheduler task `InsiderTrackerDaily` using the required Conda interpreter and UTC-safe trigger.
- 2026-09-08: Added migration 011 to persist discovery metadata needed for deterministic saved-byte replay.
- 2026-09-09: Manually launched the installed task. It ran to completion through Task Scheduler and returned controlled partial-failure code 2 because of known Norway quarantines, one new recoverable Norway layout and Sweden throttling.
- 2026-09-09: Added deterministic `audit-sample` CSV generation and produced 50-event France and Sweden review manifests locally.
- 2026-09-09: Launched the installed Task Scheduler entry after FI hardening. Every live source completed; exit code 2 was solely the expected NewsWeb evidence quarantine, demonstrating controlled partial-failure reporting.
- 2026-09-09: Added migration 012 for filing-version issuer names and transaction-group instrument names after independent audit exposed lossy shared-entity labels.
- 2026-09-09: Added migration 013 to preserve an option's reported underlying-share ISIN without assigning it as the option's own ISIN.
