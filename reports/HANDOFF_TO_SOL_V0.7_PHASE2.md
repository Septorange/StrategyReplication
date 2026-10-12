# Handoff to Sol · V0.7 Phase 2 Experiment Library

Implementation branch: `feature/v07-phase2-experiment-library`  
Base commit: `ad55e07`  
Implementation report: `V0.7_PHASE2_EXPERIMENT_LIBRARY_REPORT.md`  
Inventory report: `V0.7_PHASE2_GATE2_0_INVENTORY.md`

The Phase 2 implementation adds selected-snapshot Python experiments, durable run/evaluation/saved-scheme identity, a SQLite library backed by disk artifacts, common-window comparison for any two saved schemes, and the corresponding Mode B controls. Original P1–P4 remain disabled. The main acceptance experiment, extended snapshot through `2026-09-24` with `target_vol=12%` and commodity cost `5bps`, completed through frozen V6 Phase3B Python functions with 2,670 daily observations. Both commodity roll and rebalance cost sums are nonzero.

## Independent audit requests

Please audit the implementation without broad redesign, with focus on:

1. Confirm every `READY` parameter reaches the intended V6 functions and unsupported P1–P4 changes remain rejected.
2. Verify the extension loader locates the exact local inputs for the registered snapshot, checks the registry rebuild-manifest digest and per-input SHA-256, and never writes into the V6 or published snapshot trees.
3. Recompute full-identity SHA-256 and verify deterministic repeated POST behavior, cache collision handling, stale cache rejection, and stable run/evaluation IDs after service restart.
4. Check evaluation start/end against actual trading dates and `latest_verified_date`, including reversed, missing and out-of-range boundaries.
5. Independently compare default-parameter extended output day by day to the published extended snapshot, including PnL, weights, net returns and cost fields.
6. Verify the 5bps experiment applies to both commodity contract rolls and Phase3B rebalance costs, without duplicate cost deduction or leakage into baseline data.
7. Verify pairwise comparison aligns by exact common dates, recomputes both schemes on that same interval and reports correct rebased NAV, drawdown, costs and exposure.
8. Exercise Mode B after service restart: reopen the extended 12%/5bps saved scheme and compare it directly with another saved scheme.
9. Review error behavior for missing/corrupt SQLite rows, result JSON and stage artifacts. Confirm the interface never presents missing data as zero or a synthetic result as real.

The result JSON is now SHA-256-bound by `artifact_manifest.json`; the resolver checks the manifest, adapter version, full identity and SQLite run metadata. Cache execution locks both full identity and short directory alias and publishes completed temp directories without deleting an existing alias. The parent should still exercise corrupt/missing artifact paths through the API.

## Explicit boundaries

The adapter reuses snapshot-specific Phase3A baseline weights and Phase2 signals/trade returns, then reruns real V6 Phase3B functions. It does not claim that disabled upstream parameters were recomputed. The modified response/library layer remains unaudited. Do not mark Sol approval based on this handoff. No data upload, push, merge, V6 edit or published-snapshot edit is part of this work.

At handoff, `py_compile`, `node --check`, `git diff --check`, and four targeted library/runner tests pass. Full pytest reports 58 passed and one legacy evidence failure: `test_required_real_experiments_have_saved_engine_evidence` compares V0.6 source hashes pinned before the Phase 2 changes to the now-updated adapter files. Historical evidence was left unchanged. The parent should decide how that legacy assertion is handled while preserving provenance. Extended default-parameter daily reconciliation is complete and documented in `V0.7_PHASE2_DEFAULT_EXTENDED_RECONCILIATION.json`. Browser/restart acceptance and independent Sol review remain pending; this handoff does not signify audit approval.
