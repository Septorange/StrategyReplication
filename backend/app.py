from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from .config import FRONTEND, DEMO_MODE
from .experiment_runner import ExperimentRunner
from .replay_service import ReplayService
from .research_service import ResearchService
from .schemas import ExperimentRequest
from .analytics_service import AnalyticsService
from .analytics_schemas import (HistoryResponse, PerformanceResponse, WinRateResponse, ClassContributionResponse, AssetContributionResponse, ExposureResponse, DrawdownResponse)
from .parameter_registry import parameter_capabilities
from .utils import records
from .v6_loader import V6Loader

loader = V6Loader()
replay = ReplayService(loader)
research = ResearchService(loader)
experiments = ExperimentRunner(loader.summary)
analytics = AnalyticsService()
app = FastAPI(title='Strategy Lab Research Workstation', version='0.6.0')


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get('/api/health')
def health():
    return {'status':'ok','version':'V6','demo_mode':DEMO_MODE,'snapshot':True}


# Backward-compatible V6 endpoints.
@app.get('/api/v6/summary')
def summary():
    return loader.summary


@app.get('/api/v6/rules')
def rules():
    return loader.rules


@app.get('/api/v6/assets')
def assets():
    return {'assets':sorted(loader.assets.asset.unique().tolist())}


@app.get('/api/v6/series')
def series(from_date: str|None=None, to_date: str|None=None):
    x = loader.portfolio
    if from_date:
        x = x[x.date >= from_date]
    if to_date:
        x = x[x.date <= to_date]
    return {'rows':records(x)}


@app.get('/api/v6/day/{date}')
def day(date: str):
    return guard(replay.day, date)


@app.get('/api/v6/momentum/{date}')
def momentum(date: str):
    return guard(replay.momentum, date)


@app.get('/api/v6/weights/{date}')
def weights(date: str):
    return guard(replay.weights, date)


@app.get('/api/v6/rolls/{date}')
def rolls(date: str):
    return guard(replay.rolls, date)


@app.get('/api/v6/attribution/{date}')
def attribution_day(date: str):
    return guard(replay.attribution, date)


# V0.5 version-ready research API.
@app.get('/api/strategy/versions')
def strategy_versions():
    return research.versions()


@app.get('/api/strategy/{version}/summary')
def strategy_summary(version: str):
    guard(research._require_v6, version)
    return loader.summary


@app.get('/api/strategy/{version}/rules')
def strategy_rules(version: str):
    guard(research._require_v6, version)
    return loader.rules


@app.get('/api/strategy/{version}/series')
def strategy_series(version: str, from_date: str|None=None, to_date: str|None=None):
    guard(research._require_v6, version)
    return series(from_date, to_date)


@app.get('/api/strategy/{version}/exposure-series')
def strategy_exposure_series(version: str, from_date: str|None=None, to_date: str|None=None):
    return guard(research.exposure_series, version, from_date, to_date)


@app.get('/api/strategy/{version}/day/{date}')
def strategy_day(version: str, date: str):
    guard(research._require_v6, version)
    return guard(replay.day, date)


@app.get('/api/strategy/{version}/decision/{date}/{asset}')
def strategy_decision(version: str, date: str, asset: str):
    return guard(research.decision, version, date, asset)


@app.get('/api/strategy/{version}/events')
def strategy_events(
    version: str,
    from_date: str|None=None,
    to_date: str|None=None,
    event_group: str|None=None,
    event_type: str|None=None,
    asset: str|None=None,
    limit: int=Query(500, ge=1, le=5000),
):
    return guard(research.events, version, from_date, to_date, event_group, event_type, asset, limit)


@app.get('/api/strategy/{version}/events/{event_id}')
def strategy_event(version: str, event_id: str):
    return guard(research.event, version, event_id)


@app.get('/api/strategy/{version}/drawdowns')
def strategy_drawdowns(version: str, top: int=Query(10, ge=1, le=50)):
    guard(research._require_v6, version)
    return research.drawdowns(top)


@app.get('/api/strategy/{version}/attribution')
def strategy_attribution(version: str, from_date: str, to_date: str, level: str='asset'):
    if level not in {'asset','class'}:
        raise HTTPException(422, 'level must be asset or class')
    return guard(research.attribution, version, from_date, to_date, level)


@app.get('/api/strategy/{version}/roll-history/{asset}')
def strategy_roll_history(version: str, asset: str, from_date: str|None=None, to_date: str|None=None, events_only: bool=False):
    return guard(research.roll_history, version, asset, from_date, to_date, events_only)


@app.get('/api/research/lineage')
def research_lineage():
    return research.lineage()


@app.get('/api/research/data-quality')
def research_data_quality():
    return research.data_quality()


@app.post('/api/experiment')
def experiment(request: ExperimentRequest):
    return experiments.run(request)



@app.get('/api/experiment/parameters')
def experiment_parameters():
    return parameter_capabilities()

@app.get('/api/strategy/{version}/analytics/history', response_model=HistoryResponse, response_model_exclude_none=False)
def analytics_history(version: str, from_date: str|None=Query(None,alias='from'), to_date: str|None=Query(None,alias='to'), display_window: int=Query(120,ge=2,le=504)):
    guard(research._require_v6,version)
    # Return extended metadata too; schema is validated separately in tests.
    return analytics.history(from_date,to_date,display_window)

@app.get('/api/strategy/{version}/analytics/performance-by-year',response_model=PerformanceResponse)
def analytics_performance(version: str):
    guard(research._require_v6,version)
    return analytics.performance_by_year()

@app.get('/api/strategy/{version}/analytics/win-rates',response_model=WinRateResponse)
def analytics_winrates(version: str, overlap: bool=True):
    guard(research._require_v6,version)
    return analytics.win_rates(overlap)

@app.get('/api/strategy/{version}/analytics/annual-class-contribution',response_model=ClassContributionResponse)
def analytics_classes(version: str):
    guard(research._require_v6,version)
    return analytics.class_contribution()

@app.get('/api/strategy/{version}/analytics/annual-asset-contribution',response_model=AssetContributionResponse)
def analytics_assets(version: str):
    guard(research._require_v6,version)
    return analytics.asset_contribution()

@app.get('/api/strategy/{version}/analytics/class-exposure-and-vol',response_model=ExposureResponse)
def analytics_exposure(version: str, display_window: int=Query(120,ge=2,le=504), from_date: str|None=Query(None,alias='from'), to_date: str|None=Query(None,alias='to')):
    guard(research._require_v6,version)
    return analytics.exposure(display_window,from_date,to_date)

@app.get('/api/strategy/{version}/analytics/top-drawdowns',response_model=DrawdownResponse)
def analytics_drawdowns(version: str, limit: int=Query(5,ge=1,le=50)):
    guard(research._require_v6,version)
    return analytics.top_drawdowns(limit)

app.mount('/', StaticFiles(directory=FRONTEND, html=True), name='frontend')
