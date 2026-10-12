"""Frozen V6 rule boundary fixtures; no fixture enters formal runtime data."""
import importlib.util,sys
import pandas as pd
from backend.config import V6_BASE

def module(name):
    spec=importlib.util.spec_from_file_location(name,V6_BASE/'src'/f'{name}.py')
    result=importlib.util.module_from_spec(spec)
    previous=sys.dont_write_bytecode;sys.dont_write_bytecode=True
    try:spec.loader.exec_module(result)
    finally:sys.dont_write_bytecode=previous
    return result

def quotes(asset, dates, contracts):
    rows=[]
    for d in dates:
        for code,oi,expiry,maturity in contracts:
            rows.append(dict(asset=asset,date=d,thscode=code,openInterest=oi,volume=10,maturity_key=maturity,is_eligible=True,expiry_date=pd.Timestamp(expiry),expiry_source='TEST_FIXTURE',requires_requery=False))
    return pd.DataFrame(rows)

def active(asset, dates, held):
    return pd.DataFrame([dict(asset=asset,date=d,candidate_contract=held,confirmed_active_contract=held,switch_confirmed=False,requires_requery=False) for d in dates])

def test_equity_exact_t5_chooses_nearest_later_not_highest_oi():
    dates=pd.bdate_range('2024-01-01',periods=7)
    q=quotes('IF',dates,[('IF2401.CFE',100,'2024-01-09',202401),('IF2403.CFE',20,'2024-03-15',202403),('IF2406.CFE',80,'2024-06-21',202406)])
    a=active('IF',dates,'IF2406.CFE');a.switch_confirmed=True
    r=module('roll_engine').build_roll_calendar(a,q)
    assert r.iloc[0].days_to_expiry==6 and r.iloc[0].roll_trigger=='NO_ROLL'
    assert r.iloc[1].days_to_expiry==5 and r.iloc[1].roll_trigger=='EQUITY_T_MINUS_5'
    assert r.iloc[1].roll_to=='IF2403.CFE'
    assert r.iloc[1].held_contract_start_of_day=='IF2401.CFE'
    assert r.iloc[2].held_contract_start_of_day=='IF2403.CFE'

def test_commodity_exact_calendar_30day_boundary_and_oi_target():
    dates=pd.DatetimeIndex(['2024-01-01','2024-01-02'])
    q=quotes('CU',dates,[('CU2402.SHF',100,'2024-02-15',202402),('CU2403.SHF',20,'2024-03-15',202403),('CU2404.SHF',80,'2024-04-15',202404)])
    r=module('roll_engine').build_roll_calendar(active('CU',dates,'CU2402.SHF'),q)
    assert r.iloc[0].roll_trigger=='NO_ROLL'
    assert r.iloc[1].roll_trigger=='COMMODITY_FIXED_30D'
    assert r.iloc[1].roll_to=='CU2404.SHF'

def test_bond_hard_and_forced_data_roll_branches():
    dates=pd.bdate_range('2024-01-01',periods=7)
    q=quotes('T',dates,[('T2401.CFE',100,'2024-01-09',202401),('T2406.CFE',80,'2024-06-21',202406)])
    r=module('roll_engine').build_roll_calendar(active('T',dates,'T2401.CFE'),q)
    assert r.iloc[1].roll_trigger=='HARD_ROLL' and r.iloc[1].roll_to=='T2406.CFE'
    two=dates[:2];q=quotes('T',two,[('T2403.CFE',100,'2024-03-15',202403),('T2406.CFE',80,'2024-06-21',202406)])
    q.loc[(q.date==two[1])&(q.thscode=='T2403.CFE'),'is_eligible']=False
    r=module('roll_engine').build_roll_calendar(active('T',two,'T2403.CFE'),q)
    assert r.iloc[1].roll_trigger=='FORCED_DATA_ROLL' and r.iloc[1].roll_to=='T2406.CFE'

def test_bond_liquidity_confirmation_allows_earlier_maturity():
    dates=pd.bdate_range('2024-01-01',periods=3)
    q=quotes('TF',dates,[('TF2406.CFE',100,'2024-06-21',202406),('TF2403.CFE',80,'2024-03-15',202403)])
    q.loc[(q.date>dates[0])&(q.thscode=='TF2403.CFE'),'openInterest']=200
    a=module('active_contract').build_active_calendar(q,confirmation_days=2)
    assert not a.iloc[1].switch_confirmed and a.iloc[2].switch_confirmed
    r=module('roll_engine').build_roll_calendar(a,q)
    assert r.iloc[1].roll_trigger=='NO_ROLL'
    assert r.iloc[2].roll_trigger=='LIQUIDITY_ROLL' and r.iloc[2].roll_to=='TF2403.CFE'
