import copy,unittest
from models.records import BotData
from services.ownership_service import reconcile

class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.account={'positions':[{'symbol':'NVDA','quantity':2,'entry':100,'asset_class':'us_equity'}], 'month_fills':[],
         'ownership_registry':{'observed_at':'2026-09-17T16:00:00+00:00','claims':{'NVDA':{'owner':'momentum_master','quantity':2}},'order_owners':{},'crypto_reconciliation':{'flat_verified':True,'order_ids':[]}}}
    def test_owned_and_flat_bot_counts(self):
        for bot,count in [('momentum_master',1),('ccexchange',0),('ETFEnhancerLT',0)]:
            d=BotData(bot,"equity");reconcile(d,self.account);self.assertEqual(len(d.positions),count)
    def test_quantity_mismatch_stays_unknown(self):
        self.account['positions'][0]['quantity']=3
        d=BotData('momentum_master','equity');reconcile(d,self.account);self.assertIsNone(d.positions)
    def test_new_attributable_fills_update_quantity(self):
        self.account['positions'][0]['quantity']=1
        self.account['ownership_registry']['order_owners']['own']='momentum_master'
        self.account['month_fills']=[dict(order_id='own',symbol='NVDA',qty='1',side='sell',transaction_time='2026-09-17T16:01:00+00:00')]
        d=BotData('momentum_master','equity');reconcile(d,self.account);self.assertEqual(d.positions[0]['quantity'],1)
    def test_unknown_intervening_fill_is_not_assigned(self):
        self.account['month_fills']=[dict(order_id='unknown',symbol='NVDA',qty='1',side='buy',transaction_time='2026-09-17T16:01:00+00:00')]
        d=BotData('momentum_master','equity');reconcile(d,self.account);self.assertIsNone(d.positions)
    def test_unassigned_stock_does_not_become_lt_position(self):
        self.account['positions'].append(dict(symbol='SPY',quantity=1,entry=100,asset_class='us_equity'))
        d=BotData('ETFEnhancerLT','equity');reconcile(d,self.account);self.assertIsNone(d.positions)
    def test_incomplete_history_fails_closed(self):
        self.account['fill_warning']='offline'
        d=BotData('momentum_master','equity');reconcile(d,self.account);self.assertIsNone(d.positions)
    def test_unresolved_order_does_not_erase_verified_positions(self):
        self.account['unresolved_order_owners']=['momentum_master']
        for bot,count in [('ccexchange',0),('ETFEnhancerLT',0),('momentum_master',1)]:
            d=BotData(bot,'equity');reconcile(d,self.account)
            self.assertEqual(len(d.positions),count)
            self.assertEqual(any('reservation' in w for w in d.warnings),bot=='momentum_master')
    def test_unresolved_order_with_unknown_fill_stays_unknown(self):
        self.account['unresolved_order_owners']=['momentum_master']
        self.account['month_fills']=[dict(order_id='unknown',symbol='NVDA',qty='1',side='buy',transaction_time='2026-09-17T16:01:00+00:00')]
        d=BotData('momentum_master','equity');reconcile(d,self.account);self.assertIsNone(d.positions)
    def test_crypto_broker_symbol_without_slash_keeps_asset_class(self):
        self.account['positions']=[dict(symbol='LINKUSD',quantity=2,entry=12,asset_class='crypto')]
        self.account['ownership_registry']['claims']['LINKUSD']=dict(owner='ccexchange',quantity=2)
        d=BotData('ccexchange','crypto');reconcile(d,self.account)
        self.assertEqual(d.positions[0]['asset_class'],'crypto')
    def test_registered_crypto_fill_is_counted_before_hourly_csv_catches_up(self):
        self.account['positions']=[]
        self.account['ownership_registry']['claims']['LINKUSD']=dict(owner='ccexchange',quantity=0)
        self.account['ownership_registry']['order_owners']['owned']='ccexchange'
        self.account['month_fills']=[dict(id='fill',order_id='owned',symbol='LINK/USD',qty='2',price='12',side='buy',transaction_time='2026-09-17T16:01:00+00:00')]
        d=BotData('ccexchange','crypto');reconcile(d,self.account)
        self.assertEqual(len(d.trades),1)
        self.assertIsNone(d.positions)  # Missing broker position is still a mismatch.
        d2=BotData('ccexchange','crypto',trades=d.trades.copy());reconcile(d2,self.account)
        self.assertEqual(len(d2.trades),1)

class AccountFetchTests(unittest.TestCase):
    def test_missing_pending_order_does_not_become_account_ownership_error(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch,Mock
        from services.monitor import Monitor
        with tempfile.TemporaryDirectory() as tmp:
            with patch('services.monitor.discover',return_value=([dict(label='paper',bots=['momentum_master'],paper=True)],{},{})):
                monitor=Monitor(bot_root=Path(tmp),data_dir=Path(tmp),alpaca=True)
            reader=Mock()
            reader.snapshot.return_value=dict(identity='id',positions=[],observed_at='2026-09-18T18:00:00+00:00')
            reader.fills.return_value=[];reader.activities.return_value=[]
            reader.get.side_effect=RuntimeError('Alpaca HTTP 404')
            registry=dict(observed_at='2026-09-17T16:00:00+00:00',pending_clients=[('pending','momentum_master')],order_owners={})
            with patch('services.monitor.AlpacaReader',return_value=reader),patch('services.monitor.load_registry',return_value=registry):
                monitor.refresh_accounts()
            result=monitor.account_data['paper']
            self.assertNotIn('ownership_error',result)
            self.assertEqual(result['unresolved_order_owners'],['momentum_master'])
