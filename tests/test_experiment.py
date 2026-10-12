from backend.schemas import ExperimentRequest
from backend.experiment_runner import ExperimentRunner
def test_unsupported_momentum_is_disabled_without_source_edit():
 b={'annualized_return':0,'annualized_vol':0,'sharpe':0,'max_drawdown':0,'start_date':'2015-09-30','end_date':'2024-11-20'}
 assert ExperimentRunner(b).run(ExperimentRequest(momentum_excluded_count=2))['status']=='DISABLED'
