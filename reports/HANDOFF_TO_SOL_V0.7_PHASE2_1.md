# Handoff to independent Sol review

Branch `feature/v07-phase2-experiment-library`, HEAD `697091a`, Phase 1.5 base `ad55e07`. This handoff covers F01–F06 remediation. The certified extended saved IDs remain `scheme_d7596fefa8c84b84bd91cd168911689e` (12% target volatility) and `scheme_9fc7b5dda4a14cee9bf6119a3ab9279b` (commodity 5bps). 2020 evaluation reopen evidence returns 243 rows and the browser now opens that saved evaluation directly in the experiment detail page.

Please independently inspect the compatibility check, complete cache validator (including real Parquet parsing), public DTO redaction and FAILED-run persistence, saved-window view, SQLite migration/CRUD, and four Mode B navigation entries. Re-run `PYTHONPATH=. pytest -q`, the path-recursive API scan, damaged-cache fixture, same/cross-snapshot comparisons, first-day NAV/cumulative-return equality, and a fresh 8005 browser matrix. Do not push or merge until this review returns PASS.
