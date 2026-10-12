from __future__ import annotations
import json
from pathlib import Path
import pandas as pd
from .config import SNAPSHOT
class V6Loader:
    def __init__(self,path:Path=SNAPSHOT):
        self.path=path; self.summary=json.loads((path/'summary.json').read_text()); self.snapshot_id=self.summary.get('snapshot_id','V6_FORMAL'); self.rules=json.loads((path/'rules.json').read_text())
        self.portfolio=pd.read_json(path/'daily_portfolio.jsonl.gz',lines=True,compression='gzip'); self.portfolio.date=pd.to_datetime(self.portfolio.date)
        self.assets=pd.read_json(path/'daily_asset_state.jsonl.gz',lines=True,compression='gzip'); self.assets.date=pd.to_datetime(self.assets.date)
        self.rolls=pd.read_json(path/'daily_roll.jsonl.gz',lines=True,compression='gzip'); self.rolls.date=pd.to_datetime(self.rolls.date)
        self.momentum=pd.read_json(path/'monthly_momentum.jsonl.gz',lines=True,compression='gzip'); self.momentum.signal_date=pd.to_datetime(self.momentum.signal_date)
        self.dates=pd.DatetimeIndex(sorted(self.portfolio.date.unique()))
    def resolve(self,date):
        d=pd.Timestamp(date); eligible=self.dates[self.dates<=d]
        if not len(eligible): raise ValueError('requested date precedes snapshot')
        return pd.Timestamp(eligible[-1])
    def resolve_momentum(self,date):
        d=pd.Timestamp(date); dates=pd.DatetimeIndex(sorted(self.momentum.signal_date.unique())); eligible=dates[dates<=d]
        if not len(eligible): raise ValueError('requested date precedes first momentum signal date')
        return pd.Timestamp(eligible[-1])
