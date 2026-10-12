from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .utils import records

RISK_ASSETS = ['IF', 'IC', 'IM', 'SC', 'FG', 'I', 'M', 'AU', 'CU']
FIXED_ASSETS = ['TF', 'T']


@dataclass(frozen=True)
class VersionInfo:
    version: str
    label: str
    available: bool
    audited: bool
    status: str


VERSIONS = [
    VersionInfo('V5', 'V5', False, False, 'NOT_CONNECTED'),
    VersionInfo('V6', 'V6', True, True, 'AUDITED_BASELINE'),
    VersionInfo('V7', 'V7', False, False, 'NOT_CONNECTED'),
    VersionInfo('V8', 'V8', False, False, 'NOT_CONNECTED'),
]


LINEAGE = [
    ('monthly_base_target', 'daily_asset_state.monthly_base_target', 'phase3_formal/daily_weights.csv', 'monthly_base_target', 'direct', 'monthly pre-haircut capped target'),
    ('controlled_target', 'daily_asset_state.controlled_target', 'phase3_formal/daily_weights.csv', 'controlled_target', 'direct', 'frozen month-end controlled target during smoothing; close theory otherwise'),
    ('unscaled_execution_weight', 'daily_asset_state.unscaled_execution_weight', 'phase3_formal/daily_weights.csv', 'unscaled_execution_weight', 'direct', 'actual start-of-day unscaled execution'),
    ('final_weight', 'daily_asset_state.final_weight', 'phase3_formal/daily_weights.csv', 'final_weight', 'direct', 'unscaled execution × prior-only 10VT'),
    ('class_budget', 'daily_asset_state.class_budget', 'phase3a/target_weights.parquet', 'class_budget', 'direct', 'latest effective monthly row; fixed 1/3'),
    ('asset_budget', 'daily_asset_state.asset_budget', 'phase3a/target_weights.parquet', 'relative_asset_budget', 'derived', 'selected 1/(3*N_class), unselected 0'),
    ('risk_vol', 'daily_asset_state.risk_vol', 'phase3a/target_weights.parquet', 'risk_vol', 'direct', 'monthly as-of risk volatility'),
    ('rb_weight', 'daily_asset_state.rb_weight', 'phase3a/target_weights.parquet', 'raw_weight_before_scale', 'derived', 'asset_budget / risk_vol'),
    ('sleeve_scale', 'daily_asset_state.sleeve_scale', 'phase3a/target_weights.parquet', 'sleeve_scale', 'direct', 'equity .4, bond 1, commodity .8'),
    ('scaled_raw_weight', 'daily_asset_state.scaled_raw_weight', 'phase3a/target_weights.parquet', 'raw_weight_after_scale', 'derived', 'rb_weight × sleeve_scale; before cap'),
    ('cap', 'daily_asset_state.cap', 'phase3a/target_weights.parquet', 'cap', 'direct', 'single-asset cap'),
    ('post_cap_weight', 'daily_asset_state.post_cap_weight', 'phase3a/target_weights.parquet', 'post_cap_weight', 'direct', 'min(scaled_raw_weight, cap)'),
    ('post_haircut_weight', 'daily_asset_state.post_haircut_weight', 'phase3_formal/daily_weights.csv', 'monthly_base_target,single_asset_haircut', 'derived', 'current-close diagnostic target'),
    ('pre10vt_weight', 'daily_asset_state.pre10vt_weight', 'phase3_formal/daily_weights.csv', 'unscaled_execution_weight', 'derived', 'start-of-day execution before 10VT'),
    ('portfolio_vol_estimate', 'daily_asset_state.portfolio_vol_estimate', 'phase3_formal/daily_weights.csv', 'portfolio_vol_estimate', 'direct', 'previous 120 unscaled gross portfolio returns × sqrt252'),
    ('raw_10vt_multiplier', 'daily_asset_state.raw_10vt_multiplier', 'phase3_formal/daily_weights.csv', 'raw_10vt_multiplier', 'direct', '.10 / prior-only sigma120'),
    ('final_10vt_multiplier', 'daily_asset_state.final_10vt_multiplier', 'phase3_formal/daily_weights.csv', 'final_10vt_multiplier', 'direct', 'clip(raw, .5, 1.5)'),
    ('trade_return_gross', 'daily_asset_state.trade_return_gross', 'phase2/trade_returns.parquet', 'trade_return_gross', 'direct', 'same-contract settlement return; old start-of-day holding'),
    ('trade_return_net', 'daily_asset_state.trade_return_net', 'phase2/trade_returns.parquet', 'trade_return_net', 'direct', 'gross minus contract roll cost'),
    ('roll_cost', 'daily_asset_state.roll_cost', 'phase2/trade_returns.parquet', 'roll_cost', 'direct', 'contract turnover × bps / 10000'),
    ('rebalance_cost', 'daily_asset_state.rebalance_cost', 'phase3_formal/daily_asset_contribution.csv', 'rebalance_cost', 'direct', '.5 × abs(end-start) × class bps / 10000'),
    ('asset_contribution', 'daily_asset_state.asset_contribution', 'phase3_formal/daily_asset_contribution.csv', 'asset_contribution', 'direct', 'start weight × trade_return_net − rebalance cost'),
]


class ResearchService:
    def __init__(self, loader):
        self.l = loader
        self._drawdowns = self._build_drawdowns()
        self._events = self._build_events()

    def _require_v6(self, version: str):
        if version.upper() != 'V6':
            raise ValueError(f'{version} is not connected; V6 is the only audited baseline in V0.5')

    def versions(self):
        return {'versions': [v.__dict__ for v in VERSIONS], 'default': 'V6'}

    def lineage(self):
        return {'version': 'V6', 'status': 'AUDITED', 'fields': [
            {'field': f, 'snapshot': s, 'source_file': sf, 'source_column': sc, 'mapping': typ, 'meaning': meaning, 'audit_status': 'PASS'}
            for f, s, sf, sc, typ, meaning in LINEAGE
        ]}

    def data_quality(self):
        rolls = self.l.rolls
        expiry_source = rolls[rolls.get('expiry_source', pd.Series(index=rolls.index, dtype=object)).eq('EXPIRY_UNVERIFIED_EXCEPTION')]
        expiry = rolls[rolls.get('status', pd.Series(index=rolls.index, dtype=object)).eq('EXPIRY_UNVERIFIED')]
        prelisting = self.l.assets[
            self.l.assets['signal_source'].isna() & self.l.assets['ret_20'].isna()
        ] if 'signal_source' in self.l.assets else pd.DataFrame()
        return {
            'expiry_unverified_count': int(len(expiry)),
            'expiry_unverified_by_asset': expiry.groupby('asset').size().to_dict() if len(expiry) else {},
            'expiry_exception_source_count': int(len(expiry_source)),
            'prelisting_null_signal_rows': int(len(prelisting)),
            'commodity_cost_status': self.l.rules.get('costs', {}).get('commodity_status', 'PENDING_VERIFICATION'),
        }

    def exposure_series(self, version: str, from_date=None, to_date=None):
        self._require_v6(version)
        x = self.l.assets[['date','asset_class','final_weight']].copy()
        if from_date:
            x = x[x.date >= pd.Timestamp(from_date)]
        if to_date:
            x = x[x.date <= pd.Timestamp(to_date)]
        wide = x.groupby(['date','asset_class']).final_weight.sum().unstack(fill_value=0).reset_index()
        for c in ['equity','bond','commodity']:
            if c not in wide:
                wide[c] = 0.0
        return {'version':'V6', 'rows':records(wide[['date','equity','bond','commodity']])}

    def decision(self, version: str, date: str, asset: str):
        self._require_v6(version)
        asset = asset.upper()
        d = self.l.resolve(date)
        day = self.l.assets[self.l.assets.date.eq(d)].copy()
        row = day[day.asset.eq(asset)]
        if row.empty:
            raise ValueError(f'asset {asset} not found on {d.date()}')
        r = row.iloc[0]
        risk = day[day.asset.isin(RISK_ASSETS)].copy()
        eligible_mask = (
            risk.trade_eligible.fillna(False).astype(bool)
            & risk.signal_usable.fillna(False).astype(bool)
            & risk.risk_estimate_usable.fillna(False).astype(bool)
        )
        eligible_risk = risk[eligible_mask]
        selected_risk = eligible_risk[eligible_risk.selected.fillna(False).astype(bool)] if 'selected' in eligible_risk else eligible_risk.iloc[0:0]
        excluded = sorted(set(eligible_risk.asset) - set(selected_risk.asset))
        unavailable = sorted(set(risk.asset) - set(eligible_risk.asset))
        class_rows = day[day.asset_class.eq(r.asset_class)]
        selected_class = class_rows[class_rows.selected.fillna(False).astype(bool)] if 'selected' in class_rows else class_rows

        def val(name, default=None):
            x = r.get(name, default)
            return None if pd.isna(x) else (x.item() if isinstance(x, np.generic) else x)

        portfolio_row = self.l.portfolio[self.l.portfolio.date.eq(d)].iloc[0]
        roll_row = self.l.rolls[(self.l.rolls.date.eq(d)) & (self.l.rolls.asset.eq(asset))]
        roll_info = records(roll_row)[0] if not roll_row.empty else None
        final_mult = val('final_10vt_multiplier')
        pre = val('pre10vt_weight')
        return {
            'version': 'V6',
            'requested_date': str(pd.Timestamp(date).date()),
            'resolved_date': str(d.date()),
            'asset': asset,
            'asset_class': val('asset_class'),
            'summary': {
                'selected': bool(val('selected', False)) if val('selected') is not None else None,
                'signal_source': val('signal_source'),
                'final_weight': val('final_weight'),
                'trade_return_net': val('trade_return_net'),
                'asset_contribution': val('asset_contribution'),
                'final_10vt_multiplier': final_mult,
            },
            'eligibility': {
                'trade_eligible': val('trade_eligible'),
                'signal_usable': val('signal_usable'),
                'risk_estimate_usable': val('risk_estimate_usable'),
                'signal_source': val('signal_source'),
            },
            'momentum': {
                'participates_in_elimination': asset in RISK_ASSETS,
                'signals': {k: val(k) for k in ['ret_20','ret_60','ret_240','sharpe_20','sharpe_60','sharpe_240']},
                'ranks': {k: val(k) for k in ['rank_ret20','rank_ret60','rank_ret240','rank_sharpe20','rank_sharpe60','rank_sharpe240']},
                'mean_rank': val('mean_rank'),
                'selected': val('selected'),
                'risk_universe_count': int(len(eligible_risk)),
                'selected_risk_assets': selected_risk.asset.tolist(),
                'excluded_risk_assets': excluded,
                'unavailable_risk_assets': unavailable,
            },
            'risk_budget': {
                'class_budget': val('class_budget'),
                'selected_in_class': int(len(selected_class)),
                'asset_budget': val('asset_budget'),
                'risk_vol': val('risk_vol'),
                'rb_weight': val('rb_weight'),
            },
            'sleeve_scale': {
                'scale': val('sleeve_scale'),
                'scaled_raw_weight': val('scaled_raw_weight'),
            },
            'cap': {
                'cap': val('cap'),
                'post_cap_weight': val('post_cap_weight'),
                'binding': bool(val('scaled_raw_weight') is not None and val('cap') is not None and val('scaled_raw_weight') > val('cap') + 1e-12),
                'redistributed': False,
            },
            'haircut': {
                'vol20': val('vol_20'),
                'vol60': val('vol_60'),
                'short_vol': val('short_vol'),
                'long_vol': val('long_vol'),
                'historical_threshold': val('historical_threshold'),
                'triggered': val('haircut_flag'),
                'multiplier': val('haircut_multiplier'),
                'post_haircut_weight': val('post_haircut_weight'),
            },
            'execution': {
                'current_close_theoretical_target': val('midmonth_theoretical_target'),
                'monthly_base_target': val('monthly_base_target'),
                'controlled_target': val('controlled_target'),
                'monthly_smoothing_state': val('monthly_smoothing_state'),
                'monthly_smoothing_step': val('monthly_smoothing_step'),
                'deviation': val('deviation'),
                'midmonth_trigger': val('midmonth_trigger'),
                'unscaled_execution_weight': val('unscaled_execution_weight'),
                'pre10vt_weight': pre,
                'time_semantics': 'close targets affect future execution; same-day PnL uses start-of-day execution weight',
            },
            '10vt': {
                'portfolio_vol_estimate': val('portfolio_vol_estimate'),
                'raw_multiplier': val('raw_10vt_multiplier'),
                'final_multiplier': final_mult,
                'target_vol': self.l.rules.get('10vt', {}).get('target_vol'),
                'window': self.l.rules.get('10vt', {}).get('min_history'),
                'lower_bound': self.l.rules.get('10vt', {}).get('multiplier_min'),
                'upper_bound': self.l.rules.get('10vt', {}).get('multiplier_max'),
            },
            'final_weight': {
                'pre10vt_weight': pre,
                'multiplier': final_mult,
                'final_weight': val('final_weight'),
                'identity_error': None if pre is None or final_mult is None or val('final_weight') is None else float(abs(pre*final_mult-val('final_weight'))),
            },
            'pnl': {
                'weight_start_of_day': val('weight_start_of_day'),
                'trade_return_gross': val('trade_return_gross'),
                'roll_cost': val('roll_cost'),
                'trade_return_net': val('trade_return_net'),
                'rebalance_cost': val('rebalance_cost'),
                'asset_contribution': val('asset_contribution'),
                'portfolio_return_net': None if pd.isna(portfolio_row.get('portfolio_return_net')) else float(portfolio_row.get('portfolio_return_net')),
            },
            'roll': roll_info,
        }

    def _build_drawdowns(self):
        p = self.l.portfolio.sort_values('date')[['date','nav_net']].dropna().copy()
        p['hwm'] = p.nav_net.cummax()
        p['dd'] = p.nav_net / p.hwm - 1
        episodes = []
        in_dd = False
        start_idx = None
        for i, row in p.reset_index(drop=True).iterrows():
            if row.dd < -1e-14 and not in_dd:
                in_dd = True
                start_idx = max(0, i-1)
            recovered = in_dd and row.dd >= -1e-14
            last = i == len(p)-1
            if in_dd and (recovered or last):
                end_idx = i
                seg = p.reset_index(drop=True).iloc[start_idx:end_idx+1]
                trough_pos = seg.dd.idxmin()
                start = p.reset_index(drop=True).iloc[start_idx]
                trough = p.reset_index(drop=True).loc[trough_pos]
                recovery = p.reset_index(drop=True).iloc[end_idx] if recovered else None
                episodes.append({
                    'start_date': str(start.date.date()),
                    'trough_date': str(trough.date.date()),
                    'recovery_date': str(recovery.date.date()) if recovery is not None else None,
                    'max_drawdown': float(trough.dd),
                    'duration_days': int(end_idx-start_idx),
                    'recovered': bool(recovered),
                })
                in_dd = False
                start_idx = None
        episodes.sort(key=lambda x: x['max_drawdown'])
        return episodes

    def drawdowns(self, top: int = 10):
        return {'version':'V6', 'rows': self._drawdowns[:max(1, min(int(top), 50))]}

    def _event(self, date, event_type, event_group, title, asset=None, asset_class=None, severity=1.0, description='', before=None, value=None, after=None, date_from=None, date_to=None, source_field=None):
        key_asset = asset or 'PORTFOLIO'
        eid = f'{pd.Timestamp(date).strftime("%Y%m%d")}-{event_type}-{key_asset}'
        return {
            'event_id': eid,
            'date': str(pd.Timestamp(date).date()),
            'event_type': event_type,
            'event_group': event_group,
            'asset': asset,
            'asset_class': asset_class,
            'severity': float(severity) if severity is not None and np.isfinite(severity) else None,
            'title': title,
            'description': description,
            'before_value': before,
            'event_value': value,
            'after_value': after,
            'related_date_from': date_from,
            'related_date_to': date_to,
            'source_field': source_field,
        }

    def _build_events(self):
        events: list[dict[str, Any]] = []
        p = self.l.portfolio.sort_values('date').copy()
        a = self.l.assets.sort_values(['asset','date']).copy()
        r = self.l.rolls.sort_values(['date','asset']).copy()

        # Extreme daily returns.
        ret = p[['date','portfolio_return_net']].dropna()
        for _, row in ret.nsmallest(12, 'portfolio_return_net').iterrows():
            events.append(self._event(row.date, 'TOP_DAILY_LOSS', 'PERFORMANCE', '极端单日下跌', severity=abs(row.portfolio_return_net), value=float(row.portfolio_return_net), source_field='portfolio_return_net'))
        for _, row in ret.nlargest(12, 'portfolio_return_net').iterrows():
            events.append(self._event(row.date, 'TOP_DAILY_GAIN', 'PERFORMANCE', '极端单日上涨', severity=abs(row.portfolio_return_net), value=float(row.portfolio_return_net), source_field='portfolio_return_net'))

        # Drawdown landmarks.
        for rank, dd in enumerate(self._drawdowns[:10], 1):
            sev = abs(dd['max_drawdown'])
            events.append(self._event(dd['start_date'], 'DRAWDOWN_START', 'PERFORMANCE', f'回撤 #{rank} 开始', severity=sev, value=0.0, date_from=dd['start_date'], date_to=dd['recovery_date'] or dd['trough_date'], source_field='nav_net'))
            events.append(self._event(dd['trough_date'], 'DRAWDOWN_TROUGH', 'PERFORMANCE', f'回撤 #{rank} 谷底', severity=sev, value=dd['max_drawdown'], date_from=dd['start_date'], date_to=dd['recovery_date'] or dd['trough_date'], source_field='nav_net'))
            if dd['recovery_date']:
                events.append(self._event(dd['recovery_date'], 'DRAWDOWN_RECOVERY', 'PERFORMANCE', f'回撤 #{rank} 修复', severity=sev, value=0.0, date_from=dd['start_date'], date_to=dd['recovery_date'], source_field='nav_net'))

        # 10VT state transitions and largest changes.
        mult = p[['date','final_10vt_multiplier']].dropna().copy()
        mult['prev'] = mult.final_10vt_multiplier.shift(1)
        floor = mult.final_10vt_multiplier <= 0.500000000001
        prev_floor = mult.prev <= 0.500000000001
        for _, row in mult[floor & ~prev_floor.fillna(False)].iterrows():
            events.append(self._event(row.date, '10VT_FLOOR_ENTER', 'RISK', '10VT 进入 0.5 下限', severity=1.0, before=None if pd.isna(row.prev) else float(row.prev), value=float(row.final_10vt_multiplier), source_field='final_10vt_multiplier'))
        for _, row in mult[~floor & prev_floor.fillna(False)].iterrows():
            events.append(self._event(row.date, '10VT_FLOOR_EXIT', 'RISK', '10VT 离开 0.5 下限', severity=1.0, before=float(row.prev), value=float(row.final_10vt_multiplier), source_field='final_10vt_multiplier'))
        mult['delta'] = (mult.final_10vt_multiplier-mult.prev).abs()
        for _, row in mult.nlargest(20, 'delta').iterrows():
            if pd.notna(row.delta) and row.delta > 0:
                events.append(self._event(row.date, '10VT_LARGE_CHANGE', 'RISK', '10VT 显著变化', severity=float(row.delta), before=float(row.prev), value=float(row.final_10vt_multiplier), source_field='final_10vt_multiplier'))

        # Haircut transitions.
        if 'haircut_flag' in a:
            a['prev_haircut'] = a.groupby('asset').haircut_flag.shift(1)
            for _, row in a[(a.haircut_flag.eq(True)) & ~(a.prev_haircut.eq(True))].iterrows():
                events.append(self._event(row.date, 'HAIRCUT_ON', 'RISK', f'{row.asset} 触发波动率 haircut', asset=row.asset, asset_class=row.asset_class, severity=1.0, value=float(row.haircut_multiplier) if pd.notna(row.haircut_multiplier) else None, source_field='haircut_flag'))
            for _, row in a[(a.haircut_flag.eq(False)) & (a.prev_haircut.eq(True))].iterrows():
                events.append(self._event(row.date, 'HAIRCUT_OFF', 'RISK', f'{row.asset} 解除波动率 haircut', asset=row.asset, asset_class=row.asset_class, severity=1.0, value=float(row.haircut_multiplier) if pd.notna(row.haircut_multiplier) else None, source_field='haircut_flag'))

        # Momentum selection transitions on effective trading dates.
        risk = a[a.asset.isin(RISK_ASSETS)].copy()
        risk['selected_bool'] = risk.selected.fillna(False).astype(bool)
        risk['prev_selected'] = risk.groupby('asset').selected_bool.shift(1)
        for _, row in risk[risk.selected_bool & risk.prev_selected.notna() & ~risk.prev_selected.eq(True)].iterrows():
            events.append(self._event(row.date, 'MOMENTUM_ENTRY', 'MOMENTUM', f'{row.asset} 进入动量组合', asset=row.asset, asset_class=row.asset_class, severity=1.0, value=float(row.mean_rank) if pd.notna(row.mean_rank) else None, source_field='selected'))
        for _, row in risk[(~risk.selected_bool) & risk.prev_selected.eq(True)].iterrows():
            events.append(self._event(row.date, 'MOMENTUM_EXIT', 'MOMENTUM', f'{row.asset} 被动量筛选剔除', asset=row.asset, asset_class=row.asset_class, severity=1.0, value=float(row.mean_rank) if pd.notna(row.mean_rank) else None, source_field='selected'))

        # Execution events (one portfolio event per date).
        day_state = a.groupby('date').first().reset_index()
        for _, row in day_state[day_state.monthly_smoothing_step.fillna(0).astype(float) > 0].iterrows():
            step = int(row.monthly_smoothing_step)
            events.append(self._event(row.date, f'MONTHLY_SMOOTHING_T{step}', 'EXECUTION', f'月度平滑 T+{step}', severity=step/4, value=step, source_field='monthly_smoothing_step'))
        for _, row in day_state[day_state.midmonth_trigger.fillna(False).astype(bool)].iterrows():
            events.append(self._event(row.date, 'MIDMONTH_TRIGGER', 'EXECUTION', '月中再平衡触发', severity=float(row.deviation) if pd.notna(row.deviation) else 1.0, value=float(row.deviation) if pd.notna(row.deviation) else None, source_field='midmonth_trigger'))

        # Roll events.
        rolled = r[r.roll_to.notna()]
        for _, row in rolled.iterrows():
            events.append(self._event(row.date, str(row.roll_trigger), 'ROLL', f'{row.asset} {row.roll_from} → {row.roll_to}', asset=row.asset, asset_class=None, severity=float(row.turnover) if pd.notna(row.turnover) else 1.0, description=str(row.status) if pd.notna(row.status) else '', value=float(row.days_to_expiry) if pd.notna(row.days_to_expiry) else None, source_field='roll_trigger'))

        # Data quality events.
        if 'expiry_source' in r:
            mask = r.expiry_source.eq('EXPIRY_UNVERIFIED_EXCEPTION') & r.status.eq('EXPIRY_UNVERIFIED')
            for _, row in r[mask].iterrows():
                events.append(self._event(row.date, 'EXPIRY_UNVERIFIED_EXCEPTION', 'DATA_QUALITY', f'{row.asset} 到期日未验证', asset=row.asset, severity=0.2, description=str(row.status) if pd.notna(row.status) else '', source_field='expiry_source'))

        # Stable ordering: newest first in default UI, severity available for ranking.
        events.sort(key=lambda x: (x['date'], x['event_group'], x['event_type'], x['asset'] or ''), reverse=True)
        return events

    def events(self, version: str, from_date=None, to_date=None, event_group=None, event_type=None, asset=None, limit=500):
        self._require_v6(version)
        rows = self._events
        if from_date:
            rows = [x for x in rows if x['date'] >= str(pd.Timestamp(from_date).date())]
        if to_date:
            rows = [x for x in rows if x['date'] <= str(pd.Timestamp(to_date).date())]
        if event_group:
            rows = [x for x in rows if x['event_group'] == event_group.upper()]
        if event_type:
            rows = [x for x in rows if x['event_type'] == event_type.upper()]
        if asset:
            rows = [x for x in rows if x['asset'] == asset.upper()]
        return {'version':'V6', 'count':len(rows), 'rows': rows[:max(1, min(int(limit), 5000))]}

    def event(self, version: str, event_id: str):
        self._require_v6(version)
        for x in self._events:
            if x['event_id'] == event_id:
                return {'version':'V6', 'event':x}
        raise ValueError(f'event {event_id} not found')

    def attribution(self, version: str, from_date: str, to_date: str, level='asset'):
        self._require_v6(version)
        start = self.l.resolve(from_date)
        end = self.l.resolve(to_date)
        if start > end:
            start, end = end, start
        a = self.l.assets[self.l.assets.date.between(start, end)].copy()
        p = self.l.portfolio[self.l.portfolio.date.between(start, end)].copy()
        w = pd.to_numeric(a.weight_start_of_day, errors='coerce').fillna(0)
        gross = pd.to_numeric(a.trade_return_gross, errors='coerce')
        roll_cost = pd.to_numeric(a.roll_cost, errors='coerce').fillna(0)
        a['gross_contribution'] = np.where(w.abs() < 1e-14, 0.0, w*gross.fillna(0))
        a['contract_roll_cost_contribution'] = np.where(w.abs() < 1e-14, 0.0, w*roll_cost)
        a['rebalance_cost_contribution'] = pd.to_numeric(a.rebalance_cost, errors='coerce').fillna(0)
        a['net_contribution'] = pd.to_numeric(a.asset_contribution, errors='coerce').fillna(0)
        group = ['asset','asset_class'] if level == 'asset' else ['asset_class']
        out = a.groupby(group, dropna=False).agg(
            gross_contribution=('gross_contribution','sum'),
            contract_roll_cost=('contract_roll_cost_contribution','sum'),
            rebalance_cost=('rebalance_cost_contribution','sum'),
            net_contribution=('net_contribution','sum'),
            average_final_weight=('final_weight','mean'),
        ).reset_index()
        net = pd.to_numeric(p.portfolio_return_net, errors='coerce').dropna()
        compounded = float((1+net).prod()-1) if len(net) else None
        arithmetic = float(net.sum()) if len(net) else None
        return {
            'version':'V6',
            'requested_from': str(pd.Timestamp(from_date).date()),
            'requested_to': str(pd.Timestamp(to_date).date()),
            'resolved_from': str(start.date()),
            'resolved_to': str(end.date()),
            'level': level,
            'portfolio': {
                'compounded_net_return': compounded,
                'arithmetic_sum_daily_net_return': arithmetic,
                'additive_net_contribution_sum': float(out.net_contribution.sum()) if len(out) else 0.0,
                'observations': int(len(p)),
                'note': 'Asset/class contributions are additive daily-return contributions; they are not compounded returns.'
            },
            'rows': records(out),
        }

    def roll_history(self, version: str, asset: str, from_date=None, to_date=None, events_only=False):
        self._require_v6(version)
        asset = asset.upper()
        x = self.l.rolls[self.l.rolls.asset.eq(asset)].copy()
        if from_date:
            x = x[x.date >= pd.Timestamp(from_date)]
        if to_date:
            x = x[x.date <= pd.Timestamp(to_date)]
        if events_only:
            x = x[x.roll_to.notna()]
        return {'version':'V6', 'asset':asset, 'rows':records(x)}


def row_bool_notna(series: pd.Series) -> pd.Series:
    return series.notna()
