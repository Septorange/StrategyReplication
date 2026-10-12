#!/usr/bin/env python3
"""Map a verified isolated V0.7 Phase 1 rebuild into the V6 Web contract.

All inputs are read-only. The output directory must be a new candidate bundle.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.utils import records
ASSET_CLASS = {'IF':'equity','IC':'equity','IM':'equity','TF':'bond','T':'bond','SC':'commodity','FG':'commodity','I':'commodity','M':'commodity','AU':'commodity','CU':'commodity'}
ASSETS = list(ASSET_CLASS)


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def write_json(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str)+'\n')


def write_parquet(frame: pd.DataFrame, path: Path):
    frame.to_parquet(path, index=False, version='1.0', data_page_version='1.0', use_dictionary=False, write_page_index=False)
    with gzip.open(path.with_suffix('.jsonl.gz'),'wt',encoding='utf-8',newline='\n') as stream:
        for row in records(frame): stream.write(json.dumps(row,ensure_ascii=False,allow_nan=False,separators=(',',':'))+'\n')


def read(path: Path):
    frame=pd.read_parquet(path)
    for col in ('date','signal_date','next_trading_date'):
        if col in frame: frame[col]=pd.to_datetime(frame[col])
    return frame


def effective_targets(targets: pd.DataFrame, dates: pd.DatetimeIndex):
    rows=[]
    t=targets.copy().sort_values(['asset','next_trading_date'])
    for asset in ASSETS:
        right=t[t.asset.eq(asset)].copy()
        left=pd.DataFrame({'date':dates})
        if right.empty:
            z=left.copy(); z['asset']=asset
        else:
            right=right.drop(columns=['date'],errors='ignore').rename(columns={'next_trading_date':'effective_date'})
            z=pd.merge_asof(left.sort_values('date'), right.sort_values('effective_date'), left_on='date',right_on='effective_date',direction='backward')
            z['asset']=asset
        rows.append(z)
    return pd.concat(rows,ignore_index=True)


def build(phase: Path, v6: Path, out: Path, snapshot_id: str, baseline_web: Path):
    if out.exists() and any(out.iterdir()): raise SystemExit(f'candidate output must be empty: {out}')
    out.mkdir(parents=True,exist_ok=True)
    rebuild_path=phase/'rebuild_manifest.json'
    if not rebuild_path.is_file(): raise SystemExit('verified rebuild_manifest.json is required')
    rebuild=json.loads(rebuild_path.read_text())
    source=json.loads((phase/'manifest.json').read_text())
    if rebuild.get('status')!='PASS' or source.get('status')!='LOCAL_UNPUBLISHED': raise SystemExit('source rebuild is not a PASS LOCAL_UNPUBLISHED candidate')
    if rebuild.get('phase3b_last_date')!=source.get('phase3b_last_date'): raise SystemExit('source and rebuild manifest end dates differ')

    portfolio=read(phase/'phase3b/portfolio_daily.parquet')
    weights=read(phase/'phase3b/final_daily_weights.parquet')
    trade=read(phase/'phase2/trade_returns.parquet')
    signals=read(phase/'phase3a/momentum_signals.parquet')
    targets=read(phase/'phase3a/target_weights.parquet')
    vol=read(phase/'phase3b/single_asset_vol_control.parquet')
    dates=pd.DatetimeIndex(portfolio.date.sort_values().unique())
    start=pd.Timestamp(json.loads((baseline_web/'summary.json').read_text())['start_date'])
    end=pd.Timestamp(source['phase3b_last_date'])
    portfolio=portfolio[portfolio.date.between(start,end)].copy().sort_values('date')
    dates=pd.DatetimeIndex(portfolio.date)
    weights=weights[weights.date.between(start,end)].copy()
    if portfolio.empty or not portfolio.date.is_monotonic_increasing or portfolio.date.duplicated().any(): raise SystemExit('portfolio dates are empty, unsorted, or duplicated')

    # Reconstruct asset contributions using the audited Phase 1 execution identity:
    # start-of-day final weight * same-contract net trade return - half-turnover rebalance cost.
    state=weights.merge(trade[['date','asset','trade_return_gross','trade_return_net','roll_cost','held_contract_start_of_day','held_contract_end_of_day','roll_from','roll_to','roll_trigger','days_to_expiry','expiry_known','expiry_source','status','data_status','candidate_contract','confirmed_active_contract','roll_mode','roll_weight_old','roll_weight_new','requires_requery','switch_reversal_1d','switch_reversal_2d','start_weights','end_weights','turnover']],on=['date','asset'],how='left',validate='one_to_one')
    if (state.trade_return_net.isna() & (state.weight_start_of_day.abs()>1e-14)).any(): raise SystemExit('held asset has missing trade return')
    costs={'equity':5.0,'bond':2.0,'commodity':0.0}
    state['rebalance_cost']=.5*(state.weight_end_of_day-state.weight_start_of_day).abs()*state.asset_class.map(costs)/10000
    state['asset_contribution']=np.where(state.weight_start_of_day.abs()>1e-14,state.weight_start_of_day*state.trade_return_net,0.0)-state.rebalance_cost
    state['final_weight']=state.weight_start_of_day

    # Monthly signal and target fields are aligned to their first effective portfolio date.
    sigcols=['date','asset','trade_eligible','signal_usable','risk_estimate_usable','signal_source','ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240']
    state=state.merge(signals[sigcols],on=['date','asset'],how='left',validate='one_to_one')
    target=effective_targets(targets,dates)
    target_cols=['date','asset','signal_date','next_trading_date','rank_ret_20','rank_ret_60','rank_ret_240','rank_sharpe_20','rank_sharpe_60','rank_sharpe_240','mean_rank','selected','class_budget','relative_asset_budget','risk_vol','raw_weight_before_scale','sleeve_scale','raw_weight_after_scale','cap','post_cap_weight','asset_cap','haircut_flag','post_haircut_weight']
    tc=[c for c in target_cols if c in target]
    state=state.merge(target[tc],on=['date','asset'],how='left',validate='one_to_one',suffixes=('','_target'))
    vv=[c for c in ['date','asset','vol_20','vol_60','vol_120','vol_240','short_vol','long_vol','direct_threshold_q90','triggered','haircut'] if c in vol]
    state=state.merge(vol[vv],on=['date','asset'],how='left',validate='one_to_one',suffixes=('','_vol'))
    # Harmonize internal audit fields expected by the V6 replay and research services.
    state['relative_asset_budget']=state.get('relative_asset_budget')
    state['asset_budget']=state.get('relative_asset_budget')
    state['rb_weight']=state.get('raw_weight_before_scale')
    state['scaled_raw_weight']=state.get('raw_weight_after_scale')
    state['historical_threshold']=state.get('direct_threshold_q90')
    state['haircut_flag']=state.get('triggered',state.get('haircut_flag'))
    state['haircut_multiplier']=state.get('haircut')
    state['post_haircut_weight']=state.monthly_base_target*state.single_asset_haircut
    state['pre10vt_weight']=state.get('unscaled_execution_weight')
    state['monthly_smoothing_step']=state['monthly_smoothing_step'].astype('Int64')
    state['midmonth_theoretical_target']=state.get('midmonth_theoretical_target')
    state['monthly_base_target']=state.get('monthly_base_target')
    state['controlled_target']=state.get('controlled_target')
    state['triggered']=state.get('triggered',False)
    state['haircut']=state.get('haircut',1.0)
    state['portfolio_vol_estimate']=state.get('portfolio_vol_estimate')
    rename={'rank_ret_20':'rank_ret20','rank_ret_60':'rank_ret60','rank_ret_240':'rank_ret240','rank_sharpe_20':'rank_sharpe20','rank_sharpe_60':'rank_sharpe60','rank_sharpe_240':'rank_sharpe240'}
    state=state.rename(columns=rename).sort_values(['date','asset'])
    if state.duplicated(['date','asset']).any(): raise SystemExit('duplicate asset state rows')

    # Preserve the exact already-audited NAV anchor at the formal-window start.
    baseline=pd.read_parquet(baseline_web/'daily_portfolio.parquet'); baseline.date=pd.to_datetime(baseline.date)
    anchor_date=baseline.date.min(); matched=portfolio[portfolio.date.eq(anchor_date)]
    if len(matched)!=1: raise SystemExit('formal anchor date is missing from Phase 1 portfolio')
    baseline_anchor=baseline.loc[baseline.date.eq(anchor_date)].iloc[0]
    scales={key:float(baseline_anchor[key]/matched[key].iloc[0]) for key in ('nav_net','nav_gross','nav_after_contract_roll')}
    for key,scale in scales.items(): portfolio[key]=portfolio[key]*scale

    roll_cols=['date','asset','held_contract_start_of_day','candidate_contract','confirmed_active_contract','roll_trigger','roll_from','roll_to','roll_mode','roll_weight_old','roll_weight_new','held_contract_end_of_day','days_to_expiry','expiry_known','expiry_source','requires_requery','status','switch_reversal_1d','switch_reversal_2d','start_weights','end_weights','turnover','roll_cost']
    # A roll row means Phase 2 has an observed contract assignment. Keep explicit
    # null/absent Phase 2 dates out of the contract lifecycle table.
    rolls=state[state.held_contract_start_of_day.notna()][[c for c in roll_cols if c in state]].copy()
    selection=read(phase/'phase3a/asset_selection.parquet')
    momentum=selection.rename(columns=rename).copy()
    for i,c in enumerate(['rank_ret20','rank_ret60','rank_ret240','rank_sharpe20','rank_sharpe60','rank_sharpe240'],1): momentum[f'rank_{i}']=momentum.get(c)
    momentum=momentum[['signal_date','asset','ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240','rank_1','rank_2','rank_3','rank_4','rank_5','rank_6','mean_rank','selected','signal_source']]

    # Canonical tables retain Parquet precision; JSONL is transport serialization only.
    web=out/'web'; web.mkdir()
    for frame,name in [(portfolio,'daily_portfolio'),(state,'daily_asset_state'),(rolls,'daily_roll'),(momentum,'monthly_momentum')]: write_parquet(frame,web/(name+'.parquet'))
    r=portfolio.portfolio_return_net.astype(float)
    nav=portfolio.nav_net.astype(float)
    peak=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
    exp=state.groupby(['date','asset_class']).weight_start_of_day.sum(min_count=1).groupby('asset_class').mean()
    mult=portfolio.final_10vt_multiplier
    summary={'version':'V07','snapshot_id':snapshot_id,'snapshot_status':'LOCAL_UNPUBLISHED','start_date':str(portfolio.date.min().date()),'end_date':str(portfolio.date.max().date()),'observations':int(len(portfolio)),'annualized_return':float(nav.iloc[-1]**(252/len(r))-1),'annualized_vol':float(r.std(ddof=1)*np.sqrt(252)),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)),'max_drawdown':float((nav/peak-1).min()),'avg_equity_exposure':float(exp.get('equity',0)),'avg_bond_exposure':float(exp.get('bond',0)),'avg_commodity_exposure':float(exp.get('commodity',0)),'mean_10vt_multiplier':float(mult.mean()),'lower_bound_hit_rate':float(mult.eq(.5).mean()),'upper_bound_hit_rate':float(mult.eq(1.5).mean()),'formal_audit_window':{'start':'2015-09-30','end':'2024-11-20'},'new_observation_period':{'start':'2024-11-21','end':str(portfolio.date.max().date())},'last_signal_date':str(pd.Timestamp(source['phase3a_last_signal_date']).date()),'demo_mode':False}
    write_json(web/'summary.json',summary)
    p3a=yaml.safe_load((v6/'config/phase3a.yaml').read_text()); p3b=yaml.safe_load((v6/'config/phase3b.yaml').read_text()); p2=yaml.safe_load((v6/'config/phase2.yaml').read_text())
    rules={'version':'V6','snapshot_id':snapshot_id,'class_budget':{'equity':1/3,'bond':1/3,'commodity':1/3},'sleeve_scale':p3a['sleeve_scale'],'caps':p3a['max_asset_weight'],'momentum':{'windows':p3a['momentum_windows'],'sharpe_windows':p3a['sharpe_windows'],'top_n_risk_assets':p3a['top_n'],'fixed_assets':['TF','T']},'haircut':p3b['single_asset_vol_control'],'midmonth':p3b['mid_month_rebalance'],'10vt':p3b['portfolio_vol_target'],'roll':{'mode':p2.get('roll_mode','instant'),'timing':'t open old-contract same-contract PnL; close switch; t+1 new contract return'},'costs':{**p3b['costs'],'commodity_status':'V6 baseline / PENDING_VERIFICATION'},'demo_mode':False}
    write_json(web/'rules.json',rules)
    mapping={'asset_contribution':'held weight * trade_return_net (zero for unheld assets) - 0.5 * abs(weight_end_of_day-weight_start_of_day) * class_bps / 10000','rebalance_cost':'0.5 * abs(weight_end_of_day-weight_start_of_day) * {equity:5,bond:2,commodity:0} bps / 10000','roll_cost':'direct from phase2/trade_returns.parquet; already deducted in trade_return_net','nav_anchor':'Phase 1 raw NAV multiplied by ratio of audited formal baseline NAV to Phase 1 NAV on 2015-09-30; preserves overlap level and subsequent daily return path'}
    web_manifest={'snapshot_id':snapshot_id,'version':'V07','synthetic_values':False,'source_status':'LOCAL_UNPUBLISHED','source_rebuild_manifest_sha256':sha256(rebuild_path),'data_start_date':summary['start_date'],'data_end_date':summary['end_date'],'phase3a_last_signal_date':summary['last_signal_date'],'files':{},'mapping':mapping,'precision':'Canonical Parquet; JSONL 15-digit float transport'}
    for f in sorted(web.iterdir()):
        if f.name!='manifest.json': web_manifest['files'][f.name]={'sha256':sha256(f),'bytes':f.stat().st_size}
    write_json(web/'manifest.json',web_manifest)
    print(json.dumps({'snapshot_id':snapshot_id,'rows':{'portfolio':len(portfolio),'assets':len(state),'rolls':len(rolls),'momentum':len(momentum)},'summary':summary,'nav_anchor_scales':scales,'max_daily_contribution_closure_error':float((state.groupby('date').asset_contribution.sum()-portfolio.set_index('date').portfolio_return_net).abs().max())},ensure_ascii=False,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--phase1-root',type=Path,default=ROOT/'data/v07_local/extended_10119bd207b16499')
    ap.add_argument('--v6-readonly-root',type=Path,required=True)
    ap.add_argument('--baseline-web',type=Path,default=ROOT/'data/v6_web')
    ap.add_argument('--output-root',type=Path,required=True)
    ap.add_argument('--snapshot-id',default='v07_extended_10119bd207b16499')
    a=ap.parse_args(); build(a.phase1_root,a.v6_readonly_root,a.output_root,a.snapshot_id,a.baseline_web)
