"""Read saved market bars on inspector requests, never on the trading path."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from models.records import parse_datetime, number
from services.source_reader import read_csv


def local_price_history(bot_root, bot, trade):
    result = dict(points=[], source=None, price_basis='underlying', warning=None)
    if bot_root is None or bot != 'ccexchange' or not trade.get('entry_time'):
        return result
    symbol = trade['symbol']
    if not re.fullmatch(r'[A-Z0-9]+/[A-Z0-9]+', symbol):
        return result
    timeframe = next((f.get('timeframe') for f in trade.get('fills', []) if f.get('timeframe')), None)
    if timeframe not in ('4Hour', '1Day'):
        result['warning'] = 'Saved price history unavailable: entry timeframe was not recorded.'
        return result
    interval = timedelta(hours=4) if timeframe == '4Hour' else timedelta(days=1)
    path = Path(bot_root)/bot/'paper_data/bars'/timeframe/(symbol.replace('/', '_')+'.csv')
    try:
        if path.stat().st_size > 8*1024*1024:
            raise ValueError('History file exceeds bounded read size')
        now = datetime.now(timezone.utc)
        entry = parse_datetime(trade['entry_time'])
        end = parse_datetime(trade['exit_time']) if trade.get('exit_time') else now
        # Include context on both sides. Timestamp bar closes at interval END,
        # so replay never displays a completed candle before it was available.
        rows = read_csv(path, ('timestamp','close'))
        points = {}
        for row in rows:
            start = parse_datetime(row['timestamp'])
            if start.tzinfo is None:
                continue
            stamp = start.astimezone(timezone.utc) + interval
            price = number(row['close'])
            if price is not None and price > 0 and entry-interval*2 <= stamp <= min(now,end+interval*2):
                points[stamp.isoformat()] = dict(timestamp=stamp.isoformat(),price=price,
                                               open=number(row.get('open')),high=number(row.get('high')),low=number(row.get('low')))
        result.update(points=sorted(points.values(),key=lambda p:p['timestamp']),
                      source=f'Saved {timeframe} market-bar closes; historical context, not decision snapshots',
                      interval_seconds=interval.total_seconds())
        if len(result['points']) > 2000:
            # Avoid drawing a misleading continuous line across removed samples.
            result['points'] = result['points'][:2000]
            result['warning'] = 'Price history limited to the first 2,000 bars.'
    except (OSError, ValueError, KeyError):
        result['warning'] = 'Saved historical prices are unavailable; execution markers remain visible.'
    return result


class MarketHistory:
    """On-demand GET-only bars, separate from account polling and trading APIs."""
    def __init__(self, bot_root, accounts=(), enabled=True):
        from collections import OrderedDict
        import threading
        self.bot_root, self.enabled = bot_root, enabled
        self.accounts = {bot: account for account in accounts for bot in account['bots']}
        self.cache = OrderedDict()
        self.lock = threading.Lock()
        self.slots = threading.BoundedSemaphore(2)

    def _get(self, account, path, params):
        import json
        import urllib.request
        import urllib.parse
        import urllib.error
        from services.alpaca_reader import NoRedirect
        if path not in ('/v2/stocks/bars','/v1beta3/crypto/us/bars','/v1beta1/options/bars'):
            raise ValueError('Market-data endpoint not allowed')
        req = urllib.request.Request('https://data.alpaca.markets'+path+'?'+urllib.parse.urlencode(params),
                                     method='GET', headers={'APCA-API-KEY-ID':account['key'],
                                     'APCA-API-SECRET-KEY':account['secret'], 'Accept':'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=5) as response:
                raw=response.read(4*1024*1024+1)
                if len(raw)>4*1024*1024:raise ValueError('Oversized market response')
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise RuntimeError('Historical market data HTTP '+str(exc.code)+'; check data access or retry later.') from None
        except (urllib.error.URLError,TimeoutError):
            raise RuntimeError('Historical market-data connection unavailable; retry later.') from None

    def history(self, bot, trade, basis='underlying', now=None):
        import copy
        import time
        from models.records import asset
        now=now or datetime.now(timezone.utc)
        empty=dict(points=[],source=None,price_basis=basis,warning=None)
        if basis not in ('underlying','option'):return empty
        local=local_price_history(self.bot_root,bot,trade) if basis=='underlying' else empty
        metadata=asset(trade['symbol'])
        option=metadata['asset_class']=='option'
        if basis=='option' and not option:
            return dict(empty,warning='This instrument is not an option contract.')
        symbol=metadata['underlying'] if option and basis=='underlying' else trade['symbol']
        crypto=trade.get('asset_class')=='crypto' or '/' in symbol
        if crypto and '/' not in symbol and symbol.endswith('USD'):symbol=symbol[:-3]+'/USD'
        if not re.fullmatch(r'[A-Z0-9.]+(?:/[A-Z0-9]+)?',symbol):return dict(empty,warning='Unsupported market symbol.')
        end=now-timedelta(minutes=16)  # compatible with delayed market-data access
        if trade.get('exit_time') and trade.get('status') not in ('OPEN','REPORTED OPEN','UNRECONCILED'):
            end=min(end,parse_datetime(trade['exit_time'])+timedelta(days=2))
        end=end.replace(second=0,microsecond=0,minute=end.minute//5*5)
        start=parse_datetime(trade['entry_time'])-timedelta(days=2) if trade.get('entry_time') else end-timedelta(days=30)
        context=None if trade.get('entry_time') else 'Entry time unknown; showing the latest 30 days. No entry marker is inferred.'
        if start>=end:return dict(empty,warning='Historical bars have not reached this trade yet; retry after the data delay.')
        if end-start>timedelta(days=730):
            start=end-timedelta(days=730);context='History limited to the latest two years of this trade.'
        days=(end-start).total_seconds()/86400
        timeframe,seconds=('1Min',60) if days<=16 else ('5Min',300) if days<=83 else ('15Min',900) if days<=250 else ('1Hour',3600)
        path='/v1beta1/options/bars' if basis=='option' else '/v1beta3/crypto/us/bars' if crypto else '/v2/stocks/bars'
        feed='sip' if not crypto and basis=='underlying' else None
        # Round end for stable five-minute caching without changing the requested start.
        end=end.replace(second=0,microsecond=0,minute=end.minute//5*5)
        key=(bot,symbol,basis,start.isoformat(),end.isoformat(),timeframe)
        with self.lock:
            saved=self.cache.get(key)
            if saved and time.monotonic()<saved[0]:
                self.cache.move_to_end(key);return copy.deepcopy(saved[1])
        account=self.accounts.get(bot)
        if not self.enabled or not account:
            if local['points']:
                return dict(local,warning='Remote market history is disabled/unconfigured; displaying the coarser saved local bars.')
            return dict(empty,warning='Historical market data requires enabled Alpaca access and this bot’s configured credentials.')
        if not self.slots.acquire(blocking=False):return dict(empty,warning='Market-history requests are busy; refresh this detail shortly.')
        result=dict(empty,symbol=symbol,interval_seconds=seconds,context=context,
                    timeframe=timeframe,
                    source=f'Alpaca {feed or ("options" if basis=="option" else "crypto US")} {timeframe} bar closes · historical market context, not decision snapshots',
                    observed_at=now.isoformat())
        params=dict(symbols=symbol,timeframe=timeframe,start=start.isoformat(),end=end.isoformat(),limit=10000,sort='asc')
        if feed:params['feed']=feed
        if path=='/v2/stocks/bars':params.update(adjustment='raw',asof='-')
        try:
            points={};tokens=set()
            for _ in range(3):
                response=self._get(account,path,params)
                for bar in (response.get('bars') or {}).get(symbol,[]):
                    stamp=parse_datetime(bar['t'])
                    if stamp.tzinfo is None:raise ValueError('Naive market timestamp')
                    stamp=stamp.astimezone(timezone.utc)+timedelta(seconds=seconds)
                    price=number(bar['c'])
                    if price is not None and price>0 and start<=stamp<=end:
                        points[stamp.isoformat()]=dict(timestamp=stamp.isoformat(),price=price,
                                                     open=number(bar.get('o')),high=number(bar.get('h')),low=number(bar.get('l')))
                token=response.get('next_page_token')
                if not token:break
                if token in tokens:raise ValueError('Repeated market-data page')
                tokens.add(token);params['page_token']=token
            else:result['warning']='Chart history is partial: the 30,000-bar request limit was reached.'
            result['points']=sorted(points.values(),key=lambda p:p['timestamp'])
            if not result['points']:result['warning']='No historical bars returned for this symbol and date range. Buy/sell fills are not substituted for ticker history.'
        except RuntimeError as exc:
            result['warning']=str(exc)
        except Exception:
            result['warning']='Historical prices unavailable or malformed; trade evidence is unaffected.'
        finally:self.slots.release()
        if not result['points'] and local['points']:
            result=dict(local,warning=(result['warning'] or 'Dense market history unavailable')+' Showing coarser saved local bars instead.')
        with self.lock:
            self.cache[key]=(time.monotonic()+(300 if result['points'] else 30),copy.deepcopy(result))
            while len(self.cache)>128 or sum(len(value[1]['points']) for value in self.cache.values())>100000:self.cache.popitem(last=False)
        return result
