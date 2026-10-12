import json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; S=ROOT/'data/v6_web'
def test_summary_reconciles():
 s=json.loads((S/'summary.json').read_text()); p=pd.read_json(S/'daily_portfolio.jsonl.gz',lines=True); nav=(1+p.portfolio_return_net).cumprod()
 assert np.isclose(nav.iloc[-1]**(252/len(p))-1,s['annualized_return']); assert np.isclose(p.portfolio_return_net.std(ddof=1)*np.sqrt(252),s['annualized_vol']); assert np.isclose(p.final_10vt_multiplier.mean(),s['mean_10vt_multiplier'])
def test_asset_state_unique_and_real():
 a=pd.read_json(S/'daily_asset_state.jsonl.gz',lines=True); m=json.loads((S/'manifest.json').read_text()); assert not a.duplicated(['date','asset']).any(); assert m['synthetic_values'] is False; assert len(a)==24420
def test_exposures_match_v6_summary():
 s=json.loads((S/'summary.json').read_text()); a=pd.read_json(S/'daily_asset_state.jsonl.gz',lines=True); x=a.groupby(['date','asset_class']).final_weight.sum().unstack().mean()
 assert np.isclose(x.equity,s['avg_equity_exposure']); assert np.isclose(x.bond,s['avg_bond_exposure']); assert np.isclose(x.commodity,s['avg_commodity_exposure'])
