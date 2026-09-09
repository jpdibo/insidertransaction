# Product Specification

## Users And Scope

The first user is an authenticated equity researcher. The product covers disclosed PDMR/PCA transactions for exactly the 17 configured jurisdictions, while distinguishing EU MAR, EEA MAR, UK MAR and SIX rules. Inclusion depends on issuer, listing, venue and publication route evidence, never ISIN prefix alone.

The default signal screen includes evidenced cash acquisitions of ordinary equity only. Grants, vesting, exercises, transfers, gifts, automatic plans, derivatives, debt and ambiguous acquisitions remain searchable but excluded. Sales remain first-class research records without inferred motive or recommendation.

## Workflows

- Feed: sort by publication evidence; compare trade date; filter country/action/issuer; inspect units and quality.
- Disclosure: inspect reported rows, selected analytical representation and source links.
- Coverage: distinguish route research, sampled parsing, adapter testing and live verification.
- API/CSV: retrieve the same accepted current view with decimals serialized as strings and spreadsheet formula-injection protection.

## Field Semantics

Known instants are ISO-8601 values retaining source offsets; date-only facts remain dates. Reported decimal text is canonicalized using `Decimal`, never SQLite `REAL`. `eligible_own_money_signal` requires cash acquisition, qualifying equity and evidence of mechanism/discretion. Anonymous SIX rows have no invented person identity.

## Access And Success

The app binds to localhost by default. `INSIDER_TRACKER_TOKEN` protects all routes when set. Public facts are separate from future private notes. Success means deterministic replay, traceable evidence, conservative uncertainty and honest coverage, not a 17-country marketing count.
