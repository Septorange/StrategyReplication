#!/usr/bin/env python3
"""Independent publication gate for one Web + Analytics candidate bundle."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
ASSET_CLASS={'IF':'equity','IC':'equity','IM':'equity','TF':'bond','T':'bond','SC':'commodity','FG':'commodity','I':'commodity','M':'commodity','AU':'commodity','CU':'commodity'}
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def verify_files(path,manifest):
    errors=[]
    for name,meta in manifest.get('files',{}).items():
        p=path/name
        if not p.is_file(): errors.append(name); continue
        if meta.get('bytes')!=p.stat().st_size or meta.get('sha256')!=sha(p): errors.append(name)
    return errors
def tree_hash(root):
    files=[]
    for base in ('src','scripts','config','data/raw','data/processed'):
        for path in sorted((root/base).rglob('*')):
            if path.is_file() and path.name!='.DS_Store': files.append({'path':str(path.relative_to(root)),'bytes':path.stat().st_size,'sha256':sha(path)})
    return {'tree_sha256':hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'file_count':len(files)}
def maxdiff(a,b):
    left=pd.to_numeric(a,errors='coerce'); right=pd.to_numeric(b,errors='coerce')
    if not left.isna().equals(right.isna()): return 1.0
    d=(left-right).abs().dropna()
    return float(d.max()) if len(d) else 0.0
def field_diff(a,b):
    if not a.isna().equals(b.isna()): return 1.0
    if pd.api.types.is_bool_dtype(a) or pd.api.types.is_bool_dtype(b):
        left=a.astype(object).where(a.notna(),'<NULL>').astype(str); right=b.astype(object).where(b.notna(),'<NULL>').astype(str)
        return 0.0 if left.equals(right) else 1.0
    if pd.api.types.is_numeric_dtype(a) or pd.api.types.is_numeric_dtype(b): return maxdiff(a,b)
    left=a.astype(object).where(a.notna(),'<NULL>').astype(str); right=b.astype(object).where(b.notna(),'<NULL>').astype(str)
    return 0.0 if left.equals(right) else 1.0
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--bundle',type=Path,required=True); ap.add_argument('--phase1-root',type=Path,default=ROOT/'data/v07_local/extended_10119bd207b16499'); ap.add_argument('--baseline-web',type=Path,default=ROOT/'data/v6_web'); ap.add_argument('--baseline-analytics',type=Path,default=ROOT/'data/v6_analytics'); ap.add_argument('--baseline-integrity-before',type=Path,default=Path('/private/tmp/phase1_5_completion_baseline_before.json')); ap.add_argument('--frozen-before',type=Path,default=ROOT/'reports/V0.7_FROZEN_HASHES_BEFORE.json'); ap.add_argument('--frozen-after',type=Path,default=ROOT/'reports/V0.7_FROZEN_HASHES_AFTER.json'); ap.add_argument('--write-report',action='store_true'); a=ap.parse_args()
    b=a.bundle; w=b/'web'; an=b/'analytics'; out={}
    try:
        wm=json.loads((w/'manifest.json').read_text()); am=json.loads((an/'manifest.json').read_text()); rebuild=json.loads((a.phase1_root/'rebuild_manifest.json').read_text()); source=json.loads((a.phase1_root/'manifest.json').read_text())
        out['web_manifest_file_errors']=verify_files(w,wm); out['analytics_manifest_file_errors']=verify_files(an,am)
        out['snapshot_ids_match']=wm.get('snapshot_id')==am.get('snapshot_id')==source.get('strategy_snapshot_id')
        out['source_validation_pass']=rebuild.get('status')=='PASS' and source.get('status')=='LOCAL_UNPUBLISHED' and rebuild.get('phase3a_validation',{}).get('passed') is True and rebuild.get('phase3a_validation',{}).get('error_count',0)==0 and rebuild.get('phase3b_validation',{}).get('passed') is True and not rebuild.get('phase3b_validation',{}).get('errors',[])
        input_hash_mismatches=[]; input_count_mismatches=[]
        for rel,digest in source.get('inputs_sha256',{}).items():
            path=a.phase1_root/rel
            if not path.is_file() or sha(path)!=digest: input_hash_mismatches.append(rel)
        for rel,count in source.get('record_counts',{}).items():
            path=a.phase1_root/rel
            if path.suffix=='.parquet' and path.is_file() and len(pd.read_parquet(path))!=count: input_count_mismatches.append(rel)
        out['source_input_hash_mismatches']=input_hash_mismatches; out['source_input_count_mismatches']=input_count_mismatches
        out['web_source_rebuild_manifest_hash_matches']=wm.get('source_rebuild_manifest_sha256')==sha(a.phase1_root/'rebuild_manifest.json')
        v6=Path(rebuild['v6_root']); readiness=json.loads((v6/'data/processed/phase2_5/production_readiness_v2.json').read_text()); checks=readiness.get('checks',{})
        out['phase2_5_readiness_pass']=readiness.get('PHASE3_READY') is True and readiness.get('phase2_rebuild_required') is False and len(checks)==12 and all(v is True for v in checks.values())
        report25=json.loads((v6/'data/processed/phase2_5/V2_PHASE2_5_REPORT.json').read_text()); checks25=report25.get('checks',{})
        out['phase2_5_report_pass']=report25.get('phase2_5_ready') is True and len(checks25)==12 and all(v is True for v in checks25.values()) and report25.get('forced_data_roll_gaps')==[]
        fg=pd.read_csv(v6/'data/processed/phase2_5/fg_requery_results.csv'); out['fg_23_targeted_status_explicit']=len(fg)==23 and set(fg.resolution.dropna().unique())=={'CONFIRMED_ZERO_CLOSE'} and set(fg.request_status.dropna().unique())=={'OK'}
        before=json.loads(a.frozen_before.read_text()); after=json.loads(a.frozen_after.read_text()); live=tree_hash(v6)
        out['frozen_v6_integrity']={'reported_before':before.get('tree_sha256'),'reported_after':after.get('tree_sha256'),'live_after':live['tree_sha256'],'reported_before_files':before.get('file_count'),'reported_after_files':after.get('file_count'),'live_after_files':live['file_count'],'unchanged':before.get('tree_sha256')==after.get('tree_sha256')==live['tree_sha256'] and before.get('file_count')==after.get('file_count')==live['file_count']==4542 and after.get('unchanged') is True}
        baseline_before=json.loads(a.baseline_integrity_before.read_text()); baseline_live={rel:sha(ROOT/rel) for rel in baseline_before if (ROOT/rel).is_file()}
        out['old_web_analytics_files_unchanged']=baseline_live==baseline_before and len(baseline_before)==28

        p=pd.read_parquet(w/'daily_portfolio.parquet'); x=pd.read_parquet(w/'daily_asset_state.parquet'); p.date=pd.to_datetime(p.date); x.date=pd.to_datetime(x.date)
        out['portfolio_rows']=len(p); out['portfolio_dates_unique_sorted']=bool(p.date.is_monotonic_increasing and not p.date.duplicated().any()); out['portfolio_window']={'start':str(p.date.min().date()),'end':str(p.date.max().date())}
        counts=x.groupby('date').asset.nunique(); out['asset_rows']=len(x); out['assets_per_day_min']=int(counts.min()); out['assets_per_day_max']=int(counts.max()); out['asset_keys_unique']=not x.duplicated(['date','asset']).any(); out['all_expected_assets']=set(x.asset.unique())==set(ASSET_CLASS)
        out['asset_date_coverage_exact']=set(x.date.unique())==set(p.date.unique()) and len(x)==len(p)*len(ASSET_CLASS) and all(set(g.asset)==set(ASSET_CLASS) for _,g in x.groupby('date'))
        held=x.weight_start_of_day.abs()>1e-14; out['held_returns_missing']=int((held & (x.trade_return_net.isna()|x.trade_return_gross.isna())).sum())
        closed=x.groupby('date').asset_contribution.sum(min_count=1).rename('sum').reset_index().merge(p[['date','portfolio_return_net']],on='date',validate='one_to_one'); out['daily_contribution_closure_max_abs']=maxdiff(closed['sum'],closed.portfolio_return_net)
        out['roll_cost_deducted_once']=bool(np.allclose(x.trade_return_net,x.trade_return_gross-x.roll_cost,atol=1e-12,equal_nan=True))
        out['post_haircut_weight_identity_max_abs']=maxdiff(x.post_haircut_weight,x.monthly_base_target*x.single_asset_haircut)
        out['final_weight_identity_max_abs']=maxdiff(x.final_weight,x.pre10vt_weight*x.final_10vt_multiplier)
        out['start_weight_matches_final_weight_max_abs']=maxdiff(x.weight_start_of_day,x.final_weight)
        for name,ret in [('net','portfolio_return_net'),('gross','portfolio_return_gross'),('after_roll','portfolio_return_after_contract_roll')]:
            navcol={'net':'nav_net','gross':'nav_gross','after_roll':'nav_after_contract_roll'}[name]
            out[f'nav_{name}_consistent_with_daily_returns_after_anchor']=bool(np.allclose(p[navcol].iloc[1:].to_numpy()/p[navcol].iloc[:-1].to_numpy(),(1+p[ret].iloc[1:]).to_numpy(),rtol=1e-10,atol=1e-12))
        summary=json.loads((w/'summary.json').read_text()); r=p.portfolio_return_net.astype(float); nav=p.nav_net.astype(float); peak=np.maximum.accumulate(np.r_[1.,nav.to_numpy()])[1:]
        independently={'observations':len(p),'annualized_return':float(nav.iloc[-1]**(252/len(r))-1),'annualized_vol':float(r.std(ddof=1)*np.sqrt(252)),'sharpe':float(r.mean()/r.std(ddof=1)*np.sqrt(252)),'max_drawdown':float((nav/peak-1).min()),'mean_10vt_multiplier':float(p.final_10vt_multiplier.mean())}
        daily_exposure=x.groupby(['date','asset_class']).weight_start_of_day.sum(min_count=1).unstack()
        for cl in ('equity','bond','commodity'): independently['avg_'+cl+'_exposure']=float(daily_exposure[cl].mean())
        out['summary_reconciliation']={k:abs(float(summary[k])-float(v)) if k!='observations' else int(summary[k])==v for k,v in independently.items()}
        base=pd.read_parquet(a.baseline_web/'daily_portfolio.parquet'); base.date=pd.to_datetime(base.date); overlap=p.merge(base,on='date',suffixes=('_new','_old'),how='inner',validate='one_to_one')
        fields=['portfolio_return_net','portfolio_return_gross','portfolio_return_after_contract_roll','contract_roll_cost','portfolio_rebalance_cost','final_10vt_multiplier','nav_net','nav_gross','nav_after_contract_roll']; od=[]
        for col in fields: od.append({'field':col,'rows':len(overlap),'max_abs_diff':maxdiff(overlap[col+'_new'],overlap[col+'_old'])})
        ba=pd.read_parquet(a.baseline_web/'daily_asset_state.parquet'); ba.date=pd.to_datetime(ba.date); ax=x.merge(ba,on=['date','asset'],suffixes=('_new','_old'),how='inner',validate='one_to_one')
        for col in ['weight_start_of_day','final_weight','trade_return_net','roll_cost','rebalance_cost','asset_contribution','final_10vt_multiplier']:
            if col+'_new' in ax and col+'_old' in ax: od.append({'field':'asset.'+col,'rows':len(ax),'max_abs_diff':maxdiff(ax[col+'_new'],ax[col+'_old'])})
        out['formal_overlap_rows']=len(overlap); out['formal_overlap_asset_rows']=len(ax); out['formal_overlap']=od
        # Trace the whole extended Web range directly back to the verified Phase 1 Parquets.
        source_p=pd.read_parquet(a.phase1_root/'phase3b/portfolio_daily.parquet'); source_p.date=pd.to_datetime(source_p.date); source_p=source_p[source_p.date.between(p.date.min(),p.date.max())].sort_values('date')
        base_anchor=base.loc[base.date.eq(p.date.min())].iloc[0]; phase_anchor=source_p.loc[source_p.date.eq(p.date.min())].iloc[0]
        scales={n:float(base_anchor[n]/phase_anchor[n]) for n in ('nav_net','nav_gross','nav_after_contract_roll')}
        source_portfolio=source_p.merge(p[['date']],on='date',how='inner',validate='one_to_one')
        prov=[]
        for col in ['portfolio_return_gross','portfolio_return_after_contract_roll','portfolio_return_net','contract_roll_cost','portfolio_rebalance_cost','total_cost','turnover','portfolio_vol_estimate','raw_10vt_multiplier','final_10vt_multiplier']:
            webcol=p[['date',col]]; src=source_p[['date',col]]; m=webcol.merge(src,on='date',suffixes=('_web','_src'),validate='one_to_one'); prov.append({'field':'portfolio.'+col,'max_abs_diff':maxdiff(m[col+'_web'],m[col+'_src'])})
        for col,scale in scales.items():
            m=p[['date',col]].merge(source_p[['date',col]],on='date',suffixes=('_web','_src'),validate='one_to_one'); prov.append({'field':'portfolio.'+col,'max_abs_diff':maxdiff(m[col+'_web'],m[col+'_src']*scale)})
        source_w=pd.read_parquet(a.phase1_root/'phase3b/final_daily_weights.parquet'); source_w.date=pd.to_datetime(source_w.date); source_w=source_w[source_w.date.between(p.date.min(),p.date.max())]
        source_t=pd.read_parquet(a.phase1_root/'phase2/trade_returns.parquet'); source_t.date=pd.to_datetime(source_t.date); source_t=source_t[source_t.date.between(p.date.min(),p.date.max())]
        expected=source_w.merge(source_t[['date','asset','trade_return_gross','trade_return_net','roll_cost']],on=['date','asset'],how='left',validate='one_to_one')
        expected['rebalance_cost']=.5*(expected.weight_end_of_day-expected.weight_start_of_day).abs()*expected.asset_class.map({'equity':5.0,'bond':2.0,'commodity':0.0})/10000
        expected['asset_contribution']=np.where(expected.weight_start_of_day.abs()>1e-14,expected.weight_start_of_day*expected.trade_return_net,0.0)-expected.rebalance_cost
        expected['post_haircut_weight']=expected.monthly_base_target*expected.single_asset_haircut
        state_fields={'weight_start_of_day':'weight_start_of_day','weight_end_of_day':'weight_end_of_day','monthly_base_target':'monthly_base_target','single_asset_haircut':'single_asset_haircut','controlled_target':'controlled_target','unscaled_execution_weight':'unscaled_execution_weight','portfolio_vol_estimate':'portfolio_vol_estimate','raw_10vt_multiplier':'raw_10vt_multiplier','final_10vt_multiplier':'final_10vt_multiplier','final_weight':'weight_start_of_day','trade_return_gross':'trade_return_gross','trade_return_net':'trade_return_net','roll_cost':'roll_cost','rebalance_cost':'rebalance_cost','asset_contribution':'asset_contribution','post_haircut_weight':'post_haircut_weight'}
        joined=x.merge(expected,on=['date','asset'],suffixes=('_web','_src'),how='outer',validate='one_to_one',indicator=True); out['web_phase1_key_mismatch_rows']=int((joined._merge!='both').sum())
        for webcol,srccol in state_fields.items(): prov.append({'field':'asset.'+webcol,'max_abs_diff':maxdiff(joined[webcol+'_web'],joined[srccol+'_src'])})
        out['web_phase1_provenance']=prov; out['web_phase1_provenance_max_abs_diff']=max(v['max_abs_diff'] for v in prov)
        roll=pd.read_parquet(w/'daily_roll.parquet'); roll.date=pd.to_datetime(roll.date)
        rollcols=['date','asset','held_contract_start_of_day','candidate_contract','confirmed_active_contract','roll_trigger','roll_from','roll_to','roll_mode','roll_weight_old','roll_weight_new','held_contract_end_of_day','days_to_expiry','expiry_known','expiry_source','requires_requery','status','switch_reversal_1d','switch_reversal_2d','start_weights','end_weights','turnover','roll_cost']
        rt=source_t[[c for c in rollcols if c in source_t.columns]]; wr=roll[[c for c in rollcols if c in roll.columns]]; rm=wr.merge(rt,on=['date','asset'],suffixes=('_web','_src'),how='outer',validate='one_to_one',indicator=True); roll_errors=[]
        for c in rollcols:
            if c in ('date','asset'): continue
            left=rm[c+'_web']; right=rm[c+'_src']; diff=field_diff(left,right)
            roll_errors.append({'field':c,'max_abs_diff':diff})
        out['roll_source_key_mismatch_rows']=int((rm._merge!='both').sum()); out['roll_source_max_field_diff']=max(v['max_abs_diff'] for v in roll_errors); out['roll_source_comparison']=roll_errors
        selection=pd.read_parquet(a.phase1_root/'phase3a/asset_selection.parquet'); selection.signal_date=pd.to_datetime(selection.signal_date).astype('datetime64[ns]'); selection.date=pd.to_datetime(selection.date).astype('datetime64[ns]'); selection.next_trading_date=pd.to_datetime(selection.next_trading_date).astype('datetime64[ns]'); x.date=pd.to_datetime(x.date).astype('datetime64[ns]')
        rank_source=['rank_ret_20','rank_ret_60','rank_ret_240','rank_sharpe_20','rank_sharpe_60','rank_sharpe_240']
        for i,col in enumerate(rank_source,1): selection[f'rank_{i}']=selection[col]
        monthly=pd.read_parquet(w/'monthly_momentum.parquet'); monthly.signal_date=pd.to_datetime(monthly.signal_date)
        momcols=['ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240','mean_rank','selected','signal_source']+[f'rank_{i}' for i in range(1,7)]
        monthly_keys=monthly[['signal_date','asset',*momcols]]; selection_keys=selection[['signal_date','asset',*momcols]]
        mm=monthly_keys.merge(selection_keys,on=['signal_date','asset'],suffixes=('_web','_src'),how='outer',validate='one_to_one',indicator=True)
        out['momentum_source_key_mismatch_rows']=int((mm._merge!='both').sum()); out['momentum_source_field_diffs']={c:field_diff(mm[c+'_web'],mm[c+'_src']) for c in momcols}; out['momentum_source_max_abs_diff']=max(out['momentum_source_field_diffs'].values())
        daily_source=pd.read_parquet(a.phase1_root/'phase3a/momentum_signals.parquet'); daily_source.date=pd.to_datetime(daily_source.date).astype('datetime64[ns]'); daily_source=daily_source[daily_source.date.isin(x.date.unique())]
        daily_fields=['trade_eligible','signal_usable','risk_estimate_usable','signal_source']
        daily_check=x[['date','asset',*daily_fields]].merge(daily_source[['date','asset',*daily_fields]],on=['date','asset'],suffixes=('_web','_src'),how='left',validate='one_to_one',indicator=True)
        out['daily_signal_source_missing_rows']=int((daily_check._merge!='both').sum()); out['daily_signal_source_field_diffs']={c:field_diff(daily_check[c+'_web'],daily_check[c+'_src']) for c in daily_fields}; out['daily_signal_source_max_diff']=max(out['daily_signal_source_field_diffs'].values())
        effective=[]
        for asset in ASSET_CLASS:
            left=x.loc[x.asset.eq(asset),['date','asset']].sort_values('date')
            right=selection.loc[selection.asset.eq(asset),['next_trading_date','signal_date','selected']].sort_values('next_trading_date')
            effective.append(pd.merge_asof(left,right,left_on='date',right_on='next_trading_date',direction='backward'))
        effective=pd.concat(effective,ignore_index=True).merge(x[['date','asset','signal_date','selected']],on=['date','asset'],suffixes=('_src','_web'),validate='one_to_one')
        daily_selection_fields=['signal_date','selected']
        out['daily_selection_source_field_diffs']={c:field_diff(effective[c+'_web'],effective[c+'_src']) for c in daily_selection_fields}; out['daily_selection_source_max_diff']=max(out['daily_selection_source_field_diffs'].values())
        tr=pd.read_parquet(a.phase1_root/'phase2/trade_returns.parquet'); tr.date=pd.to_datetime(tr.date); tr=tr.sort_values(['asset','date']); tr['next_start']=tr.groupby('asset').held_contract_start_of_day.shift(-1); valid=tr.next_start.notna(); out['roll_contract_t_to_t_plus_1_mismatches']=int((tr.loc[valid,'held_contract_end_of_day'].fillna('')!=tr.loc[valid,'next_start'].fillna('')).sum())
        # The strategy estimates sigma from the previous 120 unscaled gross portfolio returns.
        fw=pd.read_parquet(a.phase1_root/'phase3b/final_daily_weights.parquet'); fw.date=pd.to_datetime(fw.date); full_trade=pd.read_parquet(a.phase1_root/'phase2/trade_returns.parquet'); full_trade.date=pd.to_datetime(full_trade.date)
        raw=fw[['date','asset','unscaled_execution_weight']].merge(full_trade[['date','asset','trade_return_gross']],on=['date','asset'],how='left',validate='one_to_one'); raw['component']=raw.unscaled_execution_weight*raw.trade_return_gross; rawdaily=raw.groupby('date').component.sum(min_count=1).sort_index()
        independent_vol=rawdaily.rolling(120,min_periods=120).std(ddof=1).shift(1)*np.sqrt(252); independent_raw=(.10/independent_vol).replace([np.inf,-np.inf],np.nan).fillna(1.0); independent_mult=independent_raw.clip(.5,1.5)
        stored=fw[['date','portfolio_vol_estimate','raw_10vt_multiplier','final_10vt_multiplier']].drop_duplicates('date').set_index('date').sort_index(); valid_vol=stored.portfolio_vol_estimate.notna()
        out['10vt_prior_only_dates_checked']=int(valid_vol.sum()); out['10vt_vol_max_abs_error']=maxdiff(stored.loc[valid_vol,'portfolio_vol_estimate'],independent_vol.loc[valid_vol]); out['10vt_multiplier_max_abs_error']=maxdiff(stored.final_10vt_multiplier,independent_mult.reindex(stored.index))
        phase_report=json.loads((ROOT/'reports/V0.7_PHASE1_EXTENDED_BACKTEST.json').read_text()); out['phase1_report_pass']=phase_report.get('status')=='PASS' and phase_report.get('formal_overlap_status')=='PASS' and phase_report.get('new_period_data_quality')=='PASS'
        ap=pd.read_parquet(an/'portfolio_history.parquet'); ap.date=pd.to_datetime(ap.date); out['analytics_window_matches_web']=str(ap.date.min().date())==str(p.date.min().date()) and str(ap.date.max().date())==str(p.date.max().date()) and len(ap)==len(p); out['analytics_source_hash_matches_web']=am.get('source_web_manifest_sha256')==sha(w/'manifest.json')
        out['data_end_date_matches_verified_rebuild']=str(p.date.max().date())==rebuild.get('phase3b_last_date')==source.get('latest_verified_date'); out['last_signal_date_matches_verified_rebuild']=wm.get('phase3a_last_signal_date')==rebuild.get('phase3a_last_signal_date')
        critical={k:v for k,v in out.items() if isinstance(v,bool)}
        out['overall_pass']=all(critical.values()) and out['web_source_rebuild_manifest_hash_matches'] and out['web_phase1_key_mismatch_rows']==0 and out['web_phase1_provenance_max_abs_diff']<=1e-12 and out['roll_source_key_mismatch_rows']==0 and out['roll_source_max_field_diff']<=1e-12 and out['momentum_source_key_mismatch_rows']==0 and out['momentum_source_max_abs_diff']<=1e-12 and out['daily_selection_source_max_diff']<=1e-12 and out['daily_signal_source_max_diff']<=1e-12 and not out['web_manifest_file_errors'] and not out['analytics_manifest_file_errors'] and not input_hash_mismatches and not input_count_mismatches and out['phase2_5_readiness_pass'] and out['phase2_5_report_pass'] and out['fg_23_targeted_status_explicit'] and out['frozen_v6_integrity']['unchanged'] and out['old_web_analytics_files_unchanged'] and out['held_returns_missing']==0 and out['daily_contribution_closure_max_abs']<=1e-12 and out['formal_overlap_rows']==2220 and out['formal_overlap_asset_rows']==24420 and max(row['max_abs_diff'] for row in od)<=1e-12 and all((v if isinstance(v,bool) else v<=1e-10) for v in out['summary_reconciliation'].values()) and out['roll_contract_t_to_t_plus_1_mismatches']==0 and out['phase1_report_pass'] and out['10vt_vol_max_abs_error']<=1e-10 and out['10vt_multiplier_max_abs_error']<=1e-10 and out['post_haircut_weight_identity_max_abs']<=1e-12 and out['final_weight_identity_max_abs']<=1e-12 and out['start_weight_matches_final_weight_max_abs']<=1e-12
    except Exception as exc:
        out['overall_pass']=False; out['fatal_error_code']=type(exc).__name__; out['fatal_error_detail']=str(exc)
    dest=b/'publish_validation.json'
    if a.write_report: dest.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False))
    if not out.get('overall_pass'): raise SystemExit(1)
if __name__=='__main__': main()
