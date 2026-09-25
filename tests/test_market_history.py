import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from services.trade_prices import MarketHistory

NOW=datetime(2026,9,23,20,tzinfo=timezone.utc)
ACCOUNT=dict(bots=['ETFEnhancer','momentum_master','options_direct','ccexchange'],key='not-real',secret='not-real')
class MarketHistoryTests(unittest.TestCase):
    def setUp(self):self.reader=MarketHistory(None,[ACCOUNT])
    def trade(self,**kw):return dict(symbol=kw.pop('symbol','AAPL'),entry_time='2026-09-21T14:00:00Z',exit_time='2026-09-22T15:00:00Z',status='CLOSED',**kw)
    def test_equity_bars_use_sip_raw_and_end_times_and_cache(self):
        with patch.object(self.reader,'_get',return_value={'bars':{'AAPL':[{'t':'2026-09-21T14:00:00Z','o':199,'h':202,'l':198,'c':200}]}}) as get:
            result=self.reader.history('ETFEnhancer',self.trade(),now=NOW)
            self.assertEqual(result['points'][0]['timestamp'],'2026-09-21T14:01:00+00:00')
            self.assertEqual(result['points'][0]['high'],202)
            self.assertEqual(result['timeframe'],'1Min')
            self.assertEqual(get.call_args.args[2]['limit'],10000)
            args=get.call_args.args;self.assertEqual(args[1],'/v2/stocks/bars');self.assertEqual(args[2]['feed'],'sip');self.assertEqual(args[2]['adjustment'],'raw')
            self.reader.history('ETFEnhancer',self.trade(),now=NOW);self.assertEqual(get.call_count,1)
    def test_unknown_momentum_entry_still_has_market_context_not_fake_entry(self):
        t=self.trade();t.update(entry_time=None,exit_time=None,status='OPEN')
        with patch.object(self.reader,'_get',return_value={'bars':{'AAPL':[{'t':'2026-09-21T14:00:00Z','c':200}]}}):
            result=self.reader.history('momentum_master',t,now=NOW)
        self.assertTrue(result['points']);self.assertIn('Entry time unknown',result['context']);self.assertIsNone(t['entry_time'])
    def test_option_underlying_and_contract_are_separate_requests(self):
        t=self.trade(symbol='SPY260925C00680000')
        with patch.object(self.reader,'_get',return_value={'bars':{}}) as get:
            self.reader.history('options_direct',t,now=NOW)
            self.assertEqual(get.call_args.args[2]['symbols'],'SPY');self.assertEqual(get.call_args.args[1],'/v2/stocks/bars')
            self.reader.history('options_direct',t,basis='option',now=NOW)
            self.assertEqual(get.call_args.args[2]['symbols'],t['symbol']);self.assertEqual(get.call_args.args[1],'/v1beta1/options/bars')
    def test_crypto_and_bounded_pagination(self):
        responses=[{'bars':{'BTC/USD':[{'t':'2026-09-21T14:00:00Z','c':100}]},'next_page_token':'a'}, {'bars':{'BTC/USD':[{'t':'2026-09-21T14:15:00Z','c':101}]}}]
        with patch.object(self.reader,'_get',side_effect=responses) as get:
            result=self.reader.history('ccexchange',self.trade(symbol='BTC/USD',asset_class='crypto'),now=NOW)
            self.assertEqual(get.call_args.args[1],'/v1beta3/crypto/us/bars');self.assertEqual(len(result['points']),2)
        other=MarketHistory(None,[ACCOUNT])
        with patch.object(other,'_get',side_effect=[{'bars':{},'next_page_token':str(i)} for i in range(3)]) as get:
            result=other.history('ETFEnhancer',self.trade(),now=NOW)
            self.assertEqual(get.call_count,3);self.assertTrue(result['warning'])
    def test_disabled_errors_and_bad_values_preserve_trade_evidence(self):
        disabled=MarketHistory(None,[ACCOUNT],False)
        with patch.object(disabled,'_get') as get:
            self.assertFalse(disabled.history('ETFEnhancer',self.trade(),now=NOW)['points']);get.assert_not_called()
        with patch.object(self.reader,'_get',side_effect=RuntimeError('Historical market data HTTP 403')):
            result=self.reader.history('ETFEnhancer',self.trade(),now=NOW)
            self.assertFalse(result['points']);self.assertIn('403',result['warning'])
        other=MarketHistory(None,[ACCOUNT])
        with patch.object(other,'_get',return_value={'bars':{'AAPL':[{'t':'2026-09-21T14:00:00Z','c':float('nan')}]}}):
            self.assertFalse(other.history('ETFEnhancer',self.trade(),now=NOW)['points'])
    def test_no_arbitrary_urls_or_trading_authority(self):
        with self.assertRaises(ValueError):self.reader._get(ACCOUNT,'/v2/orders',{})
    def test_completed_bar_cannot_appear_before_its_close(self):
        with patch.object(self.reader,'_get',return_value={'bars':{'AAPL':[{'t':'2026-09-23T19:45:00Z','c':200}]}}):
            self.assertFalse(self.reader.history('ETFEnhancer',self.trade(),now=NOW)['points'])

    def test_all_configured_bots_share_the_same_market_history_path(self):
        import config
        reader=MarketHistory(None,[dict(ACCOUNT,bots=list(config.BOTS))])
        with patch.object(reader,'_get',return_value={'bars':{'AAPL':[{'t':'2026-09-21T14:00:00Z','c':200}]}}):
            for bot in config.BOTS:
                with self.subTest(bot=bot):self.assertTrue(reader.history(bot,self.trade(),now=NOW)['points'])

    def test_verified_momentum_subset_does_not_change_performance_reliability(self):
        import copy,tempfile
        from pathlib import Path
        import config
        from services.monitor import Monitor
        from models.records import BotData
        from tests.test_monitor import trade
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            monitor=Monitor(bot_root=root,data_dir=root/'data',alpaca=False)
            monitor.accounts=[dict(label='paper',bots=list(config.BOTS),paper=True)]
            monitor.membership={bot:'paper' for bot in config.BOTS}
            monitor.account_data={'paper':dict(positions=None,ownership_registry={'order_owners':{'owned':'momentum_master','foreign':'ETFEnhancer'}})}
            records=[trade('buy',1,100,'owned',symbol='NVDA'),trade('buy',1,200,'foreign',symbol='AAPL')]
            monitor.read_bot=lambda bot:BotData(bot,'equity',trades=copy.deepcopy(records) if bot=='momentum_master' else [],history_reliable=False)
            dashboard=monitor.refresh()
            bot=next(b for b in dashboard['bots'] if b['bot_id']=='momentum_master')
            self.assertFalse(bot['history_reliable']);self.assertIsNone(bot['trades_total']);self.assertIsNone(bot['realized_pl'])
            rows=monitor.explain.store.journal('momentum_master',{})['items']
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['symbol'],'NVDA')
            self.assertEqual(rows[0]['order_ids'],['owned'])

    def test_dense_remote_crypto_history_takes_priority_over_coarse_local_bars(self):
        local=dict(points=[dict(timestamp='2026-09-21T16:00:00Z',price=999)],source='Saved 4Hour bars',price_basis='underlying',warning=None)
        with patch('services.trade_prices.local_price_history',return_value=local), patch.object(self.reader,'_get',return_value={'bars':{'BTC/USD':[dict(t='2026-09-21T14:00:00Z',c=100,o=99,h=101,l=98)]}}) as get:
            result=self.reader.history('ccexchange',self.trade(symbol='BTC/USD'),now=NOW)
            self.assertEqual(get.call_args.args[2]['timeframe'],'1Min')
            self.assertEqual(result['points'][0]['price'],100)
            self.assertEqual(result['points'][0]['low'],98)

    def test_coarse_local_fallback_is_explicit_when_remote_fails(self):
        local=dict(points=[dict(timestamp='2026-09-21T16:00:00Z',price=999)],source='Saved 4Hour bars',price_basis='underlying',warning=None)
        with patch('services.trade_prices.local_price_history',return_value=local),patch.object(self.reader,'_get',side_effect=RuntimeError('Market data unavailable')):
            result=self.reader.history('ccexchange',self.trade(symbol='BTC/USD'),now=NOW)
            self.assertEqual(result['points'],local['points'])
            self.assertIn('coarser',result['warning'])
