// DOM integration tests; no network, trading credentials, or browser dependencies.
const assert=require('assert');
const fs=require('fs');
const {JSDOM}=require('jsdom');
function listenerCompatibility(window){
  // This host's distro jsdom mixes an older generated EventTarget wrapper with
  // a newer implementation that deduplicates on callback.objectReference.
  // Supply its missing identity metadata; production browser code is untouched.
  const add=window.EventTarget.prototype.addEventListener;
  window.EventTarget.prototype.addEventListener=function(type,callback,options){
    if(callback)callback.objectReference=callback;
    return add.call(this,type,callback,options);
  };
}
const dom=new JSDOM(fs.readFileSync('templates/index.html','utf8'),{runScripts:'outside-only',url:'http://localhost/'});
const w=dom.window;
listenerCompatibility(w);
const evaluate=code=>require('vm').runInContext(code,dom.getInternalVMContext());
w.String.prototype.replaceAll=function(a,b){return this.split(a).join(b);};
w.Array.prototype.at=function(i){return this[i<0?this.length+i:i];};
evaluate(`const selected='options_direct';
const dashboard={timezone:'UTC',bots:[]};
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const table=(headers,rows)=>'<table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const date=v=>v||'Unknown';const money=v=>v==null?'N/A':String(v);const percent=money;`);
evaluate(fs.readFileSync('static/explain.js','utf8'));
const panel=w.document.getElementById('explain-content');
const snapshot={event_id:'e',event_type:'ENTRY_DECISION',timestamp:'2026-09-16T12:00:00Z',provenance:'RECORDED',reason:'<img src=x onerror=alert(1)>',conditions:[{name:'structural_low',label:'Confirmed weekly low',required:true,passed:false,actual:23,threshold:25},{name:'liquidity',required:false,passed:true}],risk:{current_stop:200,price_basis:'underlying'},option:{delta:.7,iv:null},contract_selection:{selected:'SPY',rejected:[{symbol:'QQQ',reason:'Spread too wide'}]}};
w.testSnapshot=snapshot;
panel.innerHTML=evaluate('snapshotHTML(testSnapshot)');
assert(panel.textContent.includes('FAIL / NOT TRIGGERED'));
assert(panel.textContent.includes('Required'));
assert(panel.textContent.includes('Optional'));
assert(panel.textContent.includes('Data unavailable'));
assert(panel.textContent.includes('Spread too wide'));
assert.equal(panel.querySelectorAll('img').length,0);
panel.innerHTML=evaluate("snapshotHTML({...testSnapshot,event_type:'EXIT_DECISION',provenance:'RECONSTRUCTED',source:'Historical bars'})");
assert(panel.textContent.includes('RECONSTRUCTED'));
assert(panel.textContent.includes('EXIT_DECISION'));
const detail={trade:{symbol:'SPY',status:'OPEN',provenance:'INCOMPLETE',fills:[],order_ids:[],current:{current_price:201},current_as_of:'2026-09-16',position_confidence:'Local ledger'},events:[],audit:[{phase:'ENTRY',status:'INCOMPLETE DATA',reason:'Snapshot unavailable'}],diagnostics:[],total:0,offset:0,limit:50,explanation:'Detailed decision data unavailable for this historical trade.',audit_scope:'Displayed page only'};
w.testDetail=detail;panel.innerHTML=evaluate('inspectorHTML(testDetail)');
assert(panel.textContent.includes('CURRENT POSITION'));
assert(panel.textContent.includes('INCOMPLETE DATA'));
assert(panel.textContent.includes('historical trade'));
panel.innerHTML=evaluate("signalsHTML({items:[{...testSnapshot,event_type:'ORDER_EXPIRED',reason:'LIMIT_NOT_FILLED'}],diagnostics:[],total:1,offset:0,limit:50})");
assert(panel.textContent.includes('LIMIT_NOT_FILLED'));
assert(panel.textContent.includes('does not prove'));
evaluate("detailTab='journal';tabs();");
assert(w.document.getElementById('detail-content').hidden);
assert(!panel.hidden);
w.document.dispatchEvent(new w.CustomEvent('monitor-detail',{detail:{bot:'ETFEnhancer'}}));
assert(!w.document.getElementById('detail-content').hidden);
assert(panel.hidden);
for(const id of ['bots','bot-select','history','accounts','activity','detail-content'])assert(w.document.getElementById(id),id+' must remain');
console.log('DOM tests passed: conditions, failed rules, options, escaping, provenance, current positions, signals, tabs, and existing sections.');
// Load both real scripts together to verify the existing render and bot selector.
const full=new JSDOM(fs.readFileSync('templates/index.html','utf8'),{runScripts:'outside-only',url:'http://localhost/'});
const fw=full.window, run=code=>require('vm').runInContext(code,full.getInternalVMContext());
listenerCompatibility(fw);
fw.String.prototype.replaceAll=function(a,b){return this.split(a).join(b);};
fw.Array.prototype.at=function(i){return this[i<0?this.length+i:i];};
fw.HTMLCanvasElement.prototype.getContext=()=>({scale(){}});
fw.fetch=()=>new Promise(()=>{});
const makeBot=bot_id=>({bot_id,status:'STOPPED',reason:'test',pids:[],asset_class:'equity',history_scope:'Fixture',position_confidence:'Known empty',position_as_of:null,open_positions:0,trades_today:0,trades_month:0,trades_total:0,realized_pl:0,unrealized_pl:0,combined_pl:0,round_trips:0,positions:[],recent_trades:[],warnings:[],source_files:[],monitor_status:'OK',trade_returns:{},account:null});
fw.BOTMONITOR_INITIAL={timestamp:'2026-09-16T12:00:00Z',timezone:'UTC',refresh_seconds:10,snapshot_seconds:120,bots:[makeBot('ccexchange'),makeBot('ETFEnhancer')],accounts:[],recent_activity:[],summary:{running_bots:0,positions:{value:0,known_subtotal:0,covered_bots:2},trades_today:{value:0,known_subtotal:0,covered_bots:2},trades_month:{value:0,known_subtotal:0,covered_bots:2}},trade_definition:'Fixture'};
run(fs.readFileSync('static/app.js','utf8'));
run(fs.readFileSync('static/explain.js','utf8'));
assert(fw.document.getElementById('detail-content').textContent.includes('RECENT EXECUTION RECORDS'));
fw.document.querySelector('[data-detail-tab="journal"]').dispatchEvent(new fw.MouseEvent('click',{bubbles:true}));
assert(fw.document.getElementById('detail-content').hidden);
const select=fw.document.getElementById('bot-select');select.value='ETFEnhancer';select.dispatchEvent(new fw.Event('change'));
assert.equal(fw.document.getElementById('detail-title').textContent,'ETFEnhancer');
assert(!fw.document.getElementById('detail-content').hidden);
assert(fw.document.getElementById('explain-content').hidden);
assert(fw.document.getElementById('detail-content').textContent.includes('TOTAL TRADE ROI'));
// Verify actual canvas drawing includes market lines, reference lines and replay cutoff.
const strokes=[];
const context={scale(){},beginPath(){},moveTo(x,y){strokes.push(['move',x,y]);},lineTo(x,y){strokes.push(['line',x,y]);},stroke(){},setLineDash(v){strokes.push(['dash',...v]);},arc(){},fill(){},fillRect(...args){strokes.push(['body',...args]);},fillText(){}};
w.HTMLCanvasElement.prototype.getContext=()=>context;
panel.innerHTML=evaluate('inspectorHTML(testDetail)');
w.document.getElementById('trade-chart').getBoundingClientRect=()=>({width:800,height:250});
evaluate(`inspectorData={...testDetail,trade:{...testDetail.trade,asset_class:'crypto',direction:'LONG',fills:[{timestamp:'2026-09-01T01:00:00Z',price:100,side:'buy'},{timestamp:'2026-09-01T07:00:00Z',price:105,side:'sell'}]},events:[],price_history:{price_basis:'underlying',interval_seconds:14400,points:[{timestamp:'2026-09-01T04:00:00Z',price:101},{timestamp:'2026-09-01T08:00:00Z',price:106}],source:'Saved market bars'}};replayIndex=null;drawTrade();`);
assert(strokes.filter(p=>p[0]==='line').length>=3,'Market line and two execution reference lines must be drawn');
assert(w.document.getElementById('trade-chart-caption').textContent.includes('Saved market bars'));
strokes.length=0;
evaluate(`inspectorData.events=[{timestamp:'2026-09-01T05:00:00Z'}];replayIndex=0;drawTrade();`);
assert.equal(strokes.filter(p=>p[0]==='line').length,1,'Replay excludes the later bar and sell marker');
strokes.length=0;
evaluate(`inspectorData.price_history.points=[];replayIndex=null;drawTrade();`);
assert.equal(strokes.filter(p=>p[0]==='line').length,2,'Without market bars only horizontal references are drawn; no line connects fills');
strokes.length=0;
evaluate(`inspectorData.trade.asset_class='option';inspectorData.trade.fills[0].price=1;inspectorData.trade.fills[1].price=2;inspectorData.price_history.points=[{timestamp:'2026-09-01T04:00:00Z',price:101},{timestamp:'2026-09-01T08:00:00Z',price:106}];drawTrade();`);
assert.equal(strokes.filter(p=>p[0]==='line').length,3,'Underlying chart has market line plus two option execution-time markers, not premium prices');
// Market closures and missing intervals remain connected, with explicit dashed gaps.
strokes.length=0;
evaluate(`inspectorData.trade.fills=[];inspectorData.trade.asset_class='equity';inspectorData.events=[];replayIndex=null;inspectorData.price_history.interval_seconds=900;inspectorData.price_history.points=[{timestamp:'2026-09-18T19:45:00Z',price:101},{timestamp:'2026-09-18T20:00:00Z',price:102},{timestamp:'2026-09-21T13:45:00Z',price:99},{timestamp:'2026-09-21T14:30:00Z',price:103}];drawTrade();`);
assert.equal(strokes.filter(p=>p[0]==='line').length,1,'Only adjacent actual bars connect; no artificial weekend or missing-bar path');
assert.equal(strokes.filter(p=>p[0]==='dash'&&p[1]===5&&p[2]===4).length,0,'No invented gap connectors');
assert(w.document.getElementById('trade-chart-caption').textContent.includes('remain disconnected'));
assert.equal(evaluate(`marketTimeAxis([0,900000,259200000],900000)(259200000)`),1800000,'Weekend time is compressed, not filled with synthetic prices');
evaluate(`inspectorData.price_history.points=inspectorData.price_history.points.map(p=>({...p,open:p.price-1,high:p.price+2,low:p.price-2}));document.getElementById('chart-style').value='candles';`);
strokes.length=0;evaluate('drawTrade()');
assert.equal(strokes.filter(p=>p[0]==='body').length,4,'Candles use all four real OHLC bars');
assert.equal(strokes.filter(p=>p[0]==='line').length,4,'Candles show recorded high/low wicks without connections');
console.log('Chart line and replay cutoff tests passed.');
full.window.close();dom.window.close();
console.log('Both production scripts passed integration: existing detail render, journal tab, bot dropdown, and preserved metrics.');
