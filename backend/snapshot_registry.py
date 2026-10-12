"""Local registry for immutable, validated Web + Analytics snapshot bundles."""
from __future__ import annotations
import json
from pathlib import Path
from .config import ROOT

FORMAL_ID='V6_FORMAL'
REGISTRY_PATH=ROOT/'data'/'snapshot_registry.json'
PUBLISHED_ROOT=ROOT/'data'/'published_snapshots'

def read_registry():
    try:
        value=json.loads(REGISTRY_PATH.read_text())
        return value if isinstance(value,dict) else {'snapshots':[]}
    except (OSError,ValueError,TypeError):
        return {'schema_version':1,'default_snapshot_id':FORMAL_ID,'snapshots':[]}

def snapshot_entries():
    return read_registry().get('snapshots',[])

def get_snapshot(snapshot_id):
    if snapshot_id==FORMAL_ID:
        return {'snapshot_id':FORMAL_ID,'display_name':'正式基准','status':'AUDITED_BASELINE','selectable':True,'audit_status':'BASELINE_AUDITED','path':'data/v6_web','analytics_path':'data/v6_analytics'}
    return next((x for x in snapshot_entries() if x.get('snapshot_id')==snapshot_id and x.get('status')=='PUBLISHED' and x.get('selectable') is True),None)
