# Independent Audit Results

## 09 September 2026

| Source | Sample | Evidence | Initial result | Corrective action | Final result |
|---|---:|---|---|---|---|
| France AMF BDIF | 50 current events | 38 SHA-256-matched official PDFs | 48 pass, 2 fail, 0 blocked | Recognized issuer-declared aggregate figures and explicit effective acquisitions in comments; reparsed saved evidence | 50 pass, 0 fail, 0 blocked |
| Sweden FI Insyn | 50 current events | 50 SHA-256-matched official HTML records | 47 pass, 3 fail, 0 blocked | Persisted filing-version issuer names and transaction-group instrument names via migration 012; reparsed saved evidence | 50 pass, 0 fail, 0 blocked |
| Netherlands AFM | 50 current events | 41 SHA-256-matched official HTML records | 48 pass, 2 fail, 0 blocked | Populated version-specific issuer names and matched aggregates by exact transaction category/type; reparsed saved evidence | 50 pass, 0 fail, 0 blocked |
| Norway NewsWeb | 50 current events | 84 SHA-256-verified messages and official attachments | 34 pass, 16 fail, 0 blocked | Corrected publication joins, raw-name replay, ISIN boundaries, option/underlying identity, row representation, dates, names, instruments and venue footers; two review cycles | 50 pass, 0 fail, 0 blocked |
| Switzerland SIX | 50 current events | 50 SHA-256-matched official JSON details | 49 pass, 1 fail, 0 blocked | Corrected `correcteeId` amendment semantics, exposed party-role and reported-consideration fields in the audit manifest, and replayed saved evidence | 50 pass, 0 fail, 0 blocked |
| Germany BaFin | 50 current events | 50 SHA-256-matched official HTML details | 39 pass, 11 fail, 0 blocked | Normalized explicit `Sonstiges` explanations, retained aggregate-only monetary rows, prevented duplicate row occurrences from collapsing in audit output, and replayed saved evidence | 50 pass, 0 fail, 0 blocked |
| Germany Unternehmensregister | 50 current events | 50 SHA-256-matched official HTML publications | 19 pass, 31 fail, 0 blocked | Preserved publication-language names, corrected whole-word action matching, entity/PCA roles, gift direction, underlying ISINs and MICs; removed parser-obsolete contradictory role rows; two review cycles | 50 pass, 0 fail, 0 blocked |

The deterministic manifests and reviewer decisions remain local under `data/reports/` because they contain personal data and immutable source references. They are excluded from Git. The review compared each selected analytical row to authoritative raw evidence rather than treating parser output as proof.

France corrections cover events `event_4917b420028e67e691abae9d` and `event_110e8bb9deb8e0529d4e893f`. Sweden corrections cover events `event_644bebc268a0b625790695de`, `event_9eab8125939d33b3c94f48d5`, and `event_31f8b49dce16b44dcd023878`. Swiss correction semantics were verified on `T1Q9400078`. Netherlands, Norway and BaFin event-level decisions and evidence notes remain in their local manifests.
