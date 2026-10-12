#!/usr/bin/env python3
"""Read-only audit of the local V0.7 Phase 1 inputs for a future Web bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ASSET_CLASS = {'IF':'equity','IC':'equity','IM':'equity','TF':'bond','T':'bond','SC':'commodity','FG':'commodity','I':'commodity','M':'commodity','AU':'commodity','CU':'commodity'}


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def read_frame(path: Path) -> pd.DataFrame:
    frame=pd.read_parquet(path)
    for col in ('date','signal_date','next_trading_date'):
        if col in frame:
            frame[col]=pd.to_datetime(frame[col])
    return frame


def max_abs(left, right):
    a=pd.to_numeric(left,errors='coerce'); b=pd.to_numeric(right,errors='coerce')
    d=(a-b).abs().dropna()
    return float(d.max()) if len(d) else None


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--phase1-root',type=Path,default=ROOT/'data/v07_local/extended_10119bd207b16499')
    ap.add_argument('--v6-root',type=Path,required=True,help='Read-only frozen V6 root')
    ap.add_argument('--write-reports',action='store_true')
    args=ap.parse_args()
    phase=args.phase1_root
    local=json.loads((phase/'manifest.json').read_text())
    phase1=json.loads((ROOT/'reports/V0.7_PHASE1_EXTENDED_BACKTEST.json').read_text())
    v6=args.v6_root
    readiness=json.loads((v6/'data/processed/phase2_5/production_readiness_v2.json').read_text())
    fg=pd.read_csv(v6/'data/processed/phase2_5/fg_requery_results.csv')
    fg_status=fg.resolution.fillna('').value_counts().to_dict()

    fw=read_frame(phase/'phase3b/final_daily_weights.parquet')
    trade=read_frame(phase/'phase2/trade_returns.parquet')
    portfolio=read_frame(phase/'phase3b/portfolio_daily.parquet')
    baseline_assets=read_frame(ROOT/'data/v6_web/daily_asset_state.parquet')
    baseline_portfolio=read_frame(ROOT/'data/v6_web/daily_portfolio.parquet')

    required=['phase2/signal_returns.parquet','phase2/trade_returns.parquet','phase3a/momentum_signals.parquet','phase3a/asset_selection.parquet','phase3a/base_target_weights.parquet','phase3a/target_weights.parquet','phase3a/volatility_estimates.parquet','phase3a/phase3a_validation.json','phase3b/single_asset_vol_control.parquet','phase3b/daily_theoretical_targets.parquet','phase3b/monthly_smoothing_schedule.parquet','phase3b/final_daily_weights.parquet','phase3b/portfolio_daily.parquet']
    files_present=all((phase/f).is_file() for f in required)
    hash_errors=[]; count_errors=[]
    for rel,digest in local.get('inputs_sha256',{}).items():
        p=phase/rel
        if not p.is_file() or sha256(p)!=digest: hash_errors.append(rel)
    for rel,count in local.get('record_counts',{}).items():
        p=phase/rel
        if p.suffix=='.parquet' and p.is_file() and len(read_frame(p))!=count: count_errors.append(rel)

    # Recreate the same net asset contribution identity used by the frozen engine.
    fw['rebalance_cost']=.5*(fw.weight_end_of_day-fw.weight_start_of_day).abs()*fw.asset_class.map({'equity':5.0,'bond':2.0,'commodity':0.0})/10000
    trade_cols=['date','asset','trade_return_gross','trade_return_net','roll_cost','held_contract_start_of_day','held_contract_end_of_day','roll_from','roll_to','roll_trigger','days_to_expiry','expiry_known','expiry_source','status','data_status']
    state=fw.merge(trade[trade_cols],on=['date','asset'],how='left',validate='one_to_one')
    state['asset_contribution']=state.weight_start_of_day*state.trade_return_net-state.rebalance_cost
    held=state.weight_start_of_day.abs()>1e-14
    missing_held=int((held & (state.trade_return_gross.isna()|state.trade_return_net.isna())).sum())
    closure=state.groupby('date').asset_contribution.sum(min_count=1).rename('sum_contribution').reset_index().merge(portfolio[['date','portfolio_return_net']],on='date',validate='one_to_one')
    contribution_closure_error=float((closure.sum_contribution-closure.portfolio_return_net).abs().max())
    asset_counts=state.groupby('date').asset.nunique()
    continuity=trade.sort_values(['asset','date']).copy()
    continuity['next_start']=continuity.groupby('asset').held_contract_start_of_day.shift(-1)
    continuity['end_text']=continuity.held_contract_end_of_day.fillna('')
    continuity['next_text']=continuity.next_start.fillna('')
    has_next=continuity.next_start.notna()
    roll_transition_mismatches=int(((continuity.end_text!=continuity.next_text)&has_next).sum())

    overlap=state.merge(baseline_assets,on=['date','asset'],suffixes=('_new','_old'),how='inner')
    overlap_rows=[]
    for col in ('weight_start_of_day','final_weight','trade_return_net','roll_cost','rebalance_cost','asset_contribution','final_10vt_multiplier'):
        n=col+'_new' if col+'_new' in overlap else col
        o=col+'_old' if col+'_old' in overlap else col
        if n in overlap and o in overlap:
            overlap_rows.append({'artifact':f'daily_asset_state.{col}','matched_rows':int(len(overlap)),'max_abs_diff':max_abs(overlap[n],overlap[o]),'tolerance':1e-12,'status':'PASS' if (max_abs(overlap[n],overlap[o]) or 0)<=1e-12 else 'FAIL'})
    mp=portfolio.merge(baseline_portfolio,on='date',suffixes=('_new','_old'),how='inner')
    for col in ('portfolio_return_net','contract_roll_cost','portfolio_rebalance_cost','final_10vt_multiplier'):
        d=max_abs(mp[col+'_new'],mp[col+'_old'])
        overlap_rows.append({'artifact':f'daily_portfolio.{col}','matched_rows':int(len(mp)),'max_abs_diff':d,'tolerance':1e-12,'status':'PASS' if (d or 0)<=1e-12 else 'FAIL'})
    nav_ratio=float(mp.nav_net_old.iloc[0]/mp.nav_net_new.iloc[0])
    nav_diff=max_abs(mp.nav_net_new*nav_ratio,mp.nav_net_old)
    overlap_rows.append({'artifact':'daily_portfolio.nav_net (anchored to formal overlap)','matched_rows':int(len(mp)),'max_abs_diff':nav_diff,'tolerance':1e-12,'status':'PASS' if (nav_diff or 0)<=1e-12 else 'FAIL'})
    overlap_df=pd.DataFrame(overlap_rows)

    # Check the Phase 1 prior-only estimator result against its independent audit statement.
    phase1_source_pass=phase1.get('status')=='PASS' and phase1.get('formal_overlap_status')=='PASS' and phase1.get('new_period_data_quality')=='PASS'
    review_text=(ROOT/'reports/V0.7_REVIEW_FINAL.md').read_text()
    phase2_ready=bool(readiness.get('PHASE3_READY')) and all(bool(v) for v in readiness.get('checks',{}).values())
    fg_explicit=(len(fg)==23 and set(fg.resolution.dropna().unique())=={'CONFIRMED_ZERO_CLOSE'} and set(fg.request_status.dropna().unique())=={'OK'})
    source_missing_rebuild_manifest=not (phase/'rebuild_manifest.json').is_file()
    current_frozen_before=json.loads((ROOT/'reports/V0.7_FROZEN_HASHES_BEFORE.json').read_text())
    current_frozen_after=json.loads((ROOT/'reports/V0.7_FROZEN_HASHES_AFTER.json').read_text())
    frozen_unchanged=(current_frozen_before.get('tree_sha256')==current_frozen_after.get('tree_sha256') and current_frozen_after.get('unchanged') is True)
    nav_start=str(portfolio.date.min().date()); nav_end=str(portfolio.date.max().date())
    checks={
      'phase1_report_pass':phase1_source_pass,
      'local_manifest_status_local_unpublished':local.get('status')=='LOCAL_UNPUBLISHED',
      'required_phase1_files_present':files_present,
      'source_hashes_match_local_manifest':not hash_errors,
      'source_row_counts_match_local_manifest':not count_errors,
      'v2_phase2_5_readiness_pass':phase2_ready,
      'fg_23_targeted_rows_explicit':fg_explicit,
      'prior_only_10vt_audit_reported':'2.1e-15' in review_text and 'Prior-only' in review_text,
      'held_returns_complete':missing_held==0,
      'daily_asset_contribution_closure':contribution_closure_error<=1e-12,
      'formal_overlap_reconciliation':bool((overlap_df.status=='PASS').all()),
      'frozen_v6_source_report_unchanged':frozen_unchanged,
      'phase1_machine_rebuild_manifest_present':not source_missing_rebuild_manifest,
      'snapshot_specific_web_and_analytics_binding_implemented':False,
    }
    evidence={
      'snapshot_id':local.get('strategy_snapshot_id'),'source_status':local.get('status'),
      'phase1_report_status':phase1.get('status'),'raw_latest':local.get('latest_verified_date'),
      'phase3a_last_signal_date':local.get('phase3a_last_signal_date'),'phase3b_last_date':local.get('phase3b_last_date'),
      'portfolio_start':nav_start,'portfolio_end':nav_end,'portfolio_rows':int(len(portfolio)),
      'asset_state_rows':int(len(state)),'asset_count_per_portfolio_day_min':int(asset_counts.min()),'asset_count_per_portfolio_day_max':int(asset_counts.max()),
      'held_return_missing_count':missing_held,'daily_asset_contribution_max_abs_closure_error':contribution_closure_error,
      'roll_contract_day_to_next_start_mismatches':roll_transition_mismatches,'formal_overlap_portfolio_rows':int(len(mp)),
      'formal_overlap_asset_rows':int(len(overlap)),'formal_overlap_nav_anchor_ratio':nav_ratio,
      'phase2_5_ready':phase2_ready,'fg_requery_rows':int(len(fg)),'fg_resolution_counts':fg_status,
      'rebuild_manifest_missing':source_missing_rebuild_manifest,'hash_mismatches':hash_errors,'record_count_mismatches':count_errors,
      'frozen_tree_before_sha256':current_frozen_before.get('tree_sha256'),'frozen_tree_after_sha256':current_frozen_after.get('tree_sha256'),
      'frozen_tree_before_files':current_frozen_before.get('file_count'),'frozen_tree_after_files':current_frozen_after.get('file_count'),
      'checks':checks,
    }
    if args.write_reports:
        (ROOT/'reports/V0.7_PHASE1_5_OVERLAP_RECONCILIATION.csv').write_text(overlap_df.to_csv(index=False))
        (ROOT/'reports/V0.7_PHASE1_5_AUDIT_EVIDENCE.json').write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(evidence,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
