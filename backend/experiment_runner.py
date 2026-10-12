from __future__ import annotations

import hashlib
import json
import os
import fcntl
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from .config import ROOT, CACHE, V6_BASE, V6_PYTHON
from .parameter_registry import unsupported
from .snapshot_registry import FORMAL_ID, get_snapshot


class ExperimentRunner:
    def __init__(self, baseline):
        self.baseline = baseline
        CACHE.mkdir(exist_ok=True)
        (CACHE/'.locks').mkdir(exist_ok=True)

    def _inputs(self, snapshot_id: str):
        if snapshot_id == FORMAL_ID:
            phase2 = V6_BASE / 'data/processed/phase2'
            phase3a = V6_BASE / 'data/processed/phase3a'
            latest=json.loads((ROOT/'data/v6_web/summary.json').read_text()).get('end_date')
        else:
            entry = get_snapshot(snapshot_id)
            if not entry:
                raise ValueError(f'Unknown or unpublished snapshot: {snapshot_id}')
            local_root=(ROOT/'data/v07_local').resolve()
            local=None; manifest=None
            for candidate in local_root.iterdir():
                if not candidate.is_dir(): continue
                try: candidate_manifest=json.loads((candidate/'manifest.json').read_text())
                except (OSError,ValueError,TypeError): continue
                if candidate_manifest.get('strategy_snapshot_id')==snapshot_id:
                    local,manifest=candidate.resolve(),candidate_manifest
                    break
            if local is None or not local.is_relative_to(local_root):
                raise FileNotFoundError(f'No isolated local Phase2/Phase3A inputs registered for snapshot {snapshot_id}.')
            if manifest.get('strategy_snapshot_id') != snapshot_id or manifest.get('status') != 'LOCAL_UNPUBLISHED':
                raise ValueError('The local experiment inputs do not match the registered snapshot identity.')
            rebuild_path=local/'rebuild_manifest.json'
            rebuild_hash=hashlib.sha256(rebuild_path.read_bytes()).hexdigest()
            if rebuild_hash!=entry.get('source_rebuild_manifest_hash'):
                raise ValueError('Snapshot rebuild manifest hash does not match the published snapshot registry.')
            latest=manifest.get('latest_verified_date')
            phase2, phase3a = local / 'phase2', local / 'phase3a'
        paths = {
            'base_target_weights': phase3a / 'base_target_weights.parquet',
            'signal_returns': phase2 / 'signal_returns.parquet',
            'trade_returns': phase2 / 'trade_returns.parquet',
        }
        if not all(p.is_file() for p in paths.values()):
            raise FileNotFoundError(f'Incomplete experiment inputs for snapshot {snapshot_id}.')
        if snapshot_id!=FORMAL_ID:
            expected=manifest.get('inputs_sha256',{})
            for name,path in paths.items():
                relative=str(path.relative_to(local))
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                if expected.get(relative)!=digest:
                    raise ValueError(f'Snapshot input hash mismatch: {relative}')
        return paths, latest

    def run(self, request, *, snapshot_id: str = FORMAL_ID, baseline: dict | None = None):
        config = request.model_dump()
        reason = unsupported(config)
        if reason:
            return {'status': 'DISABLED', 'reason': reason, 'synthetic': False, 'snapshot_id': snapshot_id}
        baseline = dict(baseline or self.baseline)
        inputs, latest_verified = self._inputs(snapshot_id)
        try:
            start=date.fromisoformat(str(baseline['start_date'])[:10])
            end=date.fromisoformat(str(baseline['end_date'])[:10])
            latest=date.fromisoformat(str(latest_verified)[:10])
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError('Snapshot evaluation bounds or latest_verified_date are missing/invalid.') from exc
        if start>end or end>latest or end!=latest:
            raise ValueError(f'Snapshot evaluation end {end} must equal its latest verified date {latest}.')
        sources = [ROOT/'scripts/run_v6_experiment.py', ROOT/'backend/experiment_costs.py', ROOT/'backend/analytics_service.py', ROOT/'backend/parameter_registry.py', ROOT/'backend/experiment_runner.py', V6_BASE/'src/phase3b.py', V6_BASE/'config/phase3b.yaml', *inputs.values()]
        hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        identity = {'config': config, 'snapshot_id': snapshot_id, 'source_hashes': hashes,
                    'baseline': baseline, 'adapter_version': 4}
        identity_sha256 = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        key = identity_sha256[:16]
        dest = CACHE/key
        result_path = dest/'result.json'
        lock_path=CACHE/'.locks'/f'{identity_sha256}.lock'
        # Lock the short directory alias as well as the full identity. This
        # serializes the (extremely unlikely) case where different full hashes
        # share a 16-character alias.
        alias_lock_path=CACHE/'.locks'/f'alias-{key}.lock'
        with alias_lock_path.open('a') as alias_lock, lock_path.open('a') as lock_file:
            fcntl.flock(alias_lock.fileno(),fcntl.LOCK_EX)
            fcntl.flock(lock_file.fileno(),fcntl.LOCK_EX)
            try:
                if result_path.exists():
                    cached=json.loads(result_path.read_text())
                    manifest_path=dest/'artifact_manifest.json'
                    manifest=json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
                    if (cached.get('identity_sha256')==identity_sha256
                            and cached.get('snapshot_id')==snapshot_id
                            and cached.get('config_hash')==identity_sha256
                            and cached.get('cache_key')==key
                            and cached.get('adapter_version')==4
                            and manifest.get('identity_sha256')==identity_sha256
                            and manifest.get('config_hash')==identity_sha256
                            and manifest.get('snapshot_id')==snapshot_id
                            and manifest.get('cache_key')==key
                            and manifest.get('adapter_version')==4
                            and manifest.get('result_sha256')==hashlib.sha256(result_path.read_bytes()).hexdigest()):
                        return cached
                    raise RuntimeError(f'Experiment cache alias collision or stale identity for {key}; refusing to reuse it.')
                return self._execute(identity_sha256,key,dest,config,baseline,snapshot_id,inputs,hashes)
            finally:
                fcntl.flock(lock_file.fileno(),fcntl.LOCK_UN)
                fcntl.flock(alias_lock.fileno(),fcntl.LOCK_UN)

    def _execute(self, identity_sha256, key, dest, config, baseline, snapshot_id, inputs, hashes):
        temp_dir=Path(tempfile.mkdtemp(prefix=f'.{key}.',dir=CACHE))
        request_path=temp_dir/'request.json'
        request_path.write_text(json.dumps({'config':config,'baseline':baseline,'snapshot_id':snapshot_id,
            'identity_sha256':identity_sha256,'cache_key':key,'inputs':{k:str(v) for k,v in inputs.items()}},ensure_ascii=False))
        cmd=['/usr/bin/arch','-arm64',str(V6_PYTHON),str(ROOT/'scripts/run_v6_experiment.py'),str(request_path),str(temp_dir)]
        env={'PATH':'/usr/bin:/bin','HOME':os.path.expanduser('~'),'LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
        started=datetime.now(timezone.utc).isoformat()
        try:
            run=subprocess.run(cmd,capture_output=True,text=True,timeout=600,cwd=V6_BASE,env=env)
        except subprocess.TimeoutExpired:
            shutil.rmtree(temp_dir,ignore_errors=True)
            return {'status':'FAIL','reason':'V6 engine timeout after 600 seconds','config_hash':identity_sha256,
                    'cache_key':key,'identity_sha256':identity_sha256,'snapshot_id':snapshot_id,'synthetic':False}
        (temp_dir/'engine_stdout.log').write_text(run.stdout)
        (temp_dir/'engine_stderr.log').write_text(run.stderr)
        engine_record={'command':cmd,'cwd':str(V6_BASE),'started_utc':started,
            'completed_utc':datetime.now(timezone.utc).isoformat(),'returncode':run.returncode,
            'source_hashes':hashes,'adapter_version':4,'snapshot_id':snapshot_id,
            'identity_sha256':identity_sha256,'cache_key':key}
        (temp_dir/'engine_run.json').write_text(json.dumps(engine_record,ensure_ascii=False,indent=2)+'\n')
        if run.returncode:
            error=run.stderr[-2000:]
            shutil.rmtree(temp_dir,ignore_errors=True)
            return {'status':'FAIL','engine':'V6 src/phase3b.py','config_hash':identity_sha256,
                    'cache_key':key,'identity_sha256':identity_sha256,'snapshot_id':snapshot_id,
                    'error':error,'synthetic':False}
        payload=json.loads((temp_dir/'result.json').read_text())
        payload.update(source_hashes=hashes,snapshot_id=snapshot_id,config_hash=identity_sha256,
                       identity_sha256=identity_sha256,cache_key=key,adapter_version=4,
                       artifact_path=str(dest),output_path=str(dest))
        result_file=temp_dir/'result.json'
        result_file.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False)+'\n')
        manifest={'identity_sha256':identity_sha256,'config_hash':identity_sha256,
                  'snapshot_id':snapshot_id,'cache_key':key,'adapter_version':4,
                  'result_sha256':hashlib.sha256(result_file.read_bytes()).hexdigest(),
                  'artifact_sha256': {name: hashlib.sha256((temp_dir/name).read_bytes()).hexdigest()
                                      for name in ('daily_portfolio.parquet','single_asset_vol_control.parquet',
                                                   'final_daily_weights.parquet','events.parquet',
                                                   'experiment_trade_returns.parquet','engine_run.json')}}
        (temp_dir/'artifact_manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
        # Publish into an absent alias atomically. Never delete an existing
        # directory: it may belong to a different full hash with the same alias.
        os.rename(temp_dir,dest)
        return payload
