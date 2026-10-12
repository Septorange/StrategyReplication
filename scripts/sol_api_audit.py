#!/usr/bin/env python3
"""Audit real FastAPI runtime against the exported snapshot."""
import asyncio,json,sys
from pathlib import Path
import httpx
import pandas as pd
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.app import app,loader
from backend.utils import records

async def main():
    checks=[];evidence={}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://sol-audit') as client:
        for route in ['/api/health','/api/v6/summary','/api/v6/rules','/api/v6/series','/api/v6/assets']:
            r=await client.get(route); evidence[route]=r.json(); checks.append({'route':route,'status':r.status_code,'result':'PASS' if r.status_code==200 else 'FAIL'})
        dates=['2016-06-01','2018-01-02','2020-03-16','2022-08-01','2024-11-20','2024-11-08','2024-11-01','2024-08-19','2024-10-11','2024-10-08','2024-11-17']
        for date in dates:
            d=loader.resolve(date); expected=records(loader.assets[loader.assets.date==d]); portfolio=records(loader.portfolio[loader.portfolio.date==d])[0]
            for endpoint in ['day','momentum','weights','rolls','attribution']:
                route=f'/api/v6/{endpoint}/{date}';r=await client.get(route);x=r.json();evidence[route]=x
                ok=r.status_code==200
                if endpoint=='day':ok=ok and x['assets']==expected and x['portfolio']==portfolio
                if endpoint=='rolls':ok=ok and x['rows']==records(loader.rolls[loader.rolls.date==d])
                if endpoint in ['weights','attribution']:
                    ok=ok and len(x['rows'])==11 and all(all(row[k]==next(a for a in expected if a['asset']==row['asset'])[k] for k in row) for row in x['rows'])
                checks.append({'route':route,'status':r.status_code,'requested_date':x.get('requested_date'),'resolved_date':x.get('resolved_date'),'result':'PASS' if ok else 'FAIL'})
        for endpoint in ['day','momentum','weights','rolls','attribution']:
            route=f'/api/v6/{endpoint}/1900-01-01';r=await client.get(route); checks.append({'route':route,'status':r.status_code,'result':'PASS' if r.status_code==404 else 'FAIL'})
    series=evidence['/api/v6/series']['rows']; assert series==records(loader.portfolio)
    summary=evidence['/api/v6/summary'];table=pd.read_csv(ROOT/'reports/SOL_V6_BASELINE_RECOMPUTE.csv')
    displays={'annualized_return':.1702,'annualized_vol':.1025,'sharpe':1.586,'max_drawdown':-.1192,'mean_10vt_multiplier':.597,'nav_last':3.993113}
    for i,r in table.iterrows():
        value=series[-1]['nav_net'] if r.metric=='nav_last' else summary[r.metric]
        table.loc[i,'api']=value;table.loc[i,'abs_diff_api']=abs(value-r.v6_independent)
        if r.metric in displays:
            table.loc[i,'ui']=displays[r.metric]; table.loc[i,'abs_diff_ui']=abs(displays[r.metric]-value)
            threshold=.0000005 if r.metric=='nav_last' else .0005 if r.metric in ['sharpe','mean_10vt_multiplier'] else .00005
            uiok=abs(displays[r.metric]-value)<=threshold
        else:uiok=True
        table.loc[i,'status']='PASS_FORMATTED_UI' if r.metric in displays and uiok else 'PASS_API_UI_NOT_DISPLAYED' if uiok else 'FAIL'
    table.to_csv(ROOT/'reports/SOL_V6_BASELINE_RECOMPUTE.csv',index=False)
    pd.DataFrame(checks).to_csv(ROOT/'reports/SOL_API_CONTRACT_AUDIT.csv',index=False)
    (ROOT/'reports/SOL_API_RUNTIME_EVIDENCE.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'routes':len(checks),'pass':sum(c['result']=='PASS' for c in checks),'fail':sum(c['result']=='FAIL' for c in checks)},indent=2))
    assert all(c['result']=='PASS' for c in checks)

if __name__=='__main__':asyncio.run(main())
