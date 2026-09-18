import json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace as N
sys.path.insert(0,str(Path(__file__).resolve().parent))
from trading_ownership.guard import GuardedClient,OwnershipError,instrument

class Fake:
    def __init__(self, account='account'):
        self.account=account;self.positions=[];self.orders=[];self.sent=[];self.cancelled=[];self.replaced=[];self.fail=False;self.activities={}
    def get(self,path,**k):return self.activities.get(path,[])
    def get_account(self):return N(id=self.account)
    def get_all_positions(self):
        if self.fail:raise OSError('offline')
        return self.positions
    def get_orders(self,*a,**k):return [o for o in self.orders if o.status=='new']
    def get_order_by_client_id(self,cid):return next(o for o in self.orders if o.client_order_id==cid)
    def get_order_by_id(self,oid):return next(o for o in self.orders if o.id==oid)
    def submit_order(self,order_data):
        o=N(id=str(len(self.sent)),client_order_id=order_data.client_order_id,symbol=order_data.symbol,status='new',legs=None)
        self.orders.append(o);self.sent.append(o);return o
    def cancel_order_by_id(self,oid):self.cancelled.append(oid)
    def replace_order_by_id(self,oid,order_data):self.replaced.append(oid);return N(id='replacement')

def request(symbol,cid=None):return N(symbol=symbol,client_order_id=cid,legs=None,order_class='simple')
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.seed={'accounts':{'account':{'bots':['ETFEnhancer','momentum_master','options_direct','options_inverted','ccexchange'],'observed_at':'2026-09-17T16:00:00+00:00','claims':{'SCHD':{'owner':'ETFEnhancer','quantity':1}},'legacy_orders':{'legacy':'momentum_master'}},'other':{'bots':['momentum_master'],'observed_at':'2026-09-17T16:00:00+00:00','claims':{},'legacy_orders':{}}}}
        (self.path/'baseline.json').write_text(json.dumps(self.seed));self.raw=Fake()
        self.m=GuardedClient(self.raw,'momentum_master',self.path);self.e=GuardedClient(self.raw,'ETFEnhancer',self.path)
    def tearDown(self):self.tmp.cleanup()
    def test_foreign_position_blocks_even_with_no_open_orders(self):
        self.raw.positions=[N(symbol='SCHD',qty='1')]
        self.assertEqual(self.m.get_all_positions(),[])
        self.assertEqual(len(self.e.get_all_positions()),1)
        with self.assertRaises(OwnershipError):self.m.submit_order(request('SCHD'))
        self.assertEqual(self.raw.sent,[])
    def test_unowned_position_uses_404_contract(self):
        from alpaca.common.exceptions import APIError
        with self.assertRaises(APIError) as result:self.m.get_open_position('SCHD')
        self.assertEqual(result.exception.status_code,404)
    def test_real_sdk_request(self):
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        r=MarketOrderRequest(symbol='NVDA',notional=100,side=OrderSide.BUY,time_in_force=TimeInForce.DAY)
        self.m.submit_order(r)
        self.assertTrue(r.client_order_id.startswith('momentum_master-'))
    def test_unknown_position_is_not_adopted(self):
        self.raw.positions=[N(symbol='AAPL',qty='1')]
        with self.assertRaises(OwnershipError):self.m.submit_order(request('AAPL'))
    def test_pending_entry_blocks_second_bot(self):
        self.m.submit_order(request('SPY'))
        with self.assertRaises(OwnershipError):self.e.submit_order(request('SPY'))
        self.assertEqual(len(self.raw.sent),1)
    def test_flat_terminal_position_can_transfer(self):
        self.m.submit_order(request('SPY'));self.raw.orders[0].status='canceled'
        self.e.submit_order(request('SPY'))
        self.assertEqual(len(self.raw.sent),2)
    def test_failed_submission_keeps_reservation(self):
        self.raw.submit_order=lambda **k: (_ for _ in ()).throw(OSError('timeout'))
        with self.assertRaises(OSError):self.m.submit_order(request('SPY'))
        with self.assertRaises(StopIteration):self.e.submit_order(request('SPY'))
    def test_account_scope(self):
        self.m.submit_order(request('SPY'))
        other=Fake('other');GuardedClient(other,'momentum_master',self.path).submit_order(request('SPY'))
        self.assertEqual(len(other.sent),1)
    def test_option_contracts_are_distinct(self):
        a=GuardedClient(self.raw,'options_direct',self.path);b=GuardedClient(self.raw,'options_inverted',self.path)
        a.submit_order(request('SPY261016C00750000'));b.submit_order(request('SPY261016P00750000'))
        self.assertEqual(len(self.raw.sent),2)
    def test_crypto_alias(self):self.assertEqual(instrument('BTC/USD'),instrument('BTCUSD'))
    def test_unique_prefix_and_foreign_id_rejected(self):
        r=request('NVDA');self.m.submit_order(r)
        self.assertTrue(r.client_order_id.startswith('momentum_master-'))
        with self.assertRaises(OwnershipError):self.m.submit_order(request('QQQ','long_call_spoof'))
    def test_foreign_cancel_replace_bulk_and_raw_write_blocked(self):
        self.raw.orders=[N(id='foreign',symbol='SCHD',client_order_id='etfenhancer-paper-existing',status='new')]
        with self.assertRaises(OwnershipError):self.m.cancel_order_by_id('foreign')
        with self.assertRaises(OwnershipError):self.m.replace_order_by_id('foreign',request('SCHD'))
        for method in ('cancel_orders','close_position','close_all_positions','post','patch','delete','exercise_options_position'):
            with self.assertRaises(OwnershipError):getattr(self.m,method)
        self.assertEqual(self.raw.cancelled+self.raw.replaced,[])
    def test_offline_blocks_entry(self):
        self.raw.fail=True
        with self.assertRaises(OSError):self.m.submit_order(request('NVDA'))
        self.assertEqual(self.raw.sent,[])
    def test_legacy_order_owner(self):
        self.assertTrue(self.m.owns_order(N(id='legacy',client_order_id='old-random')))
        self.assertFalse(self.e.owns_order(N(id='legacy',client_order_id='old-random')))
    def test_unregistered_account_fails_closed(self):
        with self.assertRaises(OwnershipError):GuardedClient(Fake('bad'),'momentum_master',self.path).get_all_positions()
    def test_simultaneous_claims_have_only_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        gate=Barrier(2)
        def send(client):
            gate.wait()
            try:client.submit_order(request('SPY'));return 'sent'
            except OwnershipError:return 'blocked'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(send,[self.m,self.e]))
        self.assertEqual(sorted(results),['blocked','sent'])
        self.assertEqual(len(self.raw.sent),1)
    def test_native_fill_after_audit_can_establish_new_holding(self):
        self.raw.orders=[N(id='entry',symbol='NVDA',client_order_id='momentum_master-entry',status='filled')]
        self.raw.activities['/account/activities/FILL']=[dict(order_id='entry',symbol='NVDA',side='buy',qty='2',transaction_time='2026-09-17T16:01:00Z')]
        self.raw.positions=[N(symbol='NVDA',qty='2')]
        self.assertEqual(len(self.m.get_all_positions()),1)
        self.assertEqual(self.e.get_all_positions(),[])
    def test_unattributed_change_invalidates_existing_claim(self):
        self.raw.orders=[N(id='foreign',symbol='SCHD',client_order_id='random',status='filled')]
        self.raw.activities['/account/activities/FILL']=[dict(order_id='foreign',symbol='SCHD',side='sell',qty='0.5',transaction_time='2026-09-17T16:01:00Z')]
        self.raw.positions=[N(symbol='SCHD',qty='0.5')]
        with self.assertRaises(OwnershipError):self.e.get_all_positions()
    def test_crypto_fee_reconciles_owned_quantity(self):
        self.raw.orders=[N(id='entry',symbol='BTCUSD',client_order_id='ccexchange-entry',status='filled')]
        self.raw.activities['/account/activities/FILL']=[dict(order_id='entry',symbol='BTC/USD',side='buy',qty='1',transaction_time='2026-09-17T16:01:00Z')]
        self.raw.activities['/account/activities/CFEE']=[dict(symbol='BTCUSD',qty='-0.0025',created_at='2026-09-17T16:01:02Z')]
        self.raw.positions=[N(symbol='BTC/USD',qty='0.9975',asset_class='crypto')]
        c=GuardedClient(self.raw,'ccexchange',self.path)
        self.assertEqual(len(c.get_all_positions()),1)
    def test_incomplete_orders_fail_closed(self):
        self.raw.get_orders=lambda **kw:[N(symbol='OTHER',client_order_id='x')]*500
        with self.assertRaises(OwnershipError):self.m.submit_order(request('SPY'))
if __name__=='__main__':unittest.main()
