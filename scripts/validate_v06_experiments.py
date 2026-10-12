#!/usr/bin/env python3
"""Independently reconcile saved real runs and both commodity cost layers."""
import json,math,sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import ROOT,SNAPSHOT
from backend.analytics_service import performance
runs=json.loads((ROOT/'reports/V0.6_REAL_EXPERIMENTS.json').read_text());by={r['name']:r for r in runs};checks={}
def check(k,value):
 checks[k]={'max_abs_diff':float(value),'status':'PASS' if value<=1e-10 else 'FAIL'}
assert {'target10','target12','cost5'}<=set(by)
for name,r in by.items():
 assert r['status']=='PASS';folder=Path(r['output_path']);p=pd.read_parquet(folder/'daily_portfolio.parquet');result=json.loads((folder/'result.json').read_text())
 for k,v in performance(p.portfolio_return_net).items():
  if k in r['experiment']:check(name+'_'+k,abs(v-r['experiment'][k]))
 h=pd.DataFrame(result['history']['rows'])
 check(name+'_response_nav',np.max(abs(h.nav_net-p.nav_net)))
 check(name+'_rebase',np.max(abs((1+p.portfolio_return_net).cumprod()-p.nav_net)))
 check(name+'_cost_identity',np.max(abs(p.portfolio_return_gross-p.total_cost-p.portfolio_return_net)))
 assert result['source_hashes'] and result['stages'] and result['synthetic'] is False
base=pd.read_parquet(Path(by['target10']['output_path'])/'daily_portfolio.parquet');formal=pd.read_parquet(SNAPSHOT/'daily_portfolio.parquet')
check('baseline_replay_daily_nav',np.max(abs(base.nav_net-formal.nav_net)))
check('target12_is_real_changed_series',0 if by['target12']['experiment']['annualized_return']!=by['target10']['experiment']['annualized_return'] else 1)
folder=Path(by['cost5']['output_path']);weights=pd.read_parquet(folder/'final_daily_weights.parquet');trade=pd.read_parquet(folder/'experiment_trade_returns.parquet');p=pd.read_parquet(folder/'daily_portfolio.parquet')
weights=weights[weights.date.between(p.date.min(),p.date.max())]
joined=weights.merge(trade,on=['date','asset'],how='left');joined=joined[joined.asset_class=='commodity']
expected_roll=(joined.weight_start_of_day*joined.turnover*5/10000).groupby(joined.date).sum()
expected_rebalance=(.5*(joined.weight_end_of_day-joined.weight_start_of_day).abs()*5/10000).groupby(joined.date).sum()
check('cost5_roll_delta',np.max(abs(p.contract_roll_cost.to_numpy()-base.contract_roll_cost.to_numpy()-expected_roll.reindex(p.date,fill_value=0).to_numpy())))
check('cost5_rebalance_delta',np.max(abs(p.portfolio_rebalance_cost.to_numpy()-base.portfolio_rebalance_cost.to_numpy()-expected_rebalance.reindex(p.date,fill_value=0).to_numpy())))
assert expected_roll.sum()>0 and expected_rebalance.sum()>0
report={'status':'PASS' if all(x['status']=='PASS' for x in checks.values()) else 'FAIL','checks':checks,'commodity_roll_added':float(expected_roll.sum()),'commodity_rebalance_added':float(expected_rebalance.sum())}
(ROOT/'reports/V0.6_REAL_EXPERIMENT_VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
raise SystemExit(0 if report['status']=='PASS' else 1)
