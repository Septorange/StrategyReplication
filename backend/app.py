from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

import hashlib
import json
from pathlib import Path

from .config import FRONTEND, DEMO_MODE, ROOT, SNAPSHOT
from .experiment_runner import ExperimentRunner
from .replay_service import ReplayService
from .research_service import ResearchService
from .schemas import ExperimentRequest
from .analytics_service import AnalyticsService
from .analytics_schemas import (HistoryResponse, PerformanceResponse, WinRateResponse, ClassContributionResponse, AssetContributionResponse, ExposureResponse, DrawdownResponse)
from .parameter_registry import parameter_capabilities
from .utils import records
from .v6_loader import V6Loader

loader = None
replay = None
research = None
experiments = None
analytics = None
runtime_errors = {}
app = FastAPI(title='Strategy Lab Research Workstation', version='0.6.0')


def initialize_services():
    """Load real services when their inputs are available; keep health routable."""
    global loader, replay, research, experiments, analytics, runtime_errors
    runtime_errors = {}
    try:
        loader = V6Loader()
        replay = ReplayService(loader)
        research = ResearchService(loader)
        experiments = ExperimentRunner(loader.summary)
    except Exception as exc:  # health/status must survive a missing or malformed snapshot
        loader = replay = research = experiments = None
        runtime_errors['formal_snapshot'] = type(exc).__name__.upper()
    try:
        analytics = AnalyticsService()
    except Exception as exc:
        analytics = None
        runtime_errors['formal_analytics'] = type(exc).__name__.upper()


initialize_services()


def require_service(service, code='FORMAL_DATA_UNAVAILABLE'):
    if service is None:
        raise HTTPException(status_code=503, detail={'code': code, 'message': 'Required real snapshot data is unavailable.'})
    return service


def _snapshot_file_status(path: Path):
    try:
        manifest = json.loads((path / 'manifest.json').read_text())
        files = manifest.get('files', {})
        hashes = manifest.get('snapshot_hashes', {})
        inventory = files if files else {name: {'sha256': digest} for name,digest in hashes.items()}
        checked = bool(inventory)
        for name, expected in inventory.items():
            candidate = (path / name).resolve()
            if not candidate.is_relative_to(path.resolve()) or not candidate.is_file():
                checked = False
                break
            meta = expected if isinstance(expected, dict) else {'sha256': expected}
            if meta.get('bytes') is not None and candidate.stat().st_size != meta['bytes']:
                checked = False
                break
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if meta.get('sha256') and digest != meta['sha256']:
                checked = False
                break
        return {'available': checked, 'manifest_valid': checked}
    except (OSError, ValueError, TypeError):
        return {'available': False, 'manifest_valid': False}


def _extended_local_status():
    path = ROOT / 'data' / 'v07_local' / 'extended_10119bd207b16499'
    try:
        m = json.loads((path / 'manifest.json').read_text())
        required = [path/'phase2/signal_returns.parquet', path/'phase2/trade_returns.parquet', path/'phase3a/base_target_weights.parquet', path/'phase3b/final_daily_weights.parquet', path/'phase3b/portfolio_daily.parquet']
        present = all(p.is_file() for p in required)
        validation_manifest = (path/'rebuild_manifest.json').is_file()
        return {'available': present, 'status': m.get('status', 'UNKNOWN'), 'snapshot_id': m.get('strategy_snapshot_id'), 'data_end_date': m.get('phase3b_last_date'), 'phase3a_last_signal_date': m.get('phase3a_last_signal_date'), 'manifest_valid': present and validation_manifest, 'validation_manifest_available': validation_manifest, 'web_published': False}
    except (OSError, ValueError, TypeError):
        return {'available': False, 'status': 'NOT_FOUND', 'snapshot_id': None, 'data_end_date': None, 'phase3a_last_signal_date': None, 'manifest_valid': False, 'validation_manifest_available': False, 'web_published': False}


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get('/api/health')
def health():
    formal = _snapshot_file_status(SNAPSHOT)
    ext = _extended_local_status()
    available = loader is not None and analytics is not None and formal['available']
    return {
        'service_status': 'running' if available else 'degraded',
        'status': 'ok' if available else 'degraded',
        'version': 'V6', 'demo_mode': DEMO_MODE,
        'active_snapshot_id': 'V6_FORMAL', 'active_snapshot_status': 'AUDITED_BASELINE' if available else 'UNAVAILABLE',
        'active_data_end_date': loader.summary.get('end_date') if loader is not None else None,
        'formal_baseline_available': bool(formal['available'] and loader is not None),
        'extended_snapshot_available': False,
        'formal_web': formal, 'formal_analytics': {'available': analytics is not None, 'manifest_valid': _snapshot_file_status(ROOT/'data'/'v6_analytics').get('manifest_valid', False)},
        'extended_local': ext,
        'diagnostic_codes': sorted(runtime_errors.values()),
        'snapshot': bool(formal['available'] and loader is not None),
    }


@app.get('/api/data/status')
def data_status():
    state = health()
    return {'service_status': state['service_status'], 'active_snapshot_id': state['active_snapshot_id'], 'active_snapshot_status': state['active_snapshot_status'], 'active_data_end_date': state['active_data_end_date'], 'formal_baseline_available': state['formal_baseline_available'], 'extended_snapshot_available': state['extended_snapshot_available'], 'formal_web': state['formal_web'], 'formal_analytics': state['formal_analytics'], 'extended_local': state['extended_local'], 'diagnostic_codes': state['diagnostic_codes']}


@app.get('/api/data/snapshots')
def snapshots():
    state = health()
    formal_end = state['active_data_end_date']
    local = state['extended_local']
    return {'default_snapshot_id': 'V6_FORMAL', 'snapshots': [
        {'snapshot_id': 'V6_FORMAL', 'display_name': f'正式基准 · 截至 {formal_end or "未知"}', 'status': 'AUDITED_BASELINE' if state['formal_baseline_available'] else 'UNAVAILABLE', 'selectable': bool(state['formal_baseline_available']), 'data_end_date': formal_end, 'audit_status': 'BASELINE_AUDITED'},
        {'snapshot_id': local.get('snapshot_id') or 'V07_EXTENDED', 'display_name': f'扩展数据 · 截至 {local.get("data_end_date") or "未验证"}', 'status': local.get('status', 'NOT_FOUND'), 'selectable': False, 'data_end_date': local.get('data_end_date'), 'phase3a_last_signal_date': local.get('phase3a_last_signal_date'), 'audit_status': 'WEB_LAYER_PENDING_VALIDATION'}
    ]}


@app.get('/api/data/snapshots/{snapshot_id}/status')
def snapshot_status(snapshot_id: str):
    result = next((x for x in snapshots()['snapshots'] if x['snapshot_id'] == snapshot_id), None)
    if result is None:
        raise HTTPException(status_code=404, detail={'code': 'SNAPSHOT_NOT_REGISTERED', 'snapshot_id': snapshot_id})
    return result


# Backward-compatible V6 endpoints.
@app.get('/api/v6/summary')
def summary():
    return require_service(loader).summary


@app.get('/api/v6/rules')
def rules():
    return require_service(loader).rules


@app.get('/api/v6/assets')
def assets():
    return {'assets':sorted(require_service(loader).assets.asset.unique().tolist())}


@app.get('/api/v6/series')
def series(from_date: str|None=None, to_date: str|None=None):
    x = require_service(loader).portfolio
    if from_date:
        x = x[x.date >= from_date]
    if to_date:
        x = x[x.date <= to_date]
    return {'rows':records(x)}


@app.get('/api/v6/day/{date}')
def day(date: str):
    return guard(require_service(replay).day, date)


@app.get('/api/v6/momentum/{date}')
def momentum(date: str):
    return guard(require_service(replay).momentum, date)


@app.get('/api/v6/weights/{date}')
def weights(date: str):
    return guard(require_service(replay).weights, date)


@app.get('/api/v6/rolls/{date}')
def rolls(date: str):
    return guard(require_service(replay).rolls, date)


@app.get('/api/v6/attribution/{date}')
def attribution_day(date: str):
    return guard(require_service(replay).attribution, date)


# V0.5 version-ready research API.
@app.get('/api/strategy/versions')
def strategy_versions():
    return research.versions()


@app.get('/api/strategy/{version}/summary')
def strategy_summary(version: str):
    guard(require_service(research)._require_v6, version)
    return require_service(loader).summary


@app.get('/api/strategy/{version}/rules')
def strategy_rules(version: str):
    guard(require_service(research)._require_v6, version)
    return require_service(loader).rules


@app.get('/api/strategy/{version}/series')
def strategy_series(version: str, from_date: str|None=None, to_date: str|None=None):
    guard(require_service(research)._require_v6, version)
    return series(from_date, to_date)


@app.get('/api/strategy/{version}/exposure-series')
def strategy_exposure_series(version: str, from_date: str|None=None, to_date: str|None=None):
    return guard(require_service(research).exposure_series, version, from_date, to_date)


@app.get('/api/strategy/{version}/day/{date}')
def strategy_day(version: str, date: str):
    guard(require_service(research)._require_v6, version)
    return guard(require_service(replay).day, date)


@app.get('/api/strategy/{version}/decision/{date}/{asset}')
def strategy_decision(version: str, date: str, asset: str):
    return guard(require_service(research).decision, version, date, asset)


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
    return guard(require_service(research).events, version, from_date, to_date, event_group, event_type, asset, limit)


@app.get('/api/strategy/{version}/events/{event_id}')
def strategy_event(version: str, event_id: str):
    return guard(require_service(research).event, version, event_id)


@app.get('/api/strategy/{version}/drawdowns')
def strategy_drawdowns(version: str, top: int=Query(10, ge=1, le=50)):
    guard(require_service(research)._require_v6, version)
    return require_service(research).drawdowns(top)


@app.get('/api/strategy/{version}/attribution')
def strategy_attribution(version: str, from_date: str, to_date: str, level: str='asset'):
    if level not in {'asset','class'}:
        raise HTTPException(422, 'level must be asset or class')
    return guard(require_service(research).attribution, version, from_date, to_date, level)


@app.get('/api/strategy/{version}/roll-history/{asset}')
def strategy_roll_history(version: str, asset: str, from_date: str|None=None, to_date: str|None=None, events_only: bool=False):
    return guard(require_service(research).roll_history, version, asset, from_date, to_date, events_only)


@app.get('/api/research/lineage')
def research_lineage():
    return require_service(research).lineage()


@app.get('/api/research/data-quality')
def research_data_quality():
    return require_service(research).data_quality()


@app.post('/api/experiment')
def experiment(request: ExperimentRequest):
    return require_service(experiments).run(request)



@app.get('/api/experiment/parameters')
def experiment_parameters():
    require_service(loader)
    return parameter_capabilities()

@app.get('/api/strategy/{version}/analytics/history', response_model=HistoryResponse, response_model_exclude_none=False)
def analytics_history(version: str, from_date: str|None=Query(None,alias='from'), to_date: str|None=Query(None,alias='to'), display_window: int=Query(120,ge=2,le=504)):
    guard(require_service(research)._require_v6,version)
    # Return extended metadata too; schema is validated separately in tests.
    return require_service(analytics,'FORMAL_ANALYTICS_UNAVAILABLE').history(from_date,to_date,display_window)

@app.get('/api/strategy/{version}/analytics/performance-by-year',response_model=PerformanceResponse)
def analytics_performance(version: str):
    guard(require_service(research)._require_v6,version)
    return require_service(analytics,'FORMAL_ANALYTICS_UNAVAILABLE').performance_by_year()

@app.get('/api/strategy/{version}/analytics/win-rates',response_model=WinRateResponse)
def analytics_winrates(version: str, overlap: bool=True):
    guard(require_service(research)._require_v6,version)
    return require_service(analytics,'FORMAL_ANALYTICS_UNAVAILABLE').win_rates(overlap)

@app.get('/api/strategy/{version}/analytics/annual-class-contribution',response_model=ClassContributionResponse)
def analytics_classes(version: str):
    guard(require_service(research)._require_v6,version)
    return require_service(analytics,'FORMAL_ANALYTICS_UNAVAILABLE').class_contribution()

@app.get('/api/strategy/{version}/analytics/annual-asset-contribution',response_model=AssetContributionResponse)
def analytics_assets(version: str):
    guard(require_service(research)._require_v6,version)
    return require_service(analytics,'FORMAL_ANALYTICS_UNAVAILABLE').asset_contribution()

@app.get('/api/strategy/{version}/analytics/class-exposure-and-vol',response_model=ExposureResponse)
def analytics_exposure(version: str, display_window: int=Query(120,ge=2,le=504), from_date: str|None=Query(None,alias='from'), to_date: str|None=Query(None,alias='to')):
    guard(require_service(research)._require_v6,version)
    return require_service(analytics,'FORMAL_ANALYTICS_UNAVAILABLE').exposure(display_window,from_date,to_date)

@app.get('/api/strategy/{version}/analytics/top-drawdowns',response_model=DrawdownResponse)
def analytics_drawdowns(version: str, limit: int=Query(5,ge=1,le=50)):
    guard(require_service(research)._require_v6,version)
    return require_service(analytics,'FORMAL_ANALYTICS_UNAVAILABLE').top_drawdowns(limit)

app.mount('/', StaticFiles(directory=FRONTEND, html=True), name='frontend')
