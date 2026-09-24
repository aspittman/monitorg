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
full.window.close();dom.window.close();
console.log('Both production scripts passed integration: existing detail render, journal tab, bot dropdown, and preserved metrics.');
