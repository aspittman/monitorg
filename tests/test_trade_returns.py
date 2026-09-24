import copy,unittest
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from models.records import BotData,asset
from services.performance_service import reconstruct,closed_trade_returns
NOW=datetime(2026,9,18,20,tzinfo=timezone.utc)
TZ=ZoneInfo('America/Detroit')
def t(side,qty,price,oid,stamp='2026-09-18T14:00:00+00:00',symbol='SPY'):
    return dict(side=side,quantity=qty,price=price,order_id=oid,timestamp=stamp,sequence=0,**asset(symbol),symbol=symbol)
def data(trades,short=False):
    p,e,n=reconstruct(trades,short)
    return BotData('test','equity',trades=trades,return_events=e,realized_pl=sum(x['realized_pl'] for x in e))
class TradeReturnTests(unittest.TestCase):
    def test_weighted_roi_not_sum_or_average_percentages(self):
        d=data([t('buy',1,100,'a'),t('sell',1,110,'b'),t('buy',1,1000,'c'),t('sell',1,950,'d')])
        r=closed_trade_returns(d,NOW,TZ)['total']
        self.assertAlmostEqual(r['value'],100*(-40)/1100)
        self.assertEqual((r['capital'],r['realized_pl']),(1100,-40))
    def test_partial_close_uses_only_closed_cost(self):
        r=closed_trade_returns(data([t('buy',10,20,'a'),t('sell',2,25,'b')]),NOW,TZ)['today']
        self.assertEqual((r['capital'],r['realized_pl'],r['value']),(40,10,25))
    def test_put_uses_strike_collateral_not_received_premium(self):
        d=data([t('sell',1,6.13,'a',symbol='SPY261016P00741000'),t('buy',1,5.28,'b',symbol='SPY261016P00741000')],True)
        r=closed_trade_returns(d,NOW,TZ)['total']
        self.assertEqual(r['capital'],74100);self.assertAlmostEqual(r['value'],85/74100*100)
    def test_long_option_uses_paid_premium_and_multiplier(self):
        d=data([t('buy',2,2,'a',symbol='SPY261016C00741000'),t('sell',1,3,'b',symbol='SPY261016C00741000')])
        r=closed_trade_returns(d,NOW,TZ)['total'];self.assertEqual((r['capital'],r['value']),(200,50))
    def test_no_closes_is_not_zero_percent(self):
        r=closed_trade_returns(data([t('buy',1,100,'a')]),NOW,TZ)['today']
        self.assertIsNone(r['value']);self.assertEqual(r['status'],'no_closes')
    def test_breakeven_is_zero_percent(self):
        r=closed_trade_returns(data([t('buy',1,100,'a'),t('sell',1,100,'b')]),NOW,TZ)['today']
        self.assertEqual(r['value'],0);self.assertEqual(r['status'],'available')
    def test_unreliable_history_stays_unknown(self):
        d=data([t('buy',1,100,'a'),t('sell',1,110,'b')]);d.history_reliable=False
        self.assertIsNone(closed_trade_returns(d,NOW,TZ)['total']['value'])
    def test_unknown_covered_call_collateral_stays_unknown(self):
        d=data([t('sell',1,2,'a',symbol='SPY261016C00741000'),t('buy',1,1,'b',symbol='SPY261016C00741000')],True)
        self.assertIsNone(closed_trade_returns(d,NOW,TZ)['total']['value'])
    def test_broker_close_time_controls_period_not_entry_time(self):
        d=data([t('buy',1,100,'a','2026-08-01T00:00:00+00:00'),t('sell',1,110,'b','2026-09-01T03:59:00+00:00')])
        self.assertIsNone(closed_trade_returns(d,NOW,TZ)['month']['value'])
        d.trades[1]['timestamp']='2026-09-18T14:00:00+00:00'
        self.assertEqual(closed_trade_returns(d,NOW,TZ)['today']['value'],10)
    def test_unknown_close_time_keeps_total_but_not_period(self):
        d=data([t('buy',1,100,'a'),t('sell',1,110,'b')]);d.trades[1]['estimated_time']=True
        r=closed_trade_returns(d,NOW,TZ)
        self.assertIsNone(r['today']['value']);self.assertEqual(r['total']['value'],10)

    def test_new_broker_close_without_cost_basis_is_not_omitted_from_roi(self):
        d=data([t('buy',1,100,'a'),t('sell',1,110,'b')]);d.bot_id='ccexchange'
        d.trades.append(t('sell',1,120,'new'))
        r=closed_trade_returns(d,NOW,TZ)['total']
        self.assertIsNone(r['value']);self.assertIn('cost-basis',r['reason'])
