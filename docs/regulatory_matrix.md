# Regulatory Matrix

Research verified 07 September 2026 unless noted. These are implementation inputs, not legal advice. Effective rules must be selected using transaction/notification dates.

| Regime | Effective fact | Product treatment | Source |
|---|---|---|---|
| EU MAR | Article 19 covers PDMR/PCA transactions; Listing Act changed default annual threshold to EUR 20,000 with national adjustment | Threshold is an annual notification trigger, never a per-row filter | [Regulation (EU) 2024/2809](https://eur-lex.europa.eu/eli/reg/2024/2809/oj) |
| Germany | EUR 50,000 from 01 Jan 2026; prior intervals must remain separate | Rule-version row required before legal timeliness classification | [BaFin managers transactions](https://www.bafin.de/EN/Aufsicht/BoersenMaerkte/Emittentenleitfaden/Modul3/Kapitel2/Kapitel2_1/Kapitel2_1_node_en.html) |
| Sweden | Public register describes EUR 5,000 and records from 03 Jul 2016; national/current Listing Act treatment needs legal recheck | Registry wording is recorded; no universal EU threshold copied across history | [FI PDMR register](https://www.fi.se/en/our-registers/pdmr-transactions/) |
| UK | FCA guide states EUR 5,000; PDMR/PCA notification and issuer-publication clocks differ | No legal-late label without receipt evidence, working-day calendar and rule version | [FCA UK MAR](https://www.fca.org.uk/markets/market-abuse/regulation) |
| Switzerland | SIX Listing Rules Article 56 regime; public notices can be anonymous and are available for three years | No named-person or independent-person metric without corroborating evidence | [SIX management transactions](https://www.ser-ag.com/en/resources/notifications-market-participants/management-transactions.html) |

Country routing is maintained in `config/sources.yaml` and `docs/country_matrix.csv`. Submission portals are never treated as investor-readable feeds. Major holdings, buybacks, insider lists, suspicious-transaction reports and takeover dealing are separate classes.
