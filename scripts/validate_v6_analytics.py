#!/usr/bin/env python3
"""Independent canonical-Parquet identities, no existing analytics output writes."""
import sys,math,json
from pathlib import Path
import pandas as pd
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.config import SNAPSHOT,ROOT
from backend.analytics_service import AnalyticsService
s=AnalyticsService();p=pd.read_parquet(SNAPSHOT/'daily_portfolio.parquet');a=pd.read_parquet(SNAPSHOT/'daily_asset_state.parquet');h=s.table('portfolio_history');e=s.table('class_exposure_and_vol120')
checks={}
def verify(name,diff):
 checks[name]={'max_abs_diff':float(diff),'status':'PASS' if diff<=1e-10 else 'FAIL'}
verify('saved_NAV_tail',abs(p.nav_net.iloc[-1]-h.nav_net.iloc[-1]))
verify('daily_asset_net_sum',abs(a.groupby('date').asset_contribution.sum()-p.set_index('date').portfolio_return_net).max())
verify('daily_cost_identity',abs(p.portfolio_return_gross-p.total_cost-p.portfolio_return_net).max())
for cls in ['equity','bond','commodity']:
 g=a[a.asset_class==cls].groupby('date');ex=g.weight_start_of_day.sum();contrib=g.asset_contribution.sum()
 verify(cls+'_start_of_day_exposure',abs(ex.to_numpy()-e[cls].to_numpy()).max())
 expected=contrib.rolling(120).std(ddof=1)*math.sqrt(252)
 verify(cls+'_120D_contribution_vol',np.nanmax(abs(expected.to_numpy()-e[cls+'_vol'].to_numpy())))
verify('120D_display_vol',np.nanmax(abs(p.portfolio_return_net.rolling(120).std(ddof=1).to_numpy()*math.sqrt(252)-h.display_vol.to_numpy())))
report={'checks':checks,'status':'PASS' if all(x['status']=='PASS' for x in checks.values()) else 'FAIL'}
(ROOT/'reports/V0.6_CANONICAL_VALIDATION.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
raise SystemExit(0 if report['status']=='PASS' else 1)
