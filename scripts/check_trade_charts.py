"""Read-only market-chart connectivity check. Never writes trade data."""
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import config
from services.account_registry import discover
from services.trade_prices import MarketHistory

accounts,_,_=discover(config.BOT_ROOT,config.BOTS)
reader=MarketHistory(config.BOT_ROOT,accounts,config.ALPACA_ENABLED)
path=config.DATA_DIR/'explainability.db'
with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
    for bot in config.BOTS:
        row=db.execute('SELECT payload FROM journal WHERE bot_id=? ORDER BY timestamp DESC LIMIT 1',(bot,)).fetchone()
        if not row:
            print(bot+': no attributable journal trades to check',flush=True)
            continue
        trade=json.loads(row[0])
        result=reader.history(bot,trade)
        print(bot,trade['symbol'],'bars='+str(len(result['points'])),result['warning'] or result['source'],flush=True)
