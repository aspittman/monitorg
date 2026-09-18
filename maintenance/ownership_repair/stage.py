"""Stage minimal broker-boundary changes without touching live repositories."""
import ast,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
files={
 'ccexchange/src/ccexchange/execution.py':('from alpaca.trading.client import TradingClient','from ccexchange.bot_ownership import TradingClient'),
 'ETFEnhancer/trader.py':('from alpaca.trading.client import TradingClient','from bot_ownership import TradingClient'),
 'ETFEnhancerLT/brokerage/alpaca_client.py':('from alpaca.trading.client import TradingClient','from bot_ownership import TradingClient'),
 'momentum_master/trader.py':('from alpaca.trading.client import TradingClient','from bot_ownership import TradingClient'),
 'options_covered/broker.py':('from alpaca.trading.client import TradingClient','from bot_ownership import TradingClient'),
 'options_secured/options_trader.py':('from alpaca.trading.client import TradingClient','from bot_ownership import TradingClient'),
 'options_inverted/options_trader.py':('from alpaca.trading.client import TradingClient','from bot_ownership import TradingClient'),
 'options_direct/options_trader.py':('from alpaca.trading.client import TradingClient','from bot_ownership import TradingClient'),
}
manifest=[]
def save(relative,text):
    ast.parse(text)
    original=ROOT/relative
    dest=HERE/'staged'/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
    manifest.append({'path':relative,'before_sha256':hashlib.sha256(original.read_bytes()).hexdigest() if original.exists() else None,'after_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
for relative,(before,after) in files.items():
    text=(ROOT/relative).read_text();assert text.count(before)==1
    save(relative,text.replace(before,after))
    bot=relative.split('/')[0]
    loader=f'''"""Stable trader identity and independent shared-account isolation."""
from pathlib import Path
import sys
from alpaca.trading.client import TradingClient as _AlpacaTradingClient
TRADER_ID = {bot!r}
# Resolve the shared trading package, never the monitoring application.
_root = next((p for p in Path(__file__).resolve().parents if (p / 'trading_ownership' / '__init__.py').is_file()), None)
if _root is None:
    raise RuntimeError('Trading ownership package is missing; trading refused')
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
from trading_ownership import guarded_client

def TradingClient(*args, **kwargs):
    return guarded_client(_AlpacaTradingClient(*args, **kwargs), TRADER_ID)
'''
    save(bot+('/src/ccexchange' if bot=='ccexchange' else '')+'/bot_ownership.py',loader)
(HERE/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Staged',len(manifest),'files; live files unchanged')
