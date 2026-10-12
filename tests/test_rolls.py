from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; r=pd.read_json(ROOT/'data/v6_web/daily_roll.jsonl.gz',lines=True)
def test_authorized_roll_triggers_present():
 assert (r.roll_trigger=='EQUITY_T_MINUS_5').any(); assert (r.roll_trigger=='COMMODITY_FIXED_30D').any(); assert ((r.asset.isin(['TF','T']))&(r.roll_trigger=='LIQUIDITY_ROLL')).any()
def test_equity_and_commodity_targets_later_maturity():
 x=r[r.roll_trigger.isin(['EQUITY_T_MINUS_5','COMMODITY_FIXED_30D']) & r.roll_from.notna() & r.roll_to.notna()]
 assert len(x)>0; assert (x.roll_from!=x.roll_to).all()
def test_instant_roll_keeps_start_of_day_old_contract():
 x=r[r.roll_from.notna()&r.roll_to.notna()]; assert len(x)>0
 assert (x.held_contract_start_of_day==x.roll_from).all(); assert (x.held_contract_end_of_day==x.roll_to).all()
