# Strategy Lab V0.6 · Research Analytics

独立于 V0.5.1 的本地研究网站。冻结 V6 已审计基准与 V0.6 新分析/可视化层使用不同审计标签；V0.6 开发验证不等于 Sol 独立审计。

## 启动

```bash
cd '/Users/lijiayi/Desktop/实习——中金财富/资产配置模型/资产配置模型复现/Strategy_Lab_V0.6_Research_Analytics'
./run_local.sh
```

默认地址 http://127.0.0.1:8003。原 8000/8001/8002 保留。端口已占用会明确退出，可显式选择 `PORT=8013 ./run_local.sh` 或 `./run_local.sh --port 8013`。Web 运行时沿用本机 `/opt/anaconda3/bin/python`；真实 V6 引擎和 canonical Parquet 导出使用父工程 `.venv/bin/python` 的 arm64 环境。

## Mode A：八组真实统计

历史 NAV 与展示波动率、全期/分年度表现、八持有期重叠胜率、大类年度贡献、11资产年度贡献、大类开盘名义敞口与贡献波动率、Top5回撤图、Top5回撤表。均从冻结 V6 正式窗口 2015-09-30 至 2024-11-20 构建，不读旧版本参考 CSV。

每张图可 hover/click 研究日，年度贡献与回撤链接设置共享研究区间。CSV 标识 V6/区间/方法；单位区分收益百分比、简单贡献百分点 pp、名义敞口 x。日期/资产/类别是视图过滤，不改变真实 baseline。

## Mode B：原文七参数与能力说明

P1 动量剔除末位数量、P2 风险预算波动率窗口、P3 单资产短期波动率双窗口、P4 单资产长期波动率窗口、P5 haircut、P6 月中阈值、P7 组合目标波动率全部保留原文身份。

当前安全引擎链支持 P5/P6/P7。P1-P4 默认保留 V6 baseline 值并禁用非基准重跑，因为本轮没有经过独立审计的完整上游重算适配器。P3 V6 baseline 为 max(vol20,vol60)，P2 为 sigma240，P4 为240D。

高级可运行项为 vt_window 60/120/240、quantile、commodity_cost 0/2/5/10bps。商品成本同时进入合约换月和组合权重再平衡；0bps 仍为待官方验证的复现假设。图表波动率窗口、胜率窗口、日期和类别独立作为统计/展示控制。

A/B 真实实验调用 unchanged V6 Python，写入本项目 experiment_cache。单参数扫描只运行 READY 候选，用户显式点击后逐个 POST；取消停止后续候选，当前已经开始的服务端回测可能仍需完成。不存在 synthetic scaling 或自动寻优。

## 方法、证据与交接

- docs/V0.6_ANALYTICS_METHODS.md
- reports/V0.6_PARAMETER_CAPABILITY_MATRIX.md
- reports/V0.6_SOURCE_MAPPING.md
- reports/V0.6_BASELINE_RECONCILIATION.csv
- reports/V0.6_CHART_TABLE_AUDIT.md
- reports/V0.6_TEST_REPORT.md
- reports/HANDOFF_TO_SOL_V0.6.md

胜率窗口高度重叠，长期100%不能解释为独立预测准确率；年度贡献是日贡献简单求和，与年度复合收益口径不同；净收益展示vol与10VT使用的pre-10VT gross prior-only sigma不同。缺失、未上市和未恢复状态保持显式。

## 验证与只读边界

```bash
/opt/anaconda3/bin/python -m pytest -q
../.venv/bin/python scripts/validate_v6_analytics.py
../.venv/bin/python scripts/validate_v06_experiments.py
```

V6和V0.5.1关键文件前后哈希记于 reports/V0.6_BASELINE_INTEGRITY_BEFORE.json 与 AFTER.json。所有市场输入只读，本任务不访问iFinD、不下载行情、不改正式V6/旧网站。
