"""Gross average-cost P/L. No account equity is assigned to a bot."""
from models.records import position


def reconstruct(trades, short=False):
    lots, events, trips = {}, [], 0
    opening_side = 'sell' if short else 'buy'
    for trade in sorted(trades, key=lambda x: (x['timestamp'], x.get('sequence', 0))):
        symbol, qty, price = trade['symbol'], trade['quantity'], trade['price']
        lot = lots.setdefault(symbol, {'qty': 0.0, 'cost': 0.0})
        if trade['side'] == opening_side:
            lot['qty'] += qty
            lot['cost'] += qty * price
        else:
            if qty > lot['qty'] + 1e-9 or lot['qty'] <= 0:
                raise ValueError(f'Unmatched closing fill for {symbol}; cost basis unavailable')
            average = lot['cost'] / lot['qty']
            pnl = (price-average) * qty * trade['multiplier'] * (-1 if short else 1)
            trade['realized_pl'] = pnl
            capital = average * qty * trade['multiplier']
            basis = 'Matched entry cost'
            if short:
                capital = trade['strike'] * qty * trade['multiplier'] if trade.get('call_put') == 'put' and trade.get('strike') else None
                basis = 'Gross strike collateral' if capital is not None else 'Covered stock cost basis unavailable'
            events.append({'timestamp': trade['timestamp'], 'realized_pl': pnl,
                           'capital': capital, 'capital_basis': basis, 'order_id': trade['order_id'],
                           'sequence': trade.get('sequence',0), 'estimated_time': trade.get('estimated_time',False)})
            lot['qty'] -= qty
            lot['cost'] -= average * qty
            if abs(lot['qty']) < 1e-9:
                lot['qty'], lot['cost'] = 0, 0
                trips += 1
    positions = [position(s, l['qty'] * (-1 if short else 1), l['cost']/l['qty'],
                          'Reconstructed local fill ledger') for s, l in lots.items() if l['qty'] > 1e-9]
    return positions, events, trips


def simple_return(start_equity, end_equity, net_flow=0):
    """Only valid with a verified bot baseline and no intervening cash flows.

    Caller must supply complete, period-aligned bot valuations. No current adapter
    has this evidence, so dashboard daily/month/total returns remain null.
    """
    if start_equity is None or end_equity is None or start_equity <= 0 or net_flow != 0:
        return None
    return 100 * (end_equity / start_equity - 1)


def closed_trade_returns(data, now, timezone):
    """Gross ROI of matched closing quantities, weighted by their entry capital.

    Capital can be reused across trades: the denominator is cumulative trade
    capital, not account equity or allocated bot capital. Partial closes count
    only their matched portion. Open-position price movements are excluded.
    """
    import math
    from models.records import parse_datetime
    keys=('today','month','total')
    def unavailable(reason):
        return {k:dict(value=None,status='unavailable',reason=reason,realized_pl=None,capital=None,closes=0) for k in keys}
    if not data.history_reliable or data.parse_error:
        return unavailable('Reliable bot-owned execution history is unavailable.')
    if data.return_error or data.realized_pl is None:
        return unavailable(data.return_error or 'Unresolved cost basis or settlement history.')
    if data.bot_id == 'ccexchange' and any(t['side']=='sell' and t.get('realized_pl') is None for t in data.trades):
        return unavailable('New broker closing fills await local cost-basis reconciliation.')
    recorded_pnl=sum(e['realized_pl'] for e in data.return_events)
    if not math.isfinite(recorded_pnl) or not math.isfinite(data.realized_pl) or abs(recorded_pnl-data.realized_pl)>1e-6:
        return unavailable('Realized P/L includes lifecycle events without matched entry capital.')
    # Broker-verified execution timestamps may supersede local log times.
    trades={(t['order_id'],t.get('sequence',0)):t for t in data.trades}
    events=[]
    for event in data.return_events:
        trade=trades.get((event['order_id'],event.get('sequence',0)))
        stamp=parse_datetime(trade['timestamp'] if trade else event['timestamp'])
        if stamp>now: continue
        events.append((event,stamp.astimezone(timezone).date(),trade.get('estimated_time',False) if trade else event.get('estimated_time',False)))
    today=now.astimezone(timezone).date()
    result={}
    for period in keys:
        if period!='total' and any(uncertain for _,_,uncertain in events):
            result[period]=unavailable('A closing execution has an unverified timestamp.')[period];continue
        selected=[e for e,date,_ in events if period=='total' or (period=='today' and date==today) or (period=='month' and (date.year,date.month)==(today.year,today.month))]
        if not selected:
            result[period]=dict(value=None,status='no_closes',reason='No matched closing executions in this period; ROI has no denominator.',realized_pl=0,capital=0,closes=0);continue
        if any(e['capital'] is None or not math.isfinite(e['capital']) or e['capital']<=0 or not math.isfinite(e['realized_pl']) for e in selected):
            result[period]=unavailable('Matched entry capital or covered-stock collateral basis is unavailable.')[period];continue
        pnl=sum(e['realized_pl'] for e in selected);capital=sum(e['capital'] for e in selected)
        result[period]=dict(value=100*pnl/capital,status='available',reason='100 × gross realized P/L ÷ matched entry capital; excludes fees and unrealized P/L.',realized_pl=pnl,capital=capital,closes=len(selected))
    return result
