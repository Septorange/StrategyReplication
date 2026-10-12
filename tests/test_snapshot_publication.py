import json
from pathlib import Path
import pandas as pd
import pytest
from scripts.publish_verified_snapshot import reject_snapshot_id_reuse, restore_failed_publication
from scripts.validate_v07_publish_bundle import field_diff


def test_same_snapshot_id_is_immutable_but_rollback_can_republish_same_hash():
    prior = [{
        'snapshot_id': 'v07_extended_10119bd207b16499',
        'status': 'ROLLED_BACK',
        'selectable': False,
        'web_manifest_hash': 'web-a',
        'analytics_manifest_hash': 'analytics-a',
    }]
    reject_snapshot_id_reuse('v07_extended_10119bd207b16499', 'web-a', 'analytics-a', prior)
    with pytest.raises(SystemExit, match='immutable'):
        reject_snapshot_id_reuse('v07_extended_10119bd207b16499', 'web-b', 'analytics-a', prior)


def test_failed_health_check_rollback_restores_old_bundle_and_registry(tmp_path):
    destination=tmp_path/'published'/'snapshot'; backup=tmp_path/'published'/'snapshot.backup'; registry=tmp_path/'snapshot_registry.json'
    destination.parent.mkdir(); backup.mkdir(); destination.mkdir()
    (backup/'payload.txt').write_text('known-good')
    (destination/'payload.txt').write_text('candidate')
    old_registry=b'{"default_snapshot_id":"V6_FORMAL"}\n'
    registry.write_text('{"default_snapshot_id":"broken"}\n')
    restore_failed_publication(destination,backup,registry,old_registry)
    assert (destination/'payload.txt').read_text()=='known-good'
    assert registry.read_bytes()==old_registry
    assert not backup.exists()


def test_tampered_null_momentum_and_rank_values_fail_field_reconciliation():
    expected=pd.Series([None,0.015,0.022],dtype='object')
    null_mutation=pd.Series([0.0,0.015,0.022],dtype='object')
    momentum_mutation=pd.Series([None,0.016,0.022],dtype='object')
    rank_expected=pd.Series([1.0,2.0,3.0])
    rank_mutation=pd.Series([1.0,3.0,3.0])
    assert field_diff(expected,null_mutation)>1e-12
    assert field_diff(expected,momentum_mutation)>1e-12
    assert field_diff(rank_expected,rank_mutation)>1e-12
