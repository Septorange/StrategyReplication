import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config import ROOT
from backend.experiment_library import ExperimentLibrary, resolve_artifact
from backend.experiment_runner import ExperimentRunner


def test_run_evaluation_and_saved_scheme_survive_library_reopen(tmp_path):
    db_path = tmp_path / 'library.sqlite3'
    library = ExperimentLibrary(db_path)
    run_id = library.add_run(config_hash='abc123', snapshot_id='extended_test', status='PASS',
                             config={'target_vol': 0.12, 'commodity_cost_bps': 5},
                             artifact_path=tmp_path / 'cache' / 'abc123')
    evaluation_id = library.add_evaluation(run_id=run_id, snapshot_id='extended_test',
        from_date='2015-09-30', to_date='2026-09-24', metrics={'annualized_return': 0.1})
    saved = library.save(run_id=run_id, evaluation_id=evaluation_id, name='Extended 12% + 5bps')

    reopened = ExperimentLibrary(db_path)
    item = reopened.get_saved(saved['scheme_id'])
    assert item['run_id'] == run_id
    assert item['evaluation_id'] == evaluation_id
    assert item['snapshot_id'] == 'extended_test'
    assert item['config'] == {'target_vol': 0.12, 'commodity_cost_bps': 5}
    assert item['metrics'] == {'annualized_return': 0.1}
    assert reopened.list_saved()[0]['scheme_id'] == saved['scheme_id']


def test_duplicate_identities_are_idempotent_but_conflicting_rows_fail(tmp_path):
    library = ExperimentLibrary(tmp_path / 'library.sqlite3')
    artifact = tmp_path / 'cache' / 'id'
    run_id = 'run_' + 'a' * 64
    kwargs = dict(config_hash='a' * 64, snapshot_id='V6_FORMAL', status='PASS',
                  config={'target_vol': 0.12}, artifact_path=artifact, run_id=run_id)
    assert library.add_run(**kwargs) == run_id
    assert library.add_run(**kwargs) == run_id
    with pytest.raises(ValueError, match='identity collision'):
        library.add_run(**{**kwargs, 'config': {'target_vol': 0.10}})
    evaluation_id = 'eval_' + 'b' * 64
    evaluation = dict(run_id=run_id, snapshot_id='V6_FORMAL', from_date='2020-01-02',
                      to_date='2020-12-31', metrics={'annualized_return': 0.1}, evaluation_id=evaluation_id)
    assert library.add_evaluation(**evaluation) == evaluation_id
    assert library.add_evaluation(**evaluation) == evaluation_id
    with pytest.raises(ValueError, match='identity collision'):
        library.add_evaluation(**{**evaluation, 'to_date': '2020-12-30'})
    with pytest.raises(Exception):
        library.add_evaluation(**{**evaluation, 'run_id': 'missing_run', 'evaluation_id': 'eval_missing'})


def test_saved_artifact_must_match_sqlite_identity_and_cache_alias(tmp_path):
    config = {'target_vol': 0.12, 'commodity_cost_bps': 5}
    baseline = {'start_date': '2015-09-30', 'end_date': '2024-11-20'}
    source_hashes = {'phase3b.py': 'c' * 64}
    identity_payload = {'config': config, 'snapshot_id': 'V6_FORMAL', 'source_hashes': source_hashes,
                        'baseline': baseline, 'adapter_version': 4}
    identity = hashlib.sha256(json.dumps(identity_payload, sort_keys=True).encode()).hexdigest()
    artifact = ROOT / 'experiment_cache' / identity[:16]
    artifact.mkdir(parents=True, exist_ok=True)
    try:
        result = {'status': 'PASS', 'synthetic': False, 'config': config, 'baseline': baseline,
                  'source_hashes': source_hashes, 'snapshot_id': 'V6_FORMAL', 'config_hash': identity,
                  'identity_sha256': identity, 'cache_key': identity[:16], 'adapter_version': 4}
        result_path=artifact / 'result.json'
        result_path.write_text(json.dumps(result))
        (artifact/'artifact_manifest.json').write_text(json.dumps({
            'identity_sha256':identity,'config_hash':identity,'snapshot_id':'V6_FORMAL',
            'cache_key':identity[:16],'adapter_version':4,
            'result_sha256':hashlib.sha256(result_path.read_bytes()).hexdigest()}))
            for name in ('daily_portfolio.parquet','single_asset_vol_control.parquet',
                         'final_daily_weights.parquet','events.parquet',
                         'experiment_trade_returns.parquet','engine_run.json'):
                (artifact/name).touch()
        library = ExperimentLibrary(tmp_path / 'library.sqlite3')
        run_id = library.add_run(run_id=f'run_{identity}',config_hash=identity, snapshot_id='V6_FORMAL', status='PASS',
                                 config=config, artifact_path=artifact)
        opened = resolve_artifact(library, library.get_run(run_id))
        assert opened['identity_sha256'] == identity
        # Rewriting plausible content while preserving all identity fields is
        # still detected because the result bytes are covered by the manifest.
        result_path.write_text(json.dumps({**result, 'annualized_return': 0.99}))
        with pytest.raises(ValueError, match='manifest'):
            resolve_artifact(library, library.get_run(run_id))
        result_path.write_text(json.dumps({**result, 'snapshot_id': 'other_snapshot'}))
        with pytest.raises(ValueError, match='snapshot'):
            resolve_artifact(library, library.get_run(run_id))
    finally:
        shutil.rmtree(artifact, ignore_errors=True)


def test_same_run_is_locked_and_atomically_published_once(tmp_path, monkeypatch):
    import backend.experiment_runner as runner_module

    cache = tmp_path / 'experiment_cache'
    monkeypatch.setattr(runner_module, 'CACHE', cache)
    calls = []

    def fake_subprocess_run(command, **kwargs):
        request = json.loads(Path(command[-2]).read_text())
        output = Path(command[-1])
        calls.append(request['identity_sha256'])
        (output / 'result.json').write_text(json.dumps({
            'status': 'PASS', 'synthetic': False, 'config': request['config'],
            'baseline': request['baseline'], 'snapshot_id': request['snapshot_id'],
            'identity_sha256': request['identity_sha256'], 'cache_key': request['cache_key'],
        }))
        return SimpleNamespace(returncode=0, stdout='ok', stderr='')

    monkeypatch.setattr(runner_module.subprocess, 'run', fake_subprocess_run)
    baseline = json.loads((ROOT / 'data/v6_web/summary.json').read_text())

    class Request:
        def model_dump(self):
            return {'target_vol': 0.12, 'vt_window': 120, 'haircut': 0.5, 'quantile': 0.9,
                    'midmonth_threshold': 0.2, 'commodity_cost_bps': 5, 'momentum_excluded_count': 1,
                    'risk_budget_vol_window': 240, 'asset_short_vol_window': 20,
                    'short_vol_windows': [20, 60], 'asset_long_vol_window': 240, 'quantile_lookback': 240}

    runner = ExperimentRunner(baseline)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: runner.run(Request(), baseline=baseline), range(2)))
    assert first['identity_sha256'] == second['identity_sha256']
    assert calls == [first['identity_sha256']]
    assert Path(first['artifact_path'], 'result.json').is_file()
    assert not list(cache.glob('.????????????????.*'))
