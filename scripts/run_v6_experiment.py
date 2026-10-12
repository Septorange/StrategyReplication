#!/usr/bin/env python3
"""Run one Mode B experiment in the V6-compatible Python runtime."""
import copy,importlib.util,json,math,sys
from pathlib import Path
import pandas as pd
import yaml
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.experiment_costs import with_commodity_roll_cost
from backend.analytics_service import drawdown_episodes,performance
from backend.utils import records
V6=Path('/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6')

def compute_experiment_metrics(formal):
    """Shared formal performance convention: include initial high water of 1."""
    stats=performance(formal.portfolio_return_net)
    stats.pop('return')
    stats.update(mean_10vt_multiplier=float(formal.final_10vt_multiplier.mean()),lower_bound_hit_rate=float((formal.final_10vt_multiplier<=.5+1e-12).mean()))
    return stats

def main():
    request=json.loads(Path(sys.argv[1]).read_text()); dest=Path(sys.argv[2]); c=request['config']; baseline=request['baseline']
    spec=importlib.util.spec_from_file_location('v6_phase3b',V6/'src/phase3b.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    cfg=yaml.safe_load((V6/'config/phase3b.yaml').read_text()); cfg=copy.deepcopy(cfg); cfg['portfolio_vol_target'].update(target_vol=c['target_vol'],estimator=f"trailing_{c['vt_window']}",min_history=c['vt_window']); cfg['single_asset_vol_control'].update(quantile=c['quantile'],haircut=c['haircut']); cfg['mid_month_rebalance']['threshold']=c['midmonth_threshold']; cfg['costs']['commodity_bps']=c['commodity_cost_bps']
    base=pd.read_parquet(V6/'data/processed/phase3a/base_target_weights.parquet'); sig=pd.read_parquet(V6/'data/processed/phase2/signal_returns.parquet'); trade=pd.read_parquet(V6/'data/processed/phase2/trade_returns.parquet'); sv=cfg['single_asset_vol_control']
    trade=with_commodity_roll_cost(trade,c['commodity_cost_bps'])
    print(json.dumps({'event':'v6_engine_started','source':str(V6/'src/phase3b.py'),'functions':['build_single_asset_vol_control','build_execution','build_portfolio_daily'],'commodity_cost_bps':c['commodity_cost_bps'],'commodity_roll_cost_sum':float(trade.loc[trade.asset.isin(['SC','FG','I','M','AU','CU']),'roll_cost'].sum())}),flush=True)
    vol=mod.build_single_asset_vol_control(sig,quantile=sv['quantile'],lookback=sv['quantile_lookback'],haircut_value=sv['haircut'],method=sv['method'],short_vol_method=sv['short_vol_method'],min_quantile_history=sv['min_quantile_history'])
    _,_,events,fw=mod.build_execution(base,vol,trade,sig,cfg,midmonth_threshold=c['midmonth_threshold'],vt_estimator=cfg['portfolio_vol_target']['estimator']); port=mod.build_portfolio_daily(fw,trade,cfg); formal=port[port.date.between(baseline['start_date'],baseline['end_date'])].copy()
    # Match V6 scripts/42_build_phase3_formal.py: keep prehistory for causal VT,
    # then rebase every saved NAV to the common formal evaluation window.
    for nav_column, return_column in [('nav_gross','portfolio_return_gross'),('nav_after_contract_roll','portfolio_return_after_contract_roll'),('nav_net','portfolio_return_net')]:
        formal[nav_column]=(1+formal[return_column]).cumprod()
    m=compute_experiment_metrics(formal)
    exposure=fw[fw.date.between(baseline['start_date'],baseline['end_date'])].groupby(['date','asset_class']).weight_start_of_day.sum().unstack().reset_index()
    for cls in ['equity','bond','commodity']:m['avg_'+cls+'_exposure']=float(exposure[cls].mean())
    history=formal[['date','nav_net','nav_gross','portfolio_return_net','total_cost','contract_roll_cost','portfolio_rebalance_cost','final_10vt_multiplier']].copy()
    history['display_vol']=formal.portfolio_return_net.rolling(120,min_periods=120).std(ddof=1)*math.sqrt(252)
    cost_summary={k:float(formal[k].sum()) for k in ['contract_roll_cost','portfolio_rebalance_cost','total_cost']}
    effective=dict(momentum_excluded_count=1,risk_budget_vol_window=240,asset_short_vol_window=20,short_vol_windows=[20,60],asset_long_vol_window=240,quantile_lookback=240,**{k:c[k] for k in ['target_vol','vt_window','haircut','quantile','midmonth_threshold','commodity_cost_bps']})
    result={'status':'PASS','engine':'V6 src/phase3b.py via V6 .venv','config_hash':dest.name,'config':c,'baseline':baseline,'experiment':m,'deltas':{k:m[k]-baseline[k] for k in ['annualized_return','annualized_vol','sharpe','max_drawdown']},'output_path':str(dest),'synthetic':False,'cost_scope':'commodity contract roll and portfolio weight rebalance; experiment-only override','effective_params':effective,'parameter_differences':{k: {'baseline':v,'experiment':effective[k]} for k,v in {'haircut':.5,'midmonth_threshold':.2,'target_vol':.1,'vt_window':120,'quantile':.9,'commodity_cost_bps':0}.items() if effective[k]!=v},'history':{'rows':records(history)},'exposure':{'rows':records(exposure)},'drawdowns':{'rows':records(drawdown_episodes(formal).head(5))},'costs':cost_summary,'stages':[{'stage':'Phase3A','action':'reuse immutable baseline; upstream parameters locked','artifact':'base_target_weights.parquet'},{'stage':'Phase2','action':'immutable gross/trade returns; independent commodity roll-cost overlay','artifact':'experiment_trade_returns.parquet'},{'stage':'Phase3B','action':'real vol_control / execution / portfolio functions rerun with full prehistory','artifacts':['single_asset_vol_control.parquet','final_daily_weights.parquet','daily_portfolio.parquet','events.parquet']}], 'formal_window':{'from':baseline['start_date'],'to':baseline['end_date']},'data_status':'REAL_V6_EXPERIMENT','adapter_audit_status':'NEW_V0.6_RESPONSE_LAYER_PENDING_INDEPENDENT_AUDIT'}
    trade[['date','asset','turnover','cost_bps','cost_status','roll_cost','trade_return_gross','trade_return_net']].to_parquet(dest/'experiment_trade_returns.parquet',index=False)
    vol.to_parquet(dest/'single_asset_vol_control.parquet',index=False); fw.to_parquet(dest/'final_daily_weights.parquet',index=False); formal.to_parquet(dest/'daily_portfolio.parquet',index=False); events.to_parquet(dest/'events.parquet',index=False); (dest/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'event':'v6_engine_completed','observations':len(formal),'output_path':str(dest),'experiment':m}),flush=True)

if __name__=='__main__':
    main()
