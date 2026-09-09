# Launch Checklist

| Gate | State | Evidence / next action |
|---|---|---|
| SQLite-only fresh initialization | passed | Executed in Conda `short_selling`, Python 3.10.18 / SQLite 3.50.3 |
| Deterministic replay/no duplicate alert | passed | `test_replay_is_idempotent_and_aggregate_not_doubled` |
| Exact decimals and GBX | passed | `test_exact_decimals_and_locales`, `test_gbx_and_anonymous_identity` |
| Corrections/current view | passed on synthetic ordering/retraction cases | Add real correction-before-original sample |
| Backup/restore/raw verification | passed | `test_backup_restore_and_resume` |
| Interface/API/CSV | passed locally | Add browser accessibility review and production auth proxy |
| Real source transaction | passed for active slice | Norway, Sweden, Germany, Switzerland, France, Netherlands and Denmark populate canonical data |
| 50 audited observations per major source | partial | France, Sweden, Netherlands, Norway, Switzerland and BaFin independently pass 50/50 after evidence-driven corrections; remaining major sources are pending |
| 17 verified live adapters | blocked | 7 jurisdiction routes implemented; 10 remain |
| Commercial rights | not applicable | User confirmed private/non-commercial use |
| Persistent scheduler | passed | `InsiderTrackerDaily` installed, automatic firing observed, and manual launch completed all sources; controlled result 2 is solely a retained Norway evidence quarantine |
| Public/commercial launch | out of scope | User confirmed this is a private, non-commercial research tool |

Private pilot result: **working seven-jurisdiction live slice with explicit quarantines; not yet 17-country coverage**.
