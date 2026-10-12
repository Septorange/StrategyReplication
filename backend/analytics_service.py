"""Read-only V6 analytics. Display windows never rerun or change strategy weights."""
from __future__ import annotations
import hashlib,json,math
from pathlib import Path
import numpy as np
import pandas as pd
from .config import ROOT
from .utils import records
ANALYTICS=ROOT/'data/v6_analytics'
ASSET_CLASSES={'IF':'equity','IC':'equity','IM':'equity','TF':'bond','T':'bond','SC':'commodity','FG':'commodity','I':'commodity','M':'commodity','AU':'commodity','CU':'commodity'}
HORIZONS={1:'日度',5:'周度',21:'月度',63:'季度',126:'半年度',252:'年度',378:'18个月',504:'两年度'}


def performance(r):
    r=pd.Series(r,dtype=float); nav=(1+r).cumprod(); vol=float(r.std(ddof=1)*math.sqrt(252))
    high=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
    return {'return':float(nav.iloc[-1]-1),'annualized_return':float(nav.iloc[-1]**(252/len(r))-1),'annualized_vol':vol,'sharpe':float(r.mean()/r.std(ddof=1)*math.sqrt(252)) if vol else None,'max_drawdown':float((nav/high-1).min()),'observations':len(r)}


def drawdown_episodes(portfolio):
    """Peak -> trough -> first recovery to high water; trading-index distances."""
    dates=portfolio.date.tolist(); nav=portfolio.nav_net.to_numpy(float); high=1.; peak=0; active=None; episodes=[]
    for i,(date,value) in enumerate(zip(dates,nav)):
        if value>=high:
            if active is not None:
                active.update(recovery_date=date,recovery_days=i-active.pop('_trough_index'))
                episodes.append(active); active=None
            high=value; peak=i
        else:
            dd=value/high-1
            if active is None:
                active={'peak_date':dates[peak],'trough_date':date,'recovery_date':None,'max_drawdown':dd,'drawdown_days':i-peak,'recovery_days':None,'_trough_index':i}
            elif dd<active['max_drawdown']:
                active.update(trough_date=date,max_drawdown=dd,drawdown_days=i-peak,_trough_index=i)
    if active is not None:
        active.pop('_trough_index'); episodes.append(active)
    episodes.sort(key=lambda x:x['max_drawdown'])
    for e in episodes: e['episode_id']='V6-DD-'+pd.Timestamp(e['peak_date']).strftime('%Y%m%d')+'-'+pd.Timestamp(e['trough_date']).strftime('%Y%m%d')
    return pd.DataFrame(episodes,columns=['episode_id','peak_date','trough_date','recovery_date','max_drawdown','drawdown_days','recovery_days'])


def compute_tables(p,a,window=120):
    p=p.sort_values('date').copy(); a=a.copy(); a['year']=a.date.dt.year
    history=p[['date','nav_net','nav_gross','portfolio_return_net','total_cost','contract_roll_cost','portfolio_rebalance_cost','final_10vt_multiplier']].copy()
    history['display_vol']=p.portfolio_return_net.rolling(window,min_periods=window).std(ddof=1)*math.sqrt(252)
    yearly=[]
    for label,g in [('自回测基日',p)]+[(str(year),g) for year,g in p.groupby(p.date.dt.year)]:
        m=performance(g.portfolio_return_net); year=None if label=='自回测基日' else int(label)
        yearly.append(dict(period=label,year=year,**m,start=g.date.min(),end=g.date.max(),partial_year=year is not None and (g.date.min().month!=1 or g.date.max().month!=12)))
    contrib=a.groupby(['year','asset_class'],as_index=False).asset_contribution.sum(min_count=1).rename(columns={'asset_contribution':'contribution'})
    asset_rows=[]
    for year in sorted(a.year.unique()):
        for asset,cls in ASSET_CLASSES.items():
            g=a[(a.year==year)&(a.asset==asset)]
            if g.empty: value=None; status='MISSING'
            elif not g.trade_eligible.eq(True).any(): value=None; status='NOT_LISTED_OR_NOT_ELIGIBLE'
            elif not (g.weight_start_of_day.abs()>1e-14).any(): value=0.; status='NOT_PARTICIPATING'
            elif g.loc[g.weight_start_of_day.abs()>1e-14,'asset_contribution'].isna().any(): value=None; status='MISSING_HELD_RETURN'
            else: value=float(g.asset_contribution.sum(min_count=1)); status='PARTICIPATED'
            asset_rows.append(dict(year=int(year),asset=asset,asset_class=cls,contribution=value,status=status))
    exposure=a.groupby(['date','asset_class']).weight_start_of_day.sum(min_count=1).unstack().reindex(p.date)
    clsreturns=a.groupby(['date','asset_class']).asset_contribution.sum(min_count=1).unstack().reindex(p.date)
    for cls in ('equity','bond','commodity'):
        exposure[cls+'_vol']=clsreturns[cls].rolling(window,min_periods=window).std(ddof=1)*math.sqrt(252)
    return {'portfolio_history':history,'annual_performance':pd.DataFrame(yearly),'annual_class_contribution':contrib,'annual_asset_contribution':pd.DataFrame(asset_rows),'class_exposure_and_vol120':exposure.reset_index(),'drawdown_episodes':drawdown_episodes(p)}


class AnalyticsService:
    def __init__(self,path:Path=ANALYTICS):
        self.path=path; self.manifest=json.loads((path/'manifest.json').read_text()); self._tables={}
        self.source_hash=hashlib.sha256((path/'manifest.json').read_bytes()).hexdigest()
    def table(self,name):
        if name not in self._tables:
            frame=pd.DataFrame(json.loads((self.path/(name+'.json')).read_text()))
            for col in ('date','start','end','peak_date','trough_date','recovery_date'):
                if col in frame: frame[col]=pd.to_datetime(frame[col])
            self._tables[name]=frame
        return self._tables[name].copy()
    def response(self,rows,method,units,**extra):
        return dict(strategy_version='V6',formal_window=self.manifest['formal_window'],method_id=method,data_status='REAL_V6_DERIVED',display_vol_window=extra.pop('display_vol_window',120),units=units,rows=records(rows),source_manifest_hash=self.source_hash,analytics_audit_status='NEW_VISUALIZATION_LAYER_PENDING_INDEPENDENT_AUDIT',**extra)
    def history(self,from_date=None,to_date=None,display_window=120):
        x=self.table('portfolio_history'); x['display_vol']=x.portfolio_return_net.rolling(display_window,min_periods=display_window).std(ddof=1)*math.sqrt(252)
        if from_date: x=x[x.date>=pd.Timestamp(from_date)]
        if to_date: x=x[x.date<=pd.Timestamp(to_date)]
        return self.response(x,'formal_net_nav_and_inclusive_display_vol_v1',{'nav_net':'NAV','nav_gross':'NAV','display_vol':'annualized fraction','cost':'daily return fraction'},display_vol_window=display_window,warning='Display net-return volatility is distinct from the strategy prior-only pre-10VT estimator.')
    def performance_by_year(self):
        return self.response(self.table('annual_performance'),'compound_calendar_year_and_formal_annualized_v1',{'return':'compound interval fraction','annualized_return':'annualized fraction','annualized_vol':'annualized fraction','max_drawdown':'negative fraction'},full_period_return_field='annualized_return',sharpe_definition='daily mean / sample std * sqrt(252), risk-free rate 0',partial_year_note='First and last years contain only the formal observations shown in start/end.')
    def win_rates(self,overlap=True):
        nav=self.table('portfolio_history').nav_net.to_numpy(float); rows=[]
        for h,label in HORIZONS.items():
            starts=np.arange(0,max(0,len(nav)-h),1 if overlap else h); r=nav[starts+h]/nav[starts]-1
            valid=r[np.isfinite(r)]; up=valid[valid>0]; down=valid[valid<0]; denominator=len(up)+len(down)
            rows.append(dict(horizon=h,label=label,up=len(up),down=len(down),zero=int((valid==0).sum()),nonfinite=int((~np.isfinite(r)).sum()),windows=len(r),win_rate=len(up)/denominator if denominator else None,up_avg=float(up.mean()) if len(up) else None,down_avg=float(down.mean()) if len(down) else None))
        return self.response(pd.DataFrame(rows),'forward_nav_ratio_overlapping_v1' if overlap else 'forward_nav_ratio_nonoverlap_v1',{'horizon':'trading days','win_rate':'fraction','up_avg':'return fraction','down_avg':'return fraction'},overlap=overlap,warning='Overlapping holding-period observations are not independent and are not predictive accuracy.')
    def class_contribution(self):
        return self.response(self.table('annual_class_contribution'),'sum_daily_net_asset_contribution_v1',{'contribution':'return fraction; multiply by 100 for pp'},warning='Arithmetic daily contribution sums do not equal geometrically compounded annual NAV returns.')
    def asset_contribution(self):
        return self.response(self.table('annual_asset_contribution'),'sum_daily_net_asset_contribution_with_eligibility_v1',{'contribution':'return fraction; multiply by 100 for pp'})
    def exposure(self,display_window=120,from_date=None,to_date=None):
        x=self.table('class_exposure_and_vol120')
        if display_window!=120:
            # Save unrounded class return contributions as the causal display input.
            c=self.table('daily_class_contribution')
            for cls in ('equity','bond','commodity'): x[cls+'_vol']=c[cls].rolling(display_window,min_periods=display_window).std(ddof=1)*math.sqrt(252)
        if from_date: x=x[x.date>=pd.Timestamp(from_date)]
        if to_date: x=x[x.date<=pd.Timestamp(to_date)]
        return self.response(x,'start_of_day_nominal_and_class_contribution_vol_v1',{'equity':'nominal x','bond':'nominal x','commodity':'nominal x','class_vol':'annualized fraction'},display_vol_window=display_window,warning='Class contribution volatility is not a market-return volatility or risk contribution RC.')
    def top_drawdowns(self,limit=5):
        return self.response(self.table('drawdown_episodes').head(limit),'high_water_1_peak_trough_first_recovery_v1',{'max_drawdown':'negative fraction','drawdown_days':'trading-index distance','recovery_days':'trading-index distance'},warning='Unrecovered episodes retain null recovery dates and durations.')
