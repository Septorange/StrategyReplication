#!/usr/bin/env python3
import asyncio,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from backend.app import app

async def main():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
        paths=[
            '/api/health','/api/v6/summary','/api/v6/day/2024-11-20','/api/v6/momentum/2024-11-20',
            '/api/v6/rolls/2024-11-20','/api/v6/weights/2024-11-20','/api/v6/attribution/2024-11-20',
            '/api/strategy/versions','/api/strategy/V6/decision/2024-11-20/IF','/api/strategy/V6/events?limit=5',
            '/api/strategy/V6/drawdowns?top=5','/api/strategy/V6/attribution?from_date=2024-11-01&to_date=2024-11-20&level=asset',
            '/api/strategy/V6/roll-history/IF?events_only=true','/api/strategy/V6/exposure-series?from_date=2024-01-01',
            '/api/research/lineage','/api/research/data-quality','/'
        ]
        for path in paths:
            r=await c.get(path); assert r.status_code==200,(path,r.status_code,r.text[:300]); print(path,r.status_code)
asyncio.run(main())
