# Phase 2.1 WIP checkpoint

日期：2026-10-13

本轮已停止功能开发、反复测试和 Sol 调用。当前分支为 `feature/v07-phase2-experiment-library`，代码修复父提交为 `b58272ab1ecbe25c3b9c8d7e34f3f9e9a37afc34`，本地 checkpoint 提交为 `f0eb4036ec87d60aa2a9f13aa074e6a1529ec586`；之后仅补充了本段 SHA 说明。

已保存的工作包括：Phase 2.1 的 F01–F06 修复链、严格缓存产物校验、保存评估窗口恢复、API 路径脱敏、方案库管理、真实逐日比较、分类/资产贡献聚合、换手阶段数据读取、缺失收益的闭合检查，以及审计交接和冻结文件清单。SQLite 实验方案、运行缓存和既有报告均保留在本机。

已通过：`PYTHONPATH=. /opt/anaconda3/bin/python -m pytest -q`，65 passed；`node --check frontend/app.js`；Python `py_compile`；`git diff --check`。8005 已启动在当前工作目录，健康接口在宿主机检查中返回 200；8003 和 8004 未修改、未重启。

剩余状态：本轮未完成全部独立浏览器矩阵；Sol 终审在额度控制前停止，不能据此宣称 Phase 2.1 最终验收或 PASS。历史已跟踪的 80 个 `experiment_cache` 文件仍需未来推送前单独审查；未执行删除、脱离跟踪、历史改写或数据清理。未推送 GitHub，未合并 `main`，未提交行情数据、SQLite、运行缓存或密钥。

下次继续的最少步骤：确认服务仍绑定 8005；以 `b58272a` 为精确审计对象重新运行一次独立 Sol 审计和必要的串行浏览器检查；根据审计结论做最小修复或验收。不要从旧的 `75dcc08` 审计报告推断当前 HEAD 的结论。
