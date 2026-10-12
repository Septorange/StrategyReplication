from typing import Any
from pydantic import BaseModel, ConfigDict, Field
class AnalyticsResponse(BaseModel):
    model_config=ConfigDict(extra="allow")
    strategy_version: str
    formal_window: dict[str,str]
    method_id: str
    data_status: str
    display_vol_window: int
    units: dict[str,str]
    rows: list[dict[str,Any]]
    source_manifest_hash: str

class HistoryRow(BaseModel):
    date: str
    nav_net: float
    nav_gross: float
    portfolio_return_net: float
    total_cost: float
    contract_roll_cost: float
    portfolio_rebalance_cost: float
    final_10vt_multiplier: float
    display_vol: float|None

class PerformanceRow(BaseModel):
    period: str
    year: int|None
    return_value: float=Field(alias="return")
    annualized_return: float
    annualized_vol: float
    sharpe: float|None
    max_drawdown: float
    observations: int
    start: str
    end: str
    partial_year: bool

class WinRateRow(BaseModel):
    horizon: int
    label: str
    up: int
    down: int
    zero: int
    nonfinite: int
    windows: int
    win_rate: float|None
    up_avg: float|None
    down_avg: float|None

class ClassContributionRow(BaseModel):
    year: int
    asset_class: str
    contribution: float|None

class AssetContributionRow(ClassContributionRow):
    asset: str
    status: str

class ExposureRow(BaseModel):
    date: str
    equity: float
    bond: float
    commodity: float
    equity_vol: float|None
    bond_vol: float|None
    commodity_vol: float|None

class DrawdownRow(BaseModel):
    episode_id: str
    peak_date: str
    trough_date: str
    recovery_date: str|None
    max_drawdown: float
    drawdown_days: int
    recovery_days: int|None

class HistoryResponse(AnalyticsResponse):
    rows: list[HistoryRow]
class PerformanceResponse(AnalyticsResponse):
    rows: list[PerformanceRow]
class WinRateResponse(AnalyticsResponse):
    rows: list[WinRateRow]
class ClassContributionResponse(AnalyticsResponse):
    rows: list[ClassContributionRow]
class AssetContributionResponse(AnalyticsResponse):
    rows: list[AssetContributionRow]
class ExposureResponse(AnalyticsResponse):
    rows: list[ExposureRow]
class DrawdownResponse(AnalyticsResponse):
    rows: list[DrawdownRow]
