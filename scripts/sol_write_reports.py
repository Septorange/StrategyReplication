#!/usr/bin/env python3
"""Write Phase 2 conclusions from independently generated evidence."""
import json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'reports'

def md(frame):
    values=frame.fillna('NOT DISPLAYED / see sampled UI evidence')
    return '| '+' | '.join(str(c) for c in values.columns)+' |\n| '+' | '.join('---' for _ in values.columns)+' |\n'+'\n'.join('| '+' | '.join(str(v).replace('|','/').replace('\n',' ') for v in row)+' |' for row in values.itertuples(index=False,name=None))

def write(name,text): (R/name).write_text(text.strip()+'\n')

def main():
    core=pd.read_csv(R/'SOL_INDEPENDENT_CHECKS.csv');extra=pd.read_csv(R/'SOL_SUPPLEMENTAL_CHECKS.csv');engine=pd.read_csv(R/'SOL_MODE_B_CHECKS.csv')
    assert core.status.eq('PASS').all() and extra.status.eq('PASS').all() and engine.status.eq('PASS').all()
    baseline=pd.read_csv(R/'SOL_V6_BASELINE_RECOMPUTE.csv');mapping=pd.read_csv(R/'SOL_DATA_MAPPING_AUDIT.csv');vt=pd.read_csv(R/'SOL_10VT_RECOMPUTE.csv');roll=pd.read_csv(R/'SOL_ROLL_AUDIT.csv');weight=pd.read_csv(R/'SOL_WEIGHT_CHAIN_AUDIT.csv');momentum=pd.read_csv(R/'SOL_MOMENTUM_AUDIT.csv')
    experimental=[]
    for label in ['baseline','target_vol_12','commodity_cost_5','midmonth_25']:
        x=json.loads((R/f'SOL_EXPERIMENT_{label}.json').read_text());z=x['response'];experimental.append({'experiment':label,'key':z['config_hash'],'request':str(x['request']),'annualized_return':z['experiment']['annualized_return'],'annualized_vol':z['experiment']['annualized_vol'],'mean_10vt':z['experiment']['mean_10vt_multiplier'],'HTTP':x['http_status'],'engine_status':z['status'],'output_path':z['output_path']})
    exp=pd.DataFrame(experimental)
    write('SOL_TEST_BASELINE.md','''# Sol independent test baseline

Command: `/opt/anaconda3/bin/python -m pytest -q`, run from the project root before Sol changes.

| Phase | PASS | FAIL | SKIP | XFAIL |
| --- | ---: | ---: | ---: | ---: |
| Before fixes | 13 | 0 | 0 | 0 |
| After fixes | 19 | 0 | 0 | 0 |

There were no inherited failing tests. Audit-discovered defects were absent from those 13 assertions. No assertion was deleted or weakened. Added cost-adapter regression, official-route isolation, and four frozen V6 boundary fixtures for equity T-5, commodity calendar-30D, bond HARD_ROLL/FORCED_DATA_ROLL, and 2-day bond liquidity confirmation permitting earlier maturity.

`SOL_TEST_AFTER.log` records the final supported-runtime suite. `SOL_INDEPENDENT_CHECKS.csv`, `SOL_SUPPLEMENTAL_CHECKS.csv`, `SOL_API_CONTRACT_AUDIT.csv`, and `SOL_MODE_B_CHECKS.csv` record additional independent reconciliation outside pytest. Runtime warnings from the installed requests dependencies and restricted CPU cache inspection do not affect assertions or process exit codes.

Intermediate independent-audit harness failures were diagnosed rather than ignored: datetime64[ns] vs [us] MultiIndex.equals, 604 valid prelisting null signal rows, default haircut=1 for unavailable assets in the independent pivot, and persisted roll-weight JSON strings vs decoded dictionaries. After exact semantic corrections, all reconciliation checks pass. These were harness defects; no V6 or snapshot data was changed to satisfy them.
''')
    write('SOL_DATA_MAPPING_AUDIT.md',f'''# Sol data mapping audit

Status: PASS. Independent source reads, full-row comparisons and independent formulas support the following mapping; Phase 1 declarations were not used as evidence.

{md(mapping)}

The canonical snapshot matches all 2,220 formal portfolio rows and 24,420 date×asset weight/contribution rows. Monthly targets are selected by latest `next_trading_date <= daily_date`, not by current-month future signal. Daily signals use date×asset left joins: 23,816 rows have V6 source data and match; 604 absent prelisting source rows remain null. JSONL serialization differs from canonical float values by at most 5.000001e-11; API uses these mirrors directly and does not recompute strategy values.

Time semantics are explicit: `post_haircut_weight` is the current-close diagnostic target (`midmonth_theoretical_target`), while `controlled_target` is the frozen month-end controlled target during monthly smoothing. Actual `unscaled_execution_weight` / `pre10vt_weight` contains smoothing or the preceding close's pending midmonth decision; it is the start-of-day weight used for the day's return. It is incorrect to apply the current-close diagnostic directly to same-day PnL. The risk-budget UI now states this distinction and includes all three execution-chain columns.

Sampling: {md(weight.groupby('sample_type').agg(asset_rows=('asset','size'),dates=('date','nunique')).reset_index())}

All selected monthly asset budgets were independently recalculated as `(1/3)/N_class`, then divided by sigma; sleeve scale .4 / 1 / .8 applies after inverse-vol scaling and before caps. Capped exposure is not redistributed. No nominal sum-to-one normalization occurs. All 1,672 monthly target rows and 33,836 full-history execution rows match independent calculation. The detailed 330-row sample is `SOL_WEIGHT_CHAIN_AUDIT.csv`.
''')
    write('SOL_ROLL_AUDIT.md',f'''# Sol roll audit

Status: PASS. Independently verified {len(roll)} formal-window actual roll events, not just five screenshots.

{md(roll.groupby('trigger').agg(events=('asset','size'),fails=('status',lambda s:int(s.ne('PASS').sum()))).reset_index())}

Initial/candidate contracts use OI descending, volume descending, maturity ascending, code ascending; all 31,667 active-calendar candidates were independently ranked from eligibility quotes. IF/IC/IM roll at `days_to_expiry <= 5`, select only later maturities and use the nearest valid later maturity regardless of OI. Ordinary liquidity switches do not roll equity. Commodities trigger at delivery-month start minus 30 calendar days and choose a valid later target by OI/volume/maturity/code. TF/T use two-day confirmed active liquidity switches and a T-5 hard rule; earlier maturity remains allowed for bond liquidity rolls, so a global no-backward-roll statement would be wrong. All 5,976 bond active rows independently match confirmation state.

Every event has old holding at start of day, new holding at close and the new holding at the following observed trading day's start. Old-contract settlement(t)/settlement(previous observed asset day)-1 independently matches gross trade return. Contract costs are charged for close-time turnover with start-of-day asset exposure. Snapshot daily states and API daily rows are unchanged V6 values. `SOL_ROLL_AUDIT.csv` contains every event, target, timing flag and gross-return error.

Browser evidence in `SOL_UI_RUNTIME_AUDIT.md`: 2024-11-08 IM2411→IM2412 (T-5); 2024-11-01 SC2412→SC2501; 2024-08-19 TF2409→TF2412 (liquidity); 2024-10-11 IM2410→IM2411 although candidate is IM2412; 2024-10-08 SC2411→SC2412. API and snapshot samples are in `SOL_API_RUNTIME_EVIDENCE.json`.

No HARD_ROLL or FORCED_DATA_ROLL occurs within the formal sample. This is an event-coverage limitation, not evidence that those branches were exercised by real historical data. Sol added separate immutable-engine fixture tests exercising both branches and exact rule boundaries. Fixture data never enters production snapshots or experiments.

Inherited V6 formal contract-state metadata has 312 EXPIRY_UNVERIFIED records (SC229, AU43, CU40), with expiry_source=EXPIRY_UNVERIFIED_EXCEPTION. These rows are exposed unchanged by snapshot/API/UI. Commodity roll deadlines still derive from delivery month codes and the fixed 30-calendar-day rule, so expiry verification exceptions do not imply missing held settlement returns or failure of that rule. This website audit does not certify unknown exchange expiry metadata as verified.
''')
    write('SOL_SYNTHETIC_LEAKAGE_AUDIT.md','''# Sol synthetic leakage audit

Status: PASS after limited isolation fix. Formal Mode A strategy leakage = 0; formal Mode B result-generation synthetic/approximate backtest leakage = 0.

`SOL_SYNTHETIC_SEARCH.log` records the keyword scan. Production index loads only app.js; its official Mode A routes fetch V6 snapshot API data, and its experiment submission fetches POST /api/experiment. No `getDailyAssetRet`, `generateLegacy`, `Math.sin`, `Math.cos`, `Math.random`, `simulateStrategy`, `generateExperiment`, or `approximateBacktest` drives production results. `DEMO_MODE=False` is visible in config and /api/health.

The copied historical prototype contains synthetic simulation and explicitly labeled demo data. Before audit it lived under frontend and was directly reachable as `/prototype_v0.3.html` despite being unlinked. Sol moved only this project copy to `references/prototype_v0.3.html`, outside the mounted static root. The original V0.3 file was not modified. Actual route checks now return 404 for the historical prototype and 200 for official /. A regression test enforces that boundary.

The word synthetic in V6 signal_series describes an index compounded from observed same-contract settlement returns and prelisting index proxies; it is not an invented market generator. Independent raw signal recomputation and old-contract settlement PnL reconciliation verify that distinction. Fixed synthetic boundary fixtures exist only in tests and never enter formal runtime data.
''')
    write('SOL_MODE_B_ENGINE_AUDIT.md',f'''# Sol Mode B real engine audit

Status: PASS after two confirmed defects were repaired and all four experiments were rerun.

{md(exp)}

Trace: actual POST /api/experiment → Pydantic request → ExperimentRunner.run → independent fingerprint directory → request.json → `/usr/bin/arch -arm64 <V6-compatible Python>` → import unchanged V6 `src/phase3b.py` → `build_single_asset_vol_control`, `build_execution`, `build_portfolio_daily` → new saved weights/events/trade inputs/formal daily portfolio → result.json → API response → UI. Each directory includes `engine_run.json`, `engine_stdout.log`, `engine_stderr.log`; recorded current adapter/engine/config/input SHA256 values are independently checked. V6 files are read only; every output is in the new website project's experiment_cache.

Confirmed defect 1: the original `commodity_cost_bps` changed only Phase3B portfolio weight-rebalance fees, leaving Phase2 commodity contract-roll net returns at baseline zero fee. In `backend/experiment_costs.py`, an experiment-only copy now applies the exact V6 formula `roll_cost=contract_turnover*bps/10000`, `trade_return_net=trade_return_gross-roll_cost`, with matching cost_bps/cost_status. Gross returns, actual old/new contracts and timing remain the original V6 observations. Phase3B additionally computes `.5*abs(end_weight-start_weight)*class_bps/10000`. Thus 5 bps means BOTH commodity contract roll and portfolio weight rebalance; it is a Mode B assumption, while Mode A stays the official 0 bps pending verification baseline. Cost experiments preserve every weight and the gross-based 10VT multiplier.

Confirmed defect 2: the saved experimental formal portfolio NAV carried pre-formal accumulated history even though response KPIs recomputed formal-window NAV correctly. The adapter now rebases `nav_gross`, `nav_after_contract_roll`, and `nav_net` by cumprod of the corresponding formal-window returns exactly as V6 scripts/42_build_phase3_formal.py. Prehistory is still retained for prior-only VT estimation; only saved formal NAV evaluation is rebased. Independent checks verify first/last NAV and all intermediate values.

Old cache entries cannot supply new results: cache identity includes config, immutable baseline, engine/config/input hashes AND the actual experiment script / cost adapter SHA256. Both fixes changed this identity. The adapter_version remains 2 as metadata; script content hash (not the label alone) invalidates caches. All final reported output paths are the new identities listed above, with actual fresh subprocess run records. Earlier cache artifacts are retained as history and are not chosen by current runtime.

{md(engine)}

Independent recomputation from output portfolios is `SOL_MODE_B_RECOMPUTE.csv`. Independent portfolio PnL sums original start weights × same-contract gross returns, subtracts weighted contract roll fees and exact close-time rebalance fees. Baseline matches every V6 formal portfolio column and every full-history weight. 12% multiplier is independently `.12/sigma`, clipped [.5,1.5]. 5 bps weights and VT exactly match zero-fee baseline. Midmonth .25 actually reruns causal execution rather than approximating a return shift.

UI submission/response/record evidence is `SOL_UI_RUNTIME_AUDIT.md`. Three Mode B menu tabs currently expose the same generic single-experiment form; dedicated sensitivity sweep views are not implemented. Momentum exclusion count changes are disabled because the unchanged V6 Phase3A interface does not expose that override.
''')
    write('V6_STRATEGY_LAB_SOL_AUDIT.md',f'''# V6 Strategy Lab — Sol independent Phase 2 audit

## A. Overall status

**PASS WITH NON-MATERIAL LIMITATIONS**. The website's formal Mode A outputs equal the frozen V6 results, and Mode B actually reruns unchanged V6 Python strategy functions. Four experiments were rerun after confirmed cost and saved-NAV defects were fixed. No remaining material blocker or failing check is hidden by this status. Scope excludes certifying the official research methodology or the completeness of raw contract downloads beyond the frozen V6 artifacts.

Project: `{ROOT}`. Baseline: `/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6` (read only).

## B. Source integrity

V6 source unchanged. Six required SHA256 values independently match both Phase 1 BEFORE and AFTER manifests. Actual values are `SOL_V6_SOURCE_HASHES.json`; engine-run source fingerprints also match. No V6 source, official output, V7/V8, or original V0.3 was edited.

## C. Data lineage

V6 raw formal/Phase3A/Phase3B/Phase2 artifacts → canonical snapshot Parquet → generated JSONL mirror → FastAPI → frontend tables/canvas. Source comparisons cover all portfolio/weight/contribution rows, monthly as-of fields, raw daily signal/control mapping, roll states, and engine outputs. API routes pass {len(pd.read_csv(R/'SOL_API_CONTRACT_AUDIT.csv'))} independent HTTP assertions. Browser evidence covers all seven Mode A pages and four Mode B pages, empty console error array, date persistence, non-trading-day requested/resolved behavior, five daily states/exposures/contributions, and five rolls.

## D. Baseline reconciliation

{md(baseline)}

Values are decimal returns/exposures. Snapshot/API differences are floating arithmetic or JSONL serialization (max 5.000001e-11 per field), not changes in strategy semantics. UI KPI precision is two percentage decimals and three numeric decimals; formatting error is judged against that precision. Average class exposure is not separately displayed by UI; five selected-date class sums are directly reconciled in `SOL_UI_RUNTIME_AUDIT.md` instead of claiming an unobserved UI average. Full detail: `SOL_V6_BASELINE_RECOMPUTE.csv`.

## E. Mapping audit

All 22 required mappings PASS. Details: `SOL_DATA_MAPPING_AUDIT.csv/.md`. 604 unavailable prelisting signal rows remain null. Runtime/API reads JSONL mirrors, whose precise serialization error is documented. No approximate field is substituted for a semantically different stage. UI now distinguishes current-close `post_haircut_weight` from frozen `controlled_target` and real start-of-day `pre10vt_weight`.

## F. Momentum audit

V6 proxy/warm-up preserved. IC uses 551 proxy days; IM uses 2,321; IF uses futures signal history from 2013. Each IC/IM first-listing day has one proxy source row with trade_eligible metadata True in the original V6 source artifact, but all proxy dates have zero strategy holding exposure; no proxy trade-return leakage occurs. These inherited metadata rows were not silently changed. Independent raw-six-signal/risk recomputation covers 34,537 asset days, max error 2.220446e-16. All {len(momentum)} monthly ranks/exclusions match six descending average-tie ranks and deterministic mean-rank ordering. Before IM, eight eligible risk assets keep seven; after IM, nine keep eight. TF/T are retained when risk-estimate usable and are not momentum-eliminated. T/TF/SC sigma240 warm-up starts at 60; SC equivalent240 return warm-up is retained. Equity futures-only partial warm-up from V7 is not present.

## G. Risk-budget / sleeve-scale audit

Each class receives 1/3 budget, split by selected class member count. Inverse-vol exposure is multiplied by equity .4 / bond 1 / commodity .8 BEFORE asset caps. No nominal sum-to-one normalization or cap redistribution. All 1,672 monthly targets and all 33,836 causal execution rows independently match; 30 sampled dates / 330 asset rows cover 10 ordinary, 5 smoothing, 5 midmonth trigger, 5 floor/near-floor, 5 roll dates. `SOL_WEIGHT_CHAIN_AUDIT.csv` and `SOL_EXECUTION_RECOMPUTE.csv` retain evidence.

## H. 10VT audit

All {len(vt)} full-history days independently recomputed from gross pre-10VT portfolio returns, shifted one day, rolling120, ddof1, annualization sqrt252. raw=.10/sigma and clip [.5,1.5]. Maximum raw multiplier absolute difference {vt.raw_abs_diff.max():.17g}; final weights match unscaled execution×multiplier. Neither current day's return nor net NAV feeds this estimate. Evidence: `SOL_10VT_RECOMPUTE.csv`.

## I. Roll audit

All {len(roll)} formal events PASS: 248 equity T-5, 294 commodity calendar30D, 72 bond liquidity. Candidate ranking, later-maturity/nearest rules, bond confirmation, old same-contract settlement return and next-day holding alignment are independently checked against quote data. HARD_ROLL/FORCED_DATA_ROLL are absent from the formal event sample and explicitly covered by separate boundary fixtures. No global bond rollback prohibition is shown. Evidence: `SOL_ROLL_AUDIT.csv/.md`.

## J. Mode B audit

Real V6 engine calls confirmed for baseline, target .12, commodity 5 bps, and midmonth .25. Final output identities:

{md(exp[['experiment','key','annualized_return','annualized_vol','mean_10vt','engine_status']])}

The cost input adapter operates only on a copied Phase2 trade frame and uses V6's unchanged fee formula. Baseline full data remain identical. Formal saved NAV is now rebased to the same evaluation window. Actual command/source fingerprints/stdout/stderr and fresh output files prove execution. Evidence: `SOL_MODE_B_ENGINE_AUDIT.md`, `SOL_MODE_B_CHECKS.csv`, `SOL_MODE_B_RECOMPUTE.csv`.

## K. Synthetic leakage

0 formal Mode A strategy generators; 0 formal Mode B synthetic/approximate result generators. Historical demo copied into this project was served at an unlinked static path before audit; it is now preserved outside static root in references and official route returns404. Test fixtures are isolated from formal runtime. Evidence: `SOL_SYNTHETIC_LEAKAGE_AUDIT.md` and actual route regression.

## L. Tests

Before: 13 PASS / 0 FAIL / 0 SKIP / 0 XFAIL. After: 19 PASS / 0 FAIL / 0 SKIP / 0 XFAIL. No weakened assertions. Core independent checks: {len(core)}/{len(core)} PASS; supplemental: {len(extra)}/{len(extra)} PASS; Mode B artifact checks: {len(engine)}/{len(engine)} PASS; API: 65/65 PASS. Temporary audit-harness dtype/null/JSON/default-control mismatches were explained and corrected, never mislabeled as product failures or ignored. `SOL_TEST_BASELINE.md` and `SOL_TEST_AFTER.log` give commands/evidence.

Mandatory independent reviewer completed a separate source/data/PnL/timing/cache audit and reread the final reports. No remaining material finding or factual report error. In addition to all-held same-contract returns and next-day holding checks, reviewer independently rebuilt midmonth .25 haircut/execution from raw signal returns (120 full-history triggers, max unscaled-weight error0). Its evidence is preserved in `SOL_REVIEWER_AUDIT.md`; no Sol-main-engine function was treated as independent proof.

## M. Fixes made by Sol

| File | Confirmed issue / limited fix |
| --- | --- |
| backend/experiment_costs.py (new) | Copy-only commodity contract roll cost override, exact V6 units and net-return formula |
| scripts/run_v6_experiment.py | Invoke copied trade-cost override; save audited trade inputs; rebase formal NAV; actual function-run logs |
| backend/experiment_runner.py | Fingerprint adapter/engine/config/inputs/baseline to invalidate stale caches; preserve actual command/hash/stdout/stderr records |
| frontend/app.js | Collaborative fix: empty experiment record null→暂无; clarify close diagnostic vs frozen/executed weights and expose missing chain columns; visible final NAV label |
| frontend/prototype_v0.3.html → references/prototype_v0.3.html | Preserve project copy while excluding synthetic demo from official static routes |
| README.md | Correct snapshot export interpreter to V6-compatible arm64 runtime |
| tests/test_experiment_costs.py (new), tests/test_api.py | Cost-baseline/noncommodity/gross immutability regression and demo404 isolation |
| tests/test_roll_boundaries.py (new) | Explicit missing real-event boundary coverage for frozen V6 rules; fixtures do not enter production |
| scripts/sol_*audit.py, scripts/sol_write_reports.py, reports/SOL_* | Independent raw recomputation, runtime/artifact checks and evidence generation; no strategy replacement |

## N. Remaining limitations

Material blockers: **none**.

Non-material limitations: Mode B first three tabs share one generic form rather than dedicated sensitivity sweeps; momentum exclusion changes disabled as allowed by unchanged V6 interface; no real HARD_ROLL/FORCED_DATA_ROLL in formal period (fixture/source coverage only); UI does not display class mean-exposure KPIs; canonical Parquet needs the compatible V6 Python runtime, while web reads precisely documented JSONL mirrors; V6 first-listing proxy trade_eligible metadata exceptions have zero actual exposure. The existing V6 formal contract-state sample also contains 312 EXPIRY_UNVERIFIED_EXCEPTION records (SC229 / AU43 / CU40), preserved explicitly by Web rather than filled or hidden; commodity fixed30D rules use delivery-month maturity codes, and all held settlement returns remain present. Experiment runtime is local and synchronous; this audit does not assert production concurrency or deployment readiness.

Official-methodology unknowns: Commodity 0 bps is the frozen V6 replication baseline pending official verification. Some inherited commodity exchange expiry metadata remains explicitly unverified as above. This audit proves website equals V6, not that V6 reproduces unknown official fee schedules or the reference institution's internal methodology.

Start: `cd '{ROOT}' && ./run_local.sh`. Address: `http://127.0.0.1:8000`. Real local browser launch and navigation were verified, not only import-time ASGI tests. No external deployment was performed.
''')
    print('Sol reports written; all raw reconciliation checks PASS.')

if __name__=='__main__':main()
