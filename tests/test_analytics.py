import asyncio,json,math
import httpx
import numpy as np
import pandas as pd
import pytest
from backend.analytics_service import AnalyticsService,drawdown_episodes,performance
from backend.analytics_schemas import AnalyticsResponse
from backend.config import ROOT,SNAPSHOT
from backend.parameter_registry import parameter_capabilities,unsupported
from backend.schemas import ExperimentRequest

s=AnalyticsService()

def test_metrics_reconcile_official_at_full_precision():
    p=s.table('portfolio_history');m=performance(p.portfolio_return_net);official=json.loads((SNAPSHOT/'summary.json').read_text())
    for k in ('annualized_return','annualized_vol','sharpe','max_drawdown'):assert abs(m[k]-official[k])<1e-10
    assert len(p)==official['observations']==2220
    assert np.allclose((1+p.portfolio_return_net).cumprod(),p.nav_net,atol=1e-12,rtol=0)


def test_history_display_vol_has_no_early_fill_or_strategy_window_conflation():
    p=s.table('portfolio_history');expected=p.portfolio_return_net.rolling(120).std(ddof=1)*math.sqrt(252)
    assert p.display_vol.iloc[:119].isna().all();assert p.display_vol.iloc[119:].notna().all()
    np.testing.assert_allclose(p.display_vol,expected,atol=1e-12,rtol=0,equal_nan=True)
    narrow=s.history('2020-01-01','2020-02-01')['rows']
    assert narrow[0]['display_vol'] is not None # filter follows full-window rolling calculation


def test_calendar_year_compounding_partial_and_highwater_1():
    p=s.table('portfolio_history');table=s.table('annual_performance')
    for row in table.iloc[1:].to_dict('records'):
        r=p[p.date.dt.year==int(row['year'])].portfolio_return_net
        assert abs(row['return']-((1+r).prod()-1))<1e-12
        nav=(1+r).cumprod();mdd=(nav/np.maximum.accumulate(np.r_[1.,nav])[1:]-1).min()
        assert abs(row['max_drawdown']-mdd)<1e-12
    assert table.iloc[1].partial_year and table.iloc[-1].partial_year
    assert performance(pd.Series([-.1,.05]))['max_drawdown']==pytest.approx(-.1)


def test_winrate_horizon_counts_and_independent_nav_ratio():
    nav=s.table('portfolio_history').nav_net.to_numpy()
    for row in s.win_rates()['rows']:
        h=row['horizon'];r=nav[h:]/nav[:-h]-1
        assert row['windows']==2220-h
        assert sum(row[k] for k in ('up','down','zero','nonfinite'))==len(r)
        assert row['up']==int((r>0).sum()) and row['down']==int((r<0).sum())
        assert row['win_rate']==pytest.approx((r>0).sum()/((r>0).sum()+(r<0).sum()))
        if row['down']==0:assert row['down_avg'] is None
    assert s.win_rates(False)['method_id']!=s.win_rates(True)['method_id']


def test_annual_assets_classes_same_contribution_identity_and_eligibility():
    assets=s.table('annual_asset_contribution');cls=s.table('annual_class_contribution')
    sums=assets.groupby(['year','asset_class']).contribution.sum().sort_index()
    expected=cls.set_index(['year','asset_class']).contribution.sort_index()
    np.testing.assert_allclose(sums,expected,atol=1e-12,rtol=0)
    pre=assets[(assets.asset=='IM')&(assets.year<2022)]
    assert pre.contribution.isna().all();assert set(pre.status)=={'NOT_LISTED_OR_NOT_ELIGIBLE'}


def test_start_of_day_exposure_and_contribution_vol_reconciliation():
    x=s.table('class_exposure_and_vol120');c=s.table('daily_class_contribution');official=json.loads((SNAPSHOT/'summary.json').read_text())
    for cls in ('equity','bond','commodity'):
        assert abs(x[cls].mean()-official['avg_'+cls+'_exposure'])<1e-10
        expected=c[cls].rolling(120).std(ddof=1)*math.sqrt(252)
        np.testing.assert_allclose(x[cls+'_vol'],expected,atol=1e-12,rtol=0,equal_nan=True)
    assert x.bond.max()>1


def test_drawdown_top5_order_dates_null_and_tied_nav_recovery():
    p=s.table('portfolio_history');x=s.table('drawdown_episodes')
    assert x.max_drawdown.is_monotonic_increasing
    assert x.iloc[0].max_drawdown==pytest.approx(-.11919211296483712,abs=1e-12)
    date_index={d:i for i,d in enumerate(p.date)}
    for row in x.to_dict('records'):
        assert row['peak_date']<=row['trough_date'];assert row['drawdown_days']==date_index[row['trough_date']]-date_index[row['peak_date']]
        if pd.notna(row['recovery_date']):
            assert row['recovery_date']>row['trough_date'];assert row['recovery_days']==date_index[row['recovery_date']]-date_index[row['trough_date']]
        else:assert pd.isna(row['recovery_days'])
    toy=pd.DataFrame({'date':pd.date_range('2020-01-01',periods=5),'nav_net':[1.,.8,1.,1.2,.9]})
    d=drawdown_episodes(toy)
    assert len(d)==2 and pd.isna(d.iloc[0].recovery_date)
    assert d.iloc[1].recovery_date==toy.date.iloc[2]


def test_locked_parameters_rejected_and_no_unknown_fields():
    registry=parameter_capabilities();assert [x['number'] for x in registry['original']]==list(range(1,8))
    assert [x['status'] for x in registry['original']]==['DISABLED']*4+['READY']*3
    assert registry['original'][2]['key']=='short_vol_windows' and registry['original'][2]['baseline']==[20,60]
    for key,value in [('momentum_excluded_count',2),('risk_budget_vol_window',120),('asset_short_vol_window',60),('short_vol_windows',[20]),('asset_long_vol_window',120),('quantile_lookback',756)]:
        assert key in unsupported(ExperimentRequest(**{key:value}).model_dump())
    assert unsupported(ExperimentRequest(risk_budget_vol_window=240,short_vol_windows=[20,60],asset_long_vol_window=240).model_dump()) is None
    with pytest.raises(Exception):ExperimentRequest(asset_universe=['IF'])


def test_analytics_endpoints_schema_null_json_and_version_guard():
    from backend.app import app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
            for path in ['history','performance-by-year','win-rates','annual-class-contribution','annual-asset-contribution','class-exposure-and-vol','top-drawdowns']:
                r=await c.get('/api/strategy/V6/analytics/'+path);assert r.status_code==200
                AnalyticsResponse.model_validate(r.json());assert 'NaN' not in r.text and 'Infinity' not in r.text
            assert (await c.get('/api/strategy/V2/analytics/history')).status_code==404
            assert (await c.get('/api/strategy/V6/analytics/class-exposure-and-vol?display_window=1')).status_code==422
            assert (await c.post('/api/experiment',json={'risk_budget_vol_window':120})).json()['status']=='DISABLED'
            assert (await c.post('/api/experiment',json={'asset_universe':['IF']})).status_code==422
    asyncio.run(run())


def test_experiment_negative_first_return_includes_initial_highwater():
    import runpy
    adapter=runpy.run_path(str(ROOT/'scripts/run_v6_experiment.py'))
    portfolio=pd.DataFrame({'portfolio_return_net':[-.1,.05], 'final_10vt_multiplier':[.5,.6]})
    metric=adapter['compute_experiment_metrics'](portfolio)
    assert metric['max_drawdown']==pytest.approx(-.1)
    assert metric['annualized_return']==pytest.approx(((.9*1.05)**126)-1)
    assert metric['observations']==2
