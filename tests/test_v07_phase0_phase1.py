import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_phase0_reports_and_frozen_hashes():
    phase0 = (ROOT / "reports/V0.7_PHASE0_INVENTORY.md").read_text()
    audit = (ROOT / "reports/V0.7_DOWNLOAD_ENTRYPOINT_AUDIT.md").read_text()
    before = json.loads((ROOT / "reports/V0.7_FROZEN_HASHES_BEFORE.json").read_text())
    after = json.loads((ROOT / "reports/V0.7_FROZEN_HASHES_AFTER.json").read_text())
    assert "Phase 0 UI 快修" in phase0
    assert "scripts/04_sync_history.py" in audit
    assert after["unchanged"] is True
    assert before["files"] == after["files"]


def test_phase1_snapshot_is_unpublished_and_reconciled():
    result = json.loads((ROOT / "reports/V0.7_PHASE1_EXTENDED_BACKTEST.json").read_text())
    assert result["status"] == "PASS"
    assert result["published"] is False
    assert result["phase2_latest"] == "2026-09-24"
    assert result["phase3b_latest"] == "2026-09-24"
    with (ROOT / "reports/V0.7_BASELINE_OVERLAP_RECONCILIATION.csv").open() as fh:
        rows = list(csv.DictReader(fh))
    assert rows and all(row["status"] == "PASS" for row in rows)
    quality = (ROOT / "reports/V0.7_NEW_PERIOD_DATA_QUALITY.md").read_text()
    assert '"missing_held_trade_returns": 0' in quality


def test_extended_local_data_is_ignored():
    ignore = (ROOT / ".gitignore").read_text()
    assert "data/v07_local/" in ignore
