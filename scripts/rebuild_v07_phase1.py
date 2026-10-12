#!/usr/bin/env python3
"""Rebuild the extended Phase 1 snapshot without the frozen formal cutoff.

Inputs are read-only V6 Phase 2 artifacts. Phase 3A and Phase 3B are imported
from the frozen source tree, but outputs go to an explicit independent root.
The runner deliberately calls ``build_portfolio_daily`` directly instead of
``formal_nav_frame`` so the output retains every available date through the
requested verified endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd
import yaml
import pyarrow


def phase3a_config(path: Path):
    from src.phase3a import Phase3AConfig
    raw = yaml.safe_load(path.read_text()) or {}
    keys = ("momentum_windows", "sharpe_windows", "volatility_windows", "risk_vol_method",
            "annualization", "sharpe_ddof", "epsilon", "top_n", "selection_assets",
            "fixed_assets", "asset_categories", "relative_class_budget", "sleeve_scale",
            "global_risk_budget_scale", "category_budgets", "max_asset_weight",
            "rank_method", "max_staleness_asset_trading_days", "cap_policy", "warmup_min_periods")
    kwargs = {key: raw[key] for key in keys if key in raw}
    for key in ("momentum_windows", "sharpe_windows", "volatility_windows"):
        if key in kwargs:
            kwargs[key] = tuple(int(x) for x in kwargs[key])
    return Phase3AConfig(**kwargs)


def load_signal_panel(phase2: Path) -> pd.DataFrame:
    returns_path = phase2 / "signal_history.parquet"
    returns = pd.read_parquet(returns_path if returns_path.exists() else phase2 / "signal_returns.parquet")
    returns["date"] = pd.to_datetime(returns["date"])
    cols = ["date", "asset", "signal_return"]
    if "signal_index" in returns.columns:
        cols += ["signal_index"]
        panel = returns[[c for c in cols + ["signal_source", "trade_eligible"] if c in returns.columns]].copy()
    else:
        index = pd.read_parquet(phase2 / "signal_index.parquet")
        index["date"] = pd.to_datetime(index["date"])
        panel = returns[cols].merge(index[["date", "asset", "signal_index"]], on=["date", "asset"], validate="one_to_one")
    if panel.duplicated(["date", "asset"]).any():
        raise RuntimeError("duplicate Phase 2 signal rows")
    return panel.sort_values(["date", "asset"]).reset_index(drop=True)


def build(args: argparse.Namespace) -> dict:
    v6 = Path(os.environ.get("STRATEGY_LAB_V6_BASE", args.v6_root)).resolve()
    output = Path(args.output_root).resolve()
    phase2 = v6 / "data/processed/phase2"
    p3a_out = output / "data/processed/phase3a"
    p3b_out = output / "data/processed/phase3b"
    p3a_out.mkdir(parents=True, exist_ok=True)
    p3b_out.mkdir(parents=True, exist_ok=True)
    existing = [p for p in output.rglob("*") if p.is_file()]
    if existing:
        raise RuntimeError(f"output root must be empty for a reproducible rebuild: {output}")
    sys.path.insert(0, str(v6))
    from src.phase3a import build_phase3a, validate_phase3a
    from src.phase3b import build_execution, build_portfolio_daily, build_single_asset_vol_control, validate_phase3b

    readiness_path = v6 / "data/processed/phase2_5/production_readiness_v2.json"
    readiness = json.loads(readiness_path.read_text())
    required_checks = ["phase2_validator", "proxy_data_validated", "v2_targeted_tests", "commodity_roll_rule_errors", "equity_roll_rule_errors", "backward_roll_errors", "invalid_roll_target_errors", "NO_ROLL_TARGET", "proxy_trade_leakage_errors", "fg_targeted_status_explicit", "forced_data_roll_gaps_explicit", "held_unknown_are_future_or_explicit"]
    phase2_5_report_path = v6 / "data/processed/phase2_5/V2_PHASE2_5_REPORT.json"
    phase2_5_report = json.loads(phase2_5_report_path.read_text())
    report_checks = phase2_5_report.get("checks", {})
    if (not readiness.get("PHASE3_READY")
            or readiness.get("phase2_rebuild_required") is not False
            or not all(readiness.get("checks", {}).get(key) is True for key in required_checks)
            or phase2_5_report.get("phase2_5_ready") is not True
            or not all(report_checks.get(key) is True for key in required_checks)
            or phase2_5_report.get("forced_data_roll_gaps") != []
            or phase2_5_report.get("fg", {}).get("fg_targeted_rows") != 23
            or phase2_5_report.get("fg", {}).get("fg_resolution_counts") != {"CONFIRMED_ZERO_CLOSE": 23}
            or phase2_5_report.get("expiry", {}).get("held_unverified_future_maturities") is not True):
        raise RuntimeError("V2 Phase 2.5 readiness gate failed")
    fg_results = pd.read_csv(v6 / "data/processed/phase2_5/fg_requery_results.csv")
    if len(fg_results) != 23 or fg_results["resolution"].value_counts().to_dict() != {"CONFIRMED_ZERO_CLOSE": 23}:
        raise RuntimeError("FG targeted requery is not explicitly resolved")

    panel = load_signal_panel(phase2)
    cfg3a = phase3a_config(v6 / "config/phase3a.yaml")
    outputs = build_phase3a(panel, cfg3a)
    validation = validate_phase3a(outputs, cfg3a, panel=panel)
    if not validation["passed"]:
        raise RuntimeError(f"Phase 3A validation failed: {validation['errors'][:10]}")
    signals, selection, base = outputs["momentum_signals"], outputs["selection"], outputs["base_target_weights"]
    signals.to_parquet(p3a_out / "momentum_signals.parquet", index=False)
    selection.to_parquet(p3a_out / "asset_selection.parquet", index=False)
    base.to_parquet(p3a_out / "base_target_weights.parquet", index=False)
    base.to_parquet(p3a_out / "target_weights.parquet", index=False)
    signals[[c for c in ["date", "asset", "vol_20", "vol_60", "vol_120", "vol_240", "risk_vol", "risk_vol_method", "risk_vol_valid", "vol_status"] if c in signals]].to_parquet(p3a_out / "volatility_estimates.parquet", index=False)
    (p3a_out / "phase3a_validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2, default=str) + "\n")
    (p3a_out / "phase3a_summary.json").write_text(json.dumps({"stage": "V0.7_PHASE3A_ISOLATED_REBUILD", "validation": validation, "first_signal_date": str(pd.to_datetime(base.signal_date).min().date()), "last_signal_date": str(pd.to_datetime(base.signal_date).max().date()), "rows": int(len(base))}, ensure_ascii=False, indent=2) + "\n")

    cfg3b = yaml.safe_load((v6 / "config/phase3b.yaml").read_text())
    signal_returns = pd.read_parquet(phase2 / "signal_returns.parquet")
    trade_returns = pd.read_parquet(phase2 / "trade_returns.parquet")
    (output / "data/processed/phase2").mkdir(parents=True, exist_ok=True)
    signal_returns.to_parquet(output / "data/processed/phase2/signal_returns.parquet", index=False)
    trade_returns.to_parquet(output / "data/processed/phase2/trade_returns.parquet", index=False)
    vol_cfg = cfg3b["single_asset_vol_control"]
    vol = build_single_asset_vol_control(signal_returns, quantile=vol_cfg["quantile"], lookback=vol_cfg["quantile_lookback"], haircut_value=vol_cfg["haircut"], method=vol_cfg["method"], short_vol_method=vol_cfg["short_vol_method"], min_quantile_history=vol_cfg["min_quantile_history"])
    daily_theory, smoothing, events, weights = build_execution(base, vol, trade_returns, signal_returns, cfg3b, midmonth_threshold=cfg3b["mid_month_rebalance"]["threshold"], vt_estimator=cfg3b["portfolio_vol_target"]["estimator"])
    portfolio = build_portfolio_daily(weights, trade_returns, cfg3b)
    validation3b = validate_phase3b(weights, portfolio, vol, float(cfg3b["mid_month_rebalance"]["threshold"]))
    if not validation3b["passed"]:
        raise RuntimeError(f"Phase 3B validation failed: {validation3b['errors'][:10]}")
    vol.to_parquet(p3b_out / "single_asset_vol_control.parquet", index=False)
    daily_theory.to_parquet(p3b_out / "daily_theoretical_targets.parquet", index=False)
    smoothing.to_parquet(p3b_out / "monthly_smoothing_schedule.parquet", index=False)
    weights.to_parquet(p3b_out / "final_daily_weights.parquet", index=False)
    portfolio.to_parquet(p3b_out / "portfolio_daily.parquet", index=False)
    events.to_csv(p3b_out / "midmonth_rebalance_events.csv", index=False)
    event_rows = []
    for _, row in weights.iterrows():
        cost_bps = 5.0 if row.asset_class == "equity" else 2.0 if row.asset_class == "bond" else 0.0
        event_rows.append({"date": row.date, "event_type": "MID_MONTH_REBALANCE" if bool(row.midmonth_trigger) else (f"MONTHLY_SMOOTH_{int(row.monthly_smoothing_step)}" if int(row.monthly_smoothing_step) > 0 else "NONE"), "asset": row.asset, "weight_start": row.weight_start_of_day, "weight_theory": row.midmonth_theoretical_target, "weight_end": row.weight_end_of_day, "delta_weight": row.weight_end_of_day - row.weight_start_of_day, "single_asset_trigger": bool(row.single_asset_haircut < 1), "midmonth_deviation": row.deviation, "10vt_multiplier": row.final_10vt_multiplier, "cost_bps": cost_bps, "estimated_cost": 0.5 * abs(row.weight_end_of_day - row.weight_start_of_day) * cost_bps / 10000.0, "notes": row.weight_status})
    pd.DataFrame(event_rows).to_csv(p3b_out / "rebalance_event_log.csv", index=False)
    manifest = {"runner": str(Path(__file__).resolve()), "runtime": {"executable": sys.executable, "python_version": sys.version.split()[0], "pandas": pd.__version__, "pyarrow": pyarrow.__version__, "yaml": getattr(yaml, "__version__", "unknown")}, "v6_root": str(v6), "phase2_source": str(phase2), "formal_nav_frame_used": False, "requested_end": args.end, "phase3a_last_signal_date": str(pd.to_datetime(base.signal_date).max().date()), "phase3b_last_date": str(pd.to_datetime(portfolio.date).max().date()), "phase3a_validation": validation, "phase3b_validation": validation3b, "phase2_5_readiness": {"source": str(readiness_path), "report_source": str(phase2_5_report_path), "phase2_rebuild_required": readiness.get("phase2_rebuild_required"), "required_checks": required_checks, "forced_data_roll_gaps": phase2_5_report.get("forced_data_roll_gaps"), "fg_resolution_count": len(fg_results), "fg_resolution_counts": phase2_5_report.get("fg", {}).get("fg_resolution_counts")}, "rows": {"phase2_signal": len(signal_returns), "phase2_trade": len(trade_returns), "phase3a_base": len(base), "phase3b_weights": len(weights), "phase3b_portfolio": len(portfolio)}, "status": "PASS"}
    (output / "rebuild_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n")
    if str(pd.to_datetime(portfolio.date).max().date()) < args.end:
        raise RuntimeError("rebuilt portfolio ends before requested verified endpoint")
    print(json.dumps(manifest, ensure_ascii=False, default=str))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--v6-root", default="/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6")
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--end", default="2026-09-24")
    build(parser.parse_args())
