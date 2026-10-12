import asyncio,httpx
import backend.app as app_module
from backend.app import app
def get(path):
 async def run():
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:return await c.get(path)
 return asyncio.run(run())
def test_health_reports_real_data_status_without_private_paths():
 r=get('/api/health'); assert r.status_code==200
 body=r.json(); assert body['service_status']=='running'; assert body['active_snapshot_id']=='V6_FORMAL'; assert body['active_data_end_date']=='2024-11-20'; assert body['formal_baseline_available'] is True; assert body['extended_snapshot_available'] is False
 assert '/Users/' not in r.text and 'token' not in r.text.lower()
def test_snapshot_registry_keeps_unpublished_extension_unselectable():
 body=get('/api/data/snapshots').json(); assert body['default_snapshot_id']=='V6_FORMAL'
 extended=next(x for x in body['snapshots'] if x['snapshot_id']=='v07_extended_10119bd207b16499')
 assert extended['status']=='LOCAL_UNPUBLISHED' and extended['selectable'] is False
 assert get('/api/data/snapshots/V6_FORMAL/status').status_code==200
 assert get('/api/data/snapshots/unknown/status').status_code==404
def test_health_survives_missing_formal_loader_and_required_api_is_explicit_503(monkeypatch):
 monkeypatch.setattr(app_module,'loader',None)
 assert get('/api/health').json()['service_status']=='degraded'
 r=get('/api/v6/summary'); assert r.status_code==503 and 'FORMAL_DATA_UNAVAILABLE' in r.text
def test_health_is_degraded_when_analytics_manifest_is_invalid(monkeypatch):
 original=app_module._snapshot_file_status
 def invalid_analytics(path):
  result=original(path)
  if path.name=='v6_analytics': return {'available':False,'manifest_valid':False}
  return result
 monkeypatch.setattr(app_module,'_snapshot_file_status',invalid_analytics)
 body=get('/api/health').json()
 assert body['service_status']=='degraded'
 assert body['formal_web']['available'] is True
 assert body['formal_analytics']['available'] is False
 assert body['formal_analytics']['manifest_valid'] is False
def test_required_get_endpoints():
 for x in ['summary','rules','assets']: assert get('/api/v6/'+x).status_code==200
 for x in ['day','momentum','weights','rolls','attribution']: assert get(f'/api/v6/{x}/2024-11-20').status_code==200
def test_nontrading_date_resolves_prior(): assert get('/api/v6/day/2024-11-17').json()['resolved_date']=='2024-11-15'
def test_momentum_before_first_signal_returns_404_without_lookahead():
 r=get('/api/v6/momentum/1900-01-01'); assert r.status_code==404; assert 'precedes first momentum signal' in r.text
def test_synthetic_reference_is_not_served_by_official_app():
 assert get('/').status_code==200
 assert get('/prototype_v0.3.html').status_code==404
