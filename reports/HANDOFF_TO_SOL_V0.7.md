# Handoff to Sol — V0.7 Phase 0/1

- Repository: `Septorange/StrategyReplication`
- Branch: `feature/v07-phase0-phase1`
- Scope completed: Phase 0 and offline Phase 1 only
- Frozen V6 base: `/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6/`
- Extended snapshot: local `data/v07_local/extended_<snapshot_id>/`, status `LOCAL_UNPUBLISHED`
- Latest verified local history: `2026-09-24`
- Phase 3A last month-end signal: `2026-08-31`
- Phase 3B last portfolio date: `2026-09-24`
- Network/iFinD calls in this task: `0`
- Frozen hash evidence: `V0.7_FROZEN_HASHES_BEFORE.json` and `V0.7_FROZEN_HASHES_AFTER.json`
- Verified rebuild: `scripts/run_v07_phase1_verified.py` -> fresh empty staging, V2 Phase 2.5 readiness/FG gate and frozen Phase 3A/3B validation PASS; `formal_nav_frame` not used
- Frozen tree scope: `src,scripts,config,data/raw,data/processed`; before/after SHA256 unchanged (`a3491af9317fdb50030fb201b6c4b44b2b1ac53a1b09880ad59c435798dbc1d7`, 4542 files)
- Rebuild runtime: `/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/.venv/bin/python` (Python 3.10.11, pandas 2.3.3, pyarrow 25.0.1, PyYAML 6.0.3)
- Overlap evidence: `V0.7_BASELINE_OVERLAP_RECONCILIATION.csv`
- Data quality evidence: `V0.7_NEW_PERIOD_DATA_QUALITY.md`

Audit focus requested: staging isolation, source-to-output mapping, date/prewarm boundaries, prior-only 10VT, no missing held returns, public-repository data exclusion and navigation numbering. Phase 2 experiment library and Phase 3 iFinD data-center integration remain out of scope for this handoff.

Gate-0 note: `04_sync_history.py --raw-dir` currently affects only its scan; its delegated `02_download_history.py` call does not propagate a destination, so a real non-dry-run would write to the downloader's fixed `ROOT/data/raw`. Phase 3 integration must add a staging-safe destination adapter before enabling updates.
