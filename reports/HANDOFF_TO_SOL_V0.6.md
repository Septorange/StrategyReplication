# Handoff to Sol — Strategy Lab V0.6

本文件是开发交接声明。开发测试与工程 reviewer 复核不等于最终独立审计；Sol High 应视本报告为待验证声明，重新计算并核查。禁止直接根据 PASS 字样宣布最终审计通过。

```text
PROJECT_PATH=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics
V6_BASE_PATH=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现6
RUN_COMMAND=./run_local.sh
LOCAL_URL=http://127.0.0.1:8003
SOURCE_HASHES_BEFORE=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics/reports/V0.6_BASELINE_INTEGRITY_BEFORE.json
SOURCE_HASHES_AFTER=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics/reports/V0.6_BASELINE_INTEGRITY_AFTER.json
ANALYTICS_SNAPSHOT=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics/data/v6_analytics/manifest.json
PARAMETER_CAPABILITY_MATRIX=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics/reports/V0.6_PARAMETER_CAPABILITY_MATRIX.md
CHART_TABLE_AUDIT=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics/reports/V0.6_CHART_TABLE_AUDIT.md
TEST_REPORT=/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics/reports/V0.6_TEST_REPORT.md
PASS_TEST_COUNT=41
FAIL_TEST_COUNT=0
SKIP_TEST_COUNT=0
REAL_EXPERIMENTS_RUN=target10,target12,commodity_cost_bps5; UI target12 and 8/10/12 scan evidence in browser report
DISABLED_PARAMS=momentum_excluded_count,risk_budget_vol_window,short_vol_windows,asset_long_vol_window,quantile_lookback
KNOWN_BLOCKERS=No material engineering blocker identified; final Sol High audit pending
KNOWN_LIMITATIONS=No genuine P1-P4 upstream adapter; no in-flight browser cancellation; fixed formal window; inherited expiry/data-quality states; commodity0bps assumption pending verification; hypothetical negative-first-NAV episode requires pre-window date-anchor policy
FINAL_SOL_AUDIT=NOT_VERIFIED
```

## 优先独立复核

核实原始七参数语义，特别 P2 sigma240、P3 max20/60、P4 long240 与高级参数的区别。确认 disabled 值改动被拒绝，未知字段 HTTP422。

从 canonical Parquet 重算 NAV/净收益、年度复合、全期年化、八个 n-h 窗口、zero 处理、三类/逐资产 pp 贡献、日初敞口及 rolling120 std。检查前119 null 与日期筛选顺序，Top5 图与表同源，峰谷/恢复交易日和未恢复 null。

核实 Phase3B 真引擎、完整前序预热与 prior-only 10VT。比较 current fingerprint 真实实验与正式 baseline；独立证明商品 roll/rebalance 双层费用，gross/held contract 未变。

核实浏览器真实 A/B、日期/年度/资产/回撤联动、CSV与PNG文件的单位/版本/口径、READY扫描与取消/timeout状态。确认V6和旧站hash不变。

审计遵循 Audit first → minimum fix → Reaudit，不重构整个项目。已修复的工程问题及复算证据见 V0.6_ENGINEERING_REVIEW.md。

## 可复算命令

在 PROJECT_PATH 执行：

```bash
/opt/anaconda3/bin/python -m pytest -q
../.venv/bin/python scripts/validate_v6_analytics.py
../.venv/bin/python scripts/validate_v06_experiments.py
./run_local.sh
```

若8003已有本交付服务在运行，最后一条会明确返回端口占用；直接访问已有页面。两条 validator 使用 parent arm64 venv 读取 canonical Parquet。不要使用Web运行时强行重写源Parquet。
