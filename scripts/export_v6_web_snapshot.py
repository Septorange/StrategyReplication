#!/usr/bin/env python3
"""Export immutable V6 outputs into a browser-oriented snapshot."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import yaml

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_V6=Path('/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6')
ASSET_CLASS={'IF':'equity','IC':'equity','IM':'equity','TF':'bond','T':'bond','SC':'commodity','FG':'commodity','I':'commodity','M':'commodity','AU':'commodity','CU':'commodity'}
ASSETS=list(ASSET_CLASS)

def read_json(p): return json.loads(Path(p).read_text())
def write_json(p,x): Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def hash_file(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load_yaml(p): return yaml.safe_load(Path(p).read_text())
def write_parquet(frame,path):
    # Keep snapshots readable by both the V6 project runtime and the local
    # FastAPI runtime, which ship different PyArrow major versions.
    frame.to_parquet(path,index=False,version='1.0',data_page_version='1.0',use_dictionary=False,write_page_index=False)
    frame.to_json(Path(path).with_suffix('.jsonl.gz'),orient='records',lines=True,date_format='iso',compression='gzip',force_ascii=False)

def effective_monthly(frame, dates):
    frame=frame.copy(); frame['effective_date']=pd.to_datetime(frame['next_trading_date'])
    out=[]
    for asset in ASSETS:
        left=pd.DataFrame({'date':dates}); right=frame[frame.asset==asset].sort_values('effective_date')
        if right.empty:
            z=left.copy(); z['asset']=asset
        else:
            z=pd.merge_asof(left.sort_values('date'),right.drop(columns=['date'],errors='ignore'),left_on='date',right_on='effective_date',direction='backward')
            z['asset']=asset
        out.append(z)
    return pd.concat(out,ignore_index=True)

def build(v6:Path,out:Path):
    out.mkdir(parents=True,exist_ok=True)
    formal=v6/'data/processed/phase3_formal'; p3b=v6/'data/processed/phase3b'; p3a=v6/'data/processed/phase3a'; p2=v6/'data/processed/phase2'
    portfolio=pd.read_csv(formal/'daily_portfolio.csv',parse_dates=['date'])
    weights=pd.read_csv(formal/'daily_weights.csv',parse_dates=['date'])
    contrib=pd.read_csv(formal/'daily_asset_contribution.csv',parse_dates=['date'])
    signals=pd.read_parquet(p3a/'momentum_signals.parquet'); signals.date=pd.to_datetime(signals.date)
    targets=pd.read_parquet(p3a/'target_weights.parquet'); targets['next_trading_date']=pd.to_datetime(targets.next_trading_date)
    vol=pd.read_parquet(p3b/'single_asset_vol_control.parquet'); vol.date=pd.to_datetime(vol.date)
    trade=pd.read_parquet(p2/'trade_returns.parquet'); trade.date=pd.to_datetime(trade.date)
    dates=pd.DatetimeIndex(portfolio.date)
    monthly=effective_monthly(targets,dates)
    sigcols=['date','asset','trade_eligible','signal_usable','risk_estimate_usable','signal_source','ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240']
    state=weights.merge(signals[sigcols],on=['date','asset'],how='left')
    monthly_cols=['date','asset','rank_ret_20','rank_ret_60','rank_ret_240','rank_sharpe_20','rank_sharpe_60','rank_sharpe_240','mean_rank','selected','class_budget','relative_asset_budget','risk_vol','raw_weight_before_scale','sleeve_scale','raw_weight_after_scale','cap','post_cap_weight']
    state=state.merge(monthly[[c for c in monthly_cols if c in monthly]],on=['date','asset'],how='left')
    vcols=['date','asset','vol_20','vol_60','short_vol','long_vol','direct_threshold_q90','triggered','haircut']
    state=state.merge(vol[[c for c in vcols if c in vol]],on=['date','asset'],how='left')
    state=state.merge(trade[['date','asset','trade_return_gross','trade_return_net','roll_cost']],on=['date','asset'],how='left')
    state=state.merge(contrib[['date','asset','rebalance_cost','asset_contribution']],on=['date','asset'],how='left')
    state=state.merge(portfolio[['date','portfolio_vol_estimate','raw_10vt_multiplier','final_10vt_multiplier']],on='date',how='left',suffixes=('','_portfolio'))
    state['asset_class']=state.asset.map(ASSET_CLASS)
    state['asset_budget']=state.get('relative_asset_budget')
    state['rb_weight']=state.get('raw_weight_before_scale')
    state['scaled_raw_weight']=state.get('raw_weight_after_scale')
    state['historical_threshold']=state.get('direct_threshold_q90')
    state['haircut_flag']=state.get('triggered')
    state['haircut_multiplier']=state.get('haircut')
    state['post_haircut_weight']=state.monthly_base_target*state.single_asset_haircut
    state['pre10vt_weight']=state.unscaled_execution_weight
    rename={'rank_ret_20':'rank_ret20','rank_ret_60':'rank_ret60','rank_ret_240':'rank_ret240','rank_sharpe_20':'rank_sharpe20','rank_sharpe_60':'rank_sharpe60','rank_sharpe_240':'rank_sharpe240'}
    state=state.rename(columns=rename).sort_values(['date','asset'])
    assert not state.duplicated(['date','asset']).any()
    write_parquet(state,out/'daily_asset_state.parquet')
    write_parquet(portfolio,out/'daily_portfolio.parquet')
    rolls=pd.read_parquet(p2/'roll_calendar.parquet'); rolls.date=pd.to_datetime(rolls.date)
    rolls=rolls[rolls.date.between(dates.min(),dates.max())].copy()
    rcost=trade[['date','asset','roll_cost']]; rolls=rolls.merge(rcost,on=['date','asset'],how='left')
    for c in ['start_weights','end_weights']:
        if c in rolls: rolls[c]=rolls[c].map(lambda x: json.dumps(x,ensure_ascii=False,default=str) if not isinstance(x,str) else x)
    write_parquet(rolls,out/'daily_roll.parquet')
    sel=pd.read_parquet(p3a/'asset_selection.parquet')
    momentum=sel.rename(columns=rename).copy()
    for i,c in enumerate(['rank_ret20','rank_ret60','rank_ret240','rank_sharpe20','rank_sharpe60','rank_sharpe240'],1): momentum[f'rank_{i}']=momentum.get(c)
    keep=['signal_date','asset','ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240','rank_1','rank_2','rank_3','rank_4','rank_5','rank_6','mean_rank','selected','signal_source']
    write_parquet(momentum[keep],out/'monthly_momentum.parquet')
    perf=read_json(formal/'performance_summary.json'); rep=perf['replication']; exp=perf['exposure_comparison']['replication_average']; vt=perf['10vt']
    summary={'version':'V6','annualized_return':rep['annualized_return'],'annualized_vol':rep['annualized_volatility'],'sharpe':rep['sharpe'],'max_drawdown':rep['max_drawdown'],'avg_equity_exposure':exp['equity'],'avg_bond_exposure':exp['bond'],'avg_commodity_exposure':exp['commodity'],'mean_10vt_multiplier':vt['mean'],'lower_bound_hit_rate':vt['lower_bound_hit_rate'],'upper_bound_hit_rate':vt['upper_bound_hit_rate'],'start_date':str(dates.min().date()),'end_date':str(dates.max().date()),'observations':len(dates),'demo_mode':False}
    write_json(out/'summary.json',summary)
    p3ac=load_yaml(v6/'config/phase3a.yaml'); p3bc=load_yaml(v6/'config/phase3b.yaml'); p2c=load_yaml(v6/'config/phase2.yaml')
    rules={'version':'V6','class_budget':{'equity':1/3,'bond':1/3,'commodity':1/3},'sleeve_scale':p3ac['sleeve_scale'],'caps':p3ac['max_asset_weight'],'momentum':{'windows':p3ac['momentum_windows'],'sharpe_windows':p3ac['sharpe_windows'],'top_n_risk_assets':p3ac['top_n'],'fixed_assets':['TF','T']},'haircut':p3bc['single_asset_vol_control'],'midmonth':p3bc['mid_month_rebalance'],'10vt':p3bc['portfolio_vol_target'],'roll':{'mode':p2c.get('roll_mode','instant'),'equity_trigger':'EQUITY_T_MINUS_5','commodity_trigger':'COMMODITY_FIXED_30D','bond_confirmation_days':2,'hard_roll_days':5},'costs':{**p3bc['costs'],'commodity_status':'V6 baseline / PENDING_VERIFICATION'},'demo_mode':False}
    write_json(out/'rules.json',rules)
    manifest={'version':'V6','synthetic_values':False,'generated_from':str(v6),'files':{},'derived_fields':{'asset_budget':'relative_asset_budget','rb_weight':'raw_weight_before_scale = asset_budget/risk_vol','scaled_raw_weight':'raw_weight_after_scale = rb_weight*sleeve_scale','post_haircut_weight':'monthly_base_target*single_asset_haircut','pre10vt_weight':'unscaled_execution_weight','historical_threshold':'direct_threshold_q90','haircut_flag':'triggered','haircut_multiplier':'haircut'},'null_policy':'Unavailable fields remain null; no synthetic fill.'}
    for name in ['summary.json','rules.json','daily_portfolio.parquet','daily_asset_state.parquet','daily_roll.parquet','monthly_momentum.parquet','daily_portfolio.jsonl.gz','daily_asset_state.jsonl.gz','daily_roll.jsonl.gz','monthly_momentum.jsonl.gz']:
        manifest['files'][name]={'sha256':hash_file(out/name),'bytes':(out/name).stat().st_size}
    write_json(out/'manifest.json',manifest)
    print(json.dumps({'summary':summary,'rows':{'portfolio':len(portfolio),'asset_state':len(state),'roll':len(rolls),'momentum':len(momentum)}},ensure_ascii=False,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--v6',type=Path,default=DEFAULT_V6); ap.add_argument('--out',type=Path,default=ROOT/'data/v6_web'); a=ap.parse_args(); build(a.v6,a.out)
