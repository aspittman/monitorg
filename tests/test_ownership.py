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
