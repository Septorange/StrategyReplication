import asyncio
import httpx
import numpy as np
from backend.app import app

async def request(path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        return await c.get(path)

def get(path):
    return asyncio.run(request(path))

def test_version_registry_and_lineage():
    v=get('/api/strategy/versions'); assert v.status_code==200
    rows=v.json()['versions']; assert any(x['version']=='V6' and x['available'] and x['audited'] for x in rows)
    l=get('/api/research/lineage'); assert l.status_code==200 and len(l.json()['fields'])>=22

def test_decision_pipeline_identity():
    r=get('/api/strategy/V6/decision/2024-11-20/IF'); assert r.status_code==200
    x=r.json(); assert x['resolved_date']=='2024-11-20' and x['asset']=='IF'
    for key in ['eligibility','momentum','risk_budget','sleeve_scale','cap','haircut','execution','10vt','final_weight','pnl']:
        assert key in x
    f=x['final_weight']; assert f['identity_error'] is not None and f['identity_error'] < 1e-10

def test_event_and_drawdown_endpoints():
    e=get('/api/strategy/V6/events?event_group=ROLL&limit=20'); assert e.status_code==200
    assert e.json()['rows'] and all(x['event_group']=='ROLL' for x in e.json()['rows'])
    d=get('/api/strategy/V6/drawdowns?top=5'); assert d.status_code==200 and len(d.json()['rows'])==5

def test_attribution_additive_identity():
    r=get('/api/strategy/V6/attribution?from_date=2024-11-01&to_date=2024-11-20&level=asset'); assert r.status_code==200
    p=r.json()['portfolio']; assert abs(p['additive_net_contribution_sum']-p['arithmetic_sum_daily_net_return']) < 1e-8

def test_data_quality_keeps_audited_unverified_status_count():
    r=get('/api/research/data-quality'); assert r.status_code==200
    q=r.json(); assert q['expiry_unverified_count']==312
    assert q['expiry_unverified_by_asset']=={'AU':43,'CU':40,'SC':229}

def test_unconnected_version_is_explicit():
    r=get('/api/strategy/V8/summary'); assert r.status_code==404 and 'not connected' in r.text
