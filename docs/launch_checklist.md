# Launch Checklist

| Gate | State | Evidence / next action |
|---|---|---|
| SQLite-only fresh initialization | passed | Executed in Conda `short_selling`, Python 3.10.18 / SQLite 3.50.3 |
| Deterministic replay/no duplicate alert | passed | `test_replay_is_idempotent_and_aggregate_not_doubled` |
| Exact decimals and GBX | passed | `test_exact_decimals_and_locales`, `test_gbx_and_anonymous_identity` |
| Corrections/current view | passed on synthetic ordering/retraction cases | Add real correction-before-original sample |
| Backup/restore/raw verification | passed | `test_backup_restore_and_resume` |
| Interface/API/CSV | passed locally | Add browser accessibility review and production auth proxy |
| Real source transaction | passed for active slice | Norway, Sweden, Germany, Switzerland and France populate canonical data |
| 50 audited observations per major source | blocked | No source meets sample gate |
| 17 verified live adapters | blocked | 5 live-verified/tested routes; 12 remain |
| Commercial rights | not applicable | User confirmed private/non-commercial use |
| Persistent scheduler | passed | `InsiderTrackerDaily` installed and verified Ready; UTC trigger renders 07:00 local during DST |
| Public/commercial launch | out of scope | User confirmed this is a private, non-commercial research tool |

Private pilot result: **working five-route live slice with explicit quarantines; not yet 17-country coverage**.
