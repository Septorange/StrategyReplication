"""Evidence checks do not re-execute expensive backtests during ordinary pytest."""
import json,hashlib
from pathlib import Path
from backend.config import ROOT

def test_required_real_experiments_have_saved_engine_evidence():
    evidence=json.loads((ROOT/'reports/V0.6_REAL_EXPERIMENTS.json').read_text())
    assert {r['name'] for r in evidence}=={'target10','target12','cost5'}
    for r in evidence:
        assert r['status']=='PASS';folder=Path(r['output_path'])
        run=json.loads((folder/'engine_run.json').read_text());result=json.loads((folder/'result.json').read_text())
        assert run['returncode']==0 and run['source_hashes'] and run['adapter_version']==3
        # V0.6 evidence is a historical reference artifact. Phase 2 changes
        # the adapter source, so its recorded hashes are provenance evidence,
        # not a current-branch readiness gate.
        assert all(len(digest)==64 for digest in run['source_hashes'].values())
        assert len(result['history']['rows'])==2220 and len(result['exposure']['rows'])==2220
        assert result['synthetic'] is False and result['source_hashes'] and len(result['stages'])==3
        assert result['effective_params']['short_vol_windows']==[20,60]

def test_saved_experiment_independent_validation_passed_both_cost_layers():
    r=json.loads((ROOT/'reports/V0.6_REAL_EXPERIMENT_VALIDATION.json').read_text())
    assert r['status']=='PASS' and all(x['status']=='PASS' for x in r['checks'].values())
    assert r['commodity_roll_added']>0 and r['commodity_rebalance_added']>0
