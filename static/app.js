'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (v, digits=0) => v == null ? '<span class="na">N/A</span>' : Number(v).toLocaleString(undefined,{maximumFractionDigits:digits});
const money = (v,signed=true) => v == null ? number(null) : `<span class="${signed?(v>0?'positive':v<0?'negative':''):''}">${v<0?'−':v>0&&signed?'+':''}$${number(Math.abs(v),2)}</span>`;
const percent = v => v == null ? number(null) : `<span class="${v>=0?'positive':'negative'}">${v>0?'+':''}${number(v,2)}%</span>`;
const tradeROI = (b,period) => {const r=b.trade_returns?.[period];return `<span title="${esc(r?.reason||'Trade ROI unavailable')}">${r?.status==='no_closes'?'<span class="na">—</span>':percent(r?.value)}</span>`;};
let dashboard, selected = 'ccexchange', history = [], chartRequest = 0;
function date(value) {return value ? new Date(value).toLocaleString(undefined,{timeZone:dashboard?.timezone||'America/New_York',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Unknown';}
function table(headers, rows) {return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th>${esc(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function render() {
  $('updated').textContent = `Updated ${date(dashboard.timestamp)}`;
  $('timezone').textContent = dashboard.timezone;
  $('interval').textContent = dashboard.refresh_seconds;
  $('snapshot-interval').textContent = `Snapshots every ${dashboard.snapshot_seconds}s`;
  const s=dashboard.summary;
  const cards=[['RUNNING BOTS',number(s.running_bots),'of 8 configured bots']];
  for(const [label,key] of [['OPEN POSITIONS','positions'],['EXECUTIONS TODAY','trades_today'],['EXECUTIONS THIS MONTH','trades_month']]) {
    const v=s[key];cards.push([label,number(v.value),`${v.known_subtotal} known · ${v.covered_bots}/8 bots with usable data`]);
  }
  $('summary').innerHTML=cards.map(c=>`<div class="card"><div class="card-label">${c[0]}</div><div class="card-value">${c[1]}</div><small>${c[2]}</small></div>`).join('');
  $('bots').innerHTML=dashboard.bots.map(b=>`<tr class="${b.bot_id===selected?'selected':''}"><td><button class="bot-button" data-bot="${esc(b.bot_id)}">${esc(b.bot_id)}</button></td><td><span class="badge ${esc(b.status)}" title="${esc(b.reason)}">${esc(b.status)}</span></td><td title="${esc(b.position_confidence)}">${number(b.open_positions)}</td><td>${number(b.trades_today)}</td><td>${number(b.trades_month)}</td><td>${tradeROI(b,'today')}</td><td>${tradeROI(b,'month')}</td><td>${tradeROI(b,'total')}</td><td><span class="badge ${b.monitor_status==='OK'&&b.warnings.length?'REVIEW':esc(b.monitor_status)}">${b.monitor_status==='OK'&&b.warnings.length?'REVIEW':esc(b.monitor_status)}</span></td></tr>`).join('');
  $('definition').textContent=dashboard.trade_definition;
  $('bot-select').innerHTML=dashboard.bots.map(b=>`<option value="${esc(b.bot_id)}" ${b.bot_id===selected?'selected':''}>${esc(b.bot_id)}</option>`).join('');
  $('activity').innerHTML=dashboard.recent_activity.slice(0,30).map(t=>`<div class="activity-row"><time>${esc(date(t.timestamp))}</time><span class="who">${esc(t.bot_id)}</span><span class="${t.side==='buy'?'positive':'negative'}">${esc(t.side.toUpperCase())}</span><span class="symbol">${esc(t.symbol)}</span></div>`).join('') || '<p class="empty">No reliably attributable executions available.</p>';
  $('accounts').innerHTML=dashboard.accounts.map(a=>`<div class="account"><div class="account-head"><div><h3>${esc(a.account)} <span class="tag">${a.paper?'PAPER':'LIVE'}</span></h3><p>${a.bots.map(esc).join(' · ')}</p></div><div>Equity ${money(a.equity,false)} · Cash ${money(a.cash,false)}<p>Observed ${esc(date(a.observed_at))}</p></div></div>${a.error?`<p class="error-text">${esc(a.error)}</p>`:''}<details><summary>Account positions (${a.positions==null?'N/A':a.positions.length}) · ownership remains separate</summary>${a.positions?.length?table(['SYMBOL','QUANTITY','CURRENT PRICE','ACCOUNT UNREALIZED $','LOCAL CLAIM'],a.positions.map(p=>[esc(p.symbol),number(p.quantity,8),money(p.current_price,false),money(p.unrealized_pl),esc(p.claimed_by.join(', ')||'Uncertain / unassigned')])):'<p class="empty">No account position data available.</p>'}</details></div>`).join('') || '<p class="empty">No usable Alpaca configuration found. Local monitoring continues.</p>';
  renderDetail();
  document.dispatchEvent(new CustomEvent("monitor-detail",{detail:{bot:selected}}));
}
function renderDetail() {
  const b=dashboard.bots.find(b=>b.bot_id===selected);if(!b)return;
  $('detail-title').textContent=b.bot_id;
  const metrics=[['EXECUTIONS TODAY',number(b.trades_today)],['EXECUTIONS MONTH',number(b.trades_month)],['EXECUTIONS IN LEDGER',number(b.trades_total)],['REALIZED P/L $',money(b.realized_pl)],['UNREALIZED P/L $',money(b.unrealized_pl)],['COMBINED P/L $',money(b.combined_pl)],['TODAY TRADE ROI',tradeROI(b,'today')],['MONTH TRADE ROI',tradeROI(b,'month')],['TOTAL TRADE ROI',tradeROI(b,'total')],['OPEN POSITIONS',number(b.open_positions)],['COMPLETED ROUND TRIPS',number(b.round_trips)],['ACCOUNT',esc(b.account||'Unknown')]];
  const positions=b.positions?.length?table(['SYMBOL / CONTRACT','QTY','ENTRY / PREMIUM','CURRENT','UNREALIZED $','UNREALIZED %'],b.positions.map(p=>[`${esc(p.symbol)}${p.contract_symbol?`<br><small class="muted">${esc(p.underlying)} · ${esc(p.expiration)} · ${number(p.strike,3)} ${esc(p.call_put)} · ×${p.multiplier}</small>`:''}`,number(p.quantity,8),money(p.entry,false),money(p.current_price,false),money(p.unrealized_pl),percent(p.unrealized_percent)])):`<p class="empty">${b.positions==null?'Position ownership is unknown. See account holdings below.':'No positions in the local ownership ledger.'}</p>`;
  const trades=b.recent_trades.length?table(['TIME','SYMBOL','SIDE','QUANTITY','PRICE / PREMIUM','REALIZED $'],b.recent_trades.slice(0,30).map(t=>[esc(date(t.timestamp)),esc(t.symbol),esc(t.side.toUpperCase()),number(t.quantity,8),money(t.price,false),money(t.realized_pl)])):'<p class="empty">No attributable execution records available.</p>';
  $('detail-content').innerHTML=`<div class="detail-meta">${esc(b.status)} · PID ${esc(b.pids.join(', ')||'N/A')} · ${esc(b.asset_class)} · ${esc(b.history_scope)}<br>Positions: ${esc(b.position_confidence)} · As of ${esc(date(b.position_as_of))}</div><div class="metrics">${metrics.map(([label,value])=>`<div class="metric"><span>${label}</span><strong>${value}</strong></div>`).join('')}</div>${b.warnings.length?`<div class="warnings">${b.warnings.map(w=>`<div>${esc(w)}</div>`).join('')}</div>`:''}<p class="footnote">${esc(b.trade_return_explanation||'')} — means no matched closes. N/A means unreliable history or missing capital basis.</p><p class="footnote">${['today','month','total'].map(period=>{const r=b.trade_returns?.[period];return r?.status==='available'?`${period.toUpperCase()}: ${money(r.realized_pl)} realized ÷ ${money(r.capital,false)} matched capital`: `${period.toUpperCase()}: ${esc(r?.reason||'Unavailable')}`;}).join(' · ')}</p><p class="footnote">Whole-bot portfolio returns: ${esc(b.return_explanation)}</p><div class="detail-heading">OPEN POSITIONS · LAST KNOWN OWNERSHIP</div>${positions}<div class="detail-heading">RECENT EXECUTION RECORDS</div>${trades}<p class="footnote">Sources: ${b.source_files.map(esc).join(' · ')||'Unavailable'}</p>`;
}
async function loadHistory() {
  const request=++chartRequest;
  try {const response=await fetch(`/api/history?bot=${encodeURIComponent(selected)}`);if(!response.ok)throw Error();const rows=await response.json();if(request===chartRequest){history=rows;drawChart();}}
  catch {if(request===chartRequest){history=[];drawChart('History could not be loaded.');}}
}
function drawChart(error) {
  const canvas=$('history'), rect=canvas.getBoundingClientRect(), scale=window.devicePixelRatio||1;
  canvas.width=rect.width*scale;canvas.height=rect.height*scale;const ctx=canvas.getContext('2d');ctx.scale(scale,scale);
  const metric=$('chart-metric').value;let points=history.map(r=>[r.timestamp,r[metric]]);
  if(metric==='daily'||metric==='monthly') {
    const buckets=new Map();for(const r of history){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:dashboard?.timezone||'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(r.timestamp));const v=Object.fromEntries(parts.map(p=>[p.type,p.value]));const key=`${v.year}-${v.month}${metric==='daily'?'-'+v.day:''}`;if(!buckets.has(key))buckets.set(key,[]);buckets.get(key).push(r);}
    points=[...buckets].map(([day,rows])=>[day,rows.length>1&&rows.every(r=>r.realized_pl!=null)?rows.at(-1).realized_pl-rows[0].realized_pl:null]);
  }
  const valid=points.filter(p=>p[1]!=null);
  $('chart-empty').hidden=valid.length>0&&!error;$('chart-empty').textContent=error||'No reliable values yet. History begins with actual monitoring snapshots.';
  $('chart-caption').textContent=`${selected} · ${history.length} monitoring snapshots`;
  if(!valid.length||error)return;
  const left=65,top=18,width=Math.max(rect.width-left-16,1),height=rect.height-55;
  let min=Math.min(...valid.map(p=>p[1])),max=Math.max(...valid.map(p=>p[1]));if(min===max){min-=1;max+=1;}
  const y=v=>top+height-(v-min)/(max-min)*height, x=i=>left+(points.length===1?.5:i/(points.length-1))*width;
  ctx.font='10px system-ui';ctx.textBaseline='middle';
  for(let i=0;i<4;i++){const value=min+(max-min)*i/3,py=y(value);ctx.strokeStyle='#243247';ctx.beginPath();ctx.moveTo(left,py);ctx.lineTo(left+width,py);ctx.stroke();ctx.fillStyle='#90a1b8';ctx.fillText(metric==='trade_roi_total'?value.toFixed(2)+'%':value.toFixed(1),4,py);}
  ctx.strokeStyle='#68dfb2';ctx.lineWidth=2;ctx.beginPath();let active=false;points.forEach((p,i)=>{if(p[1]==null){active=false;return;}if(active)ctx.lineTo(x(i),y(p[1]));else ctx.moveTo(x(i),y(p[1]));active=true;});ctx.stroke();
  for(let i=0;i<points.length;i++){if(points[i][1]!=null){ctx.fillStyle='#68dfb2';ctx.beginPath();ctx.arc(x(i),y(points[i][1]),2,0,Math.PI*2);ctx.fill();}}
  ctx.fillStyle='#90a1b8';const label=v=>v.length<=10?v:date(v);ctx.fillText(label(points[0][0]),left,rect.height-12);ctx.textAlign='right';ctx.fillText(label(points.at(-1)[0]),left+width,rect.height-12);
}
async function refresh() {
  try {const response=await fetch('/api/dashboard');if(!response.ok)throw Error(`HTTP ${response.status}`);dashboard=await response.json();render();const problem=dashboard.refresh_error||dashboard.storage_error;$('error').hidden=!problem;$('error').textContent=problem||'';await loadHistory();}
  catch {$('error').hidden=false;$('error').textContent='BotMonitor is unavailable. Displayed data may be stale. Trading operates independently.';}
  setTimeout(refresh,(dashboard?.refresh_seconds||10)*1000);
}
document.addEventListener('click',e=>{const button=e.target.closest('[data-bot]');if(button){selected=button.dataset.bot;render();loadHistory();}});
$('bot-select').addEventListener('change',e=>{selected=e.target.value;render();loadHistory();});
$('chart-metric').addEventListener('change',()=>drawChart());window.addEventListener('resize',()=>drawChart());
if(window.BOTMONITOR_INITIAL){dashboard=window.BOTMONITOR_INITIAL;render();}refresh();
