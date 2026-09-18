#!/usr/bin/env python3
"""Independent read-only manual audit of options_secured against Alpaca.

Run from the project root: ./venv/bin/python scripts/verify.py
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from services.account_registry import discover
from services.alpaca_reader import AlpacaReader
from services.source_reader import sqlite_copy, table
from services.trade_service import counts


def main():
    accounts, env, membership = discover(config.BOT_ROOT, config.BOTS)
    bot = 'options_secured'
    account = next(a for a in accounts if a['label']==membership[bot])
    reader = AlpacaReader(account)
    now = datetime.now(timezone.utc)
    month_start = now.astimezone(config.TIMEZONE).replace(day=1,hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
    fills = reader.fills(month_start.isoformat())
    broker = reader.snapshot()
    with sqlite_copy(config.BOT_ROOT/bot/env[bot].get('DB_PATH','logs/options_secured.sqlite3')) as db:
        orders = {r['client_id']:r for r in table(db,'orders')}
        rows = table(db,'fills')
        lots = [r for r in table(db,'lots') if r['qty']>0]
        pnl_rows = table(db,'pnl')
    normalized, checks, broker_orders = [], [], {}
    for row in rows:
        local_order = orders[row['client_id']]
        oid = local_order['broker_id']
        order = reader.get('/v2/orders/'+oid)
        broker_orders[oid] = order
        matched = [f for f in fills if f['order_id']==oid]
        identity_ok = order['client_order_id']==row['client_id'] and order['symbol']==row['symbol'] and order['side']==row['side']
        quantity_ok = abs(float(order['filled_qty'])-sum(r['qty'] for r in rows if r['client_id']==row['client_id']))<1e-9
        price_ok = abs(float(order['filled_avg_price'])-row['price'])<1e-8
        stamp = min((f['transaction_time'] for f in matched), default=order.get('filled_at'))
        if not stamp:
            raise RuntimeError('Broker fill timestamp unavailable')
        normalized.append(dict(order_id=oid,timestamp=stamp.replace('Z','+00:00')))
        checks.append(dict(symbol=row['symbol'],side=row['side'],quantity=row['qty'],local_price=row['price'],
                           broker_price=float(order['filled_avg_price']),identity_match=identity_ok,
                           quantity_match=quantity_ok,price_match=price_ok,broker_fill_time=stamp,
                           activity_sides=[f['side'] for f in matched]))
    position_checks = []
    for lot in lots:
        p = next((p for p in broker['positions'] if p['symbol']==lot['symbol']),None)
        position_checks.append(dict(symbol=lot['symbol'],local_quantity=-lot['qty'],broker_quantity=p['quantity'] if p else None,
                                    matches=bool(p and abs(p['quantity']+lot['qty'])<1e-9)))
    # Independently calculate the closed SPY put's premium difference from broker orders.
    spy = [o for o in broker_orders.values() if o['symbol']=='SPY261016P00741000']
    spy_pnl = sum(float(o['filled_qty'])*float(o['filled_avg_price'])*100*(1 if o['side']=='sell' else -1) for o in spy)
    local_pnl = sum(r['realized'] for r in pnl_rows)
    result = dict(verified_at=now.isoformat(), bot=bot, account=membership[bot], source='Local SQLite compared with Alpaca GET account/positions/orders/FILL activity',
                  counts=counts(normalized,now,config.TIMEZONE), local_open_positions=len(lots), position_checks=position_checks,
                  fill_checks=checks, local_realized_pl=local_pnl, broker_spy_round_trip_gross_pl=spy_pnl,
                  pnl_matches=abs(local_pnl-spy_pnl)<1e-6,
                  all_checks_pass=all(all(c[k] for k in ('identity_match','quantity_match','price_match')) for c in checks)
                       and all(p['matches'] for p in position_checks) and abs(local_pnl-spy_pnl)<1e-6)
    config.DATA_DIR.mkdir(exist_ok=True)
    (config.DATA_DIR/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
