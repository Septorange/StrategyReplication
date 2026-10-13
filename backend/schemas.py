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

class SaveExperimentRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    run_id: str
    evaluation_id: str
    name: str=Field(min_length=1,max_length=100)
    notes: str=Field(default='',max_length=2000)
    tags: list[str]=Field(default_factory=list, max_length=12)

class EvaluateExperimentRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    run_id: str
    evaluation_start: str
    evaluation_end: str

class CompareExperimentsRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scheme_a: str
    scheme_b: str
    evaluation_start: str|None=None
    evaluation_end: str|None=None
    confirmation_token: str|None=None

class CompareCheckRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scheme_a: str
    scheme_b: str

class SavedExperimentPatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str|None=Field(default=None,min_length=1,max_length=100)
    notes: str|None=Field(default=None,max_length=2000)
    tags: list[str]|None=Field(default=None,max_length=12)
