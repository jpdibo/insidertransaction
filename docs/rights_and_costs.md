# Rights And Costs

## Rights

Commercial redistribution is outside the requested scope. The pilot is private/internal and stores the evidence needed for research. If that scope changes, source terms would need review before public display, API resale or raw-document distribution; no such review is part of the current backlog.

Current constraints: NewsWeb uses observed undocumented SPA endpoints; SIX and French AMF expose public official JSON/document routes but no redistribution licence has been established; Netherlands AFM permits copying/distribution with source acknowledgement but automation terms remain unresolved; Unternehmensregister automated extraction terms remain unresolved; Denmark OAM permits download/use at user risk but commercial redistribution and GDPR basis are unresolved; Nasdaq terms prohibit capture/extraction without written approval, blocking Finland automation; FCA NSM terms restrict automated use without permission and NSM is not real time; a UK launch requires an approved/licensed PIP or RIS contract. These constraints do not prevent the current private research pilot where noted, but they block public redistribution and must not be represented as licensed rights.

## Cost Scenarios

Prices are planning assumptions dated 07 September 2026, not vendor quotes.

| Scenario | Infrastructure | Data licences | Maintenance | Assumptions |
|---|---:|---:|---:|---|
| Private pilot | EUR 10-40/month | EUR 0 pending permitted-use confirmation | 2-4 engineer days/month | 2 vCPU, 4 GB RAM, 80 GB encrypted local disk; daily polling; low OCR |
| Dependable 17-country | EUR 80-250/month | Quote unavailable | 8-15 days/month | 4 vCPU, 8 GB, 0.5-2 TB retained raw/backups, monitoring and source-change work |
| Commercial distribution | EUR 250-1,000+/month | Quote unavailable and potentially dominant | 1-2 FTE plus legal/data operations | licensed feeds/market data, redundant backups, support, security review and egress |

Measured fixture footprint is too small for reliable production extrapolation. Capacity planning must measure daily documents, attachments, PDFs/OCR share and retention. Proposed targets after live measurement: daily completion by 09:00 UTC 99%, source-relative freshness within one daily cycle, RPO 24 hours and RTO 8 hours. None is currently measured; daily polling is not real time.
