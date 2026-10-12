from pydantic import BaseModel, Field, ConfigDict
class ExperimentRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target_vol: float=Field(0.10,gt=0,le=.50)
    vt_window: int=Field(120)
    haircut: float=Field(.50,ge=0,le=1)
    quantile: float=Field(.90,gt=0,lt=1)
    midmonth_threshold: float=Field(.20,ge=0,le=5)
    commodity_cost_bps: float=Field(0,ge=0,le=10)
    momentum_excluded_count: int|None=None
    risk_budget_vol_window: int|None=None
    asset_short_vol_window: int|None=None
    short_vol_windows: list[int]|None=None
    asset_long_vol_window: int|None=None
    quantile_lookback: int|None=None
