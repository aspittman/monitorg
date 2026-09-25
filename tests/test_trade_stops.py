import json
import tempfile
import unittest
from pathlib import Path
from services.trade_stops import event_stops, legacy_stops


class StopTests(unittest.TestCase):
    def test_generic_stops_basis_cancellation_and_malformed(self):
        for bot in ('ccexchange','ETFEnhancer','ETFEnhancerLT','momentum_master','options_direct','options_inverted','options_secured','options_covered'):
            event=dict(bot_id=bot,timestamp='2026-09-01T12:00:00Z',provenance='RECORDED',risk=dict(stops=[
                dict(stop_id='hard',initial_stop=100,price_basis='underlying'),
                dict(stop_id='premium',current_stop=2,price_basis='option'),
                dict(stop_id='hard',active=False,price_basis='underlying'),
                dict(current_stop='invalid',price_basis='underlying'),None]))
            rows=event_stops([event])
            self.assertEqual([s['price'] for s in rows],[100,2,None])
            self.assertEqual(rows[1]['price_basis'],'option')
        self.assertEqual(event_stops([dict(event,risk={'current_stop':123})]),[])

    def test_legacy_crypto_exact_order_time_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bot=root/'ccexchange';(bot/'logs').mkdir(parents=True);(bot/'paper_data').mkdir()
            (bot/'paper_data/orders.csv').write_text('order_id,symbol,side,submitted_at\na,BTC/USD,buy,2026-09-01T12:00:00Z\n')
            rows=[dict(event='BUY_SUBMITTED',symbol='BTC/USD',order_id='a',initial_stop=100),
                  dict(event='POSITION_MANAGED',symbol='BTC/USD',stop=101),
                  dict(event='BUY_SUBMITTED',symbol='ETH/USD',order_id='a',initial_stop=99)]
            (bot/'logs/events.jsonl').write_text('\n'.join(map(json.dumps,rows))+'\nbroken')
            result=legacy_stops(root,'ccexchange',dict(symbol='BTC/USD',order_ids=['a']))
            self.assertEqual(len(result),1);self.assertEqual(result[0]['price'],100)
            self.assertIn('intermediate',result[0]['source'])
            self.assertEqual(legacy_stops(root,'ccexchange',dict(symbol='BTC/USD',order_ids=['b'])),[])

    def test_current_structural_stop_is_never_historical(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'ETFEnhancer/logs';path.mkdir(parents=True)
            (path/'position_state_paper.json').write_text(json.dumps({'SPY':{'entry_order_id':'a','current_structural_stop':100}}))
            trade=dict(symbol='SPY',order_ids=['a'],status='OPEN',current={'quantity':1})
            self.assertTrue(legacy_stops(root,'ETFEnhancer',trade)[0]['current_only'])
            self.assertEqual(legacy_stops(root,'ETFEnhancer',dict(trade,status='CLOSED')),[])
            self.assertEqual(legacy_stops(root,'ETFEnhancer',dict(trade,order_ids=['other'])),[])

    def test_stops_are_independent_of_timeline_page_and_bot_scoped(self):
        from services.explain_store import ExplainStore
        from services.explain_service import ExplainService
        from tests.test_explainability import event, BOT
        with tempfile.TemporaryDirectory() as d:
            store=ExplainStore(Path(d)/'test.db')
            with store.connect() as db:
                for i in range(3):
                    store.insert(db,event('STOP_UPDATED',event_id=str(i),trade_id='trade',
                                          timestamp=f'2026-09-16T12:0{i}:00Z',
                                          risk={'current_stop':100+i,'price_basis':'underlying'}),BOT)
                store.insert(db,event('STOP_UPDATED',event_id='other',trade_id='other',
                                      risk={'current_stop':999,'price_basis':'underlying'}),BOT)
            store.replace_journal(BOT,[dict(trade_id='trade',symbol='SPY',status='OPEN',order_ids=[])])
            result=ExplainService(store).inspector(BOT,'trade',limit=1,offset=2)
            self.assertEqual(len(result['events']),1)
            self.assertEqual([s['price'] for s in result['stop_history']],[100,101,102])

    def test_option_stops_follow_fill_cycle_partial_close_and_price_basis(self):
        import csv
        from adapters.options_direct import OptionsDirect
        from adapters.options_inverted import OptionsInverted
        for cls, bot, owner, contract in (
            (OptionsDirect,'options_direct','long_call','SPY261016C00741000'),
            (OptionsInverted,'options_inverted','long_put','SPY261016P00741000')):
            with self.subTest(bot=bot), tempfile.TemporaryDirectory() as d:
                root=Path(d);(root/'logs').mkdir()
                fields=['timestamp','bot_id','strategy','event','option_symbol','order_id','order_side','qty','price','reason','details']
                base=dict(timestamp='2026-09-16T12:00:00Z',bot_id=owner,strategy='swing',option_symbol=contract,order_side='buy',qty=2,price=3)
                rows=[dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=90'), # no entry
                      dict(event='ORDER_FILL',order_id='entry'),
                      dict(event='ORDER_FILL',order_id='entry'), # duplicate fill
                      dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=95'),
                      dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=95'), # unchanged
                      dict(event='OPTION_TRAIL_SNAPSHOT',details='option_trailing_stop=2'),
                      dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=bad'),
                      dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=500',strategy='foreign'),
                      dict(event='ORDER_FILL',order_id='partial',order_side='sell',qty=1),
                      dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=96'),
                      dict(event='ORDER_FILL',order_id='close',order_side='sell',qty=1),
                      dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=97'), # already closed
                      dict(event='ORDER_FILL',order_id='new'),
                      dict(event='RISK_SNAPSHOT',details='underlying_trailing_stop=94')]
                with (root/'logs/trade_analytics.csv').open('w') as stream:
                    writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
                    for row in rows:writer.writerow(dict(base,**row))
                data=cls(root,bot).read()
                self.assertEqual(len(data.trades),4)
                stops=data.trades[0]['stop_history']
                self.assertEqual([s['price'] for s in stops],[95,2,96])
                self.assertEqual([s['price_basis'] for s in stops],['underlying','option','underlying'])
                self.assertEqual(data.trades[-1]['stop_history'][0]['price'],94)
