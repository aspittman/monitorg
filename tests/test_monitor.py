import csv
import hashlib
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from adapters.options_direct import OptionsDirect
from adapters.options_secured import OptionsSecured
from app import handler_for
from models.records import BotData, asset, parse_datetime, timestamp, position
from services.monitor import Monitor
import config
from services.alpaca_reader import AlpacaReader, activity_side
from services.performance_service import reconstruct, simple_return
from services.process_monitor import inspect
from services.snapshot_store import SnapshotStore
from services.source_reader import read_csv, sqlite_copy
from services.trade_service import counts


def trade(side, qty, price, oid, stamp='2026-09-16T12:00:00+00:00', symbol='SPY261016P00741000'):
    return dict(symbol=symbol,side=side,quantity=qty,price=price,order_id=oid,timestamp=stamp,**asset(symbol))


class AccountingTests(unittest.TestCase):
    def test_short_put_multiplier_and_round_trip(self):
        trades = [trade('sell',1,6.13,'open'),trade('buy',1,5.28,'close')]
        positions,events,trips = reconstruct(trades,short=True)
        self.assertEqual(positions,[])
        self.assertAlmostEqual(events[0]['realized_pl'],85)
        self.assertEqual(trips,1)

    def test_short_opening_activity_side(self):
        self.assertEqual(activity_side('sell_short'),'sell')
        self.assertEqual(activity_side('buy'),'buy')

    def test_partial_close_average_cost(self):
        rows = [trade('buy',1,2,'a'),trade('buy',1,4,'b'),trade('sell',1,5,'c')]
        positions,events,trips = reconstruct(rows)
        self.assertEqual(positions[0]['quantity'],1)
        self.assertEqual(positions[0]['entry'],3)
        self.assertEqual(events[0]['realized_pl'],200)
        self.assertEqual(trips,0)

    def test_unmatched_exit_is_unknown(self):
        with self.assertRaisesRegex(ValueError,'Unmatched'):
            reconstruct([trade('sell',1,5,'a')])

    def test_crypto_has_no_contract_multiplier(self):
        _,events,_ = reconstruct([trade('buy',.5,100,'a',symbol='BTC/USD'),trade('sell',.5,110,'b',symbol='BTC/USD')])
        self.assertEqual(events[0]['realized_pl'],5)

    def test_adjusted_option_is_not_treated_as_stock(self):
        adjusted=asset('SPY1261016C00741000')
        self.assertEqual(adjusted['asset_class'],'option')
        self.assertIsNone(adjusted['multiplier'])

    def test_duplicates_and_month_boundary(self):
        rows = [trade('buy',1,2,'same','2026-09-01T03:59:00+00:00'),
                trade('buy',2,2,'same','2026-09-01T04:02:00+00:00'),
                trade('sell',1,3,'other','2026-09-01T04:05:00+00:00')]
        result=counts(rows,datetime(2026,9,1,12,tzinfo=timezone.utc),ZoneInfo('America/New_York'))
        self.assertEqual(result,dict(trades_today=1,trades_month=1,trades_total=2))

    def test_estimated_timestamps_do_not_fake_period_counts(self):
        row=trade('sell',1,2,'a');row['estimated_time']=True
        result=counts([row],datetime(2026,9,16,15,tzinfo=timezone.utc),ZoneInfo('UTC'))
        self.assertIsNone(result['trades_today']);self.assertIsNone(result['trades_month'])
        self.assertEqual(result['trades_total'],1)

    def test_dst_and_broker_fractional_seconds(self):
        with self.assertRaises(ValueError):
            timestamp('2026-11-01T01:30:00',ZoneInfo('America/New_York'))
        self.assertEqual(parse_datetime('2026-09-11T18:08:44.03639Z').microsecond,36390)
        self.assertEqual(parse_datetime('2026-09-11T18:08:44.123456789Z').microsecond,123456)
        self.assertEqual(timestamp('2026-09-16T14:00:00',ZoneInfo('America/Detroit')),'2026-09-16T18:00:00+00:00')

    def test_returns_need_capital_and_no_flows(self):
        self.assertIsNone(simple_return(None,100))
        self.assertIsNone(simple_return(0,100))
        self.assertIsNone(simple_return(100,110,10))
        self.assertAlmostEqual(simple_return(100,110),10)


class IsolationTests(unittest.TestCase):
    def test_sqlite_wal_copy_reads_committed_data_without_writing_source(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'live.sqlite3'
            source=sqlite3.connect(path)
            source.execute('PRAGMA journal_mode=WAL')
            source.execute('CREATE TABLE fills (qty REAL)');source.commit()
            source.execute('INSERT INTO fills VALUES (3)');source.commit()
            before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(d).iterdir()}
            with sqlite_copy(path) as copied:
                self.assertEqual(copied.execute('SELECT qty FROM fills').fetchone()[0],3)
                with self.assertRaises(sqlite3.OperationalError):copied.execute('DELETE FROM fills')
            after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(d).iterdir()}
            self.assertEqual(before,after)
            source.close()

    def test_partial_csv_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'trades.csv';p.write_text('symbol,qty\nSPY,')
            with self.assertRaises(ValueError):read_csv(p,('symbol','qty'))

    def test_transport_has_no_trading_endpoints(self):
        reader=AlpacaReader(dict(paper=True,key='test',secret='test'))
        for path in ('/v2/orders','/v2/positions/SPY','https://evil.test','/v2/account?redirect=x'):
            with self.assertRaises(ValueError):reader.get(path)

    def test_process_matching_requires_exact_root_and_script(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bots=root/'bots';bot=bots/'alpha';bot.mkdir(parents=True)
            proc=root/'proc';proc.mkdir()
            for pid,args in [(101,['python','launcher.py']), (102,['python','-c','print("launcher.py")']),
                             (103,['python','main.py','--backtest']), (104,['python','unrelated.py','launcher.py'])]:
                p=proc/str(pid);p.mkdir();(p/'cmdline').write_bytes('\0'.join(args).encode()+b'\0')
                (p/'stat').write_text(f'{pid} (python) S 0 0')
                (p/'cwd').symlink_to(bot,target_is_directory=True)
            result=inspect(bots,['alpha','other'],proc)
            self.assertEqual(result['alpha']['pids'],[101])
            self.assertEqual(result['other']['status'],'STOPPED')

    def test_snapshots_preserve_unknowns(self):
        with tempfile.TemporaryDirectory() as d:
            store=SnapshotStore(Path(d)/'monitor.db')
            bot=dict(bot_id='test',open_positions=None,realized_pl=None,unrealized_pl=None,
                     daily_return=None,monthly_return=None,total_return=None,trades_today=0,trades_month=0,trades_total=0)
            store.write(dict(timestamp='2026-09-16T12:00:00+00:00',bots=[bot]))
            rows=store.history('test')
            self.assertIsNone(rows[0]['positions']);self.assertIsNone(rows[0]['realized_pl'])
            self.assertEqual(rows[0]['trade_count_day'],0)


class AdapterTests(unittest.TestCase):
    def test_options_signals_and_synthetic_adoption_are_not_executions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'logs').mkdir()
            fields=['timestamp','bot_id','strategy','event','option_symbol','order_id','order_side','qty','price','reason']
            base=dict(timestamp='2026-09-16T12:00:00-04:00',bot_id='long_call',strategy='oasis',
                      option_symbol='SPY261016C00741000',order_side='buy',qty='1',price='2')
            with (root/'logs/trade_analytics.csv').open('w') as h:
                writer=csv.DictWriter(h,fieldnames=fields);writer.writeheader()
                for event,oid in [('SKIP','a'),('ORDER_SUBMITTED','b'),('ORDER_FILL','real'),('ORDER_FILL','real'),('ORDER_FILL','legacy-test')]:
                    writer.writerow(dict(base,event=event,order_id=oid))
            data=OptionsDirect(root,'options_direct').read()
            self.assertEqual(len(data.trades),1)
            self.assertFalse(data.history_reliable)


class ReconciliationTests(unittest.TestCase):
    def monitor(self, path, data):
        import copy
        monitor=Monitor(bot_root=path/'bots',data_dir=path/'data',alpaca=False)
        monitor.membership={b:'paper-test' for b in config.BOTS}
        monitor.accounts=[dict(label='paper-test',bots=list(config.BOTS),paper=True)]
        monitor.read_bot=lambda bot:copy.deepcopy(data.get(bot,BotData(bot,'equity',history_reliable=False)))
        return monitor

    def test_broker_short_activity_repairs_estimated_time(self):
        with tempfile.TemporaryDirectory() as d:
            row=trade('sell',1,6.13,'owned','2026-09-16T12:00:00+00:00');row['estimated_time']=True
            source=BotData('options_secured','option',trades=[row])
            monitor=self.monitor(Path(d),{'options_secured':source})
            now=datetime(2026,9,16,15,tzinfo=timezone.utc)
            before=next(b for b in monitor.refresh(now)['bots'] if b['bot_id']=='options_secured')
            self.assertIsNone(before['trades_month'])
            monitor.account_data={'paper-test':dict(identity='test',positions=[],observed_at=now.isoformat(),month_fills=[dict(
                id='fill1',order_id='owned',symbol=row['symbol'],side='sell_short',qty='1',transaction_time='2026-09-16T12:00:00.12345Z')])}
            after=next(b for b in monitor.refresh(now)['bots'] if b['bot_id']=='options_secured')
            self.assertEqual(after['trades_month'],1);self.assertEqual(after['trades_today'],1)
            self.assertFalse(after['recent_trades'][0]['estimated_time'])

    def test_shared_order_claims_invalidate_both_owners(self):
        with tempfile.TemporaryDirectory() as d:
            data={bot:BotData(bot,'equity',trades=[trade('buy',1,10,'same')]) for bot in ('ETFEnhancer','options_direct')}
            monitor=self.monitor(Path(d),data)
            result=monitor.refresh()
            for b in result['bots']:
                if b['bot_id'] in data:self.assertIsNone(b['trades_total'])

    def test_overlapping_positions_are_not_summed(self):
        with tempfile.TemporaryDirectory() as d:
            data={bot:BotData(bot,'equity',positions=[position('SPY',1,100,'test')],realized_pl=0)
                  for bot in ('ETFEnhancer','options_direct')}
            monitor=self.monitor(Path(d),data)
            result=monitor.refresh()
            for b in result['bots']:
                if b['bot_id'] in data:
                    self.assertIsNone(b['open_positions']);self.assertIsNone(b['combined_pl'])


class HTTPTests(unittest.TestCase):
    def test_http_mutations_and_host_rebinding_blocked(self):
        class Fake:
            def get_dashboard(self):return {'timestamp':'2026-09-16','bots':[]}
        server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(Fake()))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            conn=http.client.HTTPConnection('127.0.0.1',server.server_port)
            for method in ('POST','PUT','PATCH','DELETE'):
                conn.request(method,'/api/orders');response=conn.getresponse();response.read();self.assertEqual(response.status,405)
            conn.request('GET','/api/dashboard',headers={'Host':'evil.test'});response=conn.getresponse();response.read();self.assertEqual(response.status,403)
            conn.request('GET','/api/dashboard');response=conn.getresponse();body=json.loads(response.read());self.assertEqual(body['bots'],[])
            conn.request('GET','/.env');response=conn.getresponse();response.read();self.assertEqual(response.status,404)
            conn.close()
        finally:server.shutdown();server.server_close()


if __name__=='__main__':unittest.main()
