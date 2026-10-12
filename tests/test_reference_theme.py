"""V0.5.1 visual shell regression: reference aesthetic; real APIs only."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'frontend/index.html').read_text()
JS=(ROOT/'frontend/app.js').read_text()
CSS=(ROOT/'frontend/styles.css').read_text()

def test_reference_layout_and_navigation():
    for x in ['mode-choices','workspace-body','rightcol','research-context','historyScrub','overview-featured']:
        assert x in HTML+JS+CSS
    for x in ['策略复盘','参数实验','决策解释','事件研究','收益归因']:
        assert x in HTML+JS
    assert 'Strategy Lab · V0.6 Research Analytics' in HTML
    assert 'styles.css?v=0.6.0' in HTML

def test_reference_does_not_reintroduce_synthetic_strategy():
    assert 'window.DEMO_MODE=false' in HTML
    assert "api('/api/experiment'" in JS
    for forbidden in ['getDailyAssetRet','generateLegacy','simulateStrategy','Math.random','Math.sin']:
        assert forbidden not in JS
    assert 'data-chart-select' in JS
    assert 'selectedDate' in JS

def test_reference_palette_is_light_canvas_and_navy_sidebar():
    assert '--nav:#142339' in CSS
    assert '--bg:#f5f7fb' in CSS
    assert '--panel:#fff' in CSS
    assert '.rightcol' in CSS
