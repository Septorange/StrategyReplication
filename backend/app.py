from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextvars import ContextVar
from datetime import date
import uuid
import pandas as pd

import hashlib
import json
import math
import re
from pathlib import Path

from .config import FRONTEND, DEMO_MODE, ROOT, SNAPSHOT
from .experiment_runner import ExperimentRunner
from .replay_service import ReplayService
from .research_service import ResearchService
from .schemas import (ExperimentRequest, SaveExperimentRequest, EvaluateExperimentRequest,
                      CompareExperimentsRequest, CompareCheckRequest, SavedExperimentPatch)
from .experiment_library import ExperimentLibrary, resolve_artifact
from .experiment_runner import validate_cache_artifact
from .analytics_service import performance, drawdown_episodes
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
experiment_library = ExperimentLibrary()


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

def _safe_source_id(raw: str, index: int) -> str:
    """Expose a stable non-path source label in public JSON."""
    name=Path(str(raw)).name
    return name if name and name not in ('.','..') else f'source_{index}'

def _clean_json(value):
    if isinstance(value,float) and not math.isfinite(value): return None
    if isinstance(value,str): return _safe_error_message(value)
    if isinstance(value,dict): return {_safe_error_message(k):_clean_json(v) for k,v in value.items()}
    if isinstance(value,list): return [_clean_json(v) for v in value]
    return value

def _safe_error_message(value: object) -> str:
    """Keep diagnostics useful without returning server filesystem paths."""
    text=str(value)
    return re.sub(r'/(?:Users|private|home)/[^\s\"\'<>]+', '[redacted-path]', text)

def _public_result(result: dict, *, evaluation: dict|None=None) -> dict:
    """Strip server paths and reduce internal stage provenance to safe IDs."""
    out=_clean_json(json.loads(json.dumps(result, ensure_ascii=False, default=str)))
    for key in ('artifact_path','output_path','request_path','input_path','cwd'):
        out.pop(key,None)
    hashes=out.get('source_hashes')
    if isinstance(hashes,dict):
        out['source_hashes']=[{'source_id':_safe_source_id(k,i),'sha256':v} for i,(k,v) in enumerate(sorted(hashes.items()))]
    stages=out.get('stages')
    if isinstance(stages,list):
        for stage in stages:
            if isinstance(stage,dict):
                if 'artifact' in stage: stage['artifact']=Path(str(stage['artifact'])).name
                if isinstance(stage.get('artifacts'),list): stage['artifacts']=[Path(str(x)).name for x in stage['artifacts']]
    if evaluation is not None:
        out['evaluation']=evaluation
    return out

def _public_saved(item: dict) -> dict:
    out={k:v for k,v in item.items() if k not in ('artifact_path',)}
    return out

def _compatibility(a: dict, b: dict) -> dict:
    reasons=[]
    if a.get('snapshot_id') != b.get('snapshot_id'):
        reasons.append('不同数据快照，基础输入和合约映射未经逐项证明，不可直接归因于参数。')
        return {'status':'NOT_COMPARABLE','reasons':reasons,'warnings':reasons,
                'snapshot_a':a.get('snapshot_id'),'snapshot_b':b.get('snapshot_id')}
    if a.get('status') != 'PASS' or b.get('status') != 'PASS':
        reasons.append('至少一个保存方案不是完整认证产物。')
        return {'status':'NOT_COMPARABLE','reasons':reasons,'warnings':[]}
    return {'status':'COMPARABLE','reasons':[],'warnings':[],
            'snapshot_id':a.get('snapshot_id'),'engine_semantics':'V6_PHASE3B_ADAPTER_V4'}


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
    active_id=selected_snapshot.get()
    active_loader=require_service(loader)
    try:
        result=require_service(experiments).run(request,snapshot_id=active_id,baseline=active_loader.summary)
    except (OSError,ValueError,KeyError,RuntimeError) as exc:
        failed_id=f'run_failed_{uuid.uuid4().hex}'
        try:
            experiment_library.add_run(config_hash=f'failed_{uuid.uuid4().hex}',snapshot_id=active_id,
                status='FAILED',config=request.model_dump(),artifact_path=ROOT/'experiment_cache'/'.failed',run_id=failed_id)
        except Exception:
            pass
        raise HTTPException(422,detail={'code':'EXPERIMENT_INPUT_UNAVAILABLE','message':_safe_error_message(exc),'run_id':failed_id})
    if result.get('status')!='PASS':
        if result.get('status')=='FAIL':
            failed_hash=result.get('config_hash') or hashlib.sha256(json.dumps(result.get('config',request.model_dump()),sort_keys=True).encode()).hexdigest()
            failed_id=f'run_failed_{uuid.uuid4().hex}'
            try:
                experiment_library.add_run(config_hash=failed_hash,snapshot_id=active_id,status='FAILED',
                    config=result.get('config',request.model_dump()),artifact_path=ROOT/'experiment_cache'/'.failed',run_id=failed_id)
            except Exception:
                pass
            result['run_id']=failed_id
        return _public_result(result)
    identity_sha256=result.get('identity_sha256')
    if not isinstance(identity_sha256,str) or len(identity_sha256)!=64:
        raise HTTPException(500,detail={'code':'EXPERIMENT_IDENTITY_MISSING','message':'Real run lacks a full SHA-256 identity.'})
    run_id=f'run_{identity_sha256}'
    history=pd.DataFrame(result.get('history',{}).get('rows',[]))
    if history.empty or not {'date','portfolio_return_net'}.issubset(history.columns):
        raise HTTPException(500,detail={'code':'EXPERIMENT_HISTORY_MISSING','message':'Python experiment completed without daily return history.'})
    history['date']=pd.to_datetime(history.date)
    start,end=history.date.min().date().isoformat(),history.date.max().date().isoformat()
    evaluation_digest=hashlib.sha256(f'{identity_sha256}:{start}:{end}'.encode()).hexdigest()
    evaluation_id=f'eval_{evaluation_digest}'
    evaluation={'from_date':start,'to_date':end,'available_from':start,'available_to':end,
                'metrics':result['experiment'],'snapshot_id':active_id}
    experiment_library.add_run(config_hash=result['config_hash'],snapshot_id=active_id,status='PASS',
        config=result['config'],artifact_path=Path(result['artifact_path']),run_id=run_id)
    experiment_library.add_evaluation(run_id=run_id,snapshot_id=active_id,from_date=start,to_date=end,
        metrics=result['experiment'],evaluation_id=evaluation_id)
    result.update(run_id=run_id,evaluation_id=evaluation_id,evaluation=evaluation)
    return _public_result(result)


def _run_artifact(run_id: str):
    run=experiment_library.get_run(run_id)
    if not run:
        raise HTTPException(404,detail={'code':'EXPERIMENT_RUN_NOT_FOUND','run_id':run_id})
    saved={**run,'artifact_path':run['artifact_path']}
    try:
        return run,resolve_artifact(experiment_library,saved)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        raise HTTPException(409,detail={'code':'EXPERIMENT_ARTIFACT_UNAVAILABLE','message':_safe_error_message(exc),'run_id':run_id})


def _evaluate_result(result: dict, from_date: str, to_date: str):
    frame=pd.DataFrame(result.get('history',{}).get('rows',[]))
    if frame.empty:
        raise HTTPException(409,detail={'code':'EXPERIMENT_HISTORY_MISSING'})
    frame['date']=pd.to_datetime(frame.date).dt.strftime('%Y-%m-%d')
    available=set(frame.date)
    if from_date not in available or to_date not in available:
        raise HTTPException(422,detail={'code':'EVALUATION_BOUNDARY_NOT_VERIFIED_TRADING_DATE',
            'available_from':min(available),'latest_verified_date':max(available),
            'from_date':from_date,'to_date':to_date})
    if from_date>to_date or to_date>max(available):
        raise HTTPException(422,detail={'code':'EVALUATION_OUTSIDE_VERIFIED_RANGE',
            'available_from':min(available),'latest_verified_date':max(available)})
    selected=frame[frame.date.between(from_date,to_date)].sort_values('date')
    if selected.empty:
        raise HTTPException(422,detail={'code':'EVALUATION_WINDOW_EMPTY','from_date':from_date,'to_date':to_date})
    metrics=performance(selected.portfolio_return_net)
    selected=selected.copy()
    if 'nav_net' in selected:
        selected['nav_net']=(1.0+selected.portfolio_return_net.astype(float)).cumprod()
    if 'nav_gross' in selected:
        first_gross=float(selected.nav_gross.iloc[0])
        if math.isfinite(first_gross) and first_gross != 0:
            selected['nav_gross']=selected.nav_gross.astype(float)/first_gross
    exposure=pd.DataFrame(result.get('exposure',{}).get('rows',[]))
    if not exposure.empty:
        exposure['date']=pd.to_datetime(exposure.date).dt.strftime('%Y-%m-%d')
        exposure=exposure[exposure.date.isin(selected.date)]
        for col in ('equity','bond','commodity'):
            if col in exposure:
                metrics['avg_'+col+'_exposure']=float(exposure[col].mean())
    for col in ('total_cost','contract_roll_cost','portfolio_rebalance_cost'):
        if col in selected:
            metrics[col]=float(selected[col].fillna(0).sum())
    selected_drawdowns=drawdown_episodes(selected[['date','nav_net']].copy()) if 'nav_net' in selected else pd.DataFrame()
    costs={col:float(selected[col].fillna(0).sum()) for col in ('total_cost','contract_roll_cost','portfolio_rebalance_cost') if col in selected}
    return {'from_date':selected.date.min(),'to_date':selected.date.max(),'metrics':metrics,
            'rows':selected.to_dict('records'),
            'exposure':{'rows':exposure.to_dict('records')},
            'drawdowns':{'rows':selected_drawdowns.to_dict('records')},
            'costs':costs}


@app.post('/api/experiment/evaluations')
def evaluate_experiment(request: EvaluateExperimentRequest):
    run,result=_run_artifact(request.run_id)
    try:
        start=date.fromisoformat(request.evaluation_start).isoformat(); end=date.fromisoformat(request.evaluation_end).isoformat()
    except ValueError:
        raise HTTPException(422,detail={'code':'INVALID_EVALUATION_DATE'})
    if start>end:
        raise HTTPException(422,detail={'code':'INVALID_EVALUATION_RANGE'})
    evaluation=_evaluate_result(result,start,end)
    evaluation_id=f'eval_{uuid.uuid4().hex}'
    experiment_library.add_evaluation(run_id=request.run_id,snapshot_id=run['snapshot_id'],
        from_date=evaluation['from_date'],to_date=evaluation['to_date'],metrics=evaluation['metrics'],evaluation_id=evaluation_id)
    return {'evaluation_id':evaluation_id,'run_id':request.run_id,'snapshot_id':run['snapshot_id'],
            'latest_verified_date':max(str(x['date'])[:10] for x in result['history']['rows']),**evaluation}


@app.post('/api/experiment/saved')
def save_experiment(request: SaveExperimentRequest):
    run=experiment_library.get_run(request.run_id)
    if not run:
        raise HTTPException(404,detail={'code':'EXPERIMENT_RUN_NOT_FOUND','run_id':request.run_id})
    if not _run_artifact(request.run_id):
        raise HTTPException(409,detail={'code':'EXPERIMENT_ARTIFACT_UNAVAILABLE'})
    with experiment_library._connect() as db:
        evaluation=db.execute('SELECT * FROM experiment_evaluations WHERE evaluation_id=? AND run_id=?',
                              (request.evaluation_id,request.run_id)).fetchone()
    if not evaluation:
        raise HTTPException(404,detail={'code':'EXPERIMENT_EVALUATION_NOT_FOUND','evaluation_id':request.evaluation_id})
    return experiment_library.save(run_id=request.run_id,evaluation_id=request.evaluation_id,
                                   name=request.name,notes=request.notes,tags=request.tags)


@app.get('/api/experiment/saved')
def list_saved_experiments(snapshot_id: str|None = Query(None)):
    rows=experiment_library.list_saved()
    if snapshot_id:
        rows=[x for x in rows if x.get('snapshot_id')==snapshot_id]
    return {'saved':[_public_saved(x) for x in rows]}

@app.get('/api/experiments')
def list_experiments(q: str|None=None, tag: str|None=None, snapshot_id: str|None=None, status: str|None=None,
                     page: int=Query(1,ge=1), page_size: int=Query(50,ge=1,le=200)):
    rows=experiment_library.list_saved()
    if q: rows=[x for x in rows if q.lower() in (x.get('name','')+' '+x.get('notes','')+' '+' '.join(x.get('tags',[]))).lower()]
    if tag: rows=[x for x in rows if tag in x.get('tags',[])]
    if snapshot_id: rows=[x for x in rows if x.get('snapshot_id')==snapshot_id]
    if status: rows=[x for x in rows if x.get('status')==status]
    total=len(rows); start=(page-1)*page_size
    return {'items':[_public_saved(x) for x in rows[start:start+page_size]],'page':page,'page_size':page_size,'total':total}

@app.get('/api/experiments/runs/{run_id}')
def get_experiment_run(run_id: str):
    run=experiment_library.get_run(run_id)
    if not run: raise HTTPException(404,detail={'code':'EXPERIMENT_RUN_NOT_FOUND','run_id':run_id})
    try:
        if run.get('status')=='PASS':
            validate_cache_artifact(Path(run['artifact_path']),run['config_hash'],run['snapshot_id'])
    except Exception as exc:
        run['status']='CACHE_INVALID'; run['error_code']='ARTIFACT_UNAVAILABLE'; run['error_summary']=_safe_error_message(exc)[:300]
    run.pop('artifact_path',None)
    return run

@app.get('/api/experiments/runs/{run_id}/series')
def get_experiment_series(run_id: str):
    run,result=_run_artifact(run_id)
    return {'run_id':run_id,'snapshot_id':run['snapshot_id'],'history':result.get('history',{}),
            'exposure':result.get('exposure',{}),'costs':result.get('costs',{})}


@app.get('/api/experiment/saved/{scheme_id}')
def open_saved_experiment(scheme_id: str, snapshot_id: str|None = Query(None)):
    saved=experiment_library.get_saved(scheme_id)
    if not saved:
        raise HTTPException(404,detail={'code':'SAVED_SCHEME_NOT_FOUND','scheme_id':scheme_id})
    if snapshot_id and saved.get('snapshot_id')!=snapshot_id:
        raise HTTPException(409,detail={'code':'SAVED_SCHEME_SNAPSHOT_MISMATCH','scheme_snapshot_id':saved.get('snapshot_id'),'requested_snapshot_id':snapshot_id})
    try:
        result=resolve_artifact(experiment_library,saved)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        raise HTTPException(409,detail={'code':'SAVED_SCHEME_ARTIFACT_UNAVAILABLE','message':_safe_error_message(exc)})
    rows=result.get('history',{}).get('rows',[])
    available_from=min((str(x['date'])[:10] for x in rows),default=saved['from_date'])
    available_to=max((str(x['date'])[:10] for x in rows),default=saved['to_date'])
    evaluation=_evaluate_result(result,saved['from_date'],saved['to_date'])
    # The saved evaluation is the default view. Keep the full trajectory only
    # behind an explicit, clearly named field for diagnostics.
    full_history=result.get('history',{})
    result['run_full_history']=full_history
    result['history']={'rows':evaluation['rows']}
    result['exposure']=evaluation['exposure']
    result['drawdowns']=evaluation['drawdowns']
    result['costs']=evaluation['costs']
    result['experiment']=evaluation['metrics']
    result.update(run_id=saved['run_id'],evaluation_id=saved['evaluation_id'],
                  evaluation={'from_date':saved['from_date'],'to_date':saved['to_date'],
                              'available_from':available_from,'available_to':available_to,
                              'metrics':evaluation['metrics'],'observations':len(evaluation['rows'])})
    return {'saved':_public_saved(saved),'result':_public_result(result)}

@app.patch('/api/experiments/saved/{scheme_id}')
def patch_saved_experiment(scheme_id: str, request: SavedExperimentPatch):
    if not experiment_library.get_saved(scheme_id): raise HTTPException(404,detail={'code':'SAVED_SCHEME_NOT_FOUND','scheme_id':scheme_id})
    tags=request.tags
    if tags is not None and any(not isinstance(x,str) or len(x)>40 for x in tags):
        raise HTTPException(422,detail={'code':'INVALID_TAGS'})
    item=experiment_library.update_saved(scheme_id,name=request.name,notes=request.notes,tags=tags)
    return {'saved':_public_saved(item)}

@app.delete('/api/experiments/saved/{scheme_id}')
def delete_saved_experiment(scheme_id: str):
    if not experiment_library.delete_saved(scheme_id): raise HTTPException(404,detail={'code':'SAVED_SCHEME_NOT_FOUND','scheme_id':scheme_id})
    return {'deleted':True,'scheme_id':scheme_id}

@app.post('/api/experiment/compare/check')
def check_saved_comparison(request: CompareCheckRequest):
    a,b=experiment_library.get_saved(request.scheme_a),experiment_library.get_saved(request.scheme_b)
    if not a or not b: raise HTTPException(404,detail={'code':'SAVED_SCHEME_NOT_FOUND'})
    try: resolve_artifact(experiment_library,a); resolve_artifact(experiment_library,b)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        return {'status':'NOT_COMPARABLE','reasons':[_safe_error_message(exc)],'warnings':[]}
    return _compatibility(a,b)


@app.post('/api/experiment/compare')
def compare_saved_experiments(request: CompareExperimentsRequest):
    a,b=experiment_library.get_saved(request.scheme_a),experiment_library.get_saved(request.scheme_b)
    if not a or not b:
        raise HTTPException(404,detail={'code':'SAVED_SCHEME_NOT_FOUND','scheme_ids':[request.scheme_a,request.scheme_b]})
    compatibility=_compatibility(a,b)
    if compatibility['status']!='COMPARABLE':
        raise HTTPException(409,detail={**compatibility,'code':'NOT_COMPARABLE'})
    try:
        ra,rb=resolve_artifact(experiment_library,a),resolve_artifact(experiment_library,b)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        raise HTTPException(409,detail={'code':'SAVED_SCHEME_ARTIFACT_UNAVAILABLE','message':_safe_error_message(exc)})
    fa=pd.DataFrame(ra['history']['rows']); fb=pd.DataFrame(rb['history']['rows'])
    for frame in (fa,fb): frame['date']=pd.to_datetime(frame.date).dt.strftime('%Y-%m-%d')
    dates=sorted(set(fa.date).intersection(fb.date))
    if not dates:
        raise HTTPException(422,detail={'code':'NO_COMMON_OBSERVATIONS'})
    # Saved evaluations are explicit research windows. Never compare the
    # full cached trajectory merely because the underlying runs overlap.
    start=max(dates[0], a['from_date'], b['from_date'], request.evaluation_start or dates[0])
    end=min(dates[-1], a['to_date'], b['to_date'], request.evaluation_end or dates[-1])
    if start not in dates or end not in dates:
        raise HTTPException(422,detail={'code':'COMPARISON_BOUNDARY_NOT_COMMON_VERIFIED_DATE',
            'common_from':dates[0],'common_latest_verified_date':dates[-1],
            'from_date':start,'to_date':end})
    if start>end:
        raise HTTPException(422,detail={'code':'NO_COMMON_INTERVAL','common_from':dates[0],'common_to':dates[-1]})
    dates=[d for d in dates if start<=d<=end]
    fa=fa[fa.date.isin(dates)].sort_values('date').reset_index(drop=True)
    fb=fb[fb.date.isin(dates)].sort_values('date').reset_index(drop=True)
    ma,mb=performance(fa.portfolio_return_net),performance(fb.portfolio_return_net)
    for metrics,frame in ((ma,fa),(mb,fb)):
        for col in ('total_cost','contract_roll_cost','portfolio_rebalance_cost'):
            if col in frame: metrics[col]=float(frame[col].fillna(0).sum())
    for metrics,source in ((ma,ra.get('exposure',{}).get('rows',[])),(mb,rb.get('exposure',{}).get('rows',[]))):
        exposure=pd.DataFrame(source)
        if not exposure.empty and 'date' in exposure:
            exposure['date']=pd.to_datetime(exposure.date).dt.strftime('%Y-%m-%d')
            exposure=exposure[exposure.date.isin(dates)]
            for col in ('equity','bond','commodity'):
                if col in exposure: metrics['avg_'+col+'_exposure']=float(exposure[col].mean())
    paired=[]
    ea={str(x.get('date'))[:10]:x for x in ra.get('exposure',{}).get('rows',[])}
    eb={str(x.get('date'))[:10]:x for x in rb.get('exposure',{}).get('rows',[])}
    for left,right in zip(fa.to_dict('records'),fb.to_dict('records')):
        idx=len(paired); day=left['date']; xa,xb=ea.get(day,{}),eb.get(day,{})
        paired.append({'date':day,'scheme_a_nav':float((1+fa.portfolio_return_net).cumprod().iloc[idx]),
                       'scheme_b_nav':float((1+fb.portfolio_return_net).cumprod().iloc[len(paired)]),
                       'scheme_a_return':float(left['portfolio_return_net']),'scheme_b_return':float(right['portfolio_return_net']),
                       'return_delta':float(right['portfolio_return_net']-left['portfolio_return_net']),
                       'scheme_a_10vt':left.get('final_10vt_multiplier'),'scheme_b_10vt':right.get('final_10vt_multiplier'),
                       'scheme_a_equity':xa.get('equity'),'scheme_b_equity':xb.get('equity'),
                       'scheme_a_bond':xa.get('bond'),'scheme_b_bond':xb.get('bond'),
                       'scheme_a_commodity':xa.get('commodity'),'scheme_b_commodity':xb.get('commodity'),
                       'scheme_a_turnover':left.get('turnover'),'scheme_b_turnover':right.get('turnover'),
                       'scheme_a_total_cost':left.get('total_cost'),'scheme_b_total_cost':right.get('total_cost'),
                       'scheme_a_roll_cost':left.get('contract_roll_cost'),'scheme_b_roll_cost':right.get('contract_roll_cost'),
                       'scheme_a_rebalance_cost':left.get('portfolio_rebalance_cost'),'scheme_b_rebalance_cost':right.get('portfolio_rebalance_cost')})
    top=sorted(paired,key=lambda x:abs(x.get('return_delta') or 0),reverse=True)[:20]
    return {'scheme_a':{'scheme_id':a['scheme_id'],'name':a['name'],'run_id':a['run_id'],'evaluation_id':a['evaluation_id'],'snapshot_id':a['snapshot_id'],'config':a['config'],'metrics':ma},
            'scheme_b':{'scheme_id':b['scheme_id'],'name':b['name'],'run_id':b['run_id'],'evaluation_id':b['evaluation_id'],'snapshot_id':b['snapshot_id'],'config':b['config'],'metrics':mb},
            'common_interval':{'from_date':dates[0],'to_date':dates[-1],'observations':len(dates)},'history':paired,
            'top_changed_days':top,'comparison_status':'REAL_EXPERIMENTS_COMMON_WINDOW'}



@app.get('/api/experiment/parameters')
def experiment_parameters():
    require_service(loader)
    caps=parameter_capabilities()
    caps.pop('engine',None)
    caps['engine_id']='V6_PHASE3B_FROZEN_ADAPTER_V4'
    return caps

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
