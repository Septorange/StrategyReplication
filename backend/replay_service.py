from __future__ import annotations
import pandas as pd
from .utils import records
class ReplayService:
    def __init__(self,loader): self.l=loader
    def day(self,date):
        d=self.l.resolve(date); p=self.l.portfolio[self.l.portfolio.date==d]; a=self.l.assets[self.l.assets.date==d]
        return {'requested_date':str(pd.Timestamp(date).date()),'resolved_date':str(d.date()),'portfolio':records(p)[0],'assets':records(a)}
    def momentum(self,date):
        d=self.l.resolve_momentum(date); return {'requested_date':str(pd.Timestamp(date).date()),'resolved_date':str(d.date()),'rows':records(self.l.momentum[self.l.momentum.signal_date==d])}
    def rolls(self,date):
        d=self.l.resolve(date); return {'requested_date':str(pd.Timestamp(date).date()),'resolved_date':str(d.date()),'rows':records(self.l.rolls[self.l.rolls.date==d])}
    def weights(self,date):
        d=self.l.resolve(date); cols=['date','asset','asset_class','monthly_base_target','controlled_target','unscaled_execution_weight','pre10vt_weight','final_10vt_multiplier','final_weight']
        return {'requested_date':str(pd.Timestamp(date).date()),'resolved_date':str(d.date()),'rows':records(self.l.assets.loc[self.l.assets.date==d,[c for c in cols if c in self.l.assets]])}
    def attribution(self,date):
        d=self.l.resolve(date); cols=['date','asset','asset_class','trade_return_gross','trade_return_net','roll_cost','rebalance_cost','asset_contribution']
        return {'requested_date':str(pd.Timestamp(date).date()),'resolved_date':str(d.date()),'rows':records(self.l.assets.loc[self.l.assets.date==d,[c for c in cols if c in self.l.assets]])}
