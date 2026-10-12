#!/usr/bin/env python3
"""Independent raw signal/control metrics and bond confirmation audit."""
from sol_independent_audit import *

def main():
    hist=read(P/'phase2/signal_history.parquet'); scores=read(P/'phase3a/momentum_signals.parquet')
    pieces=[]
    for asset,g in hist.groupby('asset'):
        g=g.sort_values('date').copy();r=g.signal_return;idx=g.signal_index
        expected=g[['date','asset']].copy()
        for n in [20,60,240]:
            ret=idx/idx.shift(n)-1
            if asset=='SC' and n==240:
                logs=np.log1p(r); count=logs.rolling(240,min_periods=60).count()
                warm=np.expm1(logs.rolling(240,min_periods=60).sum()*240/count)
                ret=warm.where(count<240,ret)
            expected[f'ret_{n}']=ret
            minimum=60 if asset=='SC' and n==240 else n
            window=r.rolling(n,min_periods=minimum);sd=window.std(ddof=1)
            expected[f'sharpe_{n}']=(window.mean()/sd*math.sqrt(252)).where(sd>1e-12)
        minimum=60 if asset in ['T','TF','SC'] else 240
        expected['risk_vol']=(r.rolling(240,min_periods=minimum).std(ddof=1)*math.sqrt(252)).where(lambda x:x>1e-12)
        expected['signal_usable']=np.isfinite(expected[['ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240']]).all(axis=1)
        expected['risk_estimate_usable']=np.isfinite(expected.risk_vol)&(expected.risk_vol>1e-12)
        pieces.append(expected)
    expected=pd.concat(pieces);numeric=['ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240','risk_vol']
    diff=same(expected,scores,numeric+['signal_usable','risk_estimate_usable'],['date','asset'])
    check('raw_momentum_six_signal_and_risk_recompute',diff<1e-12,f'{len(expected)} asset days; max error {diff}; SC 60D equivalent240; bonds sigma240 >=60; equity full240 proxy-splice')
    vol=read(P/'phase3b/single_asset_vol_control.parquet');sig=read(P/'phase2/signal_returns.parquet');pieces=[]
    for asset,g in sig.groupby('asset'):
        g=g.sort_values('date').copy();r=g.signal_return;x=g[['date','asset']].copy()
        x['vol_20']=r.rolling(20,min_periods=20).std(ddof=1)*math.sqrt(252)
        x['vol_60']=r.rolling(60,min_periods=60).std(ddof=1)*math.sqrt(252)
        x['long_vol']=r.rolling(240,min_periods=240).std(ddof=1)*math.sqrt(252)
        x['short_vol']=x[['vol_20','vol_60']].max(axis=1,skipna=False)
        x['direct_threshold_q90']=x.long_vol.rolling(240,min_periods=120).quantile(.9)
        x['triggered']=(x.short_vol>x.direct_threshold_q90)&x.direct_threshold_q90.notna()
        x['haircut']=np.where(x.triggered,.5,1);pieces.append(x)
    expected=pd.concat(pieces);cols=['vol_20','vol_60','long_vol','short_vol','direct_threshold_q90','triggered','haircut']
    diff=same(expected,vol,cols,['date','asset']);check('raw_haircut_recompute',diff<1e-12,f'all {len(vol)} daily inputs; max error {diff}')
    a=read(S/'daily_asset_state.parquet');source=a[['date','asset']].merge(vol,on=['date','asset'],how='left')
    check('haircut_snapshot_mapping',same(source,a,cols,['date','asset'])<1e-12,'left merge; current CLOSE controls exposed without implying same-day PnL')
    t=read(P/'phase2/trade_returns.parquet');source=a[['date','asset']].merge(t,on=['date','asset'],how='left')
    check('trade_snapshot_mapping',same(source,a,['trade_return_gross','trade_return_net','roll_cost'],['date','asset'])<1e-12,'all formal asset rows')
    check('post_haircut_diagnostic',error(a.post_haircut_weight,a.midmonth_theoretical_target)<1e-12,'post_haircut current close diagnostic; controlled_target is freeze during smoothing')
    roll=read(P/'phase2/roll_calendar.parquet');snapshot=read(S/'daily_roll.parquet');formal=roll[roll.date.isin(snapshot.date)]
    check('roll_snapshot_mapping',same(formal,snapshot,[c for c in roll if c not in ['date','asset','start_weights','end_weights']],['date','asset'])<1e-12,'all 22161 daily states; dict fields separately checked')
    for c in ['start_weights','end_weights']:
        left=formal.sort_values(['date','asset'])[c].map(lambda v:json.loads(v) if isinstance(v,str) else v).tolist();right=snapshot.sort_values(['date','asset'])[c].map(json.loads).tolist()
        check('roll_'+c,left==right,'canonical V6 dict equals snapshot serialized dict')
    active=read(P/'phase2/active_contract_calendar.parquet');quotes=read(P/'phase2/contract_eligibility.parquet');valid={k:set(g.loc[g.is_eligible,'thscode']) for k,g in quotes.groupby(['asset','date'])}
    misses=[]
    for asset,path in active[active.asset.isin(['TF','T'])].groupby('asset'):
        held=None;challenger=None;streak=0
        for row in path.sort_values('date').itertuples():
            candidate=row.candidate_contract;switched=False
            if pd.isna(candidate):challenger=None;streak=0
            elif held is None:held=candidate;challenger=None;streak=0
            elif candidate==held:challenger=None;streak=0
            elif held not in valid[(asset,row.date)]:held=candidate;challenger=None;streak=0
            else:
                streak=streak+1 if challenger==candidate else 1;challenger=candidate
                if streak>=2:held=candidate;switched=True;streak=0;challenger=None
            if held!=row.confirmed_active_contract or switched!=bool(row.switch_confirmed) or streak!=row.confirmation_counter:misses.append((asset,row.date))
    check('bond_two_day_confirmation',not misses,f'{len(active[active.asset.isin(["TF","T"])])} rows, mismatches={len(misses)}; forced invalid holding exception independent')
    commodity=t[t.asset.isin(['SC','FG','I','M','AU','CU'])]
    check('mode_a_commodity_zero_baseline',commodity.cost_bps.eq(0).all() and commodity.roll_cost.eq(0).all(),'all V6 commodity contract roll costs 0; rebalance cost0 by class map')
    prod=(ROOT/'frontend/app.js').read_text();tokens=['getDailyAssetRet','generateLegacy','simulateStrategy','generateExperiment','approximateBacktest','Math.sin','Math.cos','Math.random']
    check('synthetic_runtime_path',not any(x in prod for x in tokens) and not (ROOT/'frontend/prototype_v0.3.html').exists(),'production imports only app.js; preserved demo outside static root references/')
    pd.DataFrame(CHECKS).to_csv(OUT/'SOL_SUPPLEMENTAL_CHECKS.csv',index=False)
    print(json.dumps(CHECKS,indent=2,default=str));assert all(x['status']=='PASS' for x in CHECKS)

if __name__=='__main__':main()
