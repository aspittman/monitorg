'use strict';
// Additive detail views. Existing detail DOM and performance chart stay intact.
let detailTab='overview', explainBot=selected, explainRequest=0, journalOffset=0, signalOffset=0, eventOffset=0, inspectedTrade=null, inspectorData=null, replayIndex=null;
let journalFilters={}, chartBasis='underlying';
const unavailable='<span class="na">Data unavailable</span>';
const valueHTML=v=>v==null||v===''?unavailable:typeof v==='object'?`<pre>${esc(JSON.stringify(v,null,2))}</pre>`:esc(v);
function fields(obj){return obj&&Object.keys(obj).length?table(['FIELD','VALUE'],Object.entries(obj).map(([k,v])=>[esc(k.replaceAll('_',' ')),valueHTML(v)])): `<p class="empty">Data unavailable</p>`;}
function conditionsHTML(conditions){return conditions?.length?table(['CONDITION','ROLE','RESULT','ACTUAL','THRESHOLD'],conditions.map(c=>[esc(c.label||c.name),c.required===true?'Required':c.required===false?'Optional':'Unknown',c.passed===true?'<span class="positive">PASS / TRIGGERED</span>':c.passed===false?'<span class="negative">FAIL / NOT TRIGGERED</span>':'UNKNOWN',valueHTML(c.actual),valueHTML(c.threshold)])):'<p class="empty">Detailed condition data unavailable.</p>';}
function snapshotHTML(e){return `<div class="detail-heading">${esc(e.event_type)} · ${esc(date(e.timestamp))} · ${esc(e.provenance)}</div><p class="explain-note">${esc(e.reason||'Decision reason unavailable')}${e.source?` · ${esc(e.source)}`:''}</p>${conditionsHTML(e.conditions)}${['market','indicators','risk','position','option','contract_selection','pipeline'].map(k=>e[k]?`<details class="snapshot" ${k==='risk'||k==='option'?'open':''}><summary>${esc(k.replaceAll('_',' ').toUpperCase())}</summary>${fields(e[k])}</details>`:'').join('')}${e.legacy_details?`<p class="explain-note">Recorded legacy details: ${esc(e.legacy_details)}</p>`:''}<details class="snapshot"><summary>Full event evidence</summary><pre>${esc(JSON.stringify(e,null,2))}</pre></details>`;}
function pager(offset,limit,total,scope){return `<div class="explain-controls"><button type="button" data-page="${scope}" data-offset="${Math.max(0,offset-limit)}" ${offset===0?'disabled':''}>Previous</button><span>${total?offset+1:0}–${Math.min(total,offset+limit)} of ${total}</span><button type="button" data-page="${scope}" data-offset="${offset+limit}" ${offset+limit>=total?'disabled':''}>Next</button></div>`;}
function tabs(){document.querySelectorAll('[data-detail-tab]').forEach(b=>{if(b.dataset.detailTab===detailTab)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});$('detail-content').hidden=detailTab!=='overview';$('explain-content').hidden=detailTab==='overview';}
async function explainFetch(path,params){const r=await fetch(path+'?'+new URLSearchParams({bot:explainBot,...params}));const body=await r.json();if(!r.ok)throw Error(body.error||'Explainability unavailable');return body;}
async function loadExplain(){
  tabs();if(detailTab==='overview')return;
  const request=++explainRequest, tab=detailTab, bot=explainBot;
  $('explain-content').innerHTML='<p class="empty" role="status">Loading explainability data…</p>';
  try{
    let data;
    if(tab==='journal')data=await explainFetch('/api/journal',{...journalFilters,offset:journalOffset});
    if(tab==='signals')data=await explainFetch('/api/decisions',{offset:signalOffset});
    if(tab==='inspector'){
      if(!inspectedTrade){$('explain-content').innerHTML='<p class="empty">Select a trade in the Trade Journal to inspect it.</p>';return;}
      data=await explainFetch('/api/inspector',{trade:inspectedTrade,offset:eventOffset,basis:chartBasis});
    }
    if(request!==explainRequest||tab!==detailTab||bot!==explainBot)return;
    const b=dashboard?.bots.find(b=>b.bot_id===bot), warning=b?.explain_error, imported=b?.explain_import;
    const progress=imported&&imported.bytes_imported<imported.source_bytes?`<p class="explain-note">Legacy event import is catching up: ${esc(Math.round(100*imported.bytes_imported/imported.source_bytes))}% read. Refresh detail to load newly imported evidence.</p>`:'';
    $('explain-content').innerHTML=progress+(warning?`<p class="warnings">${esc(warning)}</p>`:'')+(tab==='journal'?journalHTML(data):tab==='signals'?signalsHTML(data):inspectorHTML(data));
    if(tab==='inspector'){inspectorData=data;replayIndex=null;drawTrade();}
  }catch(e){if(request===explainRequest)$('explain-content').innerHTML=`<p class="empty" role="alert">${esc(e.message)}. Existing Overview remains available.</p>`;}
}
function journalHTML(data){
  return `<form id="journal-filters" class="explain-controls"><label>Symbol <input name="symbol" value="${esc(journalFilters.symbol||'')}" placeholder="Exact symbol"></label><label>From (UTC) <input name="from" type="date" value="${esc(journalFilters.from||'')}"></label><label>To (UTC) <input name="to" type="date" value="${esc(journalFilters.to||'')}"></label><label>Outcome <select name="outcome">${[['','All'],['winners','Winners'],['losers','Losers']].map(([v,l])=>`<option value="${v}" ${journalFilters.outcome===v?'selected':''}>${l}</option>`).join('')}</select></label><label>Sort <select name="sort"><option value="newest">Newest</option><option value="oldest" ${journalFilters.sort==='oldest'?'selected':''}>Oldest</option></select></label><button type="submit">Apply</button></form><p class="explain-note">Position cycles reconstructed from attributable fills using the existing average-cost convention. Partial exits remain in the same cycle. Decision snapshots require explicit order/trade linkage. Unknown or unreconciled history is retained as incomplete.</p>${data.rejected_events?`<p class="warnings">${data.rejected_events} malformed or conflicting telemetry records rejected. Valid events remain available.</p>`:''}${data.items.length?table(['SYMBOL','STATE','ENTRY','EXIT','REALIZED P/L','RETURN','HOLD TIME','ENTRY REASON','EXIT REASON'],data.items.map(t=>[`<button class="bot-button" data-inspect="${esc(t.trade_id)}">${esc(t.symbol)}</button>`,esc(t.status),esc(date(t.entry_time)),esc(date(t.exit_time)),money(t.pnl),percent(t.return_percent),t.hold_seconds==null?'Unknown':esc((t.hold_seconds/3600).toFixed(2)+'h'),esc(t.entry_reason||'Unavailable'),esc(t.exit_reason||'Unavailable')])):'<p class="empty">No attributable trades match these filters. Existing executions and ownership warnings remain in Overview.</p>'}${pager(data.offset,data.limit,data.total,'journal')}`;
}
function signalsHTML(data){return `<p class="explain-note">Recorded evaluations and lifecycle events. An absent event does not prove that a signal, order, or fill never occurred. Legacy SKIP rows do not prove a valid signal existed. No symbol/time guessing is used to link events.</p>${data.diagnostics.map(d=>`<p class="warnings">${esc(d.status)}: ${esc(d.reason)}</p>`).join('')}${data.items.length?data.items.map(e=>`<details class="snapshot"><summary>${esc(date(e.timestamp))} · ${esc(e.symbol)} · ${esc(e.event_type)} · ${esc(e.reason||'Reason unavailable')}</summary>${snapshotHTML(e)}</details>`).join(''):'<p class="empty">No decision events recorded. This bot continues to work with existing monitoring.</p>'}${pager(data.offset,data.limit,data.total,'signals')}`;}
function inspectorHTML(data){const t=data.trade;return `<div class="section-head"><h3>${esc(explainBot)} — ${esc(t.symbol)} · ${esc(t.status)}</h3><button type="button" data-detail-tab="journal">Back to journal</button></div><p class="explain-note">${esc(data.explanation)} ${esc(t.source||'')} · ${esc(t.provenance)}${t.estimated_time?' · Estimated fill timestamps; exact hold time unavailable':''}</p>${fields(Object.fromEntries(['direction','entry_time','entry_price','exit_time','exit_price','quantity','remaining','pnl','return_percent','hold_seconds','exit_scope','hold_scope','entry_reason','exit_reason'].map(k=>[k,t[k]])))}${t.contract?.contract_symbol?`<div class="detail-heading">OPTION CONTRACT · METADATA FROM CONTRACT SYMBOL</div>${fields(t.contract)}<p class="explain-note">Historical bid, ask, spread, Greeks, IV, volume, open interest and contract selection: Data unavailable unless shown in recorded snapshots below. Underlying prices and option premiums are separate.</p>`:''}${t.current?`<div class="detail-heading">CURRENT POSITION · ${esc(date(t.current_as_of))}</div><p class="explain-note">${esc(t.position_confidence)}</p>${fields(t.current)}<p class="explain-note">Current indicators, stops and exit conditions are available only in timestamped position snapshots below.</p>`:''}<div class="detail-heading">TRADE CHART / REPLAY</div><div class="explain-controls"><label>Price basis <select id="replay-basis"><option value="underlying" ${chartBasis==='underlying'?'selected':''}>Underlying / equity</option><option value="option" ${chartBasis==='option'?'selected':''}>Option premium</option></select></label><label>Display <select id="chart-style"><option value="line">Price line</option><option value="candles">Candlesticks (OHLC)</option></select></label><button type="button" id="replay-reset">All loaded events</button></div><canvas id="trade-chart" role="img" aria-label="Recorded price samples and explicitly scoped stop updates"></canvas><p id="trade-chart-caption" class="explain-note"></p><div class="detail-heading">DECISION TIMELINE · SELECT AN EVENT TO REPLAY</div>${data.events.length?`<div class="replay-events">${data.events.map((e,i)=>`<button type="button" data-replay="${i}">${esc(date(e.timestamp))} · ${esc(e.event_type)}</button>`).join('')}</div><div id="replay-snapshot">${data.events.filter(e=>['ENTRY_DECISION','EXIT_DECISION','POSITION_UPDATED','CONTRACT_SELECTION'].includes(e.event_type)).map(snapshotHTML).join('')||snapshotHTML(data.events[0])}</div>`:'<p class="empty">Detailed decision data unavailable for this historical trade.</p>'}${pager(data.offset,data.limit,data.total,'events')}<div class="detail-heading">TRADE AUDIT</div><p class="explain-note">${esc(data.audit_scope)}</p>${table(['PHASE','STATUS','EVIDENCE'],data.audit.map(a=>[esc(a.phase),esc(a.status),esc(a.reason)]))}${data.diagnostics.map(d=>`<p class="warnings">${esc(d.status)} · ${esc(d.reason)}</p>`).join('')}<details class="snapshot"><summary>Underlying execution evidence (${t.fills?.length||0} fills)</summary>${fields({fills:t.fills})}</details>`;}
function marketTimeAxis(times,interval){
  if(times.length<2||!Number.isFinite(interval)||interval<=0)return value=>value;
  const display=[times[0]];for(let i=1;i<times.length;i++)display.push(display[i-1]+Math.min(times[i]-times[i-1],interval));
  return value=>{if(value<=times[0])return display[0]+value-times[0];if(value>=times.at(-1))return display.at(-1)+value-times.at(-1);
    let low=0,high=times.length-1;while(high-low>1){const mid=(low+high)>>1;if(times[mid]<=value)low=mid;else high=mid;}
    return display[low]+(value-times[low])/(times[high]-times[low])*(display[high]-display[low]);
  };
}
function drawTrade(){
  const canvas=$('trade-chart');if(!canvas||!inspectorData)return;
  const t=inspectorData.trade,basis=$('replay-basis').value,events=inspectorData.events.slice(0,replayIndex==null?undefined:replayIndex+1);
  const points=[];
  for(const e of events){const stamp=Date.parse(e.timestamp),v=basis==='option'?e.option?.price:e.market?.price;
    if(typeof v==='number'&&Number.isFinite(v))points.push({x:stamp,y:v,kind:'price',provenance:e.provenance});
    for(const [name,indicator] of Object.entries(e.indicators||{}).slice(0,20)){if(indicator?.overlay===true&&indicator.price_basis===basis&&typeof indicator.value==='number'&&Number.isFinite(indicator.value))points.push({x:stamp,y:indicator.value,kind:'indicator:'+name,provenance:e.provenance});}
    if(e.risk?.price_basis===basis){const stop=e.risk.current_stop??e.risk.initial_stop;if(typeof stop==='number'&&Number.isFinite(stop))points.push({x:stamp,y:stop,kind:'stop',provenance:e.provenance});}
  }
  const overlayNames=[...new Set(points.filter(p=>p.kind.startsWith('indicator:')).map(p=>p.kind))];
  const overlayColors=['#c3a6ff','#6bd2eb','#f5ad75','#dd9cd2'];
  const cutoff=replayIndex==null?Infinity:Date.parse(events.at(-1)?.timestamp);
  const priceHistory=inspectorData.price_history;
  if(priceHistory?.price_basis===basis)for(const p of priceHistory.points||[]){const stamp=Date.parse(p.timestamp);if(stamp<=cutoff)points.push({x:stamp,y:p.price,open:p.open,high:p.high,low:p.low,kind:'history'});}
  const matching=basis===(t.asset_class==='option'?'option':'underlying');
  if(matching)for(const f of t.fills||[]){if(!f.estimated_time&&Date.parse(f.timestamp)<=cutoff)points.push({x:Date.parse(f.timestamp),y:f.price,kind:f.side===(t.direction==='SHORT'?'sell':'buy')?'entry':'exit'});}
  const optionActions=!matching&&t.asset_class==='option'&&basis==='underlying'?(t.fills||[]).filter(f=>!f.estimated_time&&Date.parse(f.timestamp)<=cutoff):[];
  const candles=$('chart-style')?.value==='candles';
  const bars=points.filter(p=>p.kind==='history').sort((a,b)=>a.x-b.x);
  $('trade-chart-caption').textContent='Price samples (green), entry fills (blue), exit fills (red), explicitly scoped stops (amber). Hollow points are RECONSTRUCTED; solid points are RECORDED. Markers use actual fill records, including partial fills. Green line: actual historical bar closes, not a buy-to-sell connector. Candlesticks show recorded open/high/low/close. Periods without observations are compressed on the time axis and remain disconnected. Hover for the recorded bar values. Without historical bars, markers stay unconnected; fills are never used as ticker history. Blue/red horizontal guides: first entry / last exit fill prices. Stop steps show recorded thresholds only. '+(overlayNames.length?' Strategy-selected price overlays: '+overlayNames.map(n=>n.slice(10)).join(', ')+'.':'')+(bars.length?' '+bars.length+' market bars loaded.':'')+(candles&&!bars.some(p=>[p.open,p.high,p.low].every(Number.isFinite))?' OHLC data unavailable for candlesticks; use Price line.':'')+(priceHistory?.source?' '+priceHistory.source+'.':'')+(priceHistory?.context?' '+priceHistory.context:'')+(priceHistory?.warning?' '+priceHistory.warning:'')+(points.length?'':'Data unavailable for this price basis.');
  const rect=canvas.getBoundingClientRect(),scale=window.devicePixelRatio||1;canvas.width=rect.width*scale;canvas.height=250*scale;const ctx=canvas.getContext('2d');ctx.scale(scale,scale);if(!points.length)return;
  const values=points.map(p=>p.y).concat(candles?bars.flatMap(p=>[p.high,p.low]).filter(Number.isFinite):[]);
  let min=values.reduce((a,b)=>Math.min(a,b),Infinity),max=values.reduce((a,b)=>Math.max(a,b),-Infinity);if(min===max){min-=1;max+=1;}
  const times=points.map(p=>p.x).concat(optionActions.map(f=>Date.parse(f.timestamp)));
  const first=Math.min(...times),last=Math.max(...times);const timeAxis=marketTimeAxis(bars.map(p=>p.x),priceHistory?.interval_seconds*1000);const x=v=>60+(timeAxis(v)-timeAxis(first))/Math.max(1,timeAxis(last)-timeAxis(first))*(rect.width-85),y=v=>210-(v-min)/(max-min)*180;
  ctx.font='11px system-ui';ctx.fillStyle='#90a1b8';for(let i=0;i<4;i++){const v=min+(max-min)*i/3;ctx.fillText(v.toFixed(2),5,y(v));}
  const observations=bars;
  ctx.strokeStyle='#68dfb2';ctx.lineWidth=1.5;
  // Draw only actual adjacent market observations, never bridge missing bars.
  observations.forEach((p,i)=>{
    if(candles&&[p.open,p.high,p.low].every(Number.isFinite)){
      ctx.strokeStyle=p.y>=p.open?'#68dfb2':'#fa8994';ctx.fillStyle=ctx.strokeStyle;
      ctx.beginPath();ctx.moveTo(x(p.x),y(p.high));ctx.lineTo(x(p.x),y(p.low));ctx.stroke();
      const width=Math.max(1,Math.min(7,(rect.width-85)/Math.max(1,bars.length)*.65));
      ctx.fillRect(x(p.x)-width/2,Math.min(y(p.open),y(p.y)),width,Math.max(1,Math.abs(y(p.open)-y(p.y))));return;
    }
    if(candles||!i)return;const previous=observations[i-1];
    if(!Number.isFinite(priceHistory.interval_seconds)||p.x-previous.x>priceHistory.interval_seconds*1500)return;
    ctx.beginPath();ctx.moveTo(x(previous.x),y(previous.y));ctx.lineTo(x(p.x),y(p.y));ctx.stroke();
  });ctx.setLineDash([]);
  canvas.onmousemove=e=>{
    const offset=e.clientX-canvas.getBoundingClientRect().left;
    let low=0,high=bars.length;while(low<high){const mid=(low+high)>>1;if(x(bars[mid].x)<offset)low=mid+1;else high=mid;}
    const candidates=[bars[low],bars[low-1]].filter(Boolean);const p=candidates.sort((a,b)=>Math.abs(x(a.x)-offset)-Math.abs(x(b.x)-offset))[0];
    canvas.title=p?`${date(new Date(p.x).toISOString())} · Close ${p.y}${Number.isFinite(p.high)?` · Open ${p.open} · High ${p.high} · Low ${p.low}`:''}`:'';
  };
  for(const kind of ['entry','exit']){const markers=points.filter(p=>p.kind===kind).sort((a,b)=>a.x-b.x);const p=kind==='entry'?markers[0]:markers.at(-1);if(p){ctx.strokeStyle=kind==='entry'?'#8bb6ff':'#fa8994';ctx.setLineDash([2,5]);ctx.beginPath();ctx.moveTo(60,y(p.y));ctx.lineTo(rect.width-25,y(p.y));ctx.stroke();ctx.setLineDash([]);}}
  for(const f of optionActions){const px=x(Date.parse(f.timestamp));ctx.strokeStyle=f.side==='buy'?'#8bb6ff':'#fa8994';ctx.fillStyle=ctx.strokeStyle;ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(px,25);ctx.lineTo(px,210);ctx.stroke();ctx.setLineDash([]);ctx.fillText(f.side.toUpperCase()+' option',Math.min(px+3,rect.width-85),20);}
  const stops=points.filter(p=>p.kind==='stop').sort((a,b)=>a.x-b.x);ctx.strokeStyle='#ebc778';ctx.beginPath();stops.forEach((p,i)=>{if(i){ctx.lineTo(x(p.x),y(stops[i-1].y));ctx.lineTo(x(p.x),y(p.y));}else ctx.moveTo(x(p.x),y(p.y));});ctx.stroke();
  for(const p of points){if(p.kind==='history'&&(candles||bars.length>500))continue;ctx.fillStyle={price:'#68dfb2',history:'#68dfb2',entry:'#8bb6ff',exit:'#fa8994',stop:'#ebc778'}[p.kind]||overlayColors[overlayNames.indexOf(p.kind)%overlayColors.length];ctx.beginPath();ctx.arc(x(p.x),y(p.y),p.kind==='history'?1:p.kind==='price'?3:5,0,Math.PI*2);if(p.provenance==='RECONSTRUCTED'){ctx.strokeStyle=ctx.fillStyle;ctx.stroke();}else ctx.fill();if(p.kind==='entry'||p.kind==='exit')ctx.fillText(p.kind,x(p.x)-12,y(p.y)-10);}
  ctx.fillStyle='#90a1b8';ctx.fillText(date(new Date(first).toISOString()),60,242);ctx.textAlign='right';ctx.fillText(date(new Date(last).toISOString()),rect.width-15,242);
}
document.addEventListener('monitor-detail',e=>{if(explainBot!==e.detail.bot){explainBot=e.detail.bot;detailTab='overview';inspectedTrade=null;inspectorData=null;journalOffset=signalOffset=eventOffset=0;journalFilters={};chartBasis='underlying';++explainRequest;tabs();}});
document.addEventListener('click',e=>{
 if(e.target.closest('[data-explain-refresh]'))loadExplain();
 const tab=e.target.closest('[data-detail-tab]');if(tab){detailTab=tab.dataset.detailTab;loadExplain();}
 const inspect=e.target.closest('[data-inspect]');if(inspect){inspectedTrade=inspect.dataset.inspect;chartBasis='underlying';eventOffset=0;detailTab='inspector';loadExplain();}
 const page=e.target.closest('[data-page]');if(page){const offset=Number(page.dataset.offset);if(page.dataset.page==='journal')journalOffset=offset;else if(page.dataset.page==='signals')signalOffset=offset;else eventOffset=offset;loadExplain();}
 const replay=e.target.closest('[data-replay]');if(replay){replayIndex=Number(replay.dataset.replay);$('replay-snapshot').innerHTML=snapshotHTML(inspectorData.events[replayIndex]);drawTrade();}
 if(e.target.id==='replay-reset'){replayIndex=null;drawTrade();}
});
document.addEventListener('submit',e=>{if(e.target.id==='journal-filters'){e.preventDefault();journalFilters=Object.fromEntries(new FormData(e.target));journalOffset=0;loadExplain();}});
document.addEventListener('change',e=>{if(e.target.id==='chart-style')drawTrade();if(e.target.id==='replay-basis'){chartBasis=e.target.value;loadExplain();}});window.addEventListener('resize',drawTrade);
