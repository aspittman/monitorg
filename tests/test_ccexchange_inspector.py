import csv
import tempfile
import unittest
from pathlib import Path
from adapters.ccexchange import CCExchange
from services.explain_service import journal_from_fills
from services.trade_prices import local_price_history
from tests.test_monitor import trade


class CryptoInspectorTests(unittest.TestCase):
    def test_sell_time_and_hold_are_known_even_when_fee_remainder_is_not(self):
        fills=[trade('buy',1,100,'buy','2026-09-01T00:00:00+00:00','BTC/USD'),
               trade('sell',.9975,105,'sell','2026-09-02T00:00:00+00:00','BTC/USD')]
        row=journal_from_fills('ccexchange',fills,dict(history_reliable=True,positions=[]))[0]
        self.assertEqual(row['exit_time'],fills[1]['timestamp'])
        self.assertEqual(row['hold_seconds'],86400)
        self.assertEqual(row['status'],'UNRECONCILED')
        self.assertIn('unverified',row['exit_scope'])
        self.assertAlmostEqual(row['remaining'],.0025)

    def test_reasons_join_only_exact_order_symbol_side_and_optional_file(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'paper_data').mkdir();(root/'state').mkdir()
            (root/'state/bot_state.json').write_text('{"positions":{}}')
            (root/'paper_data/fills.csv').write_text('order_id,symbol,side,quantity,price,filled_at\na,BTC/USD,buy,1,100,2026-09-01T00:00:00Z\nb,BTC/USD,sell,1,105,2026-09-02T00:00:00Z\n')
            adapter=CCExchange(root,'ccexchange')
            self.assertEqual(len(adapter.read().trades),2)
            path=root/'paper_data/orders.csv'
            path.write_text('order_id,symbol,side,reason,timeframe\na,BTC/USD,buy,momentum,4Hour\nb,BTC/USD,sell,ATR stop,4Hour\n')
            data=adapter.read()
            self.assertEqual(data.trades[0]['entry_reason'],'momentum')
            self.assertEqual(data.trades[1]['exit_reason'],'ATR stop')
            path.write_text(path.read_text().replace('b,BTC/USD,sell','b,ETH/USD,sell'))
            self.assertNotIn('exit_reason',adapter.read().trades[1])
            path.write_text('invalid\n')
            self.assertEqual(len(adapter.read().trades),2)

    def test_historical_bars_end_timestamps_and_optional_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);path=root/'ccexchange/paper_data/bars/4Hour/BTC_USD.csv';path.parent.mkdir(parents=True)
            path.write_text('timestamp,close\n2026-09-01T00:00:00Z,100\n2026-09-01T04:00:00Z,102\n')
            t=dict(symbol='BTC/USD',entry_time='2026-09-01T01:00:00Z',exit_time='2026-09-01T08:00:00Z',fills=[{'timeframe':'4Hour'}])
            result=local_price_history(root,'ccexchange',t)
            self.assertEqual(len(result['points']),2)
            self.assertEqual(result['points'][0]['timestamp'],'2026-09-01T04:00:00+00:00')
            self.assertEqual(result['points'][1]['price'],102)
            self.assertIn('not decision snapshots',result['source'])
            path.write_text('broken')
            self.assertEqual(local_price_history(root,'ccexchange',t)['points'],[])
            self.assertTrue(local_price_history(root,'ccexchange',t)['warning'])
            self.assertEqual(local_price_history(root,'options_direct',t)['points'],[])
