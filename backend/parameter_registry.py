"""Capability discovery for the immutable V6 adapter, not a promise of Phase3A replay."""
from .config import V6_BASE

def parameter_capabilities():
    unavailable='当前 V6 适配器尚未支持此项真实重跑；冻结 Phase3A 输入不能用于改变上游参数。'
    original=[
        (1,'momentum_excluded_count','动量剔除末位数量',1,'DISABLED','Phase3A rank_and_select','完整动量排名、月度选择与基础目标权重'),
        (2,'risk_budget_vol_window','风险预算波动率窗口',240,'DISABLED','Phase3A allocate_base_target_weights','完整 sigma_240、risk budget、base_target_weights'),
        (3,'short_vol_windows','单资产短期波动率窗口',[20,60],'DISABLED','Phase3B single_asset_vol_control','V6 baseline max(20D,60D)，未提供窗口变更适配器'),
        (4,'asset_long_vol_window','单资产长期波动率窗口',240,'DISABLED','Phase3B long_vol / historical threshold','vol240 与历史阈值预热；冻结函数固定 long_vol=vol240'),
        (5,'haircut','单资产减仓比例',.5,'READY','Phase3B vol_control → execution → portfolio','重算单资产触发后 multiplier（0.5 = 减仓50%）'),
        (6,'midmonth_threshold','月中再平衡阈值',.2,'READY','Phase3B execution → portfolio','目标/现持仓绝对差之和，次交易日执行'),
        (7,'target_vol','组合目标波动率',.1,'READY','Phase3B execution → portfolio','完整前序 pre-10VT returns, prior-only estimator, bounds [0.5,1.5]'),
    ]
    items=[dict(number=n,key=k,label=l,baseline=b,status=s,reason=unavailable if s=='DISABLED' else '真实冻结 V6 Python 函数重算',stage=st,required_upstream=u) for n,k,l,b,s,st,u in original]
    items[2]['baseline_label']='20D / 60D 双窗口取最大值（V6 实现）';items[2]['short_vol_windows']=[20,60]
    advanced=[dict(key='vt_window',label='10VT估计窗口',baseline=120,status='READY',allowed_values=[60,120,240],stage='Phase3B execution',reason='prior-only pre-10VT returns'),dict(key='quantile',label='减仓触发分位数',baseline=.9,status='READY',stage='Phase3B vol_control',reason='真实历史阈值重算'),dict(key='quantile_lookback',label='长期波动率分位数观察期',baseline=240,status='DISABLED',stage='Phase3B vol_control',reason='当前适配器保留冻结240D观察期，未开放改变预热口径'),dict(key='commodity_cost_bps',label='商品换月+再平衡成本',baseline=0,status='READY',allowed_values=[0,2,5,10],stage='Phase2 cost overlay + Phase3B portfolio',reason='两层成本均生效；baseline 0bps PENDING_VERIFICATION')]
    return dict(strategy_version='V6',original=items,advanced=advanced,display=[dict(key='display_vol_window',baseline=120,status='DISPLAY_ONLY'),dict(key='win_rate_horizon',baseline=[1,5,21,63,126,252,378,504],status='STATISTICS_ONLY'),dict(key='selected_class',status='VIEW_ONLY'),dict(key='selected_asset',status='VIEW_ONLY'),dict(key='analysis_from',status='VIEW_ONLY'),dict(key='analysis_to',status='VIEW_ONLY')],adapter_status='FROZEN_V6_FUNCTIONS_WITH_RESEARCH_ADAPTER_PENDING_INDEPENDENT_AUDIT',engine=str(V6_BASE/'src/phase3b.py'))


def unsupported(config):
    locked={'momentum_excluded_count':1,'risk_budget_vol_window':240,'asset_short_vol_window':20,'short_vol_windows':[20,60],'asset_long_vol_window':240,'quantile_lookback':240}
    for key,baseline in locked.items():
        if config.get(key) is not None and config[key]!=baseline: return key+': 当前 V6 适配器尚未支持此项真实重跑；baseline='+str(baseline)
    if config['vt_window'] not in (60,120,240): return 'vt_window must be 60, 120 or 240'
    if config['commodity_cost_bps'] not in (0,2,5,10): return 'commodity_cost_bps must be 0, 2, 5 or 10'
    return None
