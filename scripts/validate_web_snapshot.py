#!/usr/bin/env python3
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; S=ROOT/'data/v6_web'; V6=Path('/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6')
summary=json.loads((S/'summary.json').read_text()); manifest=json.loads((S/'manifest.json').read_text()); p=pd.read_parquet(S/'daily_portfolio.parquet'); a=pd.read_parquet(S/'daily_asset_state.parquet'); r=pd.read_parquet(S/'daily_roll.parquet')
nav=(1+p.portfolio_return_net).cumprod(); ann=nav.iloc[-1]**(252/len(p))-1; vol=p.portfolio_return_net.std(ddof=1)*np.sqrt(252)
checks={'summary_return':abs(ann-summary['annualized_return'])<1e-12,'summary_vol':abs(vol-summary['annualized_vol'])<1e-12,'10vt_mean':abs(p.final_10vt_multiplier.mean()-summary['mean_10vt_multiplier'])<1e-12,'asset_unique':not a.duplicated(['date','asset']).any(),'synthetic_absent':manifest['synthetic_values'] is False,'equity_roll':(r.roll_trigger=='EQUITY_T_MINUS_5').any(),'commodity_roll':(r.roll_trigger=='COMMODITY_FIXED_30D').any(),'bond_liquidity_roll':((r.asset.isin(['TF','T']))&(r.roll_trigger=='LIQUIDITY_ROLL')).any()}
out={'passed':all(checks.values()),'checks':{k:bool(v) for k,v in checks.items()},'rows':{'portfolio':len(p),'assets':len(a),'rolls':len(r)}}; print(json.dumps(out,indent=2)); sys.exit(0 if out['passed'] else 2)
