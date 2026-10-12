#!/usr/bin/env python3
"""Atomically install a validated local bundle and register it for explicit selection."""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
REGISTRY=ROOT/'data'/'snapshot_registry.json'; PUBLISHED=ROOT/'data'/'published_snapshots'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f: json.dump(value,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def restore_failed_publication(destination, backup, registry_path, old_registry):
    if destination.exists(): shutil.rmtree(destination)
    if backup.exists(): os.replace(backup,destination)
    if old_registry is None:
        registry_path.unlink(missing_ok=True)
    else:
        fd,tmpreg=tempfile.mkstemp(prefix='.registry.rollback.',dir=registry_path.parent)
        with os.fdopen(fd,'wb') as f: f.write(old_registry); f.flush(); os.fsync(f.fileno())
        os.replace(tmpreg,registry_path)

def reject_snapshot_id_reuse(snapshot_id, web_manifest_hash, analytics_manifest_hash, entries):
    prior=next((x for x in entries if x.get('snapshot_id')==snapshot_id),None)
    if prior and (prior.get('web_manifest_hash')!=web_manifest_hash or prior.get('analytics_manifest_hash')!=analytics_manifest_hash):
        raise SystemExit('snapshot ID is immutable; choose a new snapshot ID for different bundle contents')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--bundle',type=Path); ap.add_argument('--snapshot-id',default='v07_extended_10119bd207b16499'); mode=ap.add_mutually_exclusive_group(required=True); mode.add_argument('--dry-run',action='store_true'); mode.add_argument('--publish',action='store_true'); mode.add_argument('--rollback',action='store_true'); a=ap.parse_args()
    if a.rollback:
        if not REGISTRY.is_file(): raise SystemExit('snapshot registry does not exist')
        registry=json.loads(REGISTRY.read_text()); entries=registry.get('snapshots',[]); target=next((x for x in entries if x.get('snapshot_id')==a.snapshot_id),None)
        if target is None: raise SystemExit('snapshot is not registered')
        target['status']='ROLLED_BACK'; target['selectable']=False; registry['default_snapshot_id']='V6_FORMAL'; atomic_json(REGISTRY,registry)
        print(json.dumps({'rolled_back':a.snapshot_id,'default_snapshot_id':'V6_FORMAL','snapshot_files_retained':True},ensure_ascii=False,indent=2)); return
    if a.bundle is None: raise SystemExit('--bundle is required')
    b=a.bundle.resolve(); validation=b/'publish_validation.json'
    cmd=[sys.executable,str(ROOT/'scripts/validate_v07_publish_bundle.py'),'--bundle',str(b),'--write-report']
    result=subprocess.run(cmd,capture_output=True,text=True)
    if result.returncode:
        print(result.stdout); print(result.stderr,file=sys.stderr); raise SystemExit('candidate failed publication validation')
    report=json.loads(validation.read_text()); web=b/'web'; analytics=b/'analytics'; webm=json.loads((web/'manifest.json').read_text()); anm=json.loads((analytics/'manifest.json').read_text()); source=json.loads((ROOT/'data/v07_local/extended_10119bd207b16499/manifest.json').read_text())
    if webm.get('snapshot_id')!=a.snapshot_id or anm.get('snapshot_id')!=a.snapshot_id: raise SystemExit('snapshot ID mismatch')
    registry_now=json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {'snapshots':[]}
    incoming_web_hash=sha(web/'manifest.json'); incoming_analytics_hash=sha(analytics/'manifest.json')
    reject_snapshot_id_reuse(a.snapshot_id,incoming_web_hash,incoming_analytics_hash,registry_now.get('snapshots',[]))
    entry={'snapshot_id':a.snapshot_id,'display_name':f'扩展数据 · 截至 {webm["data_end_date"]}','status':'PUBLISHED','selectable':True,'data_start_date':webm['data_start_date'],'data_end_date':webm['data_end_date'],'last_signal_date':webm['phase3a_last_signal_date'],'source_rebuild_manifest_hash':webm['source_rebuild_manifest_sha256'],'web_manifest_hash':incoming_web_hash,'analytics_manifest_hash':incoming_analytics_hash,'audit_status':'WEB_LAYER_PENDING_INDEPENDENT_REVIEW','path':f'data/published_snapshots/{a.snapshot_id}/web','analytics_path':f'data/published_snapshots/{a.snapshot_id}/analytics'}
    if a.dry_run:
        print(json.dumps({'dry_run':True,'validation':'PASS','snapshot_registry_entry':entry,'summary':json.loads((web/'summary.json').read_text())},ensure_ascii=False,indent=2)); return
    PUBLISHED.mkdir(parents=True,exist_ok=True); destination=PUBLISHED/a.snapshot_id
    temp=PUBLISHED/f'.{a.snapshot_id}.{os.getpid()}.tmp'; backup=PUBLISHED/f'.{a.snapshot_id}.{os.getpid()}.rollback'
    if temp.exists(): shutil.rmtree(temp)
    shutil.copytree(b,temp,ignore=shutil.ignore_patterns('publish_audit.json'))
    if destination.exists(): os.replace(destination,backup)
    old_registry=REGISTRY.read_bytes() if REGISTRY.exists() else None
    try:
        os.replace(temp,destination)
        registry=json.loads(old_registry) if old_registry else {'schema_version':1,'default_snapshot_id':'V6_FORMAL','snapshots':[]}
        registry['schema_version']=1; registry.setdefault('default_snapshot_id','V6_FORMAL')
        registry['snapshots']=[x for x in registry.get('snapshots',[]) if x.get('snapshot_id')!=a.snapshot_id]+[entry]
        atomic_json(REGISTRY,registry)
        # Exercise the same service constructors the FastAPI runtime uses.
        from backend.v6_loader import V6Loader
        from backend.analytics_service import AnalyticsService
        from backend.replay_service import ReplayService
        from backend.research_service import ResearchService
        loaded=V6Loader(destination/'web'); analytics_service=AnalyticsService(destination/'analytics')
        ReplayService(loaded); ResearchService(loaded)
        if loaded.snapshot_id!=a.snapshot_id or loaded.summary.get('end_date')!=webm.get('data_end_date') or analytics_service.manifest.get('snapshot_id')!=a.snapshot_id or analytics_service.manifest.get('source_web_manifest_sha256')!=sha(destination/'web'/'manifest.json'):
            raise RuntimeError('published service bundle health check failed')
        if len(analytics_service.history()['rows'])!=len(loaded.portfolio): raise RuntimeError('published analytics history does not align with portfolio')
        audit={'snapshot_id':a.snapshot_id,'status':'PUBLISHED','published_at_utc':datetime.now(timezone.utc).isoformat(),'validation_sha256':sha(destination/'publish_validation.json') if (destination/'publish_validation.json').exists() else None,'web_manifest_sha256':sha(destination/'web'/'manifest.json'),'analytics_manifest_sha256':sha(destination/'analytics'/'manifest.json'),'previous_default_snapshot_id':registry['default_snapshot_id']}
        atomic_json(destination/'publish_audit.json',audit)
    except Exception:
        restore_failed_publication(destination,backup,REGISTRY,old_registry)
        raise
    else:
        if backup.exists(): shutil.rmtree(backup)
        print(json.dumps({'published':True,'snapshot_id':a.snapshot_id,'registry':str(REGISTRY.relative_to(ROOT)),'path':str(destination.relative_to(ROOT)),'rollback':f'python scripts/publish_verified_snapshot.py --snapshot-id {a.snapshot_id} --rollback'},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
