from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'frontend/index.html').read_text()
js=(ROOT/'frontend/app.js').read_text()
css=(ROOT/'frontend/styles.css').read_text()

def test_research_workstation_navigation_and_demo_off():
    for x in ['策略全景','决策解释','事件研究','收益归因','执行与换月','参数实验','版本比较','数据与审计']:
        assert x in js
    assert 'window.DEMO_MODE=false' in html
    assert 'Research Analytics' in html
    for x in ['表现与胜率','年度收益归因','持仓与风险','回撤研究','risk_budget_vol_window','short_vol_windows','momentum_excluded_count',"analytics('history'",'/api/experiment/parameters','data-export-png','sensitivityParam']:
        assert x in html+js
    assert 'V0.6 ANALYTICS · 待独立审计' in html

def test_research_context_is_global_and_experiment_uses_api():
    for x in ['strategyVersion','selectedDate','fromDate','toDate','selectedAsset','selectedEventId']:
        assert x in js
    assert "api('/api/experiment'" in js
    for forbidden in ['getDailyAssetRet','generateLegacy','simulateStrategy','generateExperiment','Math.random']:
        assert forbidden not in js

def test_decision_pipeline_and_audit_ui_present():
    for x in ['Eligibility','Momentum','Risk Budget','Sleeve Scale','Haircut','Execution','10VT','Daily PnL','Field Lineage']:
        assert x in js
    assert '.pipeline' in css and '.event-layout' in css and '.lineage-grid' in css
