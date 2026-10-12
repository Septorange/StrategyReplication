import asyncio,httpx
from backend.app import app
def get(path):
 async def run():
  async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:return await c.get(path)
 return asyncio.run(run())
def test_health(): assert get('/api/health').json()=={'status':'ok','version':'V6','demo_mode':False,'snapshot':True}
def test_required_get_endpoints():
 for x in ['summary','rules','assets']: assert get('/api/v6/'+x).status_code==200
 for x in ['day','momentum','weights','rolls','attribution']: assert get(f'/api/v6/{x}/2024-11-20').status_code==200
def test_nontrading_date_resolves_prior(): assert get('/api/v6/day/2024-11-17').json()['resolved_date']=='2024-11-15'
def test_momentum_before_first_signal_returns_404_without_lookahead():
 r=get('/api/v6/momentum/1900-01-01'); assert r.status_code==404; assert 'precedes first momentum signal' in r.text
def test_synthetic_reference_is_not_served_by_official_app():
 assert get('/').status_code==200
 assert get('/prototype_v0.3.html').status_code==404
