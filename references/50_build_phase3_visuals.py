#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate eight presentation-ready visualizations from the REAL Phase 3 formal
backtest outputs.

Default inputs:
    data/processed/phase3_formal/

Outputs:
    data/processed/phase3_visuals/

Figures/tables:
    01_strategy_history.png
    02_strategy_performance_table.png
    03_strategy_win_rate_table.png
    04_class_annual_contribution.png
    05_asset_annual_contribution_table.png
    06_class_historical_holdings.png
    07_top5_drawdowns.png
    08_top5_drawdowns_table.png

Also writes the underlying CSV tables and a visualization_manifest.json.

Important:
- All values are read/recomputed from the formal backtest artifacts.
- The 120-day volatility shown in visualization 01/06 is a PRESENTATION
  diagnostic only. It does NOT change the frozen 60D 10VT strategy rule.
- No iFinD/network call is made.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager


ASSETS = ["IF", "IC", "IM", "TF", "T", "SC", "FG", "I", "M", "AU", "CU"]
ASSET_CN = {
    "IF": "沪深300",
    "IC": "中证500",
    "IM": "中证1000",
    "TF": "中国5年国债",
    "T": "中国10年国债",
    "SC": "原油期货",
    "FG": "玻璃期货",
    "I": "铁矿石期货",
    "M": "豆粕期货",
    "AU": "沪金期货",
    "CU": "沪铜期货",
}
CLASSES = {
    "Equity": ["IF", "IC", "IM"],
    "Bond": ["TF", "T"],
    "Commodity": ["SC", "FG", "I", "M", "AU", "CU"],
}
CLASS_CN = {"Equity": "股票", "Bond": "债券", "Commodity": "商品"}


def configure_chinese_font() -> None:
    """Pick an installed CJK-capable font without bundling any font file."""
    candidates = [
        "PingFang SC",
        "Hiragino Sans GB",
        "Heiti SC",
        "Songti SC",
        "STHeiti",
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name]
            break
    plt.rcParams["axes.unicode_minus"] = False


def resolve_default_root() -> Path:
    p = Path(__file__).resolve()
    if p.parent.name == "scripts":
        return p.parents[1]
    return Path.cwd().resolve()


def require_files(input_dir: Path, names: List[str]) -> Dict[str, Path]:
    paths = {name: input_dir / name for name in names}
    missing = [str(p) for p in paths.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing required Phase 3 formal artifacts:\n  - "
            + "\n  - ".join(missing)
            + "\n\nRun scripts/42_build_phase3_formal.py first, or pass --input-dir."
        )
    return paths


def load_inputs(input_dir: Path):
    files = require_files(
        input_dir,
        [
            "daily_portfolio.csv",
            "daily_weights.csv",
            "daily_asset_contribution.csv",
            "annual_performance.csv",
            "annual_class_contribution.csv",
            "annual_asset_contribution.csv",
            "performance_summary.json",
        ],
    )

    daily = pd.read_csv(files["daily_portfolio.csv"], parse_dates=["date"]).sort_values("date")
    weights = pd.read_csv(files["daily_weights.csv"], parse_dates=["date"]).sort_values(["date", "asset"])
    contrib = pd.read_csv(files["daily_asset_contribution.csv"], parse_dates=["date"]).sort_values(["date", "asset"])
    annual_perf = pd.read_csv(files["annual_performance.csv"])
    annual_class = pd.read_csv(files["annual_class_contribution.csv"])
    annual_asset = pd.read_csv(files["annual_asset_contribution.csv"])
    summary = json.loads(files["performance_summary.json"].read_text(encoding="utf-8"))

    # Normalize possible unnamed index columns.
    for frame in (annual_class, annual_asset):
        unnamed = [c for c in frame.columns if str(c).startswith("Unnamed:")]
        if unnamed and "year" not in frame.columns:
            frame.rename(columns={unnamed[0]: "year"}, inplace=True)
        if unnamed:
            frame.drop(columns=[c for c in unnamed if c in frame.columns and c != "year"], inplace=True, errors="ignore")

    if "year" not in annual_class.columns:
        annual_class = annual_class.reset_index().rename(columns={"index": "year"})
    if "year" not in annual_asset.columns:
        annual_asset = annual_asset.reset_index().rename(columns={"index": "year"})

    required_daily = {"date", "portfolio_return_net"}
    if not required_daily.issubset(daily.columns):
        raise ValueError(f"daily_portfolio.csv missing columns: {required_daily - set(daily.columns)}")

    if "weight_start_of_day" not in weights.columns:
        raise ValueError("daily_weights.csv must contain weight_start_of_day")
    if "asset" not in weights.columns:
        raise ValueError("daily_weights.csv must contain asset")
    if "asset_contribution" not in contrib.columns:
        raise ValueError("daily_asset_contribution.csv must contain asset_contribution")

    return daily, weights, contrib, annual_perf, annual_class, annual_asset, summary


def nav_from_returns(daily: pd.DataFrame) -> pd.Series:
    return (1.0 + pd.to_numeric(daily["portfolio_return_net"], errors="coerce").fillna(0.0)).cumprod()


def annualized_vol(series: pd.Series, window: int) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").rolling(window, min_periods=window).std(ddof=1) * np.sqrt(252)


def save_figure(fig, path: Path, dpi: int) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def make_table_png(
    df: pd.DataFrame,
    title: str,
    path: Path,
    dpi: int,
    fontsize: float = 10,
    row_scale: float = 1.45,
    figsize=None,
) -> None:
    display = df.copy()
    if figsize is None:
        figsize = (max(10, 1.25 * len(display.columns)), max(3.5, 0.55 * len(display) + 2.2))
    fig, ax = plt.subplots(figsize=figsize)
    ax.axis("off")
    ax.set_title(title, fontsize=17, pad=18)
    table = ax.table(
        cellText=display.values,
        colLabels=display.columns,
        cellLoc="center",
        loc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize)
    table.scale(1, row_scale)
    for (r, c), cell in table.get_celld().items():
        if r == 0:
            cell.set_text_props(weight="bold")
    save_figure(fig, path, dpi)


def build_strategy_history(daily: pd.DataFrame, out: Path, vol_window: int, dpi: int) -> None:
    x = daily.copy()
    x["nav"] = nav_from_returns(x)
    x["display_vol"] = annualized_vol(x["portfolio_return_net"], vol_window)

    fig, ax1 = plt.subplots(figsize=(14, 7))
    line = ax1.plot(x["date"], x["nav"], linewidth=1.8, label="净值（左轴）")
    ax1.set_ylabel("净值")
    ax1.set_xlabel("")
    ax1.set_title("策略历史表现")

    ax2 = ax1.twinx()
    valid = x["display_vol"].notna()
    area = ax2.fill_between(
        x.loc[valid, "date"],
        0,
        x.loc[valid, "display_vol"],
        alpha=0.22,
        label=f"{vol_window}天波动率",
    )
    ax2.set_ylabel("年化波动率")
    ax2.yaxis.set_major_formatter(lambda v, pos: f"{v:.0%}")

    handles = line + [area]
    labels = [h.get_label() for h in handles]
    ax1.legend(handles, labels, loc="upper center", ncol=2, frameon=False)

    save_figure(fig, out / "01_strategy_history.png", dpi)


def build_performance_table(
    annual_perf: pd.DataFrame,
    summary: dict,
    out: Path,
    dpi: int,
) -> pd.DataFrame:
    overall = summary["replication"]

    years = annual_perf["year"].astype(int).tolist()
    cols = ["自回测基日"] + [str(y) for y in years]

    def lookup(row, key):
        return float(row[key])

    data = {
        "指标": ["年化收益率", "年化波动率", "夏普比率", "最大回撤"],
        "自回测基日": [
            f"{overall['annualized_return']:.2%}",
            f"{overall['annualized_volatility']:.2%}",
            f"{overall['sharpe']:.2f}",
            f"{abs(overall['max_drawdown']):.2%}",
        ],
    }

    for _, r in annual_perf.iterrows():
        y = str(int(r["year"]))
        data[y] = [
            f"{lookup(r, 'replication_annualized_return'):.2%}",
            f"{lookup(r, 'replication_annualized_volatility'):.2%}",
            f"{lookup(r, 'replication_sharpe'):.2f}",
            f"{abs(lookup(r, 'replication_max_drawdown')):.2%}",
        ]

    table_df = pd.DataFrame(data)
    table_df.to_csv(out / "02_strategy_performance_table.csv", index=False, encoding="utf-8-sig")
    make_table_png(
        table_df,
        "策略历史表现表",
        out / "02_strategy_performance_table.png",
        dpi,
        fontsize=9.5,
        row_scale=1.6,
        figsize=(16, 4.8),
    )
    return table_df


def rolling_forward_returns(nav: pd.Series, horizon: int) -> pd.Series:
    # One observation for every valid starting date.
    return nav.shift(-horizon) / nav - 1.0


def build_win_rate_table(daily: pd.DataFrame, out: Path, dpi: int) -> pd.DataFrame:
    nav = nav_from_returns(daily).reset_index(drop=True)

    horizons = [
        ("日度", 1),
        ("周度", 5),
        ("月度", 21),
        ("季度", 63),
        ("半年度", 126),
        ("年度", 252),
        ("18个月", 378),
        ("两年度", 504),
    ]

    cols = {}
    for label, h in horizons:
        r = rolling_forward_returns(nav, h).dropna()
        up = r[r > 0]
        down = r[r < 0]
        denom = len(up) + len(down)
        cols[label] = {
            "上涨次数": int(len(up)),
            "下跌次数": int(len(down)),
            "胜率": (len(up) / denom) if denom else np.nan,
            "上涨平均收益": up.mean() if len(up) else np.nan,
            "下跌平均收益": down.mean() if len(down) else np.nan,
        }

    rows = ["上涨次数", "下跌次数", "胜率", "上涨平均收益", "下跌平均收益"]
    data = {"指标": rows}
    for label, _ in horizons:
        x = cols[label]
        data[label] = [
            f"{x['上涨次数']:,}",
            f"{x['下跌次数']:,}",
            "—" if pd.isna(x["胜率"]) else f"{x['胜率']:.2%}",
            "—" if pd.isna(x["上涨平均收益"]) else f"{x['上涨平均收益']:.2%}",
            "—" if pd.isna(x["下跌平均收益"]) else f"{x['下跌平均收益']:.2%}",
        ]

    result = pd.DataFrame(data)
    result.to_csv(out / "03_strategy_win_rate_table.csv", index=False, encoding="utf-8-sig")
    make_table_png(
        result,
        "策略胜率测算表",
        out / "03_strategy_win_rate_table.png",
        dpi,
        fontsize=10,
        row_scale=1.6,
        figsize=(14, 5.2),
    )
    return result


def build_class_contribution_chart(annual_class: pd.DataFrame, out: Path, dpi: int) -> None:
    df = annual_class.copy()
    df["year"] = df["year"].astype(int)
    for c in ["Equity", "Bond", "Commodity"]:
        if c not in df.columns:
            raise ValueError(f"annual_class_contribution.csv missing {c}")

    years = df["year"].to_numpy()
    x = np.arange(len(years))
    width = 0.25

    fig, ax = plt.subplots(figsize=(14, 7))
    bars = []
    bars.append(ax.bar(x - width, df["Equity"] * 100, width, label="股票"))
    bars.append(ax.bar(x, df["Bond"] * 100, width, label="债券"))
    bars.append(ax.bar(x + width, df["Commodity"] * 100, width, label="商品"))
    ax.axhline(0, linewidth=0.8)
    ax.set_xticks(x, years)
    ax.set_ylabel("年度收益贡献（百分点）")
    ax.set_title("业绩归因：大类资产年度收益贡献")
    ax.legend(frameon=False, ncol=3)

    save_figure(fig, out / "04_class_annual_contribution.png", dpi)


def build_asset_contribution_table(annual_asset: pd.DataFrame, out: Path, dpi: int) -> pd.DataFrame:
    df = annual_asset.copy()
    df["year"] = df["year"].astype(int)
    df = df.set_index("year")

    years = [c for c in df.index]
    rows = []
    for asset in ASSETS:
        if asset not in df.columns:
            continue
        row = {"资产": ASSET_CN[asset]}
        for y in years:
            row[str(y)] = f"{float(df.loc[y, asset]):.2%}"
        rows.append(row)

    result = pd.DataFrame(rows)
    result.to_csv(out / "05_asset_annual_contribution_table.csv", index=False, encoding="utf-8-sig")
    make_table_png(
        result,
        "业绩归因：年度资产收益贡献表",
        out / "05_asset_annual_contribution_table.png",
        dpi,
        fontsize=8.7,
        row_scale=1.45,
        figsize=(16, 8),
    )
    return result


def add_asset_class(frame: pd.DataFrame) -> pd.DataFrame:
    x = frame.copy()
    if "asset_class" in x.columns and x["asset_class"].notna().all():
        x["_class"] = x["asset_class"].replace(
            {"equity": "Equity", "bond": "Bond", "commodity": "Commodity"}
        )
        return x

    mapping = {}
    for cls, assets in CLASSES.items():
        for asset in assets:
            mapping[asset] = cls
    x["_class"] = x["asset"].map(mapping)
    return x


def build_class_holdings_chart(
    weights: pd.DataFrame,
    contrib: pd.DataFrame,
    out: Path,
    vol_window: int,
    dpi: int,
) -> pd.DataFrame:
    w = add_asset_class(weights)
    c = add_asset_class(contrib)

    exposure = (
        w.groupby(["date", "_class"])["weight_start_of_day"]
        .sum()
        .unstack("_class")
        .sort_index()
        .reindex(columns=["Equity", "Bond", "Commodity"])
    )

    class_ret = (
        c.groupby(["date", "_class"])["asset_contribution"]
        .sum()
        .unstack("_class")
        .sort_index()
        .reindex(columns=["Equity", "Bond", "Commodity"])
    )
    class_vol = class_ret.rolling(vol_window, min_periods=vol_window).std(ddof=1) * np.sqrt(252)

    export = exposure.copy()
    export.columns = [f"{c}_exposure" for c in export.columns]
    for cls in ["Equity", "Bond", "Commodity"]:
        export[f"{cls}_vol_{vol_window}d"] = class_vol[cls]
    export.reset_index().to_csv(out / "06_class_historical_holdings.csv", index=False, encoding="utf-8-sig")

    fig, ax1 = plt.subplots(figsize=(15, 7))
    exposure_handles = []
    for cls in ["Equity", "Bond", "Commodity"]:
        h, = ax1.plot(exposure.index, exposure[cls], linewidth=1.4, label=f"{CLASS_CN[cls]}权重")
        exposure_handles.append(h)

    ax1.set_ylabel("组合权重")
    ax1.set_title("资产大类历史持仓")
    ax1.axhline(0, linewidth=0.7)

    ax2 = ax1.twinx()
    vol_handles = []
    for cls in ["Equity", "Bond", "Commodity"]:
        h, = ax2.plot(
            class_vol.index,
            class_vol[cls],
            linestyle="--",
            linewidth=1.0,
            alpha=0.8,
            label=f"{CLASS_CN[cls]}{vol_window}天波动率",
        )
        vol_handles.append(h)
    ax2.set_ylabel("年化波动率")
    ax2.yaxis.set_major_formatter(lambda v, pos: f"{v:.0%}")

    handles = exposure_handles + vol_handles
    ax1.legend(handles, [h.get_label() for h in handles], loc="upper center", ncol=3, frameon=False)

    save_figure(fig, out / "06_class_historical_holdings.png", dpi)
    return export


def compute_drawdown_episodes(daily: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(daily["date"]).reset_index(drop=True)
    ret = pd.to_numeric(daily["portfolio_return_net"], errors="coerce").fillna(0.0).reset_index(drop=True)
    nav = (1.0 + ret).cumprod()

    # Explicit initial high-water mark before the first formal-window return.
    peak_val = 1.0
    peak_idx = -1
    peak_date = dates.iloc[0] - pd.Timedelta(days=1)

    in_dd = False
    trough_idx = None
    trough_date = None
    worst = 0.0
    episodes = []

    for i, (d, value) in enumerate(zip(dates, nav)):
        value = float(value)
        if value >= peak_val:
            if in_dd:
                recovery_idx = i
                episodes.append(
                    {
                        "peak_idx": peak_idx,
                        "trough_idx": trough_idx,
                        "recovery_idx": recovery_idx,
                        "peak_date": peak_date,
                        "trough_date": trough_date,
                        "recovery_date": d,
                        "max_drawdown": worst,
                    }
                )
                in_dd = False
            peak_val = value
            peak_idx = i
            peak_date = d
            trough_idx = None
            trough_date = None
            worst = 0.0
        else:
            dd = value / peak_val - 1.0
            if not in_dd:
                in_dd = True
                worst = dd
                trough_idx = i
                trough_date = d
            elif dd < worst:
                worst = dd
                trough_idx = i
                trough_date = d

    if in_dd:
        episodes.append(
            {
                "peak_idx": peak_idx,
                "trough_idx": trough_idx,
                "recovery_idx": None,
                "peak_date": peak_date,
                "trough_date": trough_date,
                "recovery_date": pd.NaT,
                "max_drawdown": worst,
            }
        )

    ep = pd.DataFrame(episodes)
    if ep.empty:
        return ep

    def duration(row):
        p = int(row["peak_idx"])
        t = int(row["trough_idx"])
        return t - p if p >= 0 else t + 1

    def recovery_days(row):
        if pd.isna(row["recovery_idx"]):
            return np.nan
        return int(row["recovery_idx"]) - int(row["trough_idx"])

    ep["drawdown_days"] = ep.apply(duration, axis=1)
    ep["recovery_days"] = ep.apply(recovery_days, axis=1)
    ep = ep.sort_values("max_drawdown", ascending=True).reset_index(drop=True)
    return ep


def build_drawdown_outputs(daily: pd.DataFrame, out: Path, dpi: int) -> pd.DataFrame:
    episodes = compute_drawdown_episodes(daily)
    if episodes.empty:
        raise ValueError("No drawdown episodes found.")

    top5 = episodes.head(5).copy()
    top5_export = top5[
        ["peak_date", "trough_date", "max_drawdown", "recovery_date", "drawdown_days", "recovery_days"]
    ].copy()
    top5_export.columns = [
        "回撤起始日期",
        "回撤结束日期",
        "最大回撤",
        "再创新高日期",
        "回撤天数",
        "再创新高天数",
    ]
    top5_export.to_csv(out / "08_top5_drawdowns_table.csv", index=False, encoding="utf-8-sig")

    # Plot.
    x = daily.copy()
    x["nav"] = nav_from_returns(x)
    fig, ax = plt.subplots(figsize=(15, 7))
    ax.plot(x["date"], x["nav"], linewidth=1.7, label="策略净值")

    for _, r in top5.iterrows():
        start = pd.Timestamp(r["peak_date"])
        end = pd.Timestamp(r["trough_date"])
        ax.axvspan(start, end, alpha=0.16)
        trough_nav = x.loc[x["date"].eq(end), "nav"]
        if len(trough_nav):
            ax.annotate(
                f"{r['max_drawdown']:.2%}",
                xy=(end, float(trough_nav.iloc[0])),
                xytext=(0, -24),
                textcoords="offset points",
                ha="center",
                va="top",
                fontsize=9,
            )

    ax.set_title("历史回测前五大回撤")
    ax.set_ylabel("净值")
    ax.legend(frameon=False)
    save_figure(fig, out / "07_top5_drawdowns.png", dpi)

    # Table image.
    display = top5_export.copy()
    for c in ["回撤起始日期", "回撤结束日期", "再创新高日期"]:
        display[c] = pd.to_datetime(display[c], errors="coerce").dt.strftime("%Y/%-m/%-d")
        display[c] = display[c].fillna("—")
    display["最大回撤"] = pd.to_numeric(display["最大回撤"]).map(lambda x: f"{x:.2%}")
    display["回撤天数"] = pd.to_numeric(display["回撤天数"]).map(lambda x: f"{int(x)}")
    display["再创新高天数"] = display["再创新高天数"].map(
        lambda x: "—" if pd.isna(x) else f"{int(x)}"
    )

    make_table_png(
        display,
        "历史回测前五大回撤表",
        out / "08_top5_drawdowns_table.png",
        dpi,
        fontsize=10,
        row_scale=1.6,
        figsize=(13, 5.2),
    )
    return top5_export


def main() -> None:
    configure_chinese_font()
    default_root = resolve_default_root()

    parser = argparse.ArgumentParser(
        description="Build 8 real Phase 3 formal-backtest visualizations."
    )
    parser.add_argument("--project-root", default=str(default_root))
    parser.add_argument(
        "--input-dir",
        default="data/processed/phase3_formal",
        help="Relative to project root unless absolute.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed/phase3_visuals",
        help="Relative to project root unless absolute.",
    )
    parser.add_argument(
        "--vol-window",
        type=int,
        default=120,
        help="Display-only realized-volatility window. Does NOT change the strategy.",
    )
    parser.add_argument("--dpi", type=int, default=220)
    args = parser.parse_args()

    root = Path(args.project_root).expanduser().resolve()
    input_dir = Path(args.input_dir).expanduser()
    if not input_dir.is_absolute():
        input_dir = root / input_dir
    output_dir = Path(args.output_dir).expanduser()
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    daily, weights, contrib, annual_perf, annual_class, annual_asset, summary = load_inputs(input_dir)

    build_strategy_history(daily, output_dir, args.vol_window, args.dpi)
    build_performance_table(annual_perf, summary, output_dir, args.dpi)
    build_win_rate_table(daily, output_dir, args.dpi)
    build_class_contribution_chart(annual_class, output_dir, args.dpi)
    build_asset_contribution_table(annual_asset, output_dir, args.dpi)
    build_class_holdings_chart(weights, contrib, output_dir, args.vol_window, args.dpi)
    top5 = build_drawdown_outputs(daily, output_dir, args.dpi)

    manifest = {
        "source_directory": str(input_dir),
        "output_directory": str(output_dir),
        "formal_window": summary.get("formal_window"),
        "replication_summary": summary.get("replication"),
        "display_volatility_window_days": args.vol_window,
        "strategy_10vt_window_days": 120,
        "display_volatility_note": (
            "Displayed realized volatility and V2 strategy 10VT both use 120 trading days."
        ),
        "win_rate_horizons_trading_days": {
            "日度": 1,
            "周度": 5,
            "月度": 21,
            "季度": 63,
            "半年度": 126,
            "年度": 252,
            "18个月": 378,
            "两年度": 504,
        },
        "win_rate_definition": (
            "For each valid starting trading day: NAV[t+h]/NAV[t]-1. "
            "Win rate = positive / (positive + negative); zero-return windows are excluded."
        ),
        "drawdown_day_definition": (
            "Trading-observation distance from prior high-water mark to trough; "
            "recovery days are trading-observation distance from trough to recovery."
        ),
        "files": [
            "01_strategy_history.png",
            "02_strategy_performance_table.png",
            "03_strategy_win_rate_table.png",
            "04_class_annual_contribution.png",
            "05_asset_annual_contribution_table.png",
            "06_class_historical_holdings.png",
            "07_top5_drawdowns.png",
            "08_top5_drawdowns_table.png",
        ],
        "top5_drawdowns": top5.to_dict(orient="records"),
        "network_requests": 0,
        "ifind_requests": 0,
    }
    (output_dir / "visualization_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    print("DONE")
    print(f"Input : {input_dir}")
    print(f"Output: {output_dir}")
    for name in manifest["files"]:
        print(f"  - {output_dir / name}")


if __name__ == "__main__":
    main()
