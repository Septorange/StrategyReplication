import pandas as pd
import numpy as np
from backend.experiment_costs import with_commodity_roll_cost

def test_commodity_cost_covers_contract_roll_without_changing_gross_or_baseline():
    original=pd.DataFrame({'asset':['SC','CU','IF'],'turnover':[1.,0.,1.], 'cost_bps':[0.,0.,5.], 'cost_status':['COST_ASSUMPTION_PENDING','COST_ASSUMPTION_PENDING','ASSUMED'], 'roll_cost':[0.,0.,.0005], 'trade_return_gross':[.02,-.01,.01], 'trade_return_net':[.02,-.01,.0095]})
    baseline=with_commodity_roll_cost(original,0)
    pd.testing.assert_frame_equal(original,baseline)
    result=with_commodity_roll_cost(original,5)
    assert result.roll_cost.tolist()==[.0005,0.,.0005]
    assert np.allclose(result.trade_return_net,[.0195,-.01,.0095])
    pd.testing.assert_series_equal(result.trade_return_gross,original.trade_return_gross)
    pd.testing.assert_series_equal(result.iloc[2],original.iloc[2])
    assert original.roll_cost.tolist()==[0.,0.,.0005]
    assert result.cost_status.tolist()==['MODE_B_EXPERIMENT_ASSUMPTION','MODE_B_EXPERIMENT_ASSUMPTION','ASSUMED']
