from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextvars import ContextVar

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
from .snapshot_registry import FORMAL_ID, get_snapshot, snapshot_entries, PUBLISHED_ROOT


class SnapshotAnalyticsService(AnalyticsService):
    """Add bundle lineage to API responses without altering frozen analytics calculations."""
    def response(self, rows, method, units, **extra):
        result=super().response(rows,method,units,**extra)
        snapshot_id=self.manifest.get('snapshot_id',FORMAL_ID)
        result['snapshot_id']=snapshot_id
        result['data_status']=self.manifest.get('data_status',result['data_status'])
        entry=get_snapshot(snapshot_id) if snapshot_id!=FORMAL_ID else None
        result['analytics_audit_status']=(entry or {}).get('audit_status',self.manifest.get('analytics_status',result['analytics_audit_status']))
        if entry and entry.get('audit_report_sha256'):
            result['audit_report_sha256']=entry['audit_report_sha256']
        return result

formal_services = {}
services_cache = {}
services_by_snapshot = {}
runtime_errors = {}
app = FastAPI(title='Strategy Lab Research Workstation', version='0.6.0')
selected_snapshot = ContextVar('selected_snapshot', default=FORMAL_ID)


class ContextService:
    """Resolve an API service from the request's immutable snapshot scope."""
    def __init__(self,name): self.name=name
    def target(self): return services_by_snapshot.get(selected_snapshot.get(),formal_services).get(self.name)
    def __getattr__(self,name):
        target=self.target()
        if target is None: raise AttributeError(name)
        return getattr(target,name)


loader=ContextService('loader'); replay=ContextService('replay'); research=ContextService('research'); experiments=ContextService('experiments'); analytics=ContextService('analytics')


def initialize_services():
    """Load real services when their inputs are available; keep health routable."""
    global runtime_errors
    runtime_errors = {}
    current={}
    try:
        current['loader'] = V6Loader()
        current['replay'] = ReplayService(current['loader'])
        current['research'] = ResearchService(current['loader'])
        current['experiments'] = ExperimentRunner(current['loader'].summary)
    except Exception as exc:  # health/status must survive a missing or malformed snapshot
        runtime_errors['formal_snapshot'] = type(exc).__name__.upper()
    try:
        current['analytics'] = SnapshotAnalyticsService()
    except Exception as exc:
        runtime_errors['formal_analytics'] = type(exc).__name__.upper()
    formal_services.clear(); formal_services.update(current)
    services_cache.clear(); services_by_snapshot.clear(); services_by_snapshot[FORMAL_ID]=formal_services


def load_snapshot_services(snapshot_id):
    entry=get_snapshot(snapshot_id)
    if not entry: return None
    web=(ROOT/entry.get('path','')).resolve(); analytics_path=(ROOT/entry.get('analytics_path','')).resolve()
    if not web.is_relative_to(PUBLISHED_ROOT.resolve()) or not analytics_path.is_relative_to(PUBLISHED_ROOT.resolve()): return None
    try:
        web_hash=hashlib.sha256((web/'manifest.json').read_bytes()).hexdigest(); analytics_hash=hashlib.sha256((analytics_path/'manifest.json').read_bytes()).hexdigest()
    except OSError: return None
    if web_hash!=entry.get('web_manifest_hash') or analytics_hash!=entry.get('analytics_manifest_hash'): return None
    try:
        web_manifest=json.loads((web/'manifest.json').read_text()); analytics_manifest=json.loads((analytics_path/'manifest.json').read_text())
    except (OSError,ValueError,TypeError): return None
    if analytics_manifest.get('source_web_manifest_sha256')!=web_hash or web_manifest.get('snapshot_id')!=snapshot_id or analytics_manifest.get('snapshot_id')!=snapshot_id: return None
    cache_key=(snapshot_id,web_hash,analytics_hash)
    if cache_key in services_cache:
        services_by_snapshot[snapshot_id]=services_cache[cache_key]
        return services_cache[cache_key]
    if not _snapshot_file_status(web).get('manifest_valid') or not _snapshot_file_status(analytics_path).get('manifest_valid'): return None
    try:
        l=V6Loader(web); a=SnapshotAnalyticsService(analytics_path)
        if l.snapshot_id!=snapshot_id or a.manifest.get('snapshot_id')!=snapshot_id or not _web_schema_valid(l) or not _analytics_schema_valid(analytics_path): return None
        loaded={'loader':l,'replay':ReplayService(l),'research':ResearchService(l),'analytics':a,'experiments':formal_services.get('experiments')}
        services_cache[cache_key]=loaded; services_by_snapshot[snapshot_id]=loaded
        return loaded
    except Exception:
        return None


@app.middleware('http')
async def snapshot_scope(request: Request, call_next):
    snapshot_id=request.query_params.get('snapshot_id',FORMAL_ID)
    if request.url.path.startswith('/api/experiment'):
        snapshot_id=FORMAL_ID
    if snapshot_id!=FORMAL_ID and not get_snapshot(snapshot_id):
        return JSONResponse(status_code=404,content={'detail':{'code':'SNAPSHOT_NOT_REGISTERED','snapshot_id':snapshot_id}})
    token=selected_snapshot.set(snapshot_id)
    try:
        if snapshot_id!=FORMAL_ID and load_snapshot_services(snapshot_id) is None:
            return JSONResponse(status_code=503,content={'detail':{'code':'SNAPSHOT_BUNDLE_UNAVAILABLE','snapshot_id':snapshot_id}})
        return await call_next(request)
    finally:
        selected_snapshot.reset(token)


initialize_services()


def require_service(service, code='FORMAL_DATA_UNAVAILABLE'):
    if isinstance(service,ContextService): service=service.target()
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
        entry=get_snapshot(m.get('strategy_snapshot_id'))
        return {'available': present, 'status': m.get('status', 'UNKNOWN'), 'snapshot_id': m.get('strategy_snapshot_id'), 'data_end_date': m.get('phase3b_last_date'), 'phase3a_last_signal_date': m.get('phase3a_last_signal_date'), 'manifest_valid': present and validation_manifest, 'validation_manifest_available': validation_manifest, 'web_published': bool(entry)}
    except (OSError, ValueError, TypeError):
        return {'available': False, 'status': 'NOT_FOUND', 'snapshot_id': None, 'data_end_date': None, 'phase3a_last_signal_date': None, 'manifest_valid': False, 'validation_manifest_available': False, 'web_published': False}


def _web_schema_valid(service):
    if service is None:
        return False
    schemas = {
        'portfolio': {'date','nav_net','nav_gross','portfolio_return_net','final_10vt_multiplier'},
        'assets': {'date','asset','asset_class','weight_start_of_day','final_weight','trade_return_net','asset_contribution'},
        'rolls': {'date','asset'},
        'momentum': {'signal_date','asset'},
    }
    return all(required.issubset(set(getattr(service, name).columns)) for name,required in schemas.items())


def _analytics_schema_valid(path: Path):
    schemas = {
        'portfolio_history': {'date','nav_net','nav_gross','portfolio_return_net'},
        'annual_performance': {'period','annualized_return','max_drawdown'},
        'annual_class_contribution': {'year','asset_class','contribution'},
        'annual_asset_contribution': {'year','asset','asset_class','contribution','status'},
        'class_exposure_and_vol120': {'date','equity','bond','commodity'},
        'daily_class_contribution': {'date','equity','bond','commodity'},
        'drawdown_episodes': {'episode_id','max_drawdown'},
    }
    try:
        for name,required in schemas.items():
            rows=json.loads((path/f'{name}.json').read_text())
            if not isinstance(rows,list) or (rows and not required.issubset(set(rows[0]))):
                return False
        return True
    except (OSError,ValueError,TypeError):
        return False


def guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get('/api/health')
def health():
    active_id=selected_snapshot.get()
    formal = _snapshot_file_status(SNAPSHOT)
    formal_analytics_manifest = _snapshot_file_status(ROOT/'data'/'v6_analytics')
    formal_loader=formal_services.get('loader') if loader is not None else None
    formal['schema_valid'] = _web_schema_valid(formal_loader)
    formal['available'] = bool(formal['manifest_valid'] and formal['schema_valid'])
    formal_analytics_manifest['schema_valid'] = _analytics_schema_valid(ROOT/'data'/'v6_analytics')
    formal_analytics_manifest['available'] = bool(formal_analytics_manifest['manifest_valid'] and formal_analytics_manifest['schema_valid'] and formal_services.get('analytics') is not None)
    ext = _extended_local_status()
    active=services_by_snapshot.get(active_id,formal_services)
    active_entry=get_snapshot(active_id) or {}
    active_available=bool((formal['available'] and formal_analytics_manifest['available']) if active_id==FORMAL_ID else (active.get('loader') and active.get('analytics')))
    return {
        'service_status': 'running' if active_available else 'degraded',
        'status': 'ok' if active_available else 'degraded',
        'version': 'V6', 'demo_mode': DEMO_MODE,
        'active_snapshot_id': active_id, 'active_snapshot_status': active_entry.get('status','AUDITED_BASELINE' if formal['available'] else 'UNAVAILABLE'),
        'active_data_end_date': active['loader'].summary.get('end_date') if active.get('loader') else None,
        'formal_baseline_available': bool(formal['available'] and formal_loader is not None),
        'extended_snapshot_available': bool(ext.get('web_published')),
        'formal_web': formal, 'formal_analytics': formal_analytics_manifest,
        'extended_local': ext,
        'diagnostic_codes': sorted(runtime_errors.values()),
        'snapshot': active_available,
    }


@app.get('/api/data/status')
def data_status():
    state = health()
    return {'service_status': state['service_status'], 'active_snapshot_id': state['active_snapshot_id'], 'active_snapshot_status': state['active_snapshot_status'], 'active_data_end_date': state['active_data_end_date'], 'formal_baseline_available': state['formal_baseline_available'], 'extended_snapshot_available': state['extended_snapshot_available'], 'formal_web': state['formal_web'], 'formal_analytics': state['formal_analytics'], 'extended_local': state['extended_local'], 'diagnostic_codes': state['diagnostic_codes']}


@app.get('/api/data/snapshots')
def snapshots():
    state = health()
    formal_loader=formal_services.get('loader')
    formal_end=formal_loader.summary.get('end_date') if formal_loader else None
    local = state['extended_local']
    registered=[{'snapshot_id':e.get('snapshot_id'),'display_name':e.get('display_name'),'status':e.get('status'),'selectable':e.get('selectable') is True,'data_end_date':e.get('data_end_date'),'phase3a_last_signal_date':e.get('last_signal_date'),'audit_status':e.get('audit_status'),'audit_report_sha256':e.get('audit_report_sha256')} for e in snapshot_entries()]
    return {'default_snapshot_id': 'V6_FORMAL', 'snapshots': [
        {'snapshot_id': 'V6_FORMAL', 'display_name': f'正式基准 · 截至 {formal_end or "未知"}', 'status': 'AUDITED_BASELINE' if state['formal_baseline_available'] else 'UNAVAILABLE', 'selectable': bool(state['formal_baseline_available']), 'data_end_date': formal_end, 'audit_status': 'BASELINE_AUDITED'},
        *registered,
        *([] if any(x.get('snapshot_id')==local.get('snapshot_id') for x in registered) else [{'snapshot_id': local.get('snapshot_id') or 'V07_EXTENDED', 'display_name': f'扩展数据 · {local.get("data_end_date") or "未验证"}', 'status': local.get('status', 'NOT_FOUND'), 'selectable': False, 'data_end_date': local.get('data_end_date'), 'phase3a_last_signal_date': local.get('phase3a_last_signal_date'), 'audit_status': 'WEB_LAYER_PENDING_VALIDATION'}])
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
