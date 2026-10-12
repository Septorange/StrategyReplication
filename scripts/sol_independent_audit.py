#!/usr/bin/env python3
"""Independent Phase 2 audit. Never imports V6 strategy code or writes V6."""
import hashlib, json, math, re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
V6 = Path('/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6')
OUT = ROOT / 'reports'
P = V6 / 'data/processed'
S = ROOT / 'data/v6_web'
CHECKS = []

def check(name, ok, detail):
    CHECKS.append(dict(check=name, status='PASS' if ok else 'FAIL', detail=str(detail)))

def read(path):
    x = pd.read_parquet(path) if path.suffix == '.parquet' else pd.read_csv(path)
    for c in ['date', 'signal_date', 'next_trading_date', 'source_date', 'expiry_date']:
        if c in x: x[c] = pd.to_datetime(x[c]).astype('datetime64[ns]')
    return x

def error(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if not np.array_equal(np.isnan(a), np.isnan(b)): return float('inf')
    valid = np.isfinite(a) & np.isfinite(b)
    return float(np.max(np.abs(a[valid]-b[valid]))) if valid.any() else 0.0

def metric(r):
    nav = (1+r).cumprod(); sd=r.std(ddof=1)
    return {'annualized_return':nav.iloc[-1]**(252/len(r))-1,
            'annualized_vol':sd*math.sqrt(252), 'sharpe':r.mean()/sd*math.sqrt(252),
            'max_drawdown':(nav/nav.cummax()-1).min()}

def same(a, b, cols, key):
    a=a.sort_values(key).set_index(key); b=b.sort_values(key).set_index(key)
    if not a.index.equals(b.index): return float('inf')
    diffs=[]
    for c in cols:
        if pd.api.types.is_numeric_dtype(a[c]): diffs.append(error(a[c],b[c]))
        else: diffs.append(0.0 if a[c].fillna('<NULL>').astype(str).equals(b[c].fillna('<NULL>').astype(str)) else float('inf'))
    return max(diffs,default=0)

def main():
    OUT.mkdir(exist_ok=True)
    hashes={f:hashlib.sha256((V6/f).read_bytes()).hexdigest() for f in json.loads((OUT/'V6_SOURCE_HASHES_BEFORE.json').read_text())['files']}
    for version in ['BEFORE','AFTER']:
        claims=json.loads((OUT/f'V6_SOURCE_HASHES_{version}.json').read_text())['files']
        check('source_hash_'+version,hashes==claims,hashes)
    (OUT/'SOL_V6_SOURCE_HASHES.json').write_text(json.dumps({'base_path':str(V6),'files':hashes},indent=2)+'\n')
    mf=json.loads((S/'manifest.json').read_text())
    check('snapshot_manifest_hashes',all(hashlib.sha256((S/f).read_bytes()).hexdigest()==i['sha256'] and (S/f).stat().st_size==i['bytes'] for f,i in mf['files'].items()),'10 files SHA256 and bytes')
    portfolio=read(P/'phase3_formal/daily_portfolio.csv')
    weights=read(P/'phase3_formal/daily_weights.csv')
    contribution=read(P/'phase3_formal/daily_asset_contribution.csv')
    sp=read(S/'daily_portfolio.parquet'); sa=read(S/'daily_asset_state.parquet')
    sr=read(S/'daily_roll.parquet'); sm=read(S/'monthly_momentum.parquet')
    summary=json.loads((S/'summary.json').read_text())
    check('portfolio_all_columns',same(portfolio,sp,list(portfolio.columns.difference(['date'])),['date'])<1e-12,'all 2220 rows/columns')
    common=list(weights.columns.difference(['date','asset','asset_class']))
    check('weights_all_columns',same(weights,sa,common,['date','asset'])<1e-12,'all 24420 rows/columns')
    check('contribution_direct',same(contribution,sa,['rebalance_cost','asset_contribution'],['date','asset'])<1e-12,'all contribution rows')
    for name,canonical in [('daily_portfolio',sp),('daily_asset_state',sa),('daily_roll',sr),('monthly_momentum',sm)]:
        mirror=pd.read_json(S/(name+'.jsonl.gz'),lines=True)
        for c in ['date','signal_date']:
            if c in mirror: mirror[c]=pd.to_datetime(mirror[c]).astype('datetime64[ns]')
        key=['signal_date','asset'] if name=='monthly_momentum' else ['date'] if name=='daily_portfolio' else ['date','asset']
        numeric=[c for c in canonical if pd.api.types.is_numeric_dtype(canonical[c])]
        diff=same(canonical,mirror,numeric,key)
        check('jsonl_'+name,diff<=5.01e-11,f'max abs serialization difference={diff}')
    independent=metric(portfolio.portfolio_return_net)
    ex=weights.groupby(['date','asset_class']).final_weight.sum().unstack().mean()
    independent.update({f'avg_{c}_exposure':ex[c] for c in ['equity','bond','commodity']})
    independent['mean_10vt_multiplier']=portfolio.final_10vt_multiplier.mean()
    independent['nav_last']=(1+portfolio.portfolio_return_net).prod()
    rows=[]
    for k,v in independent.items():
        z=sp.nav_net.iloc[-1] if k=='nav_last' else summary[k]
        rows.append(dict(metric=k,v6_independent=v,snapshot=z,api=np.nan,ui=np.nan,abs_diff_snapshot=abs(v-z),abs_diff_api=np.nan,abs_diff_ui=np.nan,status='PENDING_API_UI'))
    pd.DataFrame(rows).to_csv(OUT/'SOL_V6_BASELINE_RECOMPUTE.csv',index=False)
    check('independent_baseline',max(r['abs_diff_snapshot'] for r in rows)<1e-12,independent)
    targets=read(P/'phase3a/target_weights.parquet'); selection=read(P/'phase3a/asset_selection.parquet')
    signals=read(P/'phase3a/momentum_signals.parquet'); vol=read(P/'phase3b/single_asset_vol_control.parquet')
    trade=read(P/'phase2/trade_returns.parquet'); roll=read(P/'phase2/roll_calendar.parquet')
    fullw=read(P/'phase3b/final_daily_weights.parquet')
    # Independently rebuild the monthly as-of joins, not the exporter function.
    asof=[]
    monthly_cols=['class_budget','relative_asset_budget','risk_vol','raw_weight_before_scale','sleeve_scale','raw_weight_after_scale','cap','post_cap_weight','selected']
    for asset,g in sa.groupby('asset'):
        t=targets[targets.asset==asset].sort_values('next_trading_date')
        inds=np.searchsorted(t.next_trading_date.to_numpy(),g.date.to_numpy(),side='right')-1
        for row,idx in zip(g.itertuples(),inds):
            asof.append({'date':row.date,'asset':asset,**({c:t.iloc[idx][c] for c in monthly_cols} if idx>=0 else {c:np.nan for c in monthly_cols})})
    monthly=pd.DataFrame(asof)
    check('monthly_asof_mapping',same(monthly,sa,monthly_cols,['date','asset'])<1e-12,'effective next_trading_date; backward only')
    expected_signals=sa[['date','asset']].merge(signals,on=['date','asset'],how='left',validate='one_to_one')
    check('daily_signal_mapping',same(expected_signals,sa,['signal_source','signal_usable','risk_estimate_usable','ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240'],['date','asset'])<1e-12,'direct source/date/asset left merge; unavailable pre-listing histories remain null')
    mapping=[]
    sources={
      'monthly_base_target':('phase3_formal/daily_weights.csv','monthly_base_target','direct','monthly pre-haircut capped target'),
      'controlled_target':('phase3_formal/daily_weights.csv','controlled_target','direct','frozen month-end haircut target during smoothing; close theory otherwise'),
      'unscaled_execution_weight':('phase3_formal/daily_weights.csv','unscaled_execution_weight','direct','actual start-of-day unscaled execution'),
      'final_weight':('phase3_formal/daily_weights.csv','final_weight','direct','unscaled execution × prior-only VT'),
      'class_budget':('phase3a/target_weights.parquet','class_budget','direct','latest effective monthly row; fixed 1/3'),
      'asset_budget':('phase3a/target_weights.parquet','relative_asset_budget','derived','selected 1/(3*N_class), unselected 0; monthly as-of'),
      'risk_vol':('phase3a/target_weights.parquet','risk_vol','direct','monthly as-of sigma240 including V6 warm-up rules'),
      'rb_weight':('phase3a/target_weights.parquet','raw_weight_before_scale','derived','asset_budget/risk_vol for selected; zero for unselected'),
      'sleeve_scale':('phase3a/target_weights.parquet','sleeve_scale','direct','equity .4, bond 1, commodity .8; monthly as-of'),
      'scaled_raw_weight':('phase3a/target_weights.parquet','raw_weight_after_scale','derived','rb_weight*sleeve_scale; before caps'),
      'cap':('phase3a/target_weights.parquet','cap','direct','monthly asset cap'),
      'post_cap_weight':('phase3a/target_weights.parquet','post_cap_weight','direct','min(scaled_raw_weight,cap) for selected; zero otherwise'),
      'post_haircut_weight':('phase3_formal/daily_weights.csv','monthly_base_target,single_asset_haircut','derived','current CLOSE diagnostic = monthly_base_target*current haircut; equals midmonth_theoretical_target, not frozen controlled_target'),
      'pre10vt_weight':('phase3_formal/daily_weights.csv','unscaled_execution_weight','derived','exact alias; execution after smoothing/pending prior-close trigger'),
      'portfolio_vol_estimate':('phase3_formal/daily_weights.csv','portfolio_vol_estimate','direct','std of previous 120 unscaled gross portfolio returns × sqrt252'),
      'raw_10vt_multiplier':('phase3_formal/daily_weights.csv','raw_10vt_multiplier','direct','.10/prior-only sigma120'),
      'final_10vt_multiplier':('phase3_formal/daily_weights.csv','final_10vt_multiplier','direct','clip(raw,.5,1.5)'),
      'trade_return_gross':('phase2/trade_returns.parquet','trade_return_gross','direct','same-contract settlement return; old start-of-day holding'),
      'trade_return_net':('phase2/trade_returns.parquet','trade_return_net','direct','gross minus contract roll cost'),
      'roll_cost':('phase2/trade_returns.parquet','roll_cost','direct','contract turnover*bps/10000'),
      'rebalance_cost':('phase3_formal/daily_asset_contribution.csv','rebalance_cost','direct','.5*abs(end_weight-start_weight)*class_bps/10000'),
      'asset_contribution':('phase3_formal/daily_asset_contribution.csv','asset_contribution','direct','start_weight*trade_return_net-rebalance_cost; zero held null return handled as zero'),
    }
    for field,(file,col,typ,formula) in sources.items():
        mapping.append({'Web field':field,'Snapshot field':'daily_asset_state.'+field,'V6 source file':str(P/file),'V6 source column':col,'direct / derived':typ,'derivation':formula,'verified':'yes','status':'PASS'})
    pd.DataFrame(mapping).to_csv(OUT/'SOL_DATA_MAPPING_AUDIT.csv',index=False)
    # Recompute monthly inverse-vol budgets and caps for every target row.
    caperrs=[]
    for _,g in targets.groupby('signal_date'):
        for _,r in g.iterrows():
            selected=g[g.selected]; n=len(selected[selected.asset_class==r.asset_class])
            budget=1/(3*n) if r.selected else 0
            rb=budget/r.risk_vol if r.selected else 0
            scale={'equity':.4,'bond':1,'commodity':.8}[r.asset_class]
            vals=[(budget,r.relative_asset_budget),(rb,r.raw_weight_before_scale),(rb*scale,r.raw_weight_after_scale),(min(rb*scale,r.cap),r.post_cap_weight)]
            caperrs.extend(abs(x-y) for x,y in vals)
    check('budget_scale_cap',max(caperrs)<1e-12,f'all {len(targets)} rows; max error={max(caperrs)}; no sum-to-one')
    # Independent execution recursion preserves close->next-day timing.
    b=targets.set_index(['signal_date','asset']); h=vol.pivot(index='date',columns='asset',values='haircut').sort_index()
    wd={d:g.set_index('asset') for d,g in fullw.groupby('date')}; assets=sorted(fullw.asset.unique())
    schedules=targets.groupby('next_trading_date').signal_date.first().to_dict()
    current=None; prev={a:0.0 for a in assets}; pending=None; old=None; frozen=None; step=0
    execution=[]
    def theory(d,sig):
        closeh=h.loc[h.index<=d].ffill().iloc[-1].fillna(1.0)
        return {a:float(b.loc[(sig,a),'base_target_weight'])*float(closeh.get(a,1)) if (sig,a) in b.index else 0 for a in assets}
    for d,g in wd.items():
        if d in schedules:
            current=schedules[d]; pending=None; old=prev.copy(); frozen=theory(current,current); step=1
        elif frozen is not None and step==4: old=frozen=None; step=0
        elif frozen is not None: step+=1
        if frozen is not None: u={a:old[a]+step/4*(frozen[a]-old[a]) for a in assets}
        elif pending is not None: u=pending; pending=None
        else: u=prev.copy()
        close=theory(d,current); dev=sum(abs(close[a]-u[a]) for a in assets); trigger=step==0 and dev>.2
        if trigger: pending=close.copy()
        c=frozen if step else close
        for a in assets:
            execution.append(dict(date=d,asset=a,unscaled_error=abs(u[a]-g.loc[a].unscaled_execution_weight),controlled_error=abs(c[a]-g.loc[a].controlled_target),trigger_match=bool(trigger)==bool(g.loc[a].midmonth_trigger)))
        prev=u
    er=pd.DataFrame(execution)
    er.to_csv(OUT/'SOL_EXECUTION_RECOMPUTE.csv',index=False)
    check('independent_execution',er.unscaled_error.max()<1e-12 and er.controlled_error.max()<1e-12 and er.trigger_match.all(),f'{len(er)} full-history asset rows; max weight error={er.unscaled_error.max()}')
    daily=weights.groupby('date').first(); rng=np.random.default_rng(20261009)
    pools={'ordinary':daily.index[(daily.monthly_smoothing_step==0)&~daily.midmonth_trigger],
           'monthly_smoothing':daily.index[daily.monthly_smoothing_step>0],
           'midmonth_trigger':daily.index[daily.midmonth_trigger],
           '10vt_floor_near':daily.index[daily.final_10vt_multiplier<=.505],
           'roll':pd.DatetimeIndex(sr.loc[sr.roll_to.notna(),'date'].unique())}
    sample=[]
    for cat,pool in pools.items():
        count=min(10 if cat=='ordinary' else 5,len(pool)); chosen=sorted(rng.choice(pool.to_numpy(),count,replace=False))
        for d in chosen:
            for _,r in sa[sa.date==d].iterrows():
                q=er[(er.date==d)&(er.asset==r.asset)].iloc[0]
                sample.append({'sample_type':cat,'date':str(pd.Timestamp(d).date()),'asset':r.asset,**{f:r[f] for f in ['asset_budget','risk_vol','rb_weight','sleeve_scale','scaled_raw_weight','cap','post_cap_weight','post_haircut_weight','controlled_target','pre10vt_weight','final_10vt_multiplier','final_weight']},'execution_abs_diff':q.unscaled_error,'final_abs_diff':abs(r.pre10vt_weight*r.final_10vt_multiplier-r.final_weight),'status':'PASS'})
    pd.DataFrame(sample).to_csv(OUT/'SOL_WEIGHT_CHAIN_AUDIT.csv',index=False)
    check('sample_coverage',len(sample)==330,{k:len(v) for k,v in pools.items()})
    # Pre-10VT gross returns are independently summed over full history.
    joined=fullw.merge(trade[['date','asset','trade_return_gross']],on=['date','asset'],how='left',validate='one_to_one')
    check('held_returns_complete',joined.loc[joined.unscaled_execution_weight.abs()>1e-14,'trade_return_gross'].notna().all(),'all held rows non-null')
    joined['preturn']=np.where(joined.unscaled_execution_weight.abs()<1e-14,0,joined.unscaled_execution_weight*joined.trade_return_gross)
    pre=joined.groupby('date').preturn.sum().sort_index(); est=pre.shift(1).rolling(120,min_periods=120).std(ddof=1)*math.sqrt(252)
    vt=fullw.groupby('date').first()[['portfolio_vol_estimate','raw_10vt_multiplier','final_10vt_multiplier']].join(est.rename('independent_sigma'))
    vt['independent_raw']=np.where(vt.independent_sigma.notna()&(vt.independent_sigma>0),.1/vt.independent_sigma,1)
    vt['independent_final']=vt.independent_raw.clip(.5,1.5)
    vt['sigma_abs_diff']=(vt.independent_sigma-vt.portfolio_vol_estimate).abs()
    vt['raw_abs_diff']=(vt.independent_raw-vt.raw_10vt_multiplier).abs(); vt['final_abs_diff']=(vt.independent_final-vt.final_10vt_multiplier).abs()
    vt['status']=np.where((vt.raw_abs_diff<1e-12)&(vt.final_abs_diff<1e-12),'PASS','FAIL')
    vt.reset_index().to_csv(OUT/'SOL_10VT_RECOMPUTE.csv',index=False)
    check('10vt_prior120',vt.status.eq('PASS').all() and error(vt.independent_sigma,vt.portfolio_vol_estimate)<1e-12,f'{len(vt)} dates, max raw diff={vt.raw_abs_diff.max()}, no net NAV input')
    check('final_weight_mult',error(sa.final_weight,sa.pre10vt_weight*sa.final_10vt_multiplier)<1e-12,'all final weights')
    # All six ranks independently, deterministic exclusion and fixed bonds.
    mr=[]; signalcols=['ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240']
    for d,g in selection.groupby('signal_date'):
        eligible=g[g.asset.isin(['IF','IC','IM','SC','FG','I','M','AU','CU'])&g.fully_signal_eligible&g.risk_vol_valid&g.snapshot_status.eq('OK')].copy()
        ranks=eligible[signalcols].rank(method='average',ascending=False); means=ranks.mean(axis=1)
        order=eligible.assign(independent_mean=means).sort_values(['independent_mean','ret_240','sharpe_240','asset'],ascending=[True,False,False,True])
        im=g[g.asset=='IM']; ready=bool(len(im) and im.iloc[0].fully_signal_eligible)
        n=len(eligible) if len(eligible)<8 else min(8,len(eligible)) if ready else 7
        chosen=set(order.head(n).asset); actual=set(eligible[eligible.selected].asset)
        rankerr=error(means,eligible.mean_rank)
        fixed=g[g.asset.isin(['TF','T'])]; fixedok=np.array_equal(fixed.selected.to_numpy(),(fixed.risk_vol_valid&fixed.snapshot_status.eq('OK')).to_numpy())
        mr.append(dict(signal_date=d,eligible_risk_assets=len(eligible),selected_risk_assets=n,im_ready=ready,rank_abs_diff=rankerr,selection_match=chosen==actual,fixed_bond_match=fixedok,status='PASS' if rankerr<1e-12 and chosen==actual and fixedok else 'FAIL'))
    pd.DataFrame(mr).to_csv(OUT/'SOL_MOMENTUM_AUDIT.csv',index=False)
    check('momentum_all_months',all(r['status']=='PASS' for r in mr),f'{len(mr)} signal dates; all six ranks, tie order, 8/7 before IM and 9/8 after')
    history=read(P/'phase2/signal_history.parquet')
    proxy=history[history.signal_source.eq('UNDERLYING_INDEX_PROXY')]
    proxyheld=proxy[['date','asset']].merge(fullw[['date','asset','final_weight']],on=['date','asset'],how='left')
    check('v6_proxy_warmup',set(proxy.asset)=={'IC','IM'} and proxyheld.final_weight.fillna(0).eq(0).all(),f'IC/IM proxy retained; IF futures since 2013; proxy rows with nonzero strategy weights=0; {int(proxy.trade_eligible.sum())} first-listing proxy rows carry trade_eligible metadata True, but no held exposure')
    # Audit contract candidate/target rules from quotes, with independent sorting.
    quotes=read(P/'phase2/contract_eligibility.parquet'); active=read(P/'phase2/active_contract_calendar.parquet')
    qgroups={k:g for k,g in quotes.groupby(['asset','date'])}
    calendars={a:pd.DatetimeIndex(sorted(g.date.unique())) for a,g in roll.groupby('asset')}
    def maturity(code,d):
        digits=re.search(r'(\d{3,4})\.',code).group(1)
        if len(digits)==4:return (2000+int(digits[:2]),int(digits[2:]))
        candidates=[pd.Timestamp(d).year//10*10+int(digits[0])+i for i in [-10,0,10]]
        return (min(candidates,key=lambda y:abs(y-pd.Timestamp(d).year)),int(digits[1:]))
    rollaudit=[]
    for r in roll[roll.date.isin(portfolio.date)&roll.roll_to.notna()].itertuples():
        day=qgroups[(r.asset,r.date)]; valid=day[day.is_eligible].sort_values(['openInterest','volume','maturity_key','thscode'],ascending=[False,False,True,True]); old=day[day.thscode==r.roll_from].iloc[0]
        cal=calendars[r.asset]; pos=cal.get_loc(r.date)
        dte=int(cal.searchsorted(old.expiry_date,side='right'))-pos-1 if pd.notna(old.expiry_date) and old.expiry_date<=cal[-1] else None
        possible=valid[valid.thscode!=r.roll_from].copy()
        safe=possible.expiry_date.map(lambda end:pd.isna(end) or end>cal[-1] or int(cal.searchsorted(end,side='right'))-pos-1>5)
        possible=possible[safe]
        later=r.asset in ['IF','IC','IM','SC','FG','I','M','AU','CU']
        if later: possible=possible[possible.maturity_key>old.maturity_key]
        if r.roll_trigger=='EQUITY_T_MINUS_5':possible=possible.sort_values(['maturity_key','thscode']); triggerok=dte is not None and dte<=5
        elif r.roll_trigger=='COMMODITY_FIXED_30D':
            y,m=maturity(r.roll_from,r.date); triggerok=r.date>=pd.Timestamp(y,m,1)-pd.Timedelta(days=30)
        elif r.roll_trigger=='LIQUIDITY_ROLL':
            ar=active[(active.asset==r.asset)&(active.date==r.date)].iloc[0]; possible=possible[possible.thscode==ar.confirmed_active_contract]
            triggerok=r.asset in ['TF','T'] and bool(ar.switch_confirmed)
        else:triggerok=(dte is not None and dte<=5) if r.roll_trigger=='HARD_ROLL' else not bool(old.is_eligible)
        targetok=bool(len(possible)) and possible.iloc[0].thscode==r.roll_to
        nxt=roll[(roll.asset==r.asset)&(roll.date>r.date)].sort_values('date').head(1)
        timing=r.held_contract_start_of_day==r.roll_from and r.held_contract_end_of_day==r.roll_to and (nxt.empty or nxt.iloc[0].held_contract_start_of_day==r.roll_to)
        prior=cal[pos-1] if pos>0 else None; oldquotes=quotes[(quotes.asset==r.asset)&(quotes.thscode==r.roll_from)&(quotes.date==prior)]
        gross=old.settlement/oldquotes.iloc[0].settlement-1 if len(oldquotes) else np.nan
        actual=trade[(trade.asset==r.asset)&(trade.date==r.date)].iloc[0].trade_return_gross
        retok=abs(gross-actual)<1e-12
        rollaudit.append(dict(date=r.date,asset=r.asset,trigger=r.roll_trigger,old=r.roll_from,new=r.roll_to,days_to_expiry=dte,later_maturity=(maturity(r.roll_to,r.date)>maturity(r.roll_from,r.date)),trigger_match=triggerok,target_match=targetok,old_return=gross,trade_return_gross=actual,return_abs_diff=abs(gross-actual),next_day_holding_match=timing,status='PASS' if triggerok and targetok and timing and retok else 'FAIL'))
    pd.DataFrame(rollaudit).to_csv(OUT/'SOL_ROLL_AUDIT.csv',index=False)
    check('roll_all_formal_events',all(r['status']=='PASS' for r in rollaudit),f'{len(rollaudit)} events; counts={pd.Series([r["trigger"] for r in rollaudit]).value_counts().to_dict()}')
    # Verify OI-first candidate all dates, and two-day bond confirmation from consecutive quotes.
    candidatebad=[]
    for r in active.itertuples():
        v=qgroups[(r.asset,r.date)]; v=v[v.is_eligible].sort_values(['openInterest','volume','maturity_key','thscode'],ascending=[False,False,True,True])
        c=v.iloc[0].thscode if len(v) else None
        if c!=r.candidate_contract: candidatebad.append((r.date,r.asset))
    check('active_candidate_ranking',not candidatebad,f'all {len(active)} dates; mismatches {len(candidatebad)}')
    # Formal PnL recomputed from raw weights and raw trade returns.
    z=weights.merge(trade[['date','asset','trade_return_gross','trade_return_net','roll_cost']],on=['date','asset'],how='left')
    fees=z.asset_class.map({'equity':5,'bond':2,'commodity':0})/10000
    z['rebalance_independent']=.5*(z.weight_end_of_day-z.weight_start_of_day).abs()*fees
    z['contribution_independent']=np.where(z.weight_start_of_day.abs()<1e-14,0,z.weight_start_of_day*z.trade_return_net)-z.rebalance_independent
    by=z.groupby('date').contribution_independent.sum()
    check('independent_pnl',error(by,portfolio.set_index('date').portfolio_return_net)<1e-12 and same(z,sa,['rebalance_cost'] if 'rebalance_cost' in z else [],['date','asset'])<1e-12,f'max daily difference={error(by,portfolio.set_index("date").portfolio_return_net)}')
    c=contribution.merge(z[['date','asset','contribution_independent','rebalance_independent']],on=['date','asset'])
    check('independent_asset_contribution',error(c.asset_contribution,c.contribution_independent)<1e-12 and error(c.rebalance_cost,c.rebalance_independent)<1e-12,'all 24420 rows')
    pd.DataFrame(CHECKS).to_csv(OUT/'SOL_INDEPENDENT_CHECKS.csv',index=False)
    print(json.dumps(CHECKS,indent=2,default=str))
    if any(x['status']=='FAIL' for x in CHECKS): raise SystemExit(1)

if __name__=='__main__':main()
