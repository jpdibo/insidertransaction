# Independent Audit Results

## 09 September 2026

| Source | Sample | Evidence | Initial result | Corrective action | Final result |
|---|---:|---|---|---|---|
| France AMF BDIF | 50 current events | 38 SHA-256-matched official PDFs | 48 pass, 2 fail, 0 blocked | Recognized issuer-declared aggregate figures and explicit effective acquisitions in comments; reparsed saved evidence | 50 pass, 0 fail, 0 blocked |
| Sweden FI Insyn | 50 current events | 50 SHA-256-matched official HTML records | 47 pass, 3 fail, 0 blocked | Persisted filing-version issuer names and transaction-group instrument names via migration 012; reparsed saved evidence | 50 pass, 0 fail, 0 blocked |

The deterministic manifests and reviewer decisions remain local under `data/reports/` because they contain personal data and immutable source references. They are excluded from Git. The review compared each selected analytical row to authoritative raw evidence rather than treating parser output as proof.

France corrections cover events `event_4917b420028e67e691abae9d` and `event_110e8bb9deb8e0529d4e893f`. Sweden corrections cover events `event_644bebc268a0b625790695de`, `event_9eab8125939d33b3c94f48d5`, and `event_31f8b49dce16b44dcd023878`.
