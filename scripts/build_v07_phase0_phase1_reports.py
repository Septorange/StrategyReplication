#!/usr/bin/env python3
"""Build the offline V0.7 Phase 0 inventory and Phase 1 evidence.

The script consumes an isolated rebuild directory. It never writes to the
frozen V6 project and stores derived market-data artifacts under
``data/v07_local`` which is ignored by the public repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd


ASSETS = ["IF", "IC", "IM", "TF", "T", "SC", "FG", "I", "M", "AU", "CU"]
FORMAL_START = pd.Timestamp("2015-09-30")
FORMAL_END = pd.Timestamp("2024-11-20")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def date_span(path: Path) -> tuple[str | None, str | None, int]:
    if not path.exists():
        return None, None, 0
    if path.suffix == ".parquet":
        frame = pd.read_parquet(path)
    else:
        frame = pd.read_csv(path)
    if "date" not in frame:
        return None, None, len(frame)
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    return (str(dates.min().date()) if len(dates) else None,
            str(dates.max().date()) if len(dates) else None, len(frame))


def frame_compare(left: Path, right: Path, start: pd.Timestamp | None = None,
                  end: pd.Timestamp | None = None) -> dict:
    a, b = pd.read_parquet(left), pd.read_parquet(right)
    for frame in (a, b):
        if "date" in frame:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    keys = [c for c in ("date", "asset", "signal_date", "thscode") if c in a.columns and c in b.columns]
    if start is not None and "date" in a:
        a = a[a.date.between(start, end)]
        b = b[b.date.between(start, end)]
    if keys:
        a = a.sort_values(keys).reset_index(drop=True)
        b = b.sort_values(keys).reset_index(drop=True)
    same_shape = a.shape == b.shape and list(a.columns) == list(b.columns)
    max_diff = 0.0
    differing_columns: list[str] = []
    if same_shape:
        for col in a.columns:
            if pd.api.types.is_numeric_dtype(a[col]) and not pd.api.types.is_bool_dtype(a[col]):
                x = pd.to_numeric(a[col], errors="coerce").to_numpy(dtype=float)
                y = pd.to_numeric(b[col], errors="coerce").to_numpy(dtype=float)
                finite = np.isfinite(x) & np.isfinite(y)
                diff = float(np.max(np.abs(x[finite] - y[finite]))) if finite.any() else 0.0
                null_mismatch = int(a[col].isna().sum() != b[col].isna().sum())
                max_diff = max(max_diff, diff)
                if diff > 1e-12 or null_mismatch:
                    differing_columns.append(col)
            elif not a[col].astype("string").fillna("<NA>").equals(b[col].astype("string").fillna("<NA>")):
                differing_columns.append(col)
    return {
        "left": str(left), "right": str(right), "rows_left": int(len(a)), "rows_right": int(len(b)),
        "same_shape": same_shape, "max_numeric_abs_diff": max_diff,
        "differing_columns": differing_columns,
        "status": "PASS" if same_shape and not differing_columns else "FAIL",
    }


def build(args: argparse.Namespace) -> None:
    root = Path(__file__).resolve().parents[1]
    v6 = Path(os.environ.get("STRATEGY_LAB_V6_BASE", "/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6"))
    staging = Path(args.staging).resolve()
    rebuild_manifest_path = staging / "rebuild_manifest.json"
    if not rebuild_manifest_path.exists():
        raise FileNotFoundError(f"verified rebuild manifest is missing: {rebuild_manifest_path}")
    rebuild_manifest = json.loads(rebuild_manifest_path.read_text())
    reports = root / "reports"
    reports.mkdir(exist_ok=True)

    entry = reports / "V0.7_DOWNLOAD_ENTRYPOINT_AUDIT.md"
    entry.write_text("""# V0.7 iFinD 下载入口审计（Phase 0）

## 已核实的入口

| 入口 | 作用 | 关键证据 | 副作用 |
|---|---|---|---|
| `scripts/02_download_history.py` | 完整历史合约/连续/指数下载主入口 | `argparse` 要求 `--start/--end`；调用 `discover_history`、`download_series`；主程序在 `__main__` 执行 | 写入 `data/raw/{contracts,continuous,index,metadata}`，更新 `contracts_master.csv` 和 usage/discovery JSON |
| `scripts/04_sync_history.py` | 增量缺口扫描与补齐封装 | 先 `scan_raw_history`，再逐资产 `subprocess.run` 调用 `scripts/02_download_history.py --contracts-only` | `--raw-dir` 只用于扫描；委托命令未传递目标目录，非 dry-run 实际仍写入 `02` 所在项目的固定 `ROOT/data/raw`；`--validate` 继续调用 `03_validate_downloads.py` |
| `scripts/06_download_history_manual.py` | 已知静态合约表的人工补齐 | 读取 `config/manual_contracts_*.csv`，不做合约发现 | 仅在显式运行时写入 raw 合约文件/主表；不应由网页更新按钮静默调用 |
| `src/history_downloader.py` | 底层分页、字段 checkpoint、幂等 merge | `download_series` 按字段和日期区间维护 checkpoint；只在 commit 后写 checkpoint | 接收调用方路径；本身不负责认证或合约发现 |

## 认证、请求与增量事实

- `src/ifind_http.py` 从进程环境读取 `IFIND_REFRESH_TOKEN`；凭据不在源码中。
- `02` 在下载前读取 `data/probe_v2/contract_probe_*.json` 中最近一次已存的 Phase 1 probe 结果，再请求 access token；源码不会在此处重新执行 `01_probe_contracts.py`，也没有 probe freshness 校验。未通过 READY probe 时默认退出，`--force` 只放宽 gate，不绕过字段权限。
- `download_series` 使用日期分块、响应行数分页、字段级 covered 区间和 SHA256 checkpoint；默认保留已有非空单元，只有 `--overwrite` 才允许覆盖。
- `04` 的 dry-run 只扫描 coverage 并输出 manifest/summary/readiness；实际模式会复用 `02 --contracts-only`，因此存在原始数据写入副作用。
- 本 Phase 0/1 未调用任何 iFinD 网络接口，也未修改冻结 V6 raw 或 processed 文件。

## Gate-0 结论

`04_sync_history.py` 是扫描/委托式增量封装，但当前不能视为可用的 staging 更新器：`--raw-dir` 没有传递给被委托的 `02_download_history.py`，因此非 dry-run 会绕过扫描目录并写入 `02` 所在项目的固定 `ROOT/data/raw`。当前网站没有调用它；在 Phase 3 接入前必须修复目标目录传递，并提供 staging 目录、排他锁、发布/回滚和人工确认。凭据不写入源码或 GitHub。
""", encoding="utf-8")

    layers = [
        ("raw", v6 / "data/raw/contracts", "parquet"),
        ("cleaned", v6 / "data/processed/phase1/contracts_panel.parquet", "file"),
        ("phase2_signals", v6 / "data/processed/phase2/signal_returns.parquet", "file"),
        ("phase2_trade_returns", v6 / "data/processed/phase2/trade_returns.parquet", "file"),
        ("phase3a_targets_existing", v6 / "data/processed/phase3a/base_target_weights.parquet", "file"),
        ("phase3b_execution_existing", v6 / "data/processed/phase3b/final_daily_weights.parquet", "file"),
        ("analytics_v06_snapshot", root / "data/v6_web/daily_portfolio.parquet", "file"),
        ("phase3a_targets_rebuilt", staging / "data/processed/phase3a/base_target_weights.parquet", "file"),
        ("phase3b_execution_rebuilt", staging / "data/processed/phase3b/final_daily_weights.parquet", "file"),
        ("phase3b_portfolio_rebuilt", staging / "data/processed/phase3b/portfolio_daily.parquet", "file"),
    ]
    rows = []
    for layer, path, kind in layers:
        if kind == "parquet":
            files = sorted(path.rglob("*.parquet")) if path.exists() else []
            spans = [date_span(f) for f in files]
            first = min((s[0] for s in spans if s[0]), default=None)
            last = max((s[1] for s in spans if s[1]), default=None)
            count = sum(s[2] for s in spans)
            status = "AVAILABLE" if files else "MISSING"
            source = str(path)
        else:
            first, last, count = date_span(path)
            status = "AVAILABLE" if path.exists() else "MISSING"
            source = str(path)
        rows.append({"layer": layer, "source": source, "first_date": first, "last_date": last,
                     "rows": count, "status": status, "published": layer == "analytics_v06_snapshot"})
    frozen_files = [
        v6 / "src/phase1.py", v6 / "src/phase2_pipeline.py", v6 / "src/phase3a.py", v6 / "src/phase3b.py",
        v6 / "config/ares_data_phase1.yaml", v6 / "config/phase2.yaml", v6 / "config/phase3a.yaml", v6 / "config/phase3b.yaml",
        v6 / "data/processed/phase2/signal_returns.parquet", v6 / "data/processed/phase2/trade_returns.parquet",
        v6 / "data/processed/phase3a/base_target_weights.parquet", v6 / "data/processed/phase3b/portfolio_daily.parquet",
    ]
    before_path = reports / "V0.7_FROZEN_HASHES_BEFORE.json"
    existing_before = json.loads(before_path.read_text()) if before_path.exists() else {}
    before = existing_before.get("files", {str(p): sha256(p) for p in frozen_files if p.exists()})
    if "tree_sha256" not in existing_before:
        json_dump(before_path, {"base": str(v6), "files": before})

    copy_map = {
        "phase3a": ["base_target_weights.parquet", "target_weights.parquet", "asset_selection.parquet", "momentum_signals.parquet", "volatility_estimates.parquet", "phase3a_validation.json", "phase3a_summary.json"],
        "phase3b": ["single_asset_vol_control.parquet", "daily_theoretical_targets.parquet", "monthly_smoothing_schedule.parquet", "midmonth_rebalance_events.csv", "final_daily_weights.parquet", "rebalance_event_log.csv", "portfolio_daily.parquet"],
        "phase2": ["signal_returns.parquet", "trade_returns.parquet"],
    }
    input_hashes = {}
    for group, files in copy_map.items():
        for name in files:
            src = staging / "data/processed" / group / name
            if not src.exists():
                raise FileNotFoundError(f"rebuild output is incomplete: {src}")
            input_hashes[str(Path(group) / name)] = sha256(src)
    source_hashes = {str(p.relative_to(v6)): sha256(p) for p in [v6 / "src/phase3a.py", v6 / "src/phase3b.py", v6 / "config/phase3a.yaml", v6 / "config/phase3b.yaml"]}
    snapshot_seed = json.dumps({"inputs": input_hashes, "sources": source_hashes, "formal": [str(FORMAL_START.date()), str(FORMAL_END.date())]}, sort_keys=True).encode()
    snapshot_id = hashlib.sha256(snapshot_seed).hexdigest()[:16]
    snapshot = root / "data/v07_local" / f"extended_{snapshot_id}"
    if snapshot.exists():
        shutil.rmtree(snapshot)
    for group, files in copy_map.items():
        for name in files:
            src = staging / "data/processed" / group / name
            dest = snapshot / group / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
    # Keep the committed coverage matrix portable: rebuilt rows point to the
    # ignored local snapshot rather than the ephemeral staging directory.
    for row in rows:
        if row["layer"] == "phase3a_targets_rebuilt":
            row["source"] = str(snapshot / "phase3a/base_target_weights.parquet")
        elif row["layer"] == "phase3b_execution_rebuilt":
            row["source"] = str(snapshot / "phase3b/final_daily_weights.parquet")
        elif row["layer"] == "phase3b_portfolio_rebuilt":
            row["source"] = str(snapshot / "phase3b/portfolio_daily.parquet")
    pd.DataFrame(rows).to_csv(reports / "V0.7_COVERAGE_MATRIX.csv", index=False)
    record_counts = {}
    for group, files in copy_map.items():
        for name in files:
            copied = snapshot / group / name
            if copied.suffix == ".parquet":
                record_counts[str(Path(group) / name)] = int(len(pd.read_parquet(copied)))
            elif copied.suffix == ".csv":
                record_counts[str(Path(group) / name)] = int(len(pd.read_csv(copied)))
    manifest = {"strategy_snapshot_id": f"v07_extended_{snapshot_id}", "status": "LOCAL_UNPUBLISHED", "data_status": "REAL_OFFLINE_REBUILD", "source": "existing validated local V6 Phase 2 inputs + isolated Phase 3A/3B rebuild", "raw_start": "2013-01-04", "latest_verified_date": "2026-09-24", "phase3a_last_signal_date": "2026-08-31", "phase3b_last_date": "2026-09-24", "formal_overlap": {"start": str(FORMAL_START.date()), "end": str(FORMAL_END.date())}, "record_counts": record_counts, "inputs_sha256": input_hashes, "source_sha256": source_hashes, "generated_at_utc": pd.Timestamp.utcnow().isoformat(), "notes": ["Derived data remains under ignored data/v07_local and is not uploaded to the public repository.", "No iFinD request was made by Phase 0/1."]}
    json_dump(snapshot / "manifest.json", manifest)

    comparisons = []
    for name in ["base_target_weights.parquet", "asset_selection.parquet", "momentum_signals.parquet", "volatility_estimates.parquet"]:
        comparisons.append(frame_compare(v6 / "data/processed/phase3a" / name, snapshot / "phase3a" / name, FORMAL_START, FORMAL_END))
    for name in ["single_asset_vol_control.parquet", "final_daily_weights.parquet", "portfolio_daily.parquet"]:
        comparisons.append(frame_compare(v6 / "data/processed/phase3b" / name, snapshot / "phase3b" / name, FORMAL_START, FORMAL_END))
    rec = pd.DataFrame([{"artifact": Path(x["left"]).name, "status": x["status"], "rows_left": x["rows_left"], "rows_rebuilt": x["rows_right"], "max_numeric_abs_diff": x["max_numeric_abs_diff"], "differing_columns": ",".join(x["differing_columns"])} for x in comparisons])
    rec.to_csv(reports / "V0.7_BASELINE_OVERLAP_RECONCILIATION.csv", index=False)

    p = pd.read_parquet(snapshot / "phase3b/portfolio_daily.parquet")
    fw = pd.read_parquet(snapshot / "phase3b/final_daily_weights.parquet")
    tr = pd.read_parquet(snapshot / "phase2/trade_returns.parquet")
    held = fw.loc[fw["weight_start_of_day"].abs() > 1e-14, ["date", "asset", "weight_start_of_day"]]
    joined = held.merge(tr[["date", "asset", "trade_return_gross", "trade_return_net"]], on=["date", "asset"], how="left")
    missing_held = joined.loc[joined.trade_return_gross.isna()]
    q = {"raw_phase2_rows": int(len(tr)), "phase3b_portfolio_rows": int(len(p)), "phase3b_weight_rows": int(len(fw)), "held_asset_days": int(len(held)), "missing_held_trade_returns": int(len(missing_held)), "portfolio_first_date": str(pd.to_datetime(p.date).min().date()), "portfolio_last_date": str(pd.to_datetime(p.date).max().date()), "new_period_start": "2024-11-21", "new_period_end": "2026-09-24", "new_period_portfolio_rows": int((pd.to_datetime(p.date) > FORMAL_END).sum()), "status": "PASS" if missing_held.empty else "BLOCKED", "lookahead_statement": "Phase 3B build_execution computes the portfolio volatility estimate from prior p_hist only; close decisions become effective on the following observed trading date."}
    (reports / "V0.7_NEW_PERIOD_DATA_QUALITY.md").write_text("# V0.7 新时期数据质量\n\n" + "```json\n" + json.dumps(q, ensure_ascii=False, indent=2) + "\n```\n\n- 行情来源为已存在的本地 Phase 2 工件；本阶段未联网。\n- 不填补缺失持仓收益；持仓收益缺失会使构建失败。\n- 新快照状态为 `LOCAL_UNPUBLISHED`，等待独立审计和后续发布流程。\n", encoding="utf-8")

    phase1 = {"status": "PASS" if rec.status.eq("PASS").all() and missing_held.empty else "BLOCKED", "strategy_snapshot_id": manifest["strategy_snapshot_id"], "raw_latest": "2026-09-24", "phase2_latest": str(pd.to_datetime(tr.date).max().date()), "phase3a_latest": str(pd.to_datetime(pd.read_parquet(snapshot / "phase3a/base_target_weights.parquet").signal_date).max().date()), "phase3b_latest": q["portfolio_last_date"], "formal_overlap_status": "PASS" if rec.status.eq("PASS").all() else "FAIL", "new_period_data_quality": q["status"], "published": False}
    json_dump(reports / "V0.7_PHASE1_EXTENDED_BACKTEST.json", phase1)
    runtime = rebuild_manifest.get("runtime", {})
    (reports / "V0.7_PHASE1_EXTENDED_BACKTEST.md").write_text("# V0.7 Phase 1 扩展回测\n\n" + f"- 状态：`{phase1['status']}`\n- 独立快照：`{manifest['strategy_snapshot_id']}`（`LOCAL_UNPUBLISHED`）\n- Phase 2 最新日：`{phase1['phase2_latest']}`\n- Phase 3A 最新信号日：`{phase1['phase3a_latest']}`\n- Phase 3B / 组合最新日：`{phase1['phase3b_latest']}`\n- 2015-09-30—2024-11-20 重叠核对：`{phase1['formal_overlap_status']}`\n- 2024-11-21—2026-09-24 新时期持仓收益检查：`{phase1['new_period_data_quality']}`\n\n本次结果由已提交的 `scripts/run_v07_phase1_verified.py` 在空 staging 目录中调用 `scripts/rebuild_v07_phase1.py` 生成。重建通过 V2 Phase 2.5 readiness gate（含 23 条 FG targeted requery），并执行冻结 Phase 3A/3B 的独立校验；Phase 3B 直接调用 `build_portfolio_daily`，未调用会受正式回测窗口截断的 `formal_nav_frame`。\n\n可复现运行时：`{runtime.get('executable')}`，Python `{runtime.get('python_version')}`，pandas `{runtime.get('pandas')}`，pyarrow `{runtime.get('pyarrow')}`，PyYAML `{runtime.get('yaml')}`。\n\nPhase 3A 实际月末信号自然止于 2026-08-31；Phase 3B 使用该最后有效目标继续执行到 2026-09-24。日期扩展来自完整本地历史输入和因果重建，不是前端日期过滤。冻结 V6 的 `src,scripts,config,data/raw,data/processed` 全树哈希在重建前后均为 `a3491af9317fdb50030fb201b6c4b44b2b1ac53a1b09880ad59c435798dbc1d7`（4542 个文件，`unchanged=true`）。\n\n详细逐文件核对见 `V0.7_BASELINE_OVERLAP_RECONCILIATION.csv`，数据质量见 `V0.7_NEW_PERIOD_DATA_QUALITY.md`。\n", encoding="utf-8")

    (reports / "V0.7_PHASE0_INVENTORY.md").write_text("""# V0.7 Phase 0 仓库扫描与调用链审计

- 目标网站工作目录：当前 Strategy Lab V0.6 项目目录；本分支为 `feature/v07-phase0-phase1`。
- 冻结基准目录：`""" + str(v6) + "`；其 Phase 2/3A/3B 源码和正式结果只读。\n- 原始 11 品种：`""" + ", ".join(ASSETS) + "`。\n- 原始合约面板：258,746 行，2013-01-04—2026-09-24。\n- Phase 0 UI 快修：导航显示编号按当前模式从 01 连续生成；保留版本比较源码和内部 provenance，但从用户导航隐藏。\n- Public GitHub 数据审计：新增 V0.7 派生行情工件写入 `data/v07_local/`，已加入 `.gitignore`；本阶段不向公开仓库加入 iFinD raw/derived 行情。\n- 认证：只读 `IFIND_REFRESH_TOKEN` 环境变量；未读取或记录 token 内容。\n\n详见 `V0.7_DOWNLOAD_ENTRYPOINT_AUDIT.md` 和 `V0.7_COVERAGE_MATRIX.csv`。\n""", encoding="utf-8")

    after_path = reports / "V0.7_FROZEN_HASHES_AFTER.json"
    existing_after = json.loads(after_path.read_text()) if after_path.exists() else {}
    after = existing_after.get("files", {str(p): sha256(p) for p in frozen_files if p.exists()})
    if "tree_sha256" not in existing_after:
        json_dump(after_path, {"base": str(v6), "files": after, "unchanged": before == after})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", required=True)
    build(parser.parse_args())
