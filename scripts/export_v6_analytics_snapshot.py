#!/usr/bin/env python3
"""Run in canonical V6 .venv; read-only inputs, independent research outputs."""
import hashlib,json,sys
from pathlib import Path
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.analytics_service import compute_tables,performance,ASSET_CLASSES
from backend.parameter_registry import parameter_capabilities
from backend.config import ROOT,SNAPSHOT,V6_BASE
from backend.utils import records
out=ROOT/'data/v6_analytics';out.mkdir(parents=True,exist_ok=True); reports=ROOT/'reports';reports.mkdir(exist_ok=True)
p=pd.read_parquet(SNAPSHOT/'daily_portfolio.parquet');a=pd.read_parquet(SNAPSHOT/'daily_asset_state.parquet')
p.date=pd.to_datetime(p.date);a.date=pd.to_datetime(a.date)
summary=json.loads((SNAPSHOT/'summary.json').read_text()); p=p[p.date.between(summary['start_date'],summary['end_date'])]
a=a[a.date.between(summary['start_date'],summary['end_date'])]
tables=compute_tables(p,a)
tables['daily_class_contribution']=a.groupby(['date','asset_class']).asset_contribution.sum(min_count=1).unstack().reindex(p.date).reset_index()
for name,frame in tables.items():
    frame.to_parquet(out/(name+'.parquet'),index=False)
    (out/(name+'.json')).write_text(json.dumps(records(frame),ensure_ascii=False,allow_nan=False)+'\n')
(out/'rolling_win_rate.json').write_text('{}\n') # replaced below using identical service computation
(out/'parameter_capabilities.json').write_text(json.dumps(parameter_capabilities(),ensure_ascii=False,indent=2)+'\n')
sources=[SNAPSHOT/'daily_portfolio.parquet',SNAPSHOT/'daily_asset_state.parquet',SNAPSHOT/'summary.json',SNAPSHOT/'rules.json',V6_BASE/'config/phase3a.yaml',V6_BASE/'config/phase3b.yaml',V6_BASE/'src/phase3b.py']
manifest={'strategy_version':'V6','formal_window':{'from':summary['start_date'],'to':summary['end_date']},'observations':len(p),'data_status':'REAL_V6_DERIVED','analytics_status':'NEW_UNAUDITED_VISUALIZATION_LAYER','source_hashes':{str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in sources},'precision':'Canonical Parquet IEEE754 -> JSON full float precision, no 10-decimal web JSONL','method_version':'v1','snapshot_hashes':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(out.glob('*.parquet'))}}
(out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
from backend.analytics_service import AnalyticsService
(out/'rolling_win_rate.json').write_text(json.dumps(AnalyticsService().win_rates(),ensure_ascii=False,indent=2)+'\n')
m=performance(p.portfolio_return_net)
exp=a.groupby(['date','asset_class']).weight_start_of_day.sum().unstack()
for cls in ('equity','bond','commodity'):m['avg_'+cls+'_exposure']=float(exp[cls].mean())
m['mean_10vt_multiplier']=float(p.final_10vt_multiplier.mean())
checks=[dict(metric=k,derived=m[k],official=summary[k],abs_diff=abs(m[k]-summary[k]),status='PASS' if abs(m[k]-summary[k])<=1e-10 else 'FAIL') for k in m if k in summary]
pd.DataFrame(checks).to_csv(reports/'V0.6_BASELINE_RECONCILIATION.csv',index=False)
print(json.dumps({'checks':checks,'snapshot':str(out)},ensure_ascii=False))
if any(c['status']=='FAIL' for c in checks):raise SystemExit('baseline reconciliation failed')
