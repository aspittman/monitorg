import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app import handler_for
from models.decision_event import validate_event
from models.records import position
from services.explain_store import ExplainStore
from services.explain_service import ExplainService, audit, diagnostics, journal_from_fills
from telemetry.monitor_event import MonitorEvents
from tests.test_monitor import trade

BOT='options_direct'
def event(kind='ENTRY_DECISION', **values):
    return dict(schema_version=1,event_id=values.pop('event_id','event1'),bot_id=BOT,strategy='actual_strategy',
                timestamp=values.pop('timestamp','2026-09-16T12:00:00Z'),symbol='SPY261016C00741000',event_type=kind,**values)
def public(**kw):
    return dict(history_reliable=kw.pop('history_reliable',True),positions=kw.pop('positions',[]),**kw)
def fills():
    return [trade('buy',2,2,'open',symbol='SPY261016C00741000'),
            trade('sell',1,3,'partial','2026-09-16T13:00:00+00:00',symbol='SPY261016C00741000'),
            trade('sell',1,4,'close','2026-09-16T14:00:00+00:00',symbol='SPY261016C00741000')]

class ExplainTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=ExplainStore(self.root/'explain.db');self.service=ExplainService(self.store)
    def tearDown(self):self.tmp.cleanup()
    def add(self,*events):
        with self.store.connect() as db:
            for e in events:self.store.insert(db,e,BOT)

    def test_validation_preserves_strategy_specific_failed_and_unknown_conditions(self):
        e=event(conditions=[dict(name='weekly_structural_low',required=True,passed=False,actual=201),dict(name='volume',required=False,passed=None)],risk={'initial_stop':200,'price_basis':'underlying'})
        self.assertEqual(validate_event(e,BOT)['conditions'],e['conditions'])
        for change in ({'schema_version':2},{'bot_id':'foreign'},{'timestamp':'2026-09-16'}, {'market':[]},{'event_type':'TRADE_NOW'},{'conditions':[dict(name='x',passed='false')]},{'market':{'price':float('nan')}}):
            with self.subTest(change=change),self.assertRaises((ValueError,TypeError)):
                validate_event(dict(e,**change),BOT)

    def test_duplicate_immutable_and_cross_bot_scoped(self):
        self.add(event());self.add(event())
        self.assertEqual(self.store.events(BOT)['total'],1)
        with self.assertRaises(ValueError):self.add(event(reason='changed'))
        with self.store.connect() as db:self.store.insert(db,dict(event(),bot_id='ETFEnhancer'),'ETFEnhancer')
        self.assertEqual(self.store.events('ETFEnhancer')['total'],1)

    def test_partial_malformed_conflicting_and_rotation(self):
        path=self.root/'events.jsonl';raw=json.dumps(event()).encode()
        path.write_bytes(b'{bad}\n'+raw[:20]);self.store.ingest(BOT,path)
        self.assertEqual(self.store.events(BOT)['total'],0)
        with path.open('ab') as f:f.write(raw[20:]+b'\n'+raw+b'\n'+json.dumps(event(reason='changed')).encode()+b'\n')
        self.store.ingest(BOT,path)
        self.assertEqual(self.store.events(BOT)['total'],1)
        self.assertEqual(self.store.journal(BOT,{})['rejected_events'],2)
        path.rename(self.root/'old.jsonl');path.write_text(json.dumps(event(event_id='new'))+'\n')
        self.store.ingest(BOT,path);self.assertEqual(self.store.events(BOT)['total'],2)
        ExplainStore(self.root/'explain.db').ingest(BOT,path)
        self.assertEqual(self.store.events(BOT)['total'],2)

    def test_oversize_read_is_bounded_and_recovers(self):
        path=self.root/'events.jsonl';path.write_bytes(b'x'*2200000+b'\n'+json.dumps(event()).encode()+b'\n')
        self.store.ingest(BOT,path)
        with self.store.connect() as db:offset=db.execute('SELECT offset FROM cursors').fetchone()[0]
        self.assertLess(offset,1200000)
        self.store.ingest(BOT,path);self.store.ingest(BOT,path)
        self.assertEqual(self.store.events(BOT)['total'],1)
        self.assertEqual(self.store.journal(BOT,{})['rejected_events'],1)

    def test_closed_journal_partial_closes_and_options(self):
        rows=journal_from_fills(BOT,fills(),public());self.assertEqual(len(rows),1)
        t=rows[0];self.assertEqual(t['pnl'],300);self.assertEqual(t['return_percent'],75)
        self.assertEqual(t['hold_seconds'],7200);self.assertEqual(t['contract']['call_put'],'call')
        self.assertEqual(t['contract']['multiplier'],100);self.assertEqual(t['exit_price'],3.5)
        self.assertEqual(t['provenance'],'RECONSTRUCTED')

    def test_short_put_collateral_and_covered_call_unknown(self):
        rows=[trade('sell',1,6.13,'a'),trade('buy',1,5.28,'b')]
        t=journal_from_fills('options_secured',rows,public())[0]
        self.assertAlmostEqual(t['pnl'],85);self.assertAlmostEqual(t['return_percent'],85/74100*100)
        for r in rows:r.update(symbol='SPY261016C00741000',call_put='call')
        self.assertIsNone(journal_from_fills('options_covered',rows,public())[0]['return_percent'])

    def test_legacy_unknown_history_does_not_leak_fills(self):
        self.assertEqual(journal_from_fills(BOT,fills(),public(history_reliable=False)),[])
        p=position('SPY',1,100,'owned')
        rows=journal_from_fills('momentum_master',fills(),public(history_reliable=False,positions=[p]))
        self.assertEqual(rows[0]['status'],'OPEN');self.assertIsNone(rows[0]['entry_time'])
        self.assertEqual(rows[0]['fills'],[])

    def test_unmatched_and_unreconciled_are_not_claimed_current(self):
        t=journal_from_fills(BOT,fills()[1:],public())[0]
        self.assertEqual(t['status'],'INCOMPLETE');self.assertIsNone(t['pnl'])
        self.assertEqual(journal_from_fills(BOT,fills()[:1],public())[0]['status'],'UNRECONCILED')
        p=position(fills()[0]['symbol'],2,2,'owned')
        self.assertEqual(journal_from_fills(BOT,fills()[:1],public(positions=[p]))[0]['status'],'OPEN')

    def test_journal_sort_filter_pagination(self):
        self.service.sync(BOT,fills(),public())
        self.assertEqual(self.store.journal(BOT,{'outcome':'winners'})['total'],1)
        self.assertEqual(self.store.journal(BOT,{'outcome':'losers'})['total'],0)
        self.assertEqual(self.store.journal(BOT,{'symbol':'QQQ'})['total'],0)
        self.assertEqual(self.store.journal(BOT,{'from':'2026-09-17'})['total'],0)
        self.assertEqual(self.store.journal(BOT,{'offset':1})['items'],[])

    def test_timeline_order_linking_stops_and_no_symbol_guessing(self):
        self.add(event(order_id='open',trade_id='actual'),event('STOP_UPDATED',event_id='stop',trade_id='actual',timestamp='2026-09-16T13:00:00Z',risk={'current_stop':200,'price_basis':'underlying'}),
                 event('EXIT_DECISION',event_id='exit',order_id='close',trade_id='actual',timestamp='2026-09-16T14:00:00Z',reason='structural stop'),event(event_id='unrelated',trade_id='other'))
        self.service.sync(BOT,fills(),public());t=self.store.journal(BOT,{})['items'][0]
        detail=self.service.inspector(BOT,t['trade_id'])
        self.assertEqual([e['event_id'] for e in detail['events']],['event1','stop','exit'])
        self.assertEqual(t['exit_reason'],'structural stop')
        self.assertEqual(self.service.inspector(BOT,t['trade_id'],1,1)['events'][0]['event_id'],'stop')

    def test_telemetry_only_lifecycle_stays_unverified(self):
        self.add(event('POSITION_OPENED',trade_id='actual'))
        self.service.sync(BOT,[],public(history_reliable=False))
        row=self.store.journal(BOT,{})['items'][0]
        self.assertEqual(row['status'],'REPORTED OPEN');self.assertIsNone(row['pnl'])
        self.assertEqual(self.service.inspector(BOT,'actual')['total'],1)

    def test_no_telemetry_explains_historical_limit(self):
        self.service.sync(BOT,fills(),public());t=self.store.journal(BOT,{})['items'][0]
        detail=self.service.inspector(BOT,t['trade_id'])
        self.assertIn('unavailable for this historical trade',detail['explanation'])
        self.assertTrue(all(a['status']=='INCOMPLETE DATA' for a in detail['audit']))

    def test_audit_does_not_reinterpret_strategy(self):
        e=validate_event(event(decision='BUY',conditions_complete=True,conditions=[dict(name='actual_rule',required=True,passed=False)]),BOT)
        self.assertEqual(audit([e])[0]['status'],'POSSIBLE RULE VIOLATION')
        e['conditions'][0]['required']=False
        self.assertEqual(audit([e])[0]['status'],'INCOMPLETE DATA')
        e['conditions'][0].update(required=True,passed=True)
        self.assertEqual(audit([e])[0]['status'],'VALID')
        e['conditions_complete']=False;self.assertEqual(audit([e])[0]['status'],'INCOMPLETE DATA')
        e.update(conditions_complete=True,provenance='RECONSTRUCTED',source='historical bars')
        self.assertEqual(audit([e])[0]['status'],'INCOMPLETE DATA')

    def test_exit_policy_must_be_explicit(self):
        e=validate_event(event('EXIT_DECISION',decision='EXIT',conditions_complete=True,conditions=[dict(name='trailing_stop',required=False,passed=False)]),BOT)
        self.assertEqual(audit([e])[1]['status'],'INCOMPLETE DATA')
        e['exit_policy']='ANY_TRIGGER';self.assertEqual(audit([e])[1]['status'],'UNEXPLAINED')
        e['conditions'][0]['passed']=True;self.assertEqual(audit([e])[1]['status'],'VALID')

    def test_missed_trade_requires_explicit_complete_pipeline(self):
        e=validate_event(event(decision='APPROVE',conditions_complete=True,conditions=[dict(name='rule',required=True,passed=True)],pipeline=dict(evaluation_complete=True,capital_sufficient=True,risk_allowed=True,order_submitted=False)),BOT)
        self.assertEqual(diagnostics([e])[0]['status'],'POSSIBLE MISSED TRADE')
        for key in e['pipeline']:
            changed=copy.deepcopy(e);changed['pipeline'].pop(key);self.assertEqual(diagnostics([changed]),[])
        self.assertEqual(diagnostics([event('SIGNAL_GENERATED')]),[])
        self.assertEqual(diagnostics([event('ORDER_EXPIRED',reason='limit not filled')])[0]['status'],'ORDER_EXPIRED')

    def test_legacy_skips_preserve_reason_not_invent_conditions(self):
        path=self.root/'logs/trade_analytics.csv';path.parent.mkdir()
        path.write_text('timestamp,bot_id,strategy,event,underlying,option_symbol,order_id,reason\n2026-09-16T12:00:00Z,long_call,variant,SKIP,SPY,,,spread_too_wide\n')
        self.service.import_legacy(BOT,self.root);self.service.import_legacy(BOT,self.root)
        e=self.store.events(BOT)['items'][0]
        self.assertEqual(e['reason'],'spread_too_wide');self.assertNotIn('conditions',e)
        self.assertNotIn('trade_id',e)

    def test_bot_helper_failure_cannot_raise_into_execution(self):
        with patch('telemetry.monitor_event.threading.Thread.start',side_effect=RuntimeError('fail')):
            emitter=MonitorEvents(self.root/'test.jsonl',BOT,'test')
            self.assertFalse(emitter.emit('ENTRY_DECISION','SPY'))
        emitter=MonitorEvents(self.root/'missing'/'events.jsonl',BOT,'test')
        self.assertFalse(emitter.emit('ENTRY_DECISION','SPY',market={'price':float('nan')}))
        self.assertTrue(emitter.emit('ENTRY_DECISION','SPY'));emitter.queue.join()
        self.store.ingest(BOT,self.root/'missing/events.jsonl')
        self.assertEqual(self.store.events(BOT)['total'],1)

    def test_legacy_multiline_partial_and_batch_budget(self):
        import csv,io
        path=self.root/'logs/trade_analytics.csv';path.parent.mkdir()
        output=io.StringIO();writer=csv.writer(output)
        writer.writerow(['timestamp','bot_id','strategy','event','underlying','order_id','reason','details'])
        for i in range(510):
            writer.writerow(['2026-09-16T12:00:00Z','long_call','variant','SKIP','SPY','',str(i),'line one\nline two'])
        path.write_text(output.getvalue())
        first=self.service.import_legacy(BOT,self.root)
        self.assertLess(first['bytes_imported'],first['source_bytes'])
        self.assertEqual(self.store.events(BOT)['total'],500)
        self.service.import_legacy(BOT,self.root)
        self.assertEqual(self.store.events(BOT)['total'],510)
        self.assertEqual(self.store.events(BOT)['items'][0]['legacy_details'],'line one\nline two')

    def test_monitor_keeps_existing_metrics_when_telemetry_fails(self):
        from services.monitor import Monitor
        from models.records import BotData
        from services.performance_service import reconstruct
        data=BotData(BOT,'option',trades=fills(),positions=[])
        _,data.return_events,data.round_trips=reconstruct(data.trades)
        data.realized_pl=sum(e['realized_pl'] for e in data.return_events)
        monitor=Monitor(bot_root=self.root,data_dir=self.root/'monitor',alpaca=False)
        monitor.read_bot=lambda bot:copy.deepcopy(data if bot==BOT else BotData(bot,'equity',history_reliable=False))
        # Preserve each configured identity in this fixture.
        original=monitor.read_bot
        def read(bot):
            result=original(bot);result.bot_id=bot;return result
        monitor.read_bot=read
        before=monitor.refresh()
        with patch.object(monitor.explain.store,'ingest',side_effect=OSError('disk unavailable')):
            after=monitor.refresh()
        for a,b in zip(before['bots'],after['bots']):
            for field in ('recent_trades','realized_pl','unrealized_pl','trade_returns','trades_total','positions'):
                self.assertEqual(a[field],b[field],field)
            self.assertIn('explain_error',b)
        self.assertEqual(monitor.explain.store.journal(BOT,{})['total'],1)

    def test_recorded_option_greeks_and_selection_are_preserved_not_synthesized(self):
        e=event('CONTRACT_SELECTION',option={'delta':0.6,'gamma':None,'bid':2.1,'ask':2.3},
                contract_selection={'candidate_count':17,'selected':'SPY','rejected':[{'symbol':'QQQ','reason':'Spread too wide'}]})
        self.add(e);actual=self.store.events(BOT)['items'][0]
        self.assertEqual(actual['option'],e['option']);self.assertNotIn('theta',actual['option'])
        self.assertEqual(actual['contract_selection'],e['contract_selection'])

class ExplainHTTPTests(unittest.TestCase):
    setUp = ExplainTests.setUp
    tearDown = ExplainTests.tearDown
    # One separate HTTP test; inherit setup/helpers, not duplicate all tests.
    def test_api_validation_read_only_and_existing_routes(self):
        self.service.sync(BOT,fills(),public())
        service=self.service
        class Fake:
            explain=service
            def get_dashboard(self):return {'bots':[],'timestamp':'2026-09-16'}
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Fake()))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            for path,code in [('/api/dashboard',200),('/api/journal?bot='+BOT,200),('/api/decisions?bot='+BOT,200),('/api/journal?bot=bad',400),('/api/journal?bot='+BOT+'&limit=-1',400),('/api/inspector?bot='+BOT+'&trade=absent',404),('/static/explain.js',200)]:
                conn.request('GET',path);r=conn.getresponse();r.read();self.assertEqual(r.status,code,path)
            conn.request('POST','/api/decisions');r=conn.getresponse();r.read();self.assertEqual(r.status,405)
            conn.close()
        finally:server.shutdown();server.server_close()
