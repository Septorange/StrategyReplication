#!/usr/bin/env python3
"""Build research analytics from one candidate Web snapshot only."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.analytics_service import compute_tables, performance, HORIZONS
from backend.utils import records

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--web-snapshot',type=Path,required=True); ap.add_argument('--out',type=Path,required=True); a=ap.parse_args()
    if a.out.exists() and any(a.out.iterdir()): raise SystemExit(f'analytics output must be empty: {a.out}')
    w=a.web_snapshot; wm=json.loads((w/'manifest.json').read_text())
    if wm.get('source_status')!='LOCAL_UNPUBLISHED' or wm.get('synthetic_values') is not False: raise SystemExit('web candidate not validated as real local source')
    p=pd.read_parquet(w/'daily_portfolio.parquet'); x=pd.read_parquet(w/'daily_asset_state.parquet')
    p.date=pd.to_datetime(p.date); x.date=pd.to_datetime(x.date)
    summary=json.loads((w/'summary.json').read_text()); p=p[p.date.between(summary['start_date'],summary['end_date'])].sort_values('date'); x=x[x.date.between(summary['start_date'],summary['end_date'])].copy()
    if not len(p) or not p.date.is_monotonic_increasing: raise SystemExit('empty or unsorted portfolio history')
    a.out.mkdir(parents=True,exist_ok=True); tables=compute_tables(p,x)
    tables['daily_class_contribution']=x.groupby(['date','asset_class']).asset_contribution.sum(min_count=1).unstack().reindex(p.date).reset_index()
    for name,frame in tables.items():
        frame.to_parquet(a.out/(name+'.parquet'),index=False,version='1.0',data_page_version='1.0',use_dictionary=False,write_page_index=False)
        (a.out/(name+'.json')).write_text(json.dumps(records(frame),ensure_ascii=False,allow_nan=False)+'\n')
    nav=p.nav_net.to_numpy(float); rows=[]
    for h,label in HORIZONS.items():
        starts=range(0,max(0,len(nav)-h),1); r=nav[[i+h for i in starts]]/nav[[i for i in starts]]-1 if len(starts) else []
        s=pd.Series(r,dtype=float); valid=s[s.map(lambda z: pd.notna(z))]; up=valid[valid>0]; down=valid[valid<0]; denom=len(up)+len(down)
        rows.append(dict(horizon=h,label=label,up=len(up),down=len(down),zero=int((valid==0).sum()),nonfinite=int(s.isna().sum()),windows=len(s),win_rate=len(up)/denom if denom else None,up_avg=float(up.mean()) if len(up) else None,down_avg=float(down.mean()) if len(down) else None))
    response={'strategy_version':'V6','formal_window':{'from':summary['start_date'],'to':summary['end_date']},'method_id':'forward_nav_ratio_overlapping_v1','data_status':'REAL_V07_DERIVED','display_vol_window':120,'units':{'horizon':'trading days','win_rate':'fraction','up_avg':'return fraction','down_avg':'return fraction'},'rows':rows,'source_manifest_hash':sha(w/'manifest.json'),'analytics_audit_status':'WEB_LAYER_PENDING_INDEPENDENT_REVIEW','overlap':True,'warning':'Overlapping holding-period observations are not independent and are not predictive accuracy.'}
    (a.out/'rolling_win_rate.json').write_text(json.dumps(response,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    files={}
    for f in sorted(a.out.iterdir()): files[f.name]={'sha256':sha(f),'bytes':f.stat().st_size}
    manifest={'snapshot_id':wm['snapshot_id'],'data_status':'REAL_V07_DERIVED','formal_window':{'from':summary['start_date'],'to':summary['end_date']},'observations':len(p),'source_web_manifest_sha256':sha(w/'manifest.json'),'method_version':'v1','files':files,'analytics_status':'WEB_LAYER_PENDING_INDEPENDENT_REVIEW'}
    (a.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    metrics=performance(p.portfolio_return_net); print(json.dumps({'snapshot_id':wm['snapshot_id'],'observations':len(p),'tables':sorted(tables),'history_end':str(p.date.max().date()),'summary_return_diff':float(metrics['annualized_return']-summary['annualized_return'])},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
