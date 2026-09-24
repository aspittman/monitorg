"""Independent gross collateral-return check against the secured-put ledger."""
import json,sys
from decimal import Decimal as D
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from config import BOT_ROOT,TIMEZONE
from services.source_reader import sqlite_copy
from adapters.options_secured import OptionsSecured
from services.performance_service import closed_trade_returns
with sqlite_copy(BOT_ROOT/'options_secured/logs/options_secured.sqlite3') as db:
    rows=[dict(r) for r in db.execute('SELECT symbol,side,qty,price,timestamp FROM fills ORDER BY timestamp,rowid')]
# Independently build average-credit lots and collateral on each buy-to-close.
lots={};closes=[]
for r in rows:
    qty=D(str(r['qty']));price=D(str(r['price']));symbol=r['symbol']
    held,credit=lots.get(symbol,(D(0),D(0)))
    if r['side']=='sell':lots[symbol]=(held+qty,credit+qty*price);continue
    assert held>=qty and held>0
    average=credit/held;strike=D(symbol[-8:])/1000
    pnl=(average-price)*qty*100;capital=strike*qty*100
    closes.append(dict(symbol=symbol,realized_pl=str(pnl),capital=str(capital)))
    lots[symbol]=(held-qty,credit-average*qty)
pnl=sum(D(r['realized_pl']) for r in closes);capital=sum(D(r['capital']) for r in closes)
expected=100*pnl/capital
source=OptionsSecured(BOT_ROOT/'options_secured','options_secured').read()
actual=closed_trade_returns(source,datetime.now(timezone.utc),TIMEZONE)['total']
assert abs(D(str(actual['value']))-expected)<D('0.000000001')
report=dict(checked_at=datetime.now(timezone.utc).isoformat(),bot='options_secured',closes=closes,expected_roi=str(expected),actual=actual,passed=True)
(ROOT/'maintenance/return_repair/validation.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
