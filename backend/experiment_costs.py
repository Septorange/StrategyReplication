"""Cost overrides on an experiment-only copy of V6 Phase 2 trade returns."""
COMMODITIES = {'SC', 'FG', 'I', 'M', 'AU', 'CU'}

def with_commodity_roll_cost(trade, bps):
    result = trade.copy(deep=True)
    selected = result.asset.isin(COMMODITIES)
    # Exact V6 src/trade_returns.py formula. Turnover is close-time contract
    # replacement; gross return still comes from the start-of-day old holding.
    result.loc[selected, 'cost_bps'] = float(bps)
    if 'cost_status' in result:
        result.loc[selected, 'cost_status'] = 'COST_ASSUMPTION_PENDING' if float(bps) == 0 else 'MODE_B_EXPERIMENT_ASSUMPTION'
    result.loc[selected, 'roll_cost'] = result.loc[selected, 'turnover'] * float(bps) / 10000
    result.loc[selected, 'trade_return_net'] = result.loc[selected, 'trade_return_gross'] - result.loc[selected, 'roll_cost']
    return result
