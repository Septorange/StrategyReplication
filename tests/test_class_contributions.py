import pandas as pd
import pytest

from backend.app import aggregate_class_contributions


def test_class_contributions_close_and_swap_and_year_boundary():
    weights = pd.DataFrame([
        ('2025-12-31', 'IF', 'Equity'), ('2025-12-31', 'IC', 'Equity'),
        ('2025-12-31', 'T', 'Bond'), ('2026-01-05', 'IF', 'Equity'),
    ], columns=['date', 'asset', 'asset_class'])
    a = {('2025-12-31', 'IF'): .01, ('2025-12-31', 'IC'): -.003,
         ('2025-12-31', 'T'): .002, ('2026-01-05', 'IF'): -.004}
    b = {key: value * 1.2 for key, value in a.items()}
    daily, annual, missing = aggregate_class_contributions(a, b, weights, weights)
    assert missing == 0
    assert sum(x['scheme_a_contribution'] for x in daily) == pytest.approx(sum(a.values()))
    assert sum(x['scheme_b_contribution'] for x in annual) == pytest.approx(sum(b.values()))
    assert next(x for x in annual if x['year'] == '2025' and x['asset_class'] == 'Equity')['scheme_a_contribution'] == pytest.approx(.007)
    reverse, _, _ = aggregate_class_contributions(b, a, weights, weights)
    for row, swapped in zip(daily, reverse):
        assert row['contribution_delta'] == pytest.approx(-swapped['contribution_delta'])


def test_missing_or_ambiguous_class_is_unavailable_not_guessed():
    values = {('2026-01-05', 'IF'): .01}
    empty = pd.DataFrame(columns=['date', 'asset'])
    assert aggregate_class_contributions(values, values, empty, empty) == ([], [], 2)
    ambiguous = pd.DataFrame([('2026-01-05', 'IF', 'Equity'),
                              ('2026-01-05', 'IF', 'Commodity')],
                             columns=['date', 'asset', 'asset_class'])
    assert aggregate_class_contributions(values, values, ambiguous, ambiguous) == ([], [], 2)


def test_compare_reads_turnover_and_classes_from_real_stage(monkeypatch):
    import importlib
    api = importlib.import_module('backend.app')
    from backend.schemas import CompareExperimentsRequest
    saved = {'scheme_id':'a','name':'A','run_id':'run','evaluation_id':'eval',
             'snapshot_id':'same','config':{},'artifact_path':'/tmp/class-test',
             'from_date':'2025-12-31','to_date':'2026-01-05'}
    monkeypatch.setattr(api.experiment_library, 'get_saved', lambda name: {**saved, 'scheme_id':name})
    monkeypatch.setattr(api, '_compatibility', lambda a,b: {'status':'COMPARABLE'})
    days = ['2025-12-31','2026-01-05']
    history = [{'date':day,'portfolio_return_net':.01,'portfolio_rebalance_cost':0.0} for day in days]
    monkeypatch.setattr(api, 'resolve_artifact', lambda *args: {'history':{'rows':history}})
    def read(path, columns):
        if path.name == 'daily_portfolio.parquet':
            return {'date':days,'turnover':[.12,.34]}
        if path.name == 'final_daily_weights.parquet':
            return {'date':days,'asset':['IF','IF'],'final_weight':[1.,1.], 'asset_class':['Equity','Equity']}
        return {'date':days,'asset':['IF','IF'],'trade_return_net':[.01,.01]}
    monkeypatch.setattr(api, '_read_parquet_columns', read)
    result = api.compare_saved_experiments(CompareExperimentsRequest(scheme_a='a',scheme_b='b'))
    assert [x['scheme_a_turnover'] for x in result['history']] == [.12,.34]
    assert result['class_contribution_status'] == 'AVAILABLE'
    assert len(result['class_return_contributions']) == 2
    assert len(result['class_annual_contributions']) == 2
    assert sum(x['scheme_a_contribution'] for x in result['class_return_contributions']) == pytest.approx(.02)
