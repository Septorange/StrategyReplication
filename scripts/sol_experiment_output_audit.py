#!/usr/bin/env python3
"""Reconcile actual experiment artifacts without calling the engine."""
from sol_independent_audit import *

def main():
    original=read(P/'phase2/trade_returns.parquet');official=read(P/'phase3_formal/daily_portfolio.csv');officialw=read(P/'phase3b/final_daily_weights.parquet')
    results={};ports={};weights={};rows=[]
    for label in ['baseline','target_vol_12','commodity_cost_5','midmonth_25']:
        evidence=json.loads((OUT/f'SOL_EXPERIMENT_{label}.json').read_text());response=evidence['response'];results[label]=response
        dest=Path(response['output_path']);port=read(dest/'daily_portfolio.parquet');fw=read(dest/'final_daily_weights.parquet');tr=read(dest/'experiment_trade_returns.parquet');ports[label]=port;weights[label]=fw
        log=json.loads((dest/'engine_run.json').read_text());stdout=(dest/'engine_stdout.log').read_text();bps=response['config']['commodity_cost_bps']
        check(label+'_runtime',evidence['http_status']==200 and response['status']=='PASS' and not response['synthetic'] and log['returncode']==0 and 'v6_engine_started' in stdout and 'v6_engine_completed' in stdout and log['cwd']==str(V6),'actual POST → subprocess → imported unchanged V6 phase3b → parquet → JSON; log='+str(dest/'engine_run.json'))
        check(label+'_source_fingerprint',all(hashlib.sha256(Path(f).read_bytes()).hexdigest()==h for f,h in log['source_hashes'].items()),'current adapter/engine/config/inputs all match provenance')
        derived=metric(port.portfolio_return_net)
        for m,v in derived.items():rows.append({'experiment':label,'metric':m,'independent':v,'api_response':response['experiment'][m],'abs_diff':abs(v-response['experiment'][m]),'status':'PASS' if abs(v-response['experiment'][m])<1e-12 else 'FAIL'})
        for nav,ret in [('nav_gross','portfolio_return_gross'),('nav_after_contract_roll','portfolio_return_after_contract_roll'),('nav_net','portfolio_return_net')]:
            expected=(1+port[ret]).cumprod();diff=error(expected,port[nav])
            check(label+'_'+nav,diff<1e-12,f'formal {len(port)} dates; first={port[nav].iloc[0]}, last={port[nav].iloc[-1]}, maxdiff={diff}')
        commodity=tr[tr.asset.isin(['SC','FG','I','M','AU','CU'])];other=tr[~tr.asset.isin(['SC','FG','I','M','AU','CU'])]
        costdiff=error(commodity.roll_cost,commodity.turnover*bps/10000)
        check(label+'_commodity_cost',costdiff<1e-12 and error(commodity.trade_return_net,commodity.trade_return_gross-commodity.roll_cost)<1e-12 and commodity.cost_bps.eq(bps).all() and commodity.cost_status.eq('COST_ASSUMPTION_PENDING' if bps==0 else 'MODE_B_EXPERIMENT_ASSUMPTION').all(),f'contract roll formula units bps/10000; maxdiff={costdiff}, unweighted roll cost sum={commodity.roll_cost.sum()}')
        check(label+'_equity_bond_cost_unchanged',same(other,original[~original.asset.isin(['SC','FG','I','M','AU','CU'])],['cost_bps','roll_cost','trade_return_net','trade_return_gross'],['date','asset'])<1e-12,'all noncommodity input columns equal V6 original')
        z=fw.merge(tr,on=['date','asset'],how='left',validate='one_to_one');z=z[z.date.between(port.date.min(),port.date.max())]
        fee=z.asset_class.map({'equity':5,'bond':2,'commodity':bps})/10000
        z['independent_roll']=np.where(z.weight_start_of_day.abs()<1e-14,0,z.weight_start_of_day*z.roll_cost)
        z['independent_gross']=np.where(z.weight_start_of_day.abs()<1e-14,0,z.weight_start_of_day*z.trade_return_gross)
        z['independent_rebalance']=.5*(z.weight_end_of_day-z.weight_start_of_day).abs()*fee
        sums=z.groupby('date')[['independent_gross','independent_roll','independent_rebalance']].sum()
        net=sums.independent_gross-sums.independent_roll-sums.independent_rebalance
        check(label+'_net_pnl',error(net,port.set_index('date').portfolio_return_net)<1e-12 and error(sums.independent_roll,port.set_index('date').contract_roll_cost)<1e-12 and error(sums.independent_rebalance,port.set_index('date').portfolio_rebalance_cost)<1e-12,f'old start-of-day return; close roll and weight fee; roll sum={sums.independent_roll.sum()}, rebalance sum={sums.independent_rebalance.sum()}')
    check('baseline_official_portfolio',same(official,ports['baseline'],[c for c in official if c!='date'],['date'])<1e-12,'all formal portfolio columns including rebased NAV')
    check('baseline_official_weights',same(officialw,weights['baseline'],[c for c in officialw if c not in ['date','asset']],['date','asset'])<1e-12,'all full-history weights identical')
    costweights=weights['commodity_cost_5'];check('cost_weights_and_10vt_unchanged',same(weights['baseline'],costweights,[c for c in costweights if c not in ['date','asset']],['date','asset'])<1e-12,'cost overrides affect net PnL only; VT uses gross history')
    target=weights['target_vol_12'];raw=.12/target.portfolio_vol_estimate;raw=raw.fillna(1);final=raw.clip(.5,1.5)
    check('target12_independent_multiplier',error(raw,target.raw_10vt_multiplier)<1e-12 and error(final,target.final_10vt_multiplier)<1e-12 and error(target.final_weight,target.unscaled_execution_weight*final)<1e-12,'target 12% genuinely propagated to saved final weights')
    pd.DataFrame(rows).to_csv(OUT/'SOL_MODE_B_RECOMPUTE.csv',index=False)
    pd.DataFrame(CHECKS).to_csv(OUT/'SOL_MODE_B_CHECKS.csv',index=False)
    print(json.dumps(CHECKS,indent=2,default=str));assert all(x['status']=='PASS' for x in CHECKS) and all(x['status']=='PASS' for x in rows)

if __name__=='__main__':main()
