const PAGES = [
  ['策略全景','整体表现、风险状态与快速研究入口'],
  ['决策解释','解释某一天、某个资产为什么形成这个最终仓位'],
  ['事件研究','自动定位值得研究的回撤、风控、执行与换月事件'],
  ['收益归因','从大类到资产拆解一段区间的收益、成本与回撤来源'],
  ['执行与换月','查看真实合约生命周期、换月触发与收益时点'],
  ['参数实验','调用真实 V6 Python 引擎并比较反事实结果'],
  ['版本比较','为 V5 / V6 / V7 / V8 的统一研究框架预留接口'],
  ['数据与审计','查看字段血缘、数据质量、规则状态与审计边界'],
  ['表现与胜率','年度表现指标与八个滚动持有期胜率'],
  ['年度收益归因','大类收益贡献与单资产年度贡献矩阵'],
  ['持仓与风险','名义敞口与大类贡献滚动波动率'],
  ['回撤研究','净值路径、Top 5 回撤区间与事件表'],
];

const ResearchContext = {
  strategyVersion:'V6', compareVersion:null, selectedDate:null, selectedYear:null, fromDate:null, toDate:null,
  selectedAsset:'IF', selectedAssetClass:null, selectedEventId:null, experimentId:null
};
window.ResearchContext = ResearchContext;

const state = {
  mode:"A", page:0, summary:null, rules:null, series:[], exposures:[], assets:[], versions:[], lineage:[], dataQuality:null,
  drawdowns:[], selectedEvent:null, eventRows:[], eventFilters:{group:'', asset:''}, experimentResult:null,
  activeDecisionStep:0, analytics:{}, parameterRegistry:null, analyticsDisplay:{assetClass:'all',volWindow:120,showGross:false,showVol:true,winRateHorizon:'all'}, experimentHistory:[], sensitivity:{running:false,cancelRequested:false,results:[],inFlight:false}, csvExports:{}
};

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = v => String(v ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = async (url, options) => { const r=await fetch(url,options); if(!r.ok) throw new Error(await r.text()); return r.json(); };
const finite = x => x!==null && x!==undefined && x!=='' && Number.isFinite(Number(x));
const num = (x,n=3) => finite(x) ? Number(x).toFixed(n) : '—';
const pct = (x,n=2) => finite(x) ? `${(Number(x)*100).toFixed(n)}%` : '—';
const signedPct = (x,n=2) => finite(x) ? `${Number(x)>=0?'+':''}${(Number(x)*100).toFixed(n)}%` : '—';
const cls = x => !finite(x) ? '' : Number(x)>0 ? 'positive' : Number(x)<0 ? 'negative' : '';
const dateOnly = x => x ? String(x).slice(0,10) : '—';
const labelClass = x => ({equity:'Equity',bond:'Bond',commodity:'Commodity'}[x] || x || '—');
const fmt = (x,type='num') => type==='pct'?pct(x):type==='signed'?signedPct(x):type==='bool'?(x===true?'YES':x===false?'NO':'—'):type==='date'?dateOnly(x):num(x);

function kpi(label,value,sub='',kind='') { return `<div class="kpi ${kind}"><div class="label">${esc(label)}</div><div class="value">${value}</div>${sub?`<div class="sub">${esc(sub)}</div>`:''}</div>`; }
function badge(text,type='neutral'){ return `<span class="badge ${type}">${esc(text)}</span>`; }
function panel(title,body,desc='',actions=''){ return `<section class="panel"><div class="panel-head"><div><h3>${esc(title)}</h3>${desc?`<p class="desc">${esc(desc)}</p>`:''}</div>${actions?`<div class="panel-actions">${actions}</div>`:''}</div>${body}</section>`; }
function detailItem(k,v){ return `<div class="detail-item"><div class="k">${esc(k)}</div><div class="v">${v}</div></div>`; }
function table(rows, columns){
  if(!rows?.length) return `<div class="empty-state">当前筛选没有数据</div>`;
  return `<div class="table-wrap"><table><thead><tr>${columns.map(c=>`<th>${esc(c.label||c.key)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${columns.map(c=>{let raw=r[c.key];let val=c.render?c.render(raw,r):esc(raw??'—');return `<td class="${c.className?c.className(raw,r):''}">${val}</td>`}).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function nav(){
  const visible=state.mode==='A'?[0,8,9,10,11,1,2,3,4,7]:[5,6];
  $('#nav').innerHTML=visible.map(i=>`<button type="button" data-page="${i}" class="${i===state.page?'active':''}"><span class="nav-index">${String(i+1).padStart(2,'0')}</span><span>${PAGES[i][0]}</span></button>`).join('');
  $$('#nav button').forEach(b=>b.addEventListener('click',()=>goToPage(Number(b.dataset.page))));
  $$('[data-mode]').forEach(b=>{b.classList.toggle('active',b.dataset.mode===state.mode);b.setAttribute('aria-pressed',String(b.dataset.mode===state.mode));});
  $('#title').textContent=PAGES[state.page][0];$('#subtitle').textContent=PAGES[state.page][1];
  $('#breadcrumbTitle').textContent=`模式${state.mode} · ${PAGES[state.page][0]}`;
  $('#pageEyebrow').textContent=state.mode==='A'?'MODE A / HISTORICAL REPLAY':'MODE B / PARAMETER RESEARCH';
  $('#modeJump').textContent=state.mode==='A'?'进入参数实验 →':'← 返回策略复盘';
}
function goToPage(page){
  state.page=page;state.mode=[5,6].includes(page)?'B':'A';nav();render();window.scrollTo({top:0,behavior:'smooth'});
}

function syncContextControls(){
  $('#strategyVersion').value=ResearchContext.strategyVersion;
  $('#selectedDate').value=ResearchContext.selectedDate||'';
  $('#selectedAsset').value=ResearchContext.selectedAsset||'';
  $('#fromDate').value=ResearchContext.fromDate||'';
  $('#toDate').value=ResearchContext.toDate||'';
  $('#contextEvent').textContent=state.selectedEvent ? `${state.selectedEvent.date} · ${state.selectedEvent.title}` : '未选择事件';
  const row=state.series.find(r=>dateOnly(r.date)===ResearchContext.selectedDate)||state.series.at(-1);
  const day=$('#sideDailySummary');
  if(day&&row){
    const d=dateOnly(row.date);
    day.innerHTML=`<div class="side-date">${esc(d)}</div><div class="side-stat"><span>当日净收益</span><b class="${cls(row.portfolio_return_net)}">${signedPct(row.portfolio_return_net)}</b></div><div class="side-stat"><span>10VT 倍率</span><b>${num(row.final_10vt_multiplier,3)} ×</b></div><div class="side-stat"><span>当日换手</span><b>${pct(row.turnover)}</b></div><div class="side-stat"><span>组合净值</span><b>${num(row.nav_net,3)}</b></div>`;
  }

}

function bindContext(){
  $('#strategyVersion').addEventListener('change',e=>{ResearchContext.strategyVersion=e.target.value;render();});
  $('#selectedDate').addEventListener('change',e=>{ResearchContext.selectedDate=e.target.value;render();});
  $('#selectedAsset').addEventListener('change',e=>{ResearchContext.selectedAsset=e.target.value;render();});
  $('#fromDate').addEventListener('change',e=>{ResearchContext.fromDate=e.target.value;if([3,8,9,10,11].includes(state.page))render();});
  $('#toDate').addEventListener('change',e=>{ResearchContext.toDate=e.target.value;if([3,8,9,10,11].includes(state.page))render();});
}

function lineSvg(rows,key,{height=250,markerDate=null,secondaryKey=null,format='num'}={}){
  const clean=rows.filter(r=>finite(r[key])); if(clean.length<2)return `<div class="empty-state">没有足够数据绘图</div>`;
  const W=900,H=height,P=34; const values=clean.flatMap(r=>[Number(r[key]),secondaryKey&&finite(r[secondaryKey])?Number(r[secondaryKey]):null]).filter(Number.isFinite);
  let lo=Math.min(...values),hi=Math.max(...values); if(hi===lo){hi+=1;lo-=1} const pad=(hi-lo)*.06;lo-=pad;hi+=pad;
  const x=i=>P+i/(clean.length-1)*(W-2*P), y=v=>H-P-(v-lo)/(hi-lo)*(H-2*P);
  const path=k=>clean.map((r,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(Number(r[k])).toFixed(1)}`).join(' ');
  const ticks=[0,.25,.5,.75,1].map(t=>{const v=lo+(hi-lo)*(1-t);const yy=P+t*(H-2*P);const lab=format==='pct'?`${(v*100).toFixed(1)}%`:v.toFixed(2);return `<line class="chart-grid" x1="${P}" y1="${yy}" x2="${W-P}" y2="${yy}"/><text class="chart-axis" x="2" y="${yy+3}">${lab}</text>`}).join('');
  let marker=''; if(markerDate){const idx=clean.findIndex(r=>dateOnly(r.date)===markerDate);if(idx>=0){marker=`<line x1="${x(idx)}" y1="${P}" x2="${x(idx)}" y2="${H-P}" stroke="#ffb15a" stroke-dasharray="4 4"/><circle class="chart-marker" cx="${x(idx)}" cy="${y(clean[idx][key])}" r="4"/>`;}}
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img">${ticks}<path class="chart-line" d="${path(key)}"/>${secondaryKey?`<path class="chart-line secondary" d="${path(secondaryKey)}"/>`:''}${marker}<rect data-chart-select="${esc(key)}" data-chart-length="${clean.length}" x="${P}" y="${P}" width="${W-2*P}" height="${H-2*P}" fill="transparent" role="button" tabindex="0" aria-label="选择净值曲线上的交易日" style="cursor:crosshair"/><text class="chart-axis" x="${P}" y="${H-6}">${dateOnly(clean[0].date)}</text><text class="chart-axis" text-anchor="end" x="${W-P}" y="${H-6}">${dateOnly(clean.at(-1).date)}</text></svg>`;
}

function multiLineSvg(rows,keys,{height=250,markerDate=null}={}){
  const clean=rows.filter(r=>keys.some(k=>finite(r[k]))); if(clean.length<2)return `<div class="empty-state">没有足够数据绘图</div>`;
  const W=900,H=height,P=34;const vals=clean.flatMap(r=>keys.map(k=>Number(r[k]))).filter(Number.isFinite);let lo=Math.min(0,...vals),hi=Math.max(...vals);if(hi===lo)hi=lo+1;const pad=(hi-lo)*.05;lo-=pad;hi+=pad;
  const x=i=>P+i/(clean.length-1)*(W-2*P),y=v=>H-P-(v-lo)/(hi-lo)*(H-2*P); const colors=['#45d7c8','#65a8ff','#ffb15a'];
  const ticks=[0,.25,.5,.75,1].map(t=>{const v=hi-t*(hi-lo),yy=P+t*(H-2*P);return `<line class="chart-grid" x1="${P}" y1="${yy}" x2="${W-P}" y2="${yy}"/><text class="chart-axis" x="2" y="${yy+3}">${(v*100).toFixed(0)}%</text>`}).join('');
  const paths=keys.map((k,j)=>{const d=clean.map((r,i)=>`${i?'L':'M'}${x(i).toFixed(1)},${y(Number(r[k]||0)).toFixed(1)}`).join(' ');return `<path d="${d}" fill="none" stroke="${colors[j]}" stroke-width="2"/>`}).join('');
  let marker='';if(markerDate){const idx=clean.findIndex(r=>dateOnly(r.date)===markerDate);if(idx>=0)marker=`<line x1="${x(idx)}" y1="${P}" x2="${x(idx)}" y2="${H-P}" stroke="#ffb15a" stroke-dasharray="4 4"/>`;}
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${ticks}${paths}${marker}<text class="chart-axis" x="${P}" y="${H-6}">${dateOnly(clean[0].date)}</text><text class="chart-axis" text-anchor="end" x="${W-P}" y="${H-6}">${dateOnly(clean.at(-1).date)}</text></svg>`;
}

const ANALYTICS_BASE='/api/strategy/V6/analytics';
const analyticsRows=x=>Array.isArray(x?.rows)?x.rows:[];
const analyticsMeta=x=>x?`${esc(x.method_id||'')} · ${esc(x.data_status||'REAL_V6_DERIVED')}${x.source_manifest_hash?` · manifest ${esc(String(x.source_manifest_hash).slice(0,12))}`:''}`:'';
async function analytics(endpoint,params={}){
  const q=new URLSearchParams(params);const url=`${ANALYTICS_BASE}/${endpoint}${q.size?'?'+q:''}`;
  if(state.analytics[url])return state.analytics[url];
  const data=await api(url);state.analytics[url]=data;return data;
}
function invalidateAnalytics(){state.analytics={};}
function inRange(rows,dateKey='date'){
  return rows.filter(r=>{const d=dateOnly(r[dateKey]);return (!ResearchContext.fromDate||d>=ResearchContext.fromDate)&&(!ResearchContext.toDate||d<=ResearchContext.toDate);});
}
function researchControls(){return `<div class="analytics-controls"><label>类别过滤<select id="analyticsClass"><option value="all">全部大类</option><option value="equity">Equity</option><option value="bond">Bond</option><option value="commodity">Commodity</option></select></label><label>展示波动窗口<select id="analyticsVolWindow">${[20,60,120,240].map(v=>`<option value="${v}" ${v===state.analyticsDisplay.volWindow?'selected':''}>${v}D · 仅展示</option>`).join('')}</select></label><label class="check-label"><input id="analyticsShowGross" type="checkbox" ${state.analyticsDisplay.showGross?'checked':''}> 显示毛净值</label><label class="check-label"><input id="analyticsShowVol" type="checkbox" ${state.analyticsDisplay.showVol?'checked':''}> 显示展示波动率</label><label>胜率持有期<select id="winRateHorizon"><option value="all">全部期限</option>${[[1,'日度'],[5,'周度'],[21,'月度'],[63,'季度'],[126,'半年度'],[252,'年度'],[378,'18个月'],[504,'两年度']].map(([n,l])=>`<option value="${n}" ${String(n)===String(state.analyticsDisplay.winRateHorizon)?'selected':''}>${l} · ${n}D</option>`).join('')}</select></label></div>`;}
function bindResearchControls(){const c=$('#analyticsClass'),w=$('#analyticsVolWindow'),g=$('#analyticsShowGross'),v=$('#analyticsShowVol'),h=$('#winRateHorizon');if(c){c.value=ResearchContext.selectedAssetClass||'all';c.onchange=()=>{ResearchContext.selectedAssetClass=c.value==='all'?null:c.value;state.analyticsDisplay.assetClass=c.value;render();};}if(w)w.onchange=()=>{state.analyticsDisplay.volWindow=Number(w.value);invalidateAnalytics();render();};if(g)g.onchange=()=>{state.analyticsDisplay.showGross=g.checked;render();};if(v)v.onchange=()=>{state.analyticsDisplay.showVol=v.checked;render();};if(h)h.onchange=()=>{state.analyticsDisplay.winRateHorizon=h.value;render();};}
function lineChart(rows,series,{height=320,selectedDate=ResearchContext.selectedDate,range=null,dual=false,source='V6 analytics API'}={}){
  const valid=rows.filter(r=>series.some(s=>finite(r[s.key])));if(valid.length<2)return `<div class="empty-state">样本不足，无法绘图</div>`;
  const W=960,H=height,L=64,R=dual?66:24,T=22,B=38,innerW=W-L-R,innerH=H-T-B;
  const scales=[0,1].map(axis=>{const group=series.filter(s=>(s.axis||0)===axis);const vals=valid.flatMap(r=>group.map(s=>Number(r[s.key]))).filter(Number.isFinite);let lo=Math.min(...vals),hi=Math.max(...vals);if(!Number.isFinite(lo)||!Number.isFinite(hi)){lo=0;hi=1;}if(lo===hi){lo-=.01;hi+=.01;}const pad=(hi-lo)*.06;return {lo:lo-pad,hi:hi+pad};});
  const x=i=>L+(i/(valid.length-1))*innerW;const y=(v,axis)=>H-B-((v-scales[axis].lo)/(scales[axis].hi-scales[axis].lo))*innerH;
  const tickMarks=[0,.25,.5,.75,1].map(t=>{const yy=T+t*innerH;const v=scales[0].hi-t*(scales[0].hi-scales[0].lo);return `<line class="chart-grid" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text class="chart-axis" x="${L-8}" y="${yy+4}" text-anchor="end">${series[0].format==='pct'?(v*100).toFixed(1)+'%':v.toFixed(2)}</text>${dual?(()=>{const rr=scales[1].hi-t*(scales[1].hi-scales[1].lo);return `<text class="chart-axis" x="${W-R+8}" y="${yy+4}">${(rr*100).toFixed(1)}%</text>`})():''}`}).join('');
  const paths=series.map((s,j)=>{let d='',active=false;valid.forEach((r,i)=>{if(!finite(r[s.key])){active=false;return;}d+=`${active?'L':'M'}${x(i).toFixed(2)},${y(Number(r[s.key]),s.axis||0).toFixed(2)} `;active=true;});return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="${j===0?2.5:2}" ${s.dash?'stroke-dasharray="6 5"':''}/>`;}).join('');
  let marker='';const idx=valid.findIndex(r=>dateOnly(r.date)===selectedDate);if(idx>=0){const j=series.findIndex(s=>finite(valid[idx][s.key]));if(j>=0)marker=`<line x1="${x(idx)}" y1="${T}" x2="${x(idx)}" y2="${H-B}" stroke="#dc9e51" stroke-dasharray="4 4"/><circle cx="${x(idx)}" cy="${y(Number(valid[idx][series[j].key]),series[j].axis||0)}" r="4" fill="#dc9e51" stroke="white" stroke-width="2"/>`;}
  const axisLabel=dual?`<text class="chart-axis-title" x="${L}" y="13">${esc(series[0].axisLabel||series[0].unit||'')}</text><text class="chart-axis-title" x="${W-R}" y="13" text-anchor="end">${esc(series.find(s=>s.axis===1)?.axisLabel||'%')}</text>`:`<text class="chart-axis-title" x="${L}" y="13">${esc(series[0].axisLabel||series[0].unit||'')}</text>`;
  return `<div class="chart-box"><svg class="analytics-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map(s=>s.label).join(', '))}">${axisLabel}${tickMarks}${paths}${marker}<text class="chart-axis" x="${L}" y="${H-8}">${dateOnly(valid[0].date)}</text><text class="chart-axis" text-anchor="end" x="${W-R}" y="${H-8}">${dateOnly(valid.at(-1).date)}</text><rect data-hover-chart="${esc(series.map(s=>s.key).join(','))}" x="${L}" y="${T}" width="${innerW}" height="${innerH}" fill="transparent"/></svg><div class="chart-tooltip" aria-live="polite"></div><div class="legend">${series.map(s=>{const cl=s.key.match(/^(equity|bond|commodity)$/)?.[1];return cl?`<button type="button" data-legend-class="${cl}" style="--legend-color:${s.color}">${esc(s.label)}</button>`:`<span style="--legend-color:${s.color}">${esc(s.label)}</span>`}).join('')}</div><small class="chart-source">来源：${esc(source)} · 点击日期同步研究上下文</small><script type="application/json" data-chart-rows>${JSON.stringify(valid).replace(/</g,'\\u003c')}</script><script type="application/json" data-chart-series>${JSON.stringify(series).replace(/</g,'\\u003c')}</script></div>`;
}
function bindAnalyticsCharts(){
  $$('.chart-box').forEach(box=>{const svg=box.querySelector('svg'),overlay=svg?.querySelector('[data-hover-chart]'),tip=box.querySelector('.chart-tooltip'),raw=box.querySelector('[data-chart-rows]'),rawSeries=box.querySelector('[data-chart-series]');if(!overlay||!raw)return;let rows=[],chartSeries=[];try{rows=JSON.parse(raw.textContent);chartSeries=JSON.parse(rawSeries?.textContent||'[]');}catch{};
    const position=e=>{const rect=svg.getBoundingClientRect(),viewX=(e.clientX-rect.left)/rect.width*960;return Math.max(0,Math.min(1,(viewX-64)/(960-64-(chartSeries.some(s=>s.axis===1)?66:24))));};
    const move=e=>{const fx=position(e),i=Math.round(fx*(rows.length-1)),r=rows[i];if(!r)return;const keys=overlay.dataset.hoverChart.split(',');tip.innerHTML=`<strong>${esc(dateOnly(r.date))}</strong>${keys.map(k=>{const s=chartSeries.find(x=>x.key===k);const val=r[k];return `<span><i style="background:${s?.color||'#476de0'}"></i>${esc(s?.label||k)}：${finite(val)?(s?.format==='pct'?pct(val):num(val,4)):'—'}</span>`}).join('')}<small>${esc(box.dataset.source||'V6 analytics API')}</small>`;tip.style.display='block';tip.style.left=`${Math.min(74,Math.max(2,fx*100))}%`;};
    overlay.addEventListener('pointermove',move);overlay.addEventListener('pointerleave',()=>tip.style.display='none');overlay.addEventListener('click',e=>{move(e);const r=rows[Math.round(position(e)*(rows.length-1))];if(r?.date){ResearchContext.selectedDate=dateOnly(r.date);syncContextControls();}});
  });
}
function downloadCsv(filename,rows,columns,method='V6 analytics'){
  const meta=[['strategy_version','V6'],['research_from',ResearchContext.fromDate||''],['research_to',ResearchContext.toDate||''],['method',method]];
  const values=rows.map(r=>columns.map(c=>c.csv?c.csv(r[c.key],r):(r[c.key]??'')));
  const csv=[...meta,...[columns.map(c=>c.label||c.key)],...values].map(row=>row.map(v=>`"${String(v).replaceAll('"','""')}"`).join(',')).join('\r\n');
  const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));a.download=`${filename}_V6_${ResearchContext.fromDate||'all'}_${ResearchContext.toDate||'all'}.csv`;a.click();URL.revokeObjectURL(a.href);
}
async function downloadPng(button){
  const panelEl=button.closest('.panel'),box=panelEl?.querySelector('svg.analytics-chart,svg[role="img"]');if(!box){showExportMessage(button,'图表不可用，无法导出 PNG。',true);return;}
  const original=button.textContent;button.disabled=true;button.textContent='正在导出…';
  let svgUrl='';
  try{
    const svg=box.cloneNode(true);svg.setAttribute('xmlns','http://www.w3.org/2000/svg');svg.querySelectorAll('script,[data-hover-chart]').forEach(n=>n.remove());
    const vb=(svg.getAttribute('viewBox')||'0 0 960 380').split(/\s+/).map(Number),vx=vb[0]||0,vy=vb[1]||0,vw=vb[2]||960,vh=vb[3]||380,footerHeight=112,scale=Math.min(3,1920/vw),width=Math.round(vw*scale),height=Math.round((vh+footerHeight)*scale);
    svg.setAttribute('viewBox',`${vx} ${vy} ${vw} ${vh+footerHeight}`);svg.setAttribute('width',String(width));svg.setAttribute('height',String(height));svg.setAttribute('xmlns','http://www.w3.org/2000/svg');
    const ns='http://www.w3.org/2000/svg',bg=document.createElementNS(ns,'rect');bg.setAttribute('x','0');bg.setAttribute('y','0');bg.setAttribute('width',String(vw));bg.setAttribute('height',String(vh));bg.setAttribute('fill','#ffffff');svg.insertBefore(bg,svg.firstChild);
    const style=document.createElementNS(ns,'style');style.textContent='.chart-grid{stroke:#e9edf4;stroke-width:1;stroke-dasharray:4 4}.chart-axis{fill:#71839a;font:10px sans-serif}.chart-axis-title{fill:#465c78;font:700 10px sans-serif}.annual-class-year.selected rect{stroke:#273f74;stroke-width:2}';svg.insertBefore(style,svg.firstChild);
    const title=panelEl?.querySelector('.panel-title,h3')?.textContent?.trim()||box.getAttribute('aria-label')||'V6 analytics',legend=panelEl?.querySelector('.legend')?.innerText?.replace(/\s+/g,' · ').trim()||box.getAttribute('aria-label')||'图表指标',scope=panelEl?.querySelector('.panel-head .desc')?.textContent?.trim()||'',source=panelEl?.querySelector('.chart-source')?.textContent?.trim()||'V6 analytics API',method=panelEl?.querySelector('.analytics-head small')?.textContent?.trim()||source,short=value=>String(value).replace(/\s+/g,' ').trim().slice(0,145);
    const footerY=vh+18,footerBg=document.createElementNS(ns,'rect');footerBg.setAttribute('x','0');footerBg.setAttribute('y',String(vh));footerBg.setAttribute('width',String(vw));footerBg.setAttribute('height',String(footerHeight));footerBg.setAttribute('fill','#f7f9fc');svg.appendChild(footerBg);
    const addFooterLine=(y,text,size=12,color='#536983',weight='400')=>{const node=document.createElementNS(ns,'text');node.setAttribute('x','20');node.setAttribute('y',String(y));node.setAttribute('fill',color);node.setAttribute('font-family','Arial,sans-serif');node.setAttribute('font-size',String(size));node.setAttribute('font-weight',weight);node.textContent=text;svg.appendChild(node);};
    addFooterLine(footerY,title,15,'#304867','700');addFooterLine(footerY+20,`V6 正式策略基线 · V0.6 新增分析（独立审计待完成） · ${ResearchContext.fromDate||'全期'} 至 ${ResearchContext.toDate||'全期'}`,11,'#566c88','600');
    addFooterLine(footerY+40,`指标：${short(legend)}`,11);addFooterLine(footerY+60,`统计口径：${short(scope||'见图表说明')}`,10,'#71839a');addFooterLine(footerY+80,`方法/来源：${short(`${method} · ${source}`)}`,9,'#8997a8');
    svgUrl=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml;charset=utf-8'}));
    const img=new Image();await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(new Error('浏览器无法渲染此 SVG 图表'));img.src=svgUrl;});
    const canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d');if(!ctx)throw new Error('当前浏览器无法创建 PNG 画布');ctx.drawImage(img,0,0,width,height);
    const png=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!png)throw new Error('浏览器未能生成 PNG 文件');
    const fileUrl=URL.createObjectURL(png),a=document.createElement('a');a.href=fileUrl;a.download=`V6_${ResearchContext.fromDate||'all'}_${ResearchContext.toDate||'all'}_analytics.png`;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(fileUrl),1500);showExportMessage(button,'PNG 已生成并开始下载。');
  }catch(error){showExportMessage(button,`PNG 导出失败：${error.message}`,true);}finally{if(svgUrl)URL.revokeObjectURL(svgUrl);button.disabled=false;button.textContent=original;}
}
function showExportMessage(button,message,isError=false){let node=button.parentElement?.querySelector('.export-status');if(!node){node=document.createElement('small');node.className='export-status';node.setAttribute('role','status');button.insertAdjacentElement('afterend',node);}node.textContent=message;node.classList.toggle('error',Boolean(isError));}
function exportActions(){return `<button class="icon-button" type="button" data-export-png>导出 PNG</button>`;}
function bindAnalyticsActions(){bindAnalyticsCharts();$$('[data-export-png]').forEach(b=>b.onclick=()=>downloadPng(b));$$('[data-export-csv]').forEach(b=>b.onclick=()=>{const id=b.dataset.exportCsv,tableEl=$(`[data-csv-table="${id}"]`),record=state.csvExports[id];if(!tableEl||!record)return;downloadCsv(id,record.rows,record.columns,b.dataset.method||'V6 derived analytics');});bindResearchControls();$$('[data-legend-class]').forEach(b=>b.onclick=()=>{const cl=b.dataset.legendClass;ResearchContext.selectedAssetClass=ResearchContext.selectedAssetClass===cl?null:cl;state.analyticsDisplay.assetClass=ResearchContext.selectedAssetClass||'all';render();});}
function analyticsTable(rows,columns,{id='analytics',rowClass=null}={}){
  if(!rows.length)return `<div class="empty-state">当前区间没有数据</div>`;
  const body=rows.map((r,i)=>`<tr ${rowClass?`class="${rowClass(r)}"`:''} data-table-row="${i}">${columns.map(c=>`<td>${c.render?c.render(r[c.key],r):esc(r[c.key]??'—')}</td>`).join('')}</tr>`).join('');
  state.csvExports[id]={rows,columns};
  return `<div class="table-wrap analytics-table" data-csv-table="${esc(id)}"><table><thead><tr>${columns.map(c=>`<th>${esc(c.label||c.key)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`;
}
function analyticsHeader(name,data,rows,cols){return `<div class="analytics-head"><div>${badge('REAL V6 DERIVED','success')} ${badge('V0.6 NEW · AUDIT PENDING','warn')}<small>${analyticsMeta(data)}</small></div><button type="button" class="icon-button" data-export-csv="${esc(name)}" data-method="${esc(data?.method_id||'V6 derived analytics')}">下载 CSV</button></div>`;}
function chartPanel(title,chart,desc,rows,columns,id){return panel(title,`${chart}<div class="panel-actions"><button type="button" class="icon-button" data-export-png>导出 PNG</button></div>`,desc);}
function drawdownChart(rows,episodes){
  const valid=rows.filter(r=>finite(r.nav_net));if(valid.length<2)return '<div class="empty-state">样本不足，无法绘图</div>';
  const W=960,H=380,L=64,R=28,T=24,B=38,iw=W-L-R,ih=H-T-B,vals=valid.map(r=>Number(r.nav_net)),lo=Math.min(...vals),hi=Math.max(...vals),pad=(hi-lo)*.05;
  const min=lo-pad,max=hi+pad,x=i=>L+i/(valid.length-1)*iw,y=v=>H-B-(v-min)/(max-min)*ih;
  const idx=d=>valid.findIndex(r=>dateOnly(r.date)===dateOnly(d));
  const shades=episodes.map((ep,i)=>{const a=idx(ep.peak_date),b=idx(ep.trough_date);if(a<0||b<0||b<a)return '';return `<rect class="dd-episode-overlay ${ep.episode_id===ResearchContext.drawdownEventId?'active':''}" data-dd-episode="${esc(ep.episode_id)}" x="${x(a)}" y="${T}" width="${Math.max(2,x(b)-x(a))}" height="${ih}" fill="${['#d5828b','#e0a86d','#8098d4','#75b7a6','#9c8dc4'][i]}" fill-opacity=".16"><title>${esc(dateOnly(ep.peak_date))} → ${esc(dateOnly(ep.trough_date))} · ${pct(ep.max_drawdown)}</title></rect>`;}).join('');
  const path=valid.map((r,i)=>`${i?'L':'M'}${x(i).toFixed(2)},${y(Number(r.nav_net)).toFixed(2)}`).join(' '),ticks=[0,.25,.5,.75,1].map(t=>{const v=max-t*(max-min),yy=T+t*ih;return `<line class="chart-grid" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text class="chart-axis" x="${L-8}" y="${yy+4}" text-anchor="end">${v.toFixed(2)}</text>`}).join('');
  const troughs=episodes.map(ep=>{const i=idx(ep.trough_date);if(i<0)return '';return `<circle cx="${x(i)}" cy="${y(Number(valid[i].nav_net))}" r="4" fill="#c96c78" stroke="white" stroke-width="2"><title>${dateOnly(ep.trough_date)} ${pct(ep.max_drawdown)}</title></circle><text class="chart-axis" x="${x(i)+5}" y="${y(Number(valid[i].nav_net))-7}">${pct(ep.max_drawdown)}</text>`}).join('');
  return `<div class="chart-box drawdown-chart"><svg class="analytics-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="V6 净值曲线与 Top 5 回撤区间"><text class="chart-axis-title" x="${L}" y="14">净值（基准=1）</text>${ticks}${shades}<path d="${path}" fill="none" stroke="#476de0" stroke-width="2.5"/>${troughs}<text class="chart-axis" x="${L}" y="${H-8}">${dateOnly(valid[0].date)}</text><text class="chart-axis" text-anchor="end" x="${W-R}" y="${H-8}">${dateOnly(valid.at(-1).date)}</text></svg><div class="legend"><span style="--legend-color:#476de0">V6 Net NAV</span><span style="--legend-color:#d5828b">Top 5 Peak → Trough 风险累积区间</span></div><small class="chart-source">点击阴影跳转区间归因；来源：V6 analytics API</small><script type="application/json" data-chart-rows>${JSON.stringify(valid).replace(/</g,'\\u003c')}</script></div>`;
}
async function renderPerformance(){
  const [p,w]=await Promise.all([analytics('performance-by-year'),analytics('win-rates',{overlap:'true'})]);
  const perf=analyticsRows(p),winsAll=analyticsRows(w),wins=state.analyticsDisplay.winRateHorizon==='all'?winsAll:winsAll.filter(r=>Number(r.horizon)===Number(state.analyticsDisplay.winRateHorizon)),meta=analyticsMeta(p);
  const partialRows=perf.filter(r=>r.year!=null&&r.partial_year),partialNote=partialRows.map(r=>`${r.year}* (${dateOnly(r.start)} 至 ${dateOnly(r.end)})`).join('、');
  const pc=[{key:'period',label:'指标 / 区间',render:(v,r)=>esc(r.year==null||String(r.period).toUpperCase()==='FULL'?'自回测基日（年化）':(r.partial_year?`${r.year}*`:r.year))},{key:'return',label:'年化 / 年度复合收益（%）',render:(v,r)=>pct(r.year==null||String(r.period).toUpperCase()==='FULL'?r.annualized_return:r.return),csv:(v,r)=>{const x=r.year==null||String(r.period).toUpperCase()==='FULL'?r.annualized_return:r.return;return finite(x)?Number(x)*100:'';}},{key:'annualized_vol',label:'年化波动率（%）',render:v=>pct(v),csv:v=>finite(v)?Number(v)*100:''},{key:'sharpe',label:'Sharpe',render:v=>num(v,3)},{key:'max_drawdown',label:'最大回撤（%）',render:v=>pct(v),csv:v=>finite(v)?Number(v)*100:''}];
  const wc=[{key:'label',label:'持有期'},{key:'horizon',label:'交易日',render:v=>num(v,0)},{key:'up',label:'上涨次数'},{key:'down',label:'下跌次数'},{key:'zero',label:'零收益次数'},{key:'windows',label:'有效窗口数'},{key:'win_rate',label:'胜率（%）',render:v=>pct(v),csv:v=>finite(v)?Number(v)*100:''},{key:'up_avg',label:'上涨平均收益（%）',render:v=>signedPct(v),csv:v=>finite(v)?Number(v)*100:''},{key:'down_avg',label:'下跌平均收益（%）',render:v=>signedPct(v),csv:v=>finite(v)?Number(v)*100:''}];
  const perfFiltered=perf;
  $('#content').innerHTML=`${researchControls()}${panel('策略历史表现表',`${analyticsHeader('performance_by_year',p,perf,pc)}${analyticsTable(perfFiltered,pc,{id:'performance_by_year',rowClass:r=>r.year!=null&&Number(r.year)===Number(ResearchContext.selectedYear)?'selected-row':''})}<div class="method-note">${partialNote?`* 部分年度：${esc(partialNote)}。`:''}全期采用 V6 正式年化指标；年度收益为自然年复合区间收益，最大回撤保留负号。${esc(meta)}</div>`,'全期展示正式年化收益；自然年展示复合收益')}${panel('滚动持有期胜率',`${analyticsHeader('rolling_win_rates',w,wins,wc)}${analyticsTable(wins,wc,{id:'rolling_win_rates'})}<div class="callout warning">胜率使用重叠交易日窗口，样本彼此相关，不代表独立预测准确率。收益等于零的窗口不计入涨跌分母；无样本显示 —。</div>`,'窗口口径：1 / 5 / 21 / 63 / 126 / 252 / 378 / 504 个交易日')}`;
  bindAnalyticsActions();
  $$('.analytics-table tr[data-table-row]').forEach((tr,i)=>{const r=perfFiltered[i];if(r?.year!=null)tr.onclick=()=>{ResearchContext.selectedYear=Number(r.year);$$('.analytics-table tr').forEach(row=>row.classList.remove('selected-row'));tr.classList.add('selected-row');};});
}
function classBarChart(rows){
  if(!rows.length)return '<div class="empty-state">当前筛选没有年度贡献数据</div>';
  const years=[...new Set(rows.map(r=>Number(r.year)))].sort((a,b)=>a-b),classes=['equity','bond','commodity'],names={equity:'Equity',bond:'Bond',commodity:'Commodity'},colors={equity:'#476de0',bond:'#139b85',commodity:'#cc9752'},vals=rows.map(r=>Number(r.contribution)).filter(Number.isFinite),max=Math.max(.00001,...vals.map(Math.abs))*100,W=Math.max(900,years.length*82),H=300,L=62,R=20,T=24,B=40,iw=W-L-R,ih=H-T-B,half=ih/2,barW=Math.min(15,iw/years.length/5),slot=iw/years.length;
  const grid=[-1,-.5,0,.5,1].map(t=>{const yy=T+half-t*half;return `<line class="chart-grid" x1="${L}" y1="${yy}" x2="${W-R}" y2="${yy}"/><text class="chart-axis" x="${L-8}" y="${yy+4}" text-anchor="end">${(max*t).toFixed(1)} pp</text>`}).join('');
  const groups=years.map((year,i)=>{const x0=L+i*slot+slot/2;const bars=classes.map((cl,j)=>{const v=rows.find(r=>Number(r.year)===year&&r.asset_class===cl)?.contribution;if(!finite(v))return '';const val=Number(v)*100,bh=Math.abs(val)/max*half,x=x0+(j-1)*(barW+3)-barW/2,y=val>=0?T+half-bh:T+half;return `<rect x="${x}" y="${y}" width="${barW}" height="${Math.max(1,bh)}" rx="2" fill="${colors[cl]}"><title>${year} ${names[cl]} ${val.toFixed(3)} pp</title></rect>`}).join('');return `<g class="annual-class-year ${Number(ResearchContext.selectedYear)===year?'selected':''}" data-year="${year}" tabindex="0" role="button" aria-label="选择 ${year} 年大类贡献">${bars}<text class="chart-axis" x="${x0}" y="${H-9}" text-anchor="middle">${year}</text></g>`}).join('');
  return `<svg class="analytics-chart class-contribution-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Equity Bond Commodity 年度贡献，单位百分点 pp"><text class="chart-axis-title" x="${L}" y="14">年度贡献（pp）</text>${grid}${groups}</svg><div class="legend">${classes.map(c=>`<span style="--legend-color:${colors[c]}">${names[c]}</span>`).join('')}</div><div class="chart-source">日收益贡献简单求和，单位 pp；与复合净收益不直接等同。点击年份联动资产矩阵。</div>`;
}
async function renderContributions(){
  const [c,a]=await Promise.all([analytics('annual-class-contribution'),analytics('annual-asset-contribution')]);
  const cr=analyticsRows(c).filter(r=>!ResearchContext.selectedAssetClass||r.asset_class===ResearchContext.selectedAssetClass),ar=analyticsRows(a),years=[...new Set(ar.map(r=>Number(r.year)))].sort((x,y)=>x-y),assets=[...new Set(ar.map(r=>r.asset))];
  const visibleAssets=ar.filter(r=>!ResearchContext.selectedAssetClass||r.asset_class===ResearchContext.selectedAssetClass);
  const matrix=assets.map(asset=>{const rows=visibleAssets.filter(r=>r.asset===asset),out={asset,asset_class:rows[0]?.asset_class||'—'};years.forEach(y=>{const row=rows.find(r=>Number(r.year)===y);out[`y${y}`]=row?.contribution??null;out[`s${y}`]=row?.status??null;});return out;}).filter(r=>visibleAssets.some(x=>x.asset===r.asset));
  const columns=[{key:'asset',label:'品种',render:(v,r)=>`<button type="button" class="table-link" data-asset="${esc(v)}">${esc(v)}</button>`},{key:'asset_class',label:'大类'},...years.map(y=>({key:`y${y}`,label:Number(ResearchContext.selectedYear)===y?`${y} · 已选`:String(y),render:(v,r)=>finite(v)?`<span class="heat-cell ${Number(v)>=0?'positive':'negative'} ${Number(ResearchContext.selectedYear)===y?'selected-year-cell':''}">${(Number(v)*100).toFixed(2)}</span>`:`<span class="muted">${esc(r[`s${y}`]||'—')}</span>`,csv:v=>finite(v)?(Number(v)*100).toFixed(8):''}))];
  const classCols=[{key:'year',label:'年份'},{key:'asset_class',label:'大类'},{key:'contribution',label:'贡献（pp）',render:v=>finite(v)?(Number(v)*100).toFixed(3):'—',csv:v=>finite(v)?(Number(v)*100).toFixed(8):''}];
  $('#content').innerHTML=`${researchControls()}${panel('大类年度收益贡献',`${analyticsHeader('annual_class_contribution',c,cr,classCols)}${classBarChart(cr)}<button type="button" class="icon-button" data-export-png>导出 PNG</button>${analyticsTable(cr,classCols,{id:'annual_class_contribution'})}`,'按日资产贡献简单求和 · 单位 pp')} ${panel('单资产年度贡献矩阵',`${analyticsHeader('annual_asset_contribution',a,ar,[{key:'year',label:'年份'},{key:'asset',label:'资产'},{key:'asset_class',label:'大类'},{key:'contribution',label:'贡献（pp）',csv:v=>finite(v)?Number(v)*100:''},{key:'status',label:'状态'}])}${analyticsTable(matrix,columns,{id:'annual_asset_contribution'})}`,'数值表示品种对组合收益的贡献；未上市/未参与与真实零贡献分开标示')}`;
  bindAnalyticsActions();
  $$('[data-year]').forEach(b=>b.onclick=()=>{ResearchContext.selectedYear=Number(b.dataset.year);state.page=9;nav();render();});
  $$('[data-asset]').forEach(b=>b.onclick=()=>{ResearchContext.selectedAsset=b.dataset.asset;state.page=1;nav();render();});
}
async function renderHoldings(){
  const d=await analytics('class-exposure-and-vol',{display_window:String(state.analyticsDisplay.volWindow)}),rows=inRange(analyticsRows(d));
  const cls=ResearchContext.selectedAssetClass||'all';const series=[{key:'equity',label:'Equity 名义敞口',color:'#476de0',axisLabel:'最终名义敞口（x NAV）'},{key:'bond',label:'Bond 名义敞口',color:'#139b85'},{key:'commodity',label:'Commodity 名义敞口',color:'#cc9752'},...(cls==='all'||cls==='equity'?[{key:'equity_vol',label:`Equity 贡献波动率 ${state.analyticsDisplay.volWindow}D`,color:'#7894e8',axis:1,format:'pct',dash:true,axisLabel:'贡献波动率（%）'}]:[]),...(cls==='all'||cls==='bond'?[{key:'bond_vol',label:`Bond 贡献波动率 ${state.analyticsDisplay.volWindow}D`,color:'#69b5a7',axis:1,format:'pct',dash:true}]:[]),...(cls==='all'||cls==='commodity'?[{key:'commodity_vol',label:`Commodity 贡献波动率 ${state.analyticsDisplay.volWindow}D`,color:'#d8ae70',axis:1,format:'pct',dash:true}]:[])];
  const active=cls==='all'?['equity','bond','commodity']:[cls];const filteredSeries=series.filter(s=>!['equity','bond','commodity'].includes(s.key)||active.includes(s.key));
  const cols=[{key:'date',label:'交易日',render:v=>dateOnly(v)},{key:'equity',label:'Equity 名义敞口 x',render:v=>finite(v)?num(v,4):'—'},{key:'bond',label:'Bond 名义敞口 x',render:v=>finite(v)?num(v,4):'—'},{key:'commodity',label:'Commodity 名义敞口 x',render:v=>finite(v)?num(v,4):'—'},{key:'equity_vol',label:'Equity 贡献波动率（%）',render:v=>pct(v),csv:v=>finite(v)?Number(v)*100:''},{key:'bond_vol',label:'Bond 贡献波动率（%）',render:v=>pct(v),csv:v=>finite(v)?Number(v)*100:''},{key:'commodity_vol',label:'Commodity 贡献波动率（%）',render:v=>pct(v),csv:v=>finite(v)?Number(v)*100:''}];
  $('#content').innerHTML=`${researchControls()}${panel('大类名义敞口与贡献波动率',`${lineChart(rows,filteredSeries,{height:390,dual:true})}<button type="button" class="icon-button" data-export-png>导出 PNG</button>${analyticsHeader('class_exposure_and_vol',d,rows,cols)}${analyticsTable(rows,cols,{id:'class_exposure_and_vol'})}`,'敞口使用最终 start-of-day 名义权重，单位 x NAV；右轴为大类日组合贡献序列的 rolling 年化波动率，不是市场波动率或风险贡献')}`;
  bindAnalyticsActions();
}
async function renderDrawdowns(){
  const [h,d]=await Promise.all([analytics('history',{display_window:String(state.analyticsDisplay.volWindow)}),analytics('top-drawdowns',{limit:'5'})]);
  const history=inRange(analyticsRows(h)),episodes=analyticsRows(d).slice(0,5),net=history.map(r=>({...r,drawdown:r.drawdown??null}));
  let peak=-Infinity;net.forEach(r=>{if(finite(r.nav_net)){peak=Math.max(peak,Number(r.nav_net));r.drawdown=Number(r.nav_net)/peak-1;}});
  const columns=[{key:'peak_date',label:'峰值日期'},{key:'trough_date',label:'最低日期'},{key:'max_drawdown',label:'最大回撤（%）',render:v=>pct(v),csv:v=>finite(v)?Number(v)*100:''},{key:'recovery_date',label:'再创新高日期',render:v=>dateOnly(v)},{key:'drawdown_days',label:'峰到谷交易日'},{key:'recovery_days',label:'谷到恢复交易日'}];
  const data=panel('净值与 Top 5 回撤区间',`${drawdownChart(net,episodes)}<button type="button" class="icon-button" data-export-png>导出 PNG</button>${analyticsHeader('top_drawdowns',d,episodes,columns)}${analyticsTable(episodes,columns,{id:'top_drawdowns',rowClass:r=>r.episode_id===ResearchContext.drawdownEventId?'selected-row':''})}`,'峰值以 1 为起点；图中着色为 peak→trough 风险累积区间。表中最低日期是 trough，恢复日期为独立字段；未恢复事件保持空值。');
  $('#content').innerHTML=`${researchControls()}${data}`;bindAnalyticsActions();
  $$('.dd-episode-overlay').forEach(rect=>rect.onclick=()=>{const ep=episodes.find(x=>x.episode_id===rect.dataset.ddEpisode);if(ep)openDrawdownAttribution(ep);});
  $$('.analytics-table tr[data-table-row]').forEach((tr,i)=>tr.onclick=()=>{const r=episodes[i];if(r)openDrawdownAttribution(r);});
}
function openDrawdownAttribution(r){ResearchContext.drawdownEventId=r.episode_id;ResearchContext.fromDate=dateOnly(r.peak_date);ResearchContext.toDate=dateOnly(r.trough_date);ResearchContext.selectedDate=dateOnly(r.trough_date);ResearchContext.selectedEventId=r.episode_id;syncContextControls();state.page=3;nav();render();}

function drawdownRows(){
  let peak=-Infinity; return state.series.map(r=>{const n=Number(r.nav_net);peak=Math.max(peak,n);return {...r,drawdown:n/peak-1}});
}

async function renderOverview(){
  const s=state.summary,dd=drawdownRows();
  const [latest,ev,hist]=await Promise.all([
    api(`/api/strategy/${ResearchContext.strategyVersion}/day/${ResearchContext.selectedDate}`),
    api(`/api/strategy/V6/events?to_date=${ResearchContext.selectedDate}&limit=8`),
    analytics('history',{display_window:String(state.analyticsDisplay.volWindow)})
  ]);
  const histRows=inRange(analyticsRows(hist));
  const historySeries=[{key:'nav_net',label:'Net NAV',color:'#476de0',axisLabel:'净值（基准=1）'},...(state.analyticsDisplay.showGross?[{key:'nav_gross',label:'Gross NAV',color:'#cc9752'}]:[]),...(state.analyticsDisplay.showVol?[{key:'display_vol',label:`${state.analyticsDisplay.volWindow}D 年化波动率`,color:'#139b85',axis:1,format:'pct',axisLabel:'年化波动率（%）'}]:[])];
  const historyCols=[{key:'date',label:'交易日'},{key:'nav_net',label:'Net NAV',render:v=>num(v,6)},{key:'nav_gross',label:'Gross NAV',render:v=>num(v,6)},{key:'display_vol',label:`${state.analyticsDisplay.volWindow}D 展示波动率（%）`,render:v=>pct(v),csv:v=>finite(v)?(Number(v)*100).toFixed(8):''}];
  const recentEvents=ev.rows, p=latest.portfolio;
  const pos=state.series.findIndex(r=>dateOnly(r.date)===ResearchContext.selectedDate);
  const focus=latest.assets.slice().sort((a,b)=>Math.abs(Number(b.final_weight||0))-Math.abs(Number(a.final_weight||0))).slice(0,5);
  const exposures=state.exposures.find(r=>dateOnly(r.date)===ResearchContext.selectedDate);
  const trace=`<div class="daily-inspector"><div class="inspector-date">${esc(ResearchContext.selectedDate)} ${badge('REAL DATA','success')}</div><div class="inspector-kpis"><div><small>组合净收益</small><strong class="${cls(p.portfolio_return_net)}">${signedPct(p.portfolio_return_net)}</strong></div><div><small>10VT 倍率</small><strong>${num(p.final_10vt_multiplier,3)}×</strong></div><div><small>当日换手</small><strong>${pct(p.turnover)}</strong></div><div><small>当日成本</small><strong>${pct(p.total_cost,4)}</strong></div></div><div class="section-title">主要持仓 · 当日最终名义权重</div><div class="holdings-bars">${focus.map(a=>`<button class="holding-row" type="button" data-focus-asset="${esc(a.asset)}"><span>${esc(a.asset)}</span><span class="holding-track"><i style="width:${Math.min(100,Math.abs(Number(a.final_weight||0))/2.5*100)}%;background:${a.asset_class==='bond'?'#547cce':a.asset_class==='equity'?'#d59b52':'#149982'}"></i></span><strong>${pct(a.final_weight,1)}</strong></button>`).join('')}</div><button class="side-action" data-open-page="1" type="button">穿透这一天的仓位决策 →</button></div>`;
  $('#content').innerHTML=`
    ${researchControls()}<div class="kpi-grid overview-kpis">
      ${kpi('年化收益',pct(s.annualized_return),'V6 formal window','accent')}
      ${kpi('年化波动',pct(s.annualized_vol),'样本标准差 × √252')}
      ${kpi('Sharpe',num(s.sharpe),'净收益口径')}
      ${kpi('最大回撤',pct(s.max_drawdown),'历史峰值回撤','negative')}
    </div>
    <div class="grid2 overview-featured">
      ${panel('策略净值与展示波动率',`${lineChart(histRows,historySeries,{height:305,dual:historySeries.some(s=>s.axis===1)})}<small class="chart-source">${analyticsMeta(hist)}</small><button type="button" class="icon-button" data-export-png>导出 PNG</button><button type="button" class="icon-button" data-export-csv="strategy_history" data-method="V6 daily NAV and rolling display volatility">下载 CSV</button><details class="data-table-details"><summary>展开日频图表数据表</summary>${analyticsTable(histRows,historyCols,{id:'strategy_history'})}</details><div class="scrub-top"><strong id="scrubDate">${esc(ResearchContext.selectedDate)}</strong><span>点击图表选择真实交易日</span></div><input type="range" class="date-scrub" id="historyScrub" min="0" max="${Math.max(0,histRows.length-1)}" value="${Math.max(0,histRows.findIndex(r=>dateOnly(r.date)===ResearchContext.selectedDate))}" aria-label="在交易日期间滑动选择研究日期">`,'净收益复利净值；展示波动率是分析诊断，不等同于 10VT 控制口径。',badge('REAL V6','success'))}
      ${panel('单日决策穿透',trace,'点击资产即可进入逐层决策解释')}
    </div>
    <div class="kpi-grid secondary-kpis">
      ${kpi('权益平均名义敞口',pct(s.avg_equity_exposure),'Equity')}
      ${kpi('债券平均名义敞口',pct(s.avg_bond_exposure),'Bond')}
      ${kpi('商品平均名义敞口',pct(s.avg_commodity_exposure),'Commodity')}
      ${kpi('平均 10VT 倍率',num(s.mean_10vt_multiplier,3),`触及下限 ${pct(s.lower_bound_hit_rate)}`)}
    </div>
    <div class="grid2">
      ${panel('组合回撤路径',lineSvg(dd,'drawdown',{height:242,markerDate:ResearchContext.selectedDate,format:'pct'}),'点击任意日期可以继续穿透')}
      ${panel('三大类最终名义敞口',`<div class="legend"><span>Equity</span><span>Bond</span><span>Commodity</span></div>${multiLineSvg(state.exposures,['equity','bond','commodity'],{height:242,markerDate:ResearchContext.selectedDate})}`,'名义敞口可超过 100%；不等同于风险贡献')}
    </div>
    <div class="grid2">
      ${panel('最近的策略研究事件',`<div class="event-list compact">${recentEvents.slice(0,6).map(eventRow).join('')}</div>`,'点击某个事件，关联到 Decision / Attribution Explorer')}
      ${panel('研究路线图',`<div class="research-steps"><div><span>01</span><section><strong>解释决策</strong><small>为什么选中某资产、为什么持有这个仓位？</small></section></div><div><span>02</span><section><strong>定位事件</strong><small>找到 haircut、10VT、midmonth、换月和回撤。</small></section></div><div><span>03</span><section><strong>检验假设</strong><small>使用 V6 Python 引擎执行真实反事实实验。</small></section></div></div><button type="button" class="primary-button" data-open-page="5">进入 Mode B 参数实验 →</button>`,'从历史决策走向参数实验')}
    </div>`;
  $$('.event-row').forEach(b=>b.addEventListener('click',()=>openEventById(b.dataset.event)));
  $$('#content [data-focus-asset]').forEach(b=>b.addEventListener('click',()=>{ResearchContext.selectedAsset=b.dataset.focusAsset;syncContextControls();goToPage(1)}));
  const scrub=$('#historyScrub');if(scrub)scrub.addEventListener('input',e=>{const row=state.series[Number(e.target.value)];if(!row)return;ResearchContext.selectedDate=dateOnly(row.date);$('#scrubDate').textContent=ResearchContext.selectedDate;$('#selectedDate').value=ResearchContext.selectedDate;syncContextControls();});
  if(scrub)scrub.addEventListener('change',()=>render());
  bindAnalyticsActions();
}

function eventRow(e){const sev=Math.min(100,Math.max(5,Number(e.severity||0)*400));return `<button class="event-row ${ResearchContext.selectedEventId===e.event_id?'active':''}" type="button" data-event="${esc(e.event_id)}"><span class="date">${esc(e.date)}</span><span class="type">${esc(e.event_group)}</span><span class="title">${esc(e.title)}</span><span class="severity"><i style="width:${sev}%"></i></span></button>`;}

const DECISION_STEPS=[
  ['Eligibility','eligibility'],['Momentum','momentum'],['Risk Budget','risk_budget'],['Sleeve Scale','sleeve_scale'],['Cap','cap'],['Haircut','haircut'],['Execution','execution'],['10VT','10vt'],['Final Weight','final_weight'],['Daily PnL','pnl']
];

function decisionStepMini(d,key){
  if(key==='eligibility')return d.eligibility.trade_eligible?'Eligible':'Unavailable';
  if(key==='momentum')return d.momentum.participates_in_elimination?(d.momentum.selected?'Selected':'Excluded'):'Fixed';
  if(key==='risk_budget')return pct(d.risk_budget.rb_weight);
  if(key==='sleeve_scale')return `×${num(d.sleeve_scale.scale,2)}`;
  if(key==='cap')return d.cap.binding?'Binding':'Not binding';
  if(key==='haircut')return d.haircut.triggered?'Triggered':'Normal';
  if(key==='execution')return pct(d.execution.pre10vt_weight);
  if(key==='10vt')return num(d['10vt'].final_multiplier,3);
  if(key==='final_weight')return pct(d.final_weight.final_weight);
  if(key==='pnl')return signedPct(d.pnl.asset_contribution);
  return '';
}

function renderDecisionDetail(d,idx){
  const key=DECISION_STEPS[idx][1],x=d[key]; let body='',formula='';
  if(key==='eligibility')body=[['Trade eligible',fmt(x.trade_eligible,'bool')],['Signal usable',fmt(x.signal_usable,'bool')],['Risk estimate usable',fmt(x.risk_estimate_usable,'bool')],['Signal source',esc(x.signal_source||'—')]];
  if(key==='momentum'){
    const sig=x.signals||{},rk=x.ranks||{}; body=[['Participates',x.participates_in_elimination?'YES':'NO'],['20D return',pct(sig.ret_20)],['60D return',pct(sig.ret_60)],['240D return',pct(sig.ret_240)],['20D Sharpe',num(sig.sharpe_20)],['60D Sharpe',num(sig.sharpe_60)],['240D Sharpe',num(sig.sharpe_240)],['Mean rank',num(x.mean_rank,2)],['Selected',fmt(x.selected,'bool')],['Selected risk assets',esc((x.selected_risk_assets||[]).join(', ')||'—')],['Excluded',esc((x.excluded_risk_assets||[]).join(', ')||'—')]];
    formula=`六项信号同日横截面排序 → 等权平均名次 → 风险资产末位剔除；TF/T 不参与淘汰。`;
  }
  if(key==='risk_budget'){body=[['Class budget',pct(x.class_budget)],['Selected in class',esc(x.selected_in_class)],['Asset budget',pct(x.asset_budget)],['Risk vol',pct(x.risk_vol)],['RB weight',pct(x.rb_weight)]];formula=`asset_budget = (1/3) / N_class；RB weight = asset_budget / risk_vol`}
  if(key==='sleeve_scale'){body=[['RB weight',pct(d.risk_budget.rb_weight)],['Sleeve scale',num(x.scale,2)],['Scaled weight',pct(x.scaled_raw_weight)]];formula=`${pct(d.risk_budget.rb_weight)} × ${num(x.scale,2)} = ${pct(x.scaled_raw_weight)}`}
  if(key==='cap'){body=[['Scaled weight',pct(d.sleeve_scale.scaled_raw_weight)],['Asset cap',pct(x.cap)],['Binding',x.binding?badge('YES','warn'):badge('NO','success')],['Post-cap',pct(x.post_cap_weight)],['Redistributed',x.redistributed?'YES':'NO']];formula=`post_cap = min(scaled_weight, cap)；超出部分不再分配。`}
  if(key==='haircut'){body=[['Vol 20',pct(x.vol20)],['Vol 60',pct(x.vol60)],['Short vol',pct(x.short_vol)],['Long vol',pct(x.long_vol)],['Historical q90',pct(x.historical_threshold)],['Triggered',x.triggered?badge('YES','warn'):badge('NO','success')],['Multiplier',num(x.multiplier,2)],['Post-haircut target',pct(x.post_haircut_weight)]];formula=`short_vol = max(vol20, vol60)；超过长期波动率历史 q90 时按 V6 haircut 倍率缩减。`}
  if(key==='execution'){body=[['Close theoretical',pct(x.current_close_theoretical_target)],['Monthly base',pct(x.monthly_base_target)],['Controlled target',pct(x.controlled_target)],['Smoothing step',esc(x.monthly_smoothing_step??'—')],['Deviation',pct(x.deviation)],['Midmonth trigger',fmt(x.midmonth_trigger,'bool')],['Start-of-day execution',pct(x.unscaled_execution_weight)],['Pre-10VT',pct(x.pre10vt_weight)]];formula=`执行权重是 start-of-day 状态；当天 close target 不追溯改变同日 PnL。`}
  if(key==='10vt'){body=[['Portfolio vol estimate',pct(x.portfolio_vol_estimate)],['Target vol',pct(x.target_vol)],['Raw multiplier',num(x.raw_multiplier,3)],['Final multiplier',num(x.final_multiplier,3)],['Bounds',`${num(x.lower_bound,1)} – ${num(x.upper_bound,1)}`],['Window',`${x.window||120} trading days`]];formula=`m = clip(10% / σ120, 0.5, 1.5)；σ120 只使用前 120 个交易日的 pre-10VT gross returns。`}
  if(key==='final_weight'){body=[['Pre-10VT',pct(x.pre10vt_weight)],['Multiplier',num(x.multiplier,3)],['Final weight',pct(x.final_weight)],['Identity error',num(x.identity_error,12)]];formula=`${pct(x.pre10vt_weight)} × ${num(x.multiplier,3)} = ${pct(x.final_weight)}`}
  if(key==='pnl'){body=[['Start weight',pct(x.weight_start_of_day)],['Gross return',signedPct(x.trade_return_gross)],['Contract roll cost',pct(x.roll_cost,4)],['Net trade return',signedPct(x.trade_return_net)],['Rebalance cost',pct(x.rebalance_cost,4)],['Asset contribution',signedPct(x.asset_contribution)],['Portfolio net return',signedPct(x.portfolio_return_net)]];formula=`asset contribution = start weight × trade_return_net − rebalance_cost`}
  return `<div class="detail-grid">${body.map(([k,v])=>detailItem(k,v)).join('')}</div>${formula?`<div class="formula">${esc(formula)}</div>`:''}${key==='execution'?`<div class="time-warning">时间语义：当前收盘理论目标 ≠ 当日开盘执行权重。收盘决策只能影响后续交易日。</div>`:''}`;
}

async function renderDecision(){
  const d=await api(`/api/strategy/${ResearchContext.strategyVersion}/decision/${ResearchContext.selectedDate}/${ResearchContext.selectedAsset}`);
  const s=d.summary;
  $('#content').innerHTML=`
    <div class="decision-hero">
      <div class="asset-hero"><div class="class">${esc(labelClass(d.asset_class))}</div><div class="symbol">${esc(d.asset)}</div><div>${s.selected?badge('SELECTED','success'):badge('NOT SELECTED','neutral')} ${s.signal_source?badge(s.signal_source,s.signal_source.includes('PROXY')?'warn':'neutral'):''}</div></div>
      <div class="metric-box"><span>Final weight</span><strong>${pct(s.final_weight)}</strong></div>
      <div class="metric-box"><span>Net asset return</span><strong class="${cls(s.trade_return_net)}">${signedPct(s.trade_return_net)}</strong></div>
      <div class="metric-box"><span>Contribution</span><strong class="${cls(s.asset_contribution)}">${signedPct(s.asset_contribution)}</strong></div>
      <div class="metric-box"><span>10VT multiplier</span><strong>${num(s.final_10vt_multiplier)}</strong></div>
    </div>
    ${panel('Decision Pipeline',`<div class="pipeline">${DECISION_STEPS.map(([name,key],i)=>`<button type="button" class="pipe-step ${i===state.activeDecisionStep?'active':''}" data-step="${i}"><span class="n">${String(i+1).padStart(2,'0')}</span><strong>${name}</strong><span class="mini">${esc(decisionStepMini(d,key))}</span></button>`).join('')}</div>`,'从资格 → 信号 → 权重 → 风控 → 执行 → PnL，逐层解释最终仓位')}
    <div class="grid2">
      ${panel(DECISION_STEPS[state.activeDecisionStep][0],`<div id="decisionDetail">${renderDecisionDetail(d,state.activeDecisionStep)}</div>`,'点击上方任一步骤查看真实数值与公式')}
      ${panel('当前日资产上下文',table((await api(`/api/v6/day/${ResearchContext.selectedDate}`)).assets,[
        {key:'asset',label:'Asset'}, {key:'selected',label:'Selected',render:v=>v?badge('YES','success'):badge('NO','neutral')},
        {key:'mean_rank',label:'Mean rank',render:v=>num(v,2)}, {key:'risk_vol',label:'Risk vol',render:v=>pct(v)},
        {key:'final_weight',label:'Final weight',render:v=>pct(v)}, {key:'asset_contribution',label:'Contribution',render:v=>signedPct(v),className:v=>cls(v)}
      ]),'同一天的横截面，帮助判断该资产相对位置')}
    </div>`;
  $$('.pipe-step').forEach(b=>b.addEventListener('click',()=>{state.activeDecisionStep=Number(b.dataset.step);renderDecision();}));
}

async function fetchEvents(){
  const q=new URLSearchParams({limit:'1200'}); if(ResearchContext.fromDate)q.set('from_date',ResearchContext.fromDate);if(ResearchContext.toDate)q.set('to_date',ResearchContext.toDate);if(state.eventFilters.group)q.set('event_group',state.eventFilters.group);if(state.eventFilters.asset)q.set('asset',state.eventFilters.asset);
  const x=await api(`/api/strategy/${ResearchContext.strategyVersion}/events?${q}`);state.eventRows=x.rows;return x.rows;
}
async function openEventById(id){
  const x=await api(`/api/strategy/${ResearchContext.strategyVersion}/events/${encodeURIComponent(id)}`);state.selectedEvent=x.event;ResearchContext.selectedEventId=id;ResearchContext.selectedDate=x.event.date;if(x.event.asset)ResearchContext.selectedAsset=x.event.asset;if(x.event.related_date_from)ResearchContext.fromDate=x.event.related_date_from;if(x.event.related_date_to)ResearchContext.toDate=x.event.related_date_to;syncContextControls();if(state.page!==2){state.page=2;nav();}render();
}

async function renderEvents(){
  const rows=await fetchEvents(); const selected=state.selectedEvent || rows[0] || null; if(!state.selectedEvent&&selected){state.selectedEvent=selected;ResearchContext.selectedEventId=selected.event_id;}
  $('#content').innerHTML=`<div class="event-layout">
    ${panel('筛选事件',`<div class="filters"><label>Event group<select id="eventGroup"><option value="">全部</option>${['PERFORMANCE','MOMENTUM','RISK','EXECUTION','ROLL','DATA_QUALITY'].map(x=>`<option ${state.eventFilters.group===x?'selected':''}>${x}</option>`).join('')}</select></label><label>Asset<select id="eventAsset"><option value="">全部</option>${state.assets.map(x=>`<option ${state.eventFilters.asset===x?'selected':''}>${x}</option>`).join('')}</select></label><div class="callout">事件由 V6 Snapshot 派生，不改变 V6 策略数据。</div></div>`)}
    ${panel(`事件列表 · ${rows.length}`,`<div class="event-list">${rows.map(eventRow).join('')}</div>`,'点击事件可同步全站 Research Context')}
    ${panel('事件详情',selected?eventDetail(selected):'<div class="empty-state">请选择事件</div>','事件可以直接进入决策解释或收益归因')}
  </div>`;
  $('#eventGroup').addEventListener('change',e=>{state.eventFilters.group=e.target.value;state.selectedEvent=null;render();});
  $('#eventAsset').addEventListener('change',e=>{state.eventFilters.asset=e.target.value;state.selectedEvent=null;render();});
  $$('.event-row').forEach(b=>b.addEventListener('click',async()=>{const x=(await api(`/api/strategy/V6/events/${encodeURIComponent(b.dataset.event)}`)).event;state.selectedEvent=x;ResearchContext.selectedEventId=x.event_id;ResearchContext.selectedDate=x.date;if(x.asset)ResearchContext.selectedAsset=x.asset;syncContextControls();render();}));
  bindEventActions();
}
function eventDetail(e){return `<div class="event-detail"><div class="big-date">${esc(e.date)}</div><div>${badge(e.event_group,'neutral')} ${badge(e.event_type,e.event_group==='DATA_QUALITY'?'warn':'neutral')}</div><h3>${esc(e.title)}</h3>${e.description?`<div class="muted">${esc(e.description)}</div>`:''}<div class="detail-grid">${detailItem('Asset',esc(e.asset||'Portfolio'))}${detailItem('Severity',num(e.severity,4))}${detailItem('Before',num(e.before_value,4))}${detailItem('Event value',num(e.event_value,4))}${detailItem('Window from',esc(e.related_date_from||'—'))}${detailItem('Window to',esc(e.related_date_to||'—'))}</div><div class="event-actions"><button class="primary-button" id="toDecision" type="button">打开决策解释</button><button class="secondary-button" id="toAttribution" type="button">打开收益归因</button></div></div>`;}
function bindEventActions(){const a=$('#toDecision'),b=$('#toAttribution');if(a)a.addEventListener('click',()=>{state.page=1;nav();render();});if(b)b.addEventListener('click',()=>{if(state.selectedEvent?.related_date_from)ResearchContext.fromDate=state.selectedEvent.related_date_from;if(state.selectedEvent?.related_date_to)ResearchContext.toDate=state.selectedEvent.related_date_to;else{ResearchContext.fromDate=state.selectedEvent?.date;ResearchContext.toDate=state.selectedEvent?.date;}syncContextControls();state.page=3;nav();render();});}

function attributionBars(rows){
  if(!rows.length)return '<div class="empty-state">无归因数据</div>';const max=Math.max(...rows.map(r=>Math.abs(Number(r.net_contribution||0))),1e-9);
  return `<div class="bar-list">${rows.slice().sort((a,b)=>Math.abs(b.net_contribution)-Math.abs(a.net_contribution)).map(r=>{const v=Number(r.net_contribution||0),w=Math.min(50,Math.abs(v)/max*50);return `<div class="bar-row"><span class="name">${esc(r.asset||labelClass(r.asset_class))}</span><div class="bar-track"><span class="bar-zero"></span><span class="bar-fill ${v<0?'neg':'pos'}" style="width:${w}%"></span></div><span class="bar-value ${cls(v)}">${signedPct(v)}</span></div>`}).join('')}</div>`;
}

async function renderAttribution(){
  const [asset,classA]=await Promise.all([
    api(`/api/strategy/V6/attribution?from_date=${ResearchContext.fromDate}&to_date=${ResearchContext.toDate}&level=asset`),
    api(`/api/strategy/V6/attribution?from_date=${ResearchContext.fromDate}&to_date=${ResearchContext.toDate}&level=class`)
  ]);
  const p=asset.portfolio;
  $('#content').innerHTML=`
    <div class="kpi-grid">
      ${kpi('区间复合净收益',signedPct(p.compounded_net_return),'compounded return',cls(p.compounded_net_return))}
      ${kpi('日收益算术和',signedPct(p.arithmetic_sum_daily_net_return),'用于贡献恒等式')}
      ${kpi('资产贡献加总',signedPct(p.additive_net_contribution_sum),'additive contributions')}
      ${kpi('交易日',p.observations,'resolved window')}
      ${kpi('起点',asset.resolved_from,'resolved')}
      ${kpi('终点',asset.resolved_to,'resolved')}
    </div>
    <div class="callout warning">资产/大类贡献是“每日组合收益贡献的加总”，不是复利收益。区间复合收益单独展示，避免把两种概念混为一谈。</div>
    ${ResearchContext.drawdownEventId?`<div class="callout warning drawdown-attribution-note">回撤事件 ${esc(ResearchContext.drawdownEventId)}：回撤幅度按谷日 NAV / 峰日 NAV − 1 计算，不含峰日收益；此处区间归因包含峰日收益，因此区间复合收益可能与最大回撤幅度不同。</div>`:''}
    <div class="grid2">
      ${panel('大类贡献',attributionBars(classA.rows),'Equity / Bond / Commodity 的 additive net contribution')}
      ${panel('资产贡献',attributionBars(asset.rows),'按绝对贡献排序；可快速识别回撤主因')}
    </div>
    ${panel('资产归因明细',table(asset.rows,[
      {key:'asset',label:'Asset'}, {key:'asset_class',label:'Class',render:v=>esc(labelClass(v))},
      {key:'gross_contribution',label:'Gross PnL',render:v=>signedPct(v),className:v=>cls(v)},
      {key:'contract_roll_cost',label:'Roll cost',render:v=>pct(v,4)}, {key:'rebalance_cost',label:'Rebal cost',render:v=>pct(v,4)},
      {key:'net_contribution',label:'Net contribution',render:v=>signedPct(v),className:v=>cls(v)}, {key:'average_final_weight',label:'Avg weight',render:v=>pct(v)}
    ]),'Price PnL、合约换月成本与组合再平衡成本分开显示')}`;
}

async function renderExecution(){
  const x=await api(`/api/strategy/V6/roll-history/${ResearchContext.selectedAsset}?from_date=${ResearchContext.fromDate}&to_date=${ResearchContext.toDate}&events_only=true`);const rows=x.rows;
  const timeline=rows.slice(-16).map(r=>`<div class="roll-block roll-event"><div class="rdate">${dateOnly(r.date)}</div><strong>${esc(r.roll_from||'—')} → ${esc(r.roll_to||'—')}</strong><span>${esc(r.roll_trigger||'—')}</span></div>`).join('');
  const selected=rows.find(r=>dateOnly(r.date)===ResearchContext.selectedDate)||rows.at(-1);
  $('#content').innerHTML=`
    <div class="grid2">
      ${panel(`${ResearchContext.selectedAsset} 合约生命周期`,`<div class="roll-timeline">${timeline||'<div class="empty-state">当前区间无换月事件</div>'}</div>`,'最近 16 次真实换月事件')}
      ${panel('换月规则',rollRule(ResearchContext.selectedAsset),'不同资产类别使用不同换月机制')}
    </div>
    ${panel('Roll Event Inspector',selected?rollInspector(selected):'<div class="empty-state">当前区间没有换月事件</div>','start-of-day 旧合约贡献 t 日收益；close 换仓后新合约从 t+1 生效')}
    ${panel('收益时点',`<div class="timing-diagram"><div class="timing-step">t 日开盘<br><strong>OLD CONTRACT</strong></div><div class="timing-arrow">→</div><div class="timing-step">t 日收益<br><strong>same-contract PnL</strong></div><div class="timing-arrow">→</div><div class="timing-step">t 日收盘<br><strong>ROLL DECISION</strong></div></div><div class="timing-diagram" style="margin-top:6px"><div class="timing-step">close 后<br><strong>NEW CONTRACT HELD</strong></div><div class="timing-arrow">→</div><div class="timing-step">t+1<br><strong>NEW CONTRACT PnL</strong></div></div>`,'V6 instant roll 的真实时间语义')}
    ${panel('区间换月明细',table(rows,[{key:'date',label:'Date',render:v=>dateOnly(v)},{key:'roll_trigger',label:'Trigger'},{key:'roll_from',label:'From'},{key:'roll_to',label:'To'},{key:'candidate_contract',label:'Candidate'},{key:'confirmed_active_contract',label:'Confirmed'},{key:'days_to_expiry',label:'DTE'},{key:'turnover',label:'Turnover',render:v=>num(v,3)},{key:'roll_cost',label:'Roll cost',render:v=>pct(v,4)}]),`${rows.length} 次换月事件`)}`;
}
function rollRule(asset){if(['IF','IC','IM'].includes(asset))return `<div class="detail-grid">${detailItem('Trigger','T-5 trading days')}${detailItem('Target','nearest valid later maturity')}${detailItem('Liquidity roll','NO')}</div>`;if(['TF','T'].includes(asset))return `<div class="detail-grid">${detailItem('Candidate','OI ↓ → Volume ↓ → Maturity ↑')}${detailItem('Confirmation','2 consecutive days')}${detailItem('Protection','T-5 HARD_ROLL')}${detailItem('Backward maturity','not globally prohibited')}</div>`;return `<div class="detail-grid">${detailItem('Trigger','delivery-month start − 30 calendar days')}${detailItem('Target','later maturity only')}${detailItem('Ranking','OI ↓ → Volume ↓ → Maturity ↑')}</div>`;}
function rollInspector(r){return `<div class="detail-grid">${detailItem('Date',dateOnly(r.date))}${detailItem('Trigger',esc(r.roll_trigger))}${detailItem('Old contract',esc(r.roll_from))}${detailItem('New contract',esc(r.roll_to))}${detailItem('Candidate',esc(r.candidate_contract))}${detailItem('Confirmed active',esc(r.confirmed_active_contract))}${detailItem('Days to expiry',esc(r.days_to_expiry??'—'))}${detailItem('Start holding',esc(r.held_contract_start_of_day))}${detailItem('Close holding',esc(r.held_contract_end_of_day))}${detailItem('Turnover',num(r.turnover))}${detailItem('Roll cost',pct(r.roll_cost,4))}${detailItem('Status',esc(r.status||'—'))}</div>`;}

function parameterControl(p,values){
  const key=p.key,ready=p.status==='READY',shortWindows=Number(p.number)===3||key==='short_vol_windows',value=values[key]??p.baseline??'';
  let control;
  if(shortWindows){control=`<input name="${esc(key)}" value="20,60" disabled>`;}
  else if(Array.isArray(p.allowed_values)&&p.allowed_values.length){control=`<select name="${esc(key)}" ${ready?'':'disabled'}>${p.allowed_values.map(v=>`<option value="${esc(v)}" ${String(v)===String(value)?'selected':''}>${esc(Array.isArray(v)?v.join(' / '):v)}</option>`).join('')}</select>`;}
  else control=`<input name="${esc(key)}" value="${esc(Array.isArray(value)?value.join(','):value)}" ${ready?'':'disabled'} ${['target_vol','haircut','midmonth_threshold','quantile'].includes(key)?'type="number" step=".01"':''}>`;
  const baseline=shortWindows?'20D / 60D 双窗口取最大值（V6 实现）':Array.isArray(p.baseline)?p.baseline.join(' / '):p.baseline??'—';
  const semantic=key==='haircut'?'V6语义：触发后保留该倍数权重（0.5 即减仓 50%）。':'';
  return `<div class="parameter-card ${ready?'ready':'disabled'}"><div class="parameter-top"><strong>P${p.number||'+'} · ${esc(p.label||key)}</strong>${badge(p.status||'NOT_VERIFIED',ready?'success':'neutral')}</div><div class="parameter-note">V6 baseline：<b>${esc(baseline)}</b> · 阶段：${esc(p.stage||'—')}</div><div class="parameter-control">${control}</div>${semantic?`<small>${semantic}</small>`:''}<small>${esc(p.reason||(ready?'Python 引擎支持真实重跑':'当前 V6 适配器尚未支持此项真实重跑'))}</small>${p.required_upstream?`<small>需重跑上游：${esc(Array.isArray(p.required_upstream)?p.required_upstream.join(' → '):p.required_upstream)}</small>`:''}</div>`;
}
function experimentForm(){
  const registry=state.parameterRegistry||{},orig=registry.original||[],adv=registry.advanced||[],c=state.experimentResult?.effective_params||state.experimentResult?.config||{};
  const seven=orig.map(p=>parameterControl(p,c)).join(''),advanced=adv.map(p=>parameterControl(p,c)).join('');
  return `<form id="experimentForm"><div class="param-groups"><section class="param-group"><h4>原文七参数 · V6 baseline 锁定</h4><p class="muted">优先显示《策略复现》原始定义。只有 READY 项能进入实际 Python 重跑。</p><div class="parameter-grid">${seven||'<div class="empty-state">参数能力清单载入中</div>'}</div></section><details class="advanced-params"><summary>高级策略与成本实验</summary><div class="parameter-grid">${advanced||'<div class="empty-state">暂无能力信息</div>'}</div></details><div class="callout">展示窗口、胜率口径、资产类别和日期范围只过滤研究视图，不修改策略回测范围。实验只通过 Python API 执行。</div><button class="primary-button" type="submit" ${orig.some(p=>p.status==='READY')?'':'disabled'}>运行真实 V6 实验</button></div></form>`;
}
function readyParameters(){const reg=state.parameterRegistry||{};return [...(reg.original||[]),...(reg.advanced||[])].filter(p=>p.status==='READY');}
function sensitivityPanel(){const ready=readyParameters(),defaultParam=ready.find(p=>p.key==='target_vol')||ready[0];return panel('单参数敏感性扫描',`<div class="sensitivity-controls"><label>READY 参数<select id="sensitivityParam">${ready.map(p=>`<option value="${esc(p.key)}" ${p.key===defaultParam?.key?'selected':''}>${esc(p.label||p.key)} · ${esc(p.key)}</option>`).join('')}</select></label><label>候选值（3–5 项，逗号分隔）<input id="sensitivityValues" value="${defaultParam?.key==='target_vol'?'8,10,12':'0.25,0.5,0.75'}"></label><div class="sensitivity-estimate" id="sensitivityEstimate">每个候选项调用一次真实 Python 回测；预计任务数：3。实际耗时取决于引擎与缓存。</div><button type="button" class="secondary-button" id="runSensitivity" ${!ready.length||state.sensitivity.running?'disabled':''}>运行敏感性扫描</button><button type="button" class="ghost-button" id="cancelSensitivity" ${state.sensitivity.running?'':'disabled'}>停止后续任务</button><div id="sensitivityStatus" class="run-status">${state.sensitivity.running?'扫描进行中':state.sensitivity.cancelRequested?'已停止排队任务':''}</div></div>${state.sensitivity.results.length?analyticsTable(state.sensitivity.results.map((r,i)=>({index:i+1,value:r.value,status:r.result?.status||'FAIL',annualized_return:r.result?.experiment?.annualized_return,max_drawdown:r.result?.experiment?.max_drawdown,config_hash:r.result?.config_hash||''})),[{key:'value',label:'候选值'},{key:'status',label:'状态'},{key:'annualized_return',label:'年化收益',render:v=>pct(v)},{key:'max_drawdown',label:'最大回撤',render:v=>pct(v)},{key:'config_hash',label:'配置哈希'}],{id:'sensitivity_results'}):'<div class="empty-state">尚无扫描结果。</div>'}`,'每次都提交 /api/experiment；浏览器不会合成或缩放回测结果。');}
function bindSensitivity(){const input=$('#sensitivityValues'),estimate=$('#sensitivityEstimate'),sel=$('#sensitivityParam');const presets={target_vol:'8,10,12',vt_window:'60,120,240',commodity_cost_bps:'0,2,5,10',midmonth_threshold:'15,20,25',haircut:'0.25,0.5,0.75',quantile:'0.8,0.9,0.95'};if(sel)sel.onchange=()=>{if(presets[sel.value])input.value=presets[sel.value];input.dispatchEvent(new Event('input'));};if(input)input.oninput=()=>{const n=input.value.split(',').map(x=>x.trim()).filter(Boolean).length;estimate.textContent=`每个候选项调用一次真实 Python 回测；预计任务数：${n}。实际耗时取决于引擎与缓存。${n<3?' 至少需要 3 项。':''}${n>5?' 最多允许 5 项。':''}`;};const cancel=$('#cancelSensitivity');if(cancel)cancel.onclick=()=>{state.sensitivity.cancelRequested=true;$('#sensitivityStatus').textContent=state.sensitivity.inFlight?'已请求停止：当前回测无法中断，将在当前任务完成后停止后续排队任务。':'已停止后续任务。';};const run=$('#runSensitivity');if(run)run.onclick=async()=>{const key=sel.value,rawValues=input.value.split(',').map(x=>x.trim()).filter(Boolean);if(rawValues.length<3||rawValues.length>5){$('#sensitivityStatus').textContent='每次敏感性扫描需选择 3 至 5 个候选值。';return;}const values=rawValues.map(v=>{const n=Number(v);return Number.isFinite(n)?(['target_vol','midmonth_threshold'].includes(key)&&n>1?n/100:n):v;});if(!values.length)return;state.sensitivity={running:true,cancelRequested:false,results:[],inFlight:false};run.disabled=true;cancel.disabled=false;$('#sensitivityStatus').textContent=`RUNNING · ${values.length} 个真实后端任务依次执行。`;
    const base={momentum_excluded_count:1,risk_budget_vol_window:240,asset_short_vol_window:20,short_vol_windows:[20,60],asset_long_vol_window:240,haircut:.5,midmonth_threshold:.2,target_vol:.1,vt_window:120,quantile:.9,quantile_lookback:240,commodity_cost_bps:0};
    for(let i=0;i<values.length;i++){if(state.sensitivity.cancelRequested)break;const cfg={...base,[key]:values[i]};if(['target_vol','vt_window','haircut','quantile','midmonth_threshold','commodity_cost_bps'].includes(key)===false&&key in base===false)continue;state.sensitivity.inFlight=true;$('#sensitivityStatus').textContent=`RUNNING · 正在执行 ${i+1}/${values.length}；取消将停止后续任务。`;try{const result=await api('/api/experiment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});state.sensitivity.results.push({value:values[i],result});}catch(error){state.sensitivity.results.push({value:values[i],result:{status:'FAIL',reason:error.message}});}state.sensitivity.inFlight=false;}
    state.sensitivity.running=false;run.disabled=false;cancel.disabled=true;$('#sensitivityStatus').textContent=state.sensitivity.cancelRequested?'已停止后续任务；已发出的当前请求完成后才停止。':`完成 ${state.sensitivity.results.length}/${values.length} 个真实回测。`;render();};}
function experimentComparison(r){if(!r?.experiment)return `<div class="empty-state">运行实验后，这里将展示 Baseline 与 Experiment 的差异。</div>`;const b=state.summary,e=r.experiment;const items=[['Annualized return','annualized_return','pct'],['Annualized vol','annualized_vol','pct'],['Sharpe','sharpe','num'],['Max drawdown','max_drawdown','pct']];return `<div class="compare-grid"><div class="compare-head">BASELINE · V6</div><div class="compare-head">Experiment</div><div class="compare-head">Δ</div>${items.map(([lab,k,t])=>{const bv=b[k],ev=e[k],d=ev-bv;return `<div class="compare-cell"><strong>${lab}</strong><br>${t==='pct'?pct(bv):num(bv)}</div><div class="compare-cell">${t==='pct'?pct(ev):num(ev)}</div><div class="compare-cell ${cls(d)}">${t==='pct'?signedPct(d):(d>=0?'+':'')+num(d)}</div>`}).join('')}</div>`;}
async function renderExperiment(){
  const costHistory=await analytics('history',{display_window:'120'});state.baselineCostRows=analyticsRows(costHistory);
  $('#content').innerHTML=`${panel('参数能力与实验配置',experimentForm(),'能力状态由 GET /api/experiment/parameters 提供；V0.6 前端不会自行解锁参数')}${panel('实验状态',`<div class="run-status" id="experimentStatus">${state.experimentResult?`上次运行：${badge(state.experimentResult.status,state.experimentResult.status==='PASS'?'success':'warn')} · ${esc(state.experimentResult.config_hash||'')}`:'尚未运行实验'}</div><div class="callout" style="margin-top:10px">实验结果由 Python V6 engine 计算并保存至独立实验输出。V6 baseline 保持只读。</div>`,'真实引擎重跑')}${sensitivityPanel()}${state.experimentResult?renderExperimentResults(state.experimentResult):''}`;
  bindAnalyticsActions();bindSensitivity();
  $('#experimentForm').addEventListener('submit',async e=>{e.preventDefault();const raw=Object.fromEntries(new FormData(e.target)),f={};for(const [k,v] of Object.entries(raw)){const n=Number(v);f[k]=v!==''&&Number.isFinite(n)?n:v;}
    const cfg={momentum_excluded_count:1,risk_budget_vol_window:240,asset_short_vol_window:20,short_vol_windows:[20,60],asset_long_vol_window:240,haircut:.5,midmonth_threshold:.2,target_vol:.1,vt_window:120,quantile:.9,quantile_lookback:240,commodity_cost_bps:0,...f};
    const status=$('#experimentStatus');status.textContent='RUNNING · 正在调用 V6 Python 引擎…';try{state.experimentResult=await api('/api/experiment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});render();}catch(err){status.innerHTML=`<span class="negative">${esc(err.message)}</span>`;}});
}
function renderExperimentResults(r){
  const exp=r.experiment||r.metrics||{},baseline=state.summary,items=[['年化收益','annualized_return','pct'],['年化波动','annualized_vol','pct'],['Sharpe','sharpe','num'],['最大回撤','max_drawdown','pct'],['平均权益敞口','avg_equity_exposure','pct'],['平均债券敞口','avg_bond_exposure','pct'],['平均商品敞口','avg_commodity_exposure','pct']];
  const rows=items.map(([label,key])=>({label,baseline:baseline[key],experiment:exp[key],delta:finite(exp[key])&&finite(baseline[key])?Number(exp[key])-Number(baseline[key]):null}));
  const kpiCols=[{key:'label',label:'指标'},{key:'baseline',label:'V6 Baseline',render:(v,row)=>row.label==='Sharpe'?num(v,3):pct(v),csv:(v,row)=>row.label==='Sharpe'?v:(finite(v)?Number(v)*100:'')},{key:'experiment',label:'Experiment',render:(v,row)=>row.label==='Sharpe'?num(v,3):pct(v),csv:(v,row)=>row.label==='Sharpe'?v:(finite(v)?Number(v)*100:'')},{key:'delta',label:'Δ',render:(v,row)=>finite(v)?(row.label==='Sharpe'?(Number(v)>=0?'+':'')+num(v,3):signedPct(v)):'—',csv:(v,row)=>row.label==='Sharpe'?v:(finite(v)?Number(v)*100:'')}];
  const experimentHistory=inRange(analyticsRows(r.history)),baselineByDate=new Map(state.series.map(x=>[dateOnly(x.date),x.nav_net]));
  const pairedHistory=experimentHistory.map(x=>({...x,baseline_nav:baselineByDate.get(dateOnly(x.date))}));
  const expExposure=analyticsRows(r.exposure),baseExposure=new Map(state.exposures.map(x=>[dateOnly(x.date),x]));
  const pairedExposure=inRange(expExposure).map(x=>{const b=baseExposure.get(dateOnly(x.date))||{};return {...x,baseline_equity:b.equity,baseline_bond:b.bond,baseline_commodity:b.commodity};});
  const baseHistData=state.baselineCostRows||[];
  const baseCosts={contract_roll_cost:baseHistData.reduce((s,x)=>s+Number(x.contract_roll_cost||0),0),portfolio_rebalance_cost:baseHistData.reduce((s,x)=>s+Number(x.portfolio_rebalance_cost||0),0),total_cost:baseHistData.reduce((s,x)=>s+Number(x.total_cost||0),0)};
  const costRows=['contract_roll_cost','portfolio_rebalance_cost','total_cost'].map(key=>({label:key==='contract_roll_cost'?'合约换月成本（全资产）':key==='portfolio_rebalance_cost'?'组合再平衡成本':'总成本',baseline:baseCosts[key],experiment:r.costs?.[key]}));
  const costCols=[{key:'label',label:'费用口径'},{key:'baseline',label:'V6 Baseline（%）',render:v=>pct(v,4),csv:v=>finite(v)?Number(v)*100:''},{key:'experiment',label:'Experiment（%）',render:v=>pct(v,4),csv:v=>finite(v)?Number(v)*100:''}];
  const eEpisodes=analyticsRows(r.drawdowns),bEpisodes=state.analytics[`${ANALYTICS_BASE}/top-drawdowns?limit=5`]?.rows||state.drawdowns;
  const eMax=eEpisodes[0]?.max_drawdown,bMax=state.summary.max_drawdown;
  return `<div class="grid2">${panel('Baseline / Experiment KPI',analyticsTable(rows,kpiCols,{id:'experiment_kpis'}),'实验与正式 V6 同区间对比；包含最大回撤及三类平均敞口')}${panel('实验运行信息',`<div class="detail-grid">${detailItem('状态',badge(r.status||'—',r.status==='PASS'?'success':'warn'))}${detailItem('配置哈希',esc(r.config_hash||'—'))}${detailItem('生效参数',`<code>${esc(JSON.stringify(r.effective_params||{}))}</code>`)}${detailItem('阶段产物',`<code>${esc(JSON.stringify(r.stages||{}))}</code>`)}${detailItem('源哈希',`<code>${esc(JSON.stringify(r.source_hashes||{}))}</code>`)}</div>`,'以响应中的真实实验诊断为准')}</div>${panel('净值路径对比',`${lineChart(pairedHistory,[{key:'baseline_nav',label:'V6 Baseline NAV',color:'#476de0',axisLabel:'NAV（基准=1）'},{key:'nav_net',label:'Experiment NAV',color:'#139b85'}],{height:320})}<button type="button" class="icon-button" data-export-png>导出 PNG</button>`,'Baseline / Experiment 使用同一正式区间；实验逐日 NAV 来自真实 Python 输出')}${pairedExposure.length?panel('名义敞口机制对比',`${lineChart(pairedExposure,[{key:'baseline_equity',label:'Baseline Equity x',color:'#476de0',axisLabel:'名义敞口（x NAV）'},{key:'equity',label:'Experiment Equity x',color:'#7792de'},{key:'baseline_bond',label:'Baseline Bond x',color:'#139b85'},{key:'bond',label:'Experiment Bond x',color:'#79b8aa'},{key:'baseline_commodity',label:'Baseline Commodity x',color:'#cc9752'},{key:'commodity',label:'Experiment Commodity x',color:'#d9b47e'}],{height:320})}<button type="button" class="icon-button" data-export-png>导出 PNG</button>`,'三类 start-of-day 最终名义敞口真实逐日对比'):''}${panel('费用与回撤对比',`${analyticsTable(costRows,costCols,{id:'experiment_costs'})}<div class="detail-grid" style="margin-top:10px">${detailItem('V6 Baseline 最大回撤',pct(bMax))}${detailItem('Experiment 最大回撤',pct(eMax))}${detailItem('商品成本覆盖',esc(r.cost_scope||'—'))}</div>`,'日成本按回测正式区间求和；商品成本实验同时覆盖合约换月与组合再平衡')}`;
}

async function renderVersions(){
  $('#content').innerHTML=`${panel('Strategy Version Registry',`<div class="version-list">${state.versions.map(v=>`<div class="version-row ${v.available?'':'disabled'}"><div class="v">${esc(v.version)}</div><div><strong>${esc(v.label)}</strong><div class="muted">${v.audited?'已独立审计；当前正式研究基准':'尚未接入 V0.6 数据链'}</div></div><div>${v.available?badge(v.status,'success'):badge(v.status,'neutral')}</div></div>`).join('')}</div>`,'V0.6 保留 version-ready 比较框架，不伪造未接入版本')}
  ${panel('未来比较框架',`<div class="callout">接入 V5 / V7 / V8 后，版本比较将从 KPI 延伸到 Momentum、Weight Chain、10VT、Roll、Cost 与 Attribution，回答“为什么版本不同”，而不是只展示数字差。</div>`,'strategyVersion 已进入全局 Research Context')}`;
}

async function renderAudit(){
  const q=state.dataQuality;$('#content').innerHTML=`<div class="kpi-grid">${kpi('审计字段',state.lineage.length,'lineage mappings')}${kpi('Expiry 未验证',q.expiry_unverified_count,'保留原状态',q.expiry_unverified_count?'negative':'')}${kpi('Prelisting null signals',q.prelisting_null_signal_rows,'no synthetic fill')}${kpi('Commodity cost','0 bps','V6 baseline / pending verification')}${kpi('Demo mode','OFF','formal runtime')}${kpi('Baseline','V6','Audited')}</div>
  <div class="grid2">${panel('数据质量',`<div class="detail-grid">${detailItem('Expiry unverified by asset',esc(JSON.stringify(q.expiry_unverified_by_asset)))}${detailItem('Commodity cost status',esc(q.commodity_cost_status))}${detailItem('Synthetic fill','NO')}${detailItem('Formal browser engine','Snapshot/API only')}</div>`,'已知限制公开展示，不隐藏')}${panel('规则状态',ruleSummary(),'V6 implementation / assumption / pending verification 分开表达')}</div>
  ${panel('Field Lineage',`<div class="lineage-grid">${state.lineage.map(x=>`<div class="lineage-card"><h4>${esc(x.field)} ${badge(x.audit_status,'success')}</h4><p>${esc(x.meaning)}</p><code>${esc(x.snapshot)}</code><br><code>← ${esc(x.source_file)} :: ${esc(x.source_column)}</code></div>`).join('')}</div>`,'核心字段可以追溯到 Snapshot 与 V6 原始输出')}`;
}
function ruleSummary(){const r=state.rules;return `<div class="detail-grid">${detailItem('Class budget','1/3 · 1/3 · 1/3')}${detailItem('Sleeve scale',`E ${num(r.sleeve_scale.equity,1)} / B ${num(r.sleeve_scale.bond,1)} / C ${num(r.sleeve_scale.commodity,1)}`)}${detailItem('10VT',`${pct(r['10vt'].target_vol)} · ${esc(r['10vt'].estimator)}`)}${detailItem('Midmonth threshold',pct(r.midmonth.threshold))}${detailItem('Roll mode',esc(r.roll.mode))}${detailItem('Commodity cost',`${num(r.costs.commodity_bps,1)} bps · PENDING_VERIFICATION`)}</div>`;}

async function render(){
  syncContextControls(); $('#content').innerHTML='<div class="loading-card">正在读取研究数据…</div>';
  try{
    if(ResearchContext.strategyVersion!=='V6' && state.page!==6){$('#content').innerHTML='<div class="empty-state">该版本尚未接入。当前 V0.6 只开放冻结的 V6 baseline。</div>';return;}
    if(state.page===0)return await renderOverview();
    if(state.page===1)return await renderDecision();
    if(state.page===2)return await renderEvents();
    if(state.page===3)return await renderAttribution();
    if(state.page===4)return await renderExecution();
    if(state.page===5)return await renderExperiment();
    if(state.page===6)return await renderVersions();
    if(state.page===7)return await renderAudit();
    if(state.page===8)return await renderPerformance();
    if(state.page===9)return await renderContributions();
    if(state.page===10)return await renderHoldings();
    if(state.page===11)return await renderDrawdowns();
  }catch(err){$('#content').innerHTML=`<div class="error-card"><strong>页面加载失败</strong><br>${esc(err.message)}</div>`;}
}

function setupRulesDialog(){
  $('#rulesBtn').addEventListener('click',()=>{$('#rulesBody').innerHTML=`<section class="dialog-section">${ruleSummary()}</section><section class="dialog-section"><h4>审计边界</h4><p class="muted">网站确认与冻结 V6 一致；不认证未知官方方法、商品真实费率或原始合约下载完整性。</p></section><section class="dialog-section"><h4>Raw rules.json</h4><pre class="json-pre">${esc(JSON.stringify(state.rules,null,2))}</pre></section>`;$('#rulesDialog').showModal();});
  $('#rulesDialog .close').addEventListener('click',()=>$('#rulesDialog').close());
}

async function init(){
  const [summary,rules,series,assets,versions,lineage,q,drawdowns,exposures,parameterRegistry]=await Promise.all([
    api('/api/v6/summary'),api('/api/v6/rules'),api('/api/v6/series'),api('/api/v6/assets'),api('/api/strategy/versions'),api('/api/research/lineage'),api('/api/research/data-quality'),api('/api/strategy/V6/drawdowns?top=10'),api('/api/strategy/V6/exposure-series'),api('/api/experiment/parameters').catch(()=>null)
  ]);
  Object.assign(state,{summary,rules,series:series.rows,assets:assets.assets,versions:versions.versions,lineage:lineage.fields,dataQuality:q,drawdowns:drawdowns.rows,exposures:exposures.rows,parameterRegistry});
  ResearchContext.selectedDate=summary.end_date;
  ResearchContext.toDate=summary.end_date;
  ResearchContext.fromDate=summary.start_date||dateOnly(state.series[0].date);
  ResearchContext.selectedAsset=state.assets.includes('IF')?'IF':state.assets[0];
  $('#selectedDate').min=summary.start_date;$('#selectedDate').max=summary.end_date;$('#fromDate').min=summary.start_date;$('#fromDate').max=summary.end_date;$('#toDate').min=summary.start_date;$('#toDate').max=summary.end_date;
  $('#strategyVersion').innerHTML=state.versions.map(v=>`<option value="${v.version}" ${v.available?'':'disabled'}>${v.version}${v.audited?' · Audited':''}</option>`).join('');
  $('#selectedAsset').innerHTML=state.assets.map(a=>`<option>${a}</option>`).join('');
  bindContext(); setupRulesDialog();
  $$('[data-mode]').forEach(b=>b.addEventListener('click',()=>goToPage(b.dataset.mode==='B'?5:0)));
  $$('#modeJump, [data-mode-switch]').forEach(b=>b.addEventListener('click',()=>goToPage(state.mode==='A'?5:0)));
  $('#rulesFromSide').addEventListener('click',()=>$('#rulesBtn').click());
  document.addEventListener('click',e=>{const b=e.target.closest('[data-open-page]');if(b)goToPage(Number(b.dataset.openPage));});
  $('#exportContext').addEventListener('click',()=>{const x={strategy_version:ResearchContext.strategyVersion,selected_date:ResearchContext.selectedDate,selected_asset:ResearchContext.selectedAsset,from:ResearchContext.fromDate,to:ResearchContext.toDate,selected_event_id:ResearchContext.selectedEventId,source:'V6 audited snapshot',generated_at:new Date().toISOString()};const blob=new Blob([JSON.stringify(x,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='strategy_lab_research_context.json';a.click();URL.revokeObjectURL(url);});
  nav(); syncContextControls(); await render();
}

init().catch(err=>{$('#content').innerHTML=`<div class="error-card"><strong>初始化失败</strong><br>${esc(err.message)}</div>`;});
