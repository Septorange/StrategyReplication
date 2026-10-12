import asyncio,httpx
import backend.app as app_module
from backend.app import app
def get(path):
 async def run():
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:return await c.get(path)
 return asyncio.run(run())
def test_health_reports_real_data_status_without_private_paths():
 r=get('/api/health'); assert r.status_code==200
 body=r.json(); assert body['service_status']=='running'; assert body['active_snapshot_id']=='V6_FORMAL'; assert body['active_data_end_date']=='2024-11-20'; assert body['formal_baseline_available'] is True; assert body['extended_snapshot_available'] is True
 assert '/Users/' not in r.text and 'token' not in r.text.lower()
def test_snapshot_registry_publishes_independently_audited_extension():
 body=get('/api/data/snapshots').json(); assert body['default_snapshot_id']=='V6_FORMAL'
 extended=next(x for x in body['snapshots'] if x['snapshot_id']=='v07_extended_10119bd207b16499')
 assert extended['status']=='PUBLISHED' and extended['selectable'] is True
 assert extended['audit_status']=='WEB_LAYER_AUDITED'
 assert len(extended['audit_report_sha256'])==64
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

def test_concurrent_formal_and_extended_requests_keep_snapshot_scope_isolated():
 async def run():
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
   return await asyncio.gather(
    c.get('/api/v6/summary?snapshot_id=V6_FORMAL'),
    c.get('/api/v6/summary?snapshot_id=v07_extended_10119bd207b16499'),
    c.get('/api/v6/series?snapshot_id=V6_FORMAL'),
    c.get('/api/v6/series?snapshot_id=v07_extended_10119bd207b16499'),
   )
 formal_summary,extended_summary,formal_series,extended_series=asyncio.run(run())
 assert formal_summary.status_code==extended_summary.status_code==200
 assert formal_summary.json()['end_date']=='2024-11-20'
 assert extended_summary.json()['end_date']=='2026-09-24'
 assert formal_series.json()['rows'][-1]['date']=='2024-11-20'
 assert extended_series.json()['rows'][-1]['date']=='2026-09-24'

def test_extended_analytics_exposes_registry_audit_attestation():
 r=get('/api/strategy/V6/analytics/history?snapshot_id=v07_extended_10119bd207b16499&display_window=120')
 assert r.status_code==200
 body=r.json()
 assert body['snapshot_id']=='v07_extended_10119bd207b16499'
 assert body['analytics_audit_status']=='WEB_LAYER_AUDITED'
 assert len(body['audit_report_sha256'])==64

def test_missing_registered_bundle_fails_closed_without_breaking_formal_baseline(monkeypatch,tmp_path):
 entry={
  'snapshot_id':'broken_snapshot','status':'PUBLISHED','selectable':True,
  'path':'data/published_snapshots/broken_snapshot/web',
  'analytics_path':'data/published_snapshots/broken_snapshot/analytics',
  'web_manifest_hash':'missing-web','analytics_manifest_hash':'missing-analytics',
 }
 monkeypatch.setattr(app_module,'ROOT',tmp_path)
 monkeypatch.setattr(app_module,'PUBLISHED_ROOT',tmp_path/'data/published_snapshots')
 monkeypatch.setattr(app_module,'get_snapshot',lambda snapshot_id: entry if snapshot_id=='broken_snapshot' else None)
 formal=get('/api/v6/summary?snapshot_id=V6_FORMAL')
 broken=get('/api/v6/summary?snapshot_id=broken_snapshot')
 assert formal.status_code==200 and formal.json()['end_date']=='2024-11-20'
 assert broken.status_code==503 and broken.json()['detail']['code']=='SNAPSHOT_BUNDLE_UNAVAILABLE'
