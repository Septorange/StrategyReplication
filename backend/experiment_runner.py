from __future__ import annotations
import hashlib,json,subprocess,os
from datetime import datetime, timezone
from .config import ROOT,CACHE,V6_BASE,V6_PYTHON
from .parameter_registry import unsupported
class ExperimentRunner:
    def __init__(self,baseline): self.baseline=baseline; CACHE.mkdir(exist_ok=True)
    def run(self,request):
        config=request.model_dump()
        reason=unsupported(config)
        if reason: return {'status':'DISABLED','reason':reason,'synthetic':False}
        # Old config-only cache entries predate complete commodity cost scope.
        # Fingerprint the actual adapter, engine, inputs and immutable baseline.
        sources=[ROOT/'scripts/run_v6_experiment.py', ROOT/'backend/experiment_costs.py', ROOT/'backend/analytics_service.py', ROOT/'backend/parameter_registry.py', ROOT/'backend/experiment_runner.py', V6_BASE/'src/phase3b.py', V6_BASE/'config/phase3b.yaml', V6_BASE/'data/processed/phase3a/base_target_weights.parquet', V6_BASE/'data/processed/phase2/signal_returns.parquet', V6_BASE/'data/processed/phase2/trade_returns.parquet']
        hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        identity={'config':config,'source_hashes':hashes,'baseline':self.baseline,'adapter_version':3}
        key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]; dest=CACHE/key; result=dest/'result.json'
        if result.exists(): return json.loads(result.read_text())
        dest.mkdir(parents=True,exist_ok=True); request_path=dest/'request.json'; request_path.write_text(json.dumps({'config':config,'baseline':self.baseline},ensure_ascii=False))
        cmd=['/usr/bin/arch','-arm64',str(V6_PYTHON),str(ROOT/'scripts/run_v6_experiment.py'),str(request_path),str(dest)]
        env={'PATH':'/usr/bin:/bin','HOME':os.path.expanduser('~'),'LANG':'en_US.UTF-8','PYTHONDONTWRITEBYTECODE':'1'}
        started=datetime.now(timezone.utc).isoformat()
        try:
            run=subprocess.run(cmd,capture_output=True,text=True,timeout=600,cwd=V6_BASE,env=env)
        except subprocess.TimeoutExpired:
            return {'status':'FAIL','reason':'V6 engine timeout after 600 seconds','config_hash':key,'synthetic':False}
        (dest/'engine_stdout.log').write_text(run.stdout)
        (dest/'engine_stderr.log').write_text(run.stderr)
        (dest/'engine_run.json').write_text(json.dumps({'command':cmd,'cwd':str(V6_BASE),'started_utc':started,'completed_utc':datetime.now(timezone.utc).isoformat(),'returncode':run.returncode,'source_hashes':hashes,'adapter_version':3},ensure_ascii=False,indent=2)+'\n')
        if run.returncode: return {'status':'FAIL','engine':'V6 src/phase3b.py','config_hash':key,'error':run.stderr[-2000:],'synthetic':False}
        payload=json.loads(result.read_text())
        payload['source_hashes']=hashes
        result.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False)+'\n')
        return payload
