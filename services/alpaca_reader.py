"""Strict GET-only transport with fixed Alpaca hosts and endpoint allowlist."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ORDER = re.compile(r'/v2/orders/[a-fA-F0-9-]{36}$')
ALLOWED = {'/v2/account', '/v2/positions', '/v2/account/activities/FILL', '/v2/orders:by_client_order_id', '/v2/account/activities/CFEE'}


def activity_side(value):
    # Verified paper options activities label opening shorts "sell_short".
    return 'sell' if value == 'sell_short' else value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Alpaca redirect refused')


class AlpacaReader:
    def __init__(self, account, timeout=8):
        self.account, self.timeout = account, timeout
        self.base = 'https://paper-api.alpaca.markets' if account['paper'] else 'https://api.alpaca.markets'
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, path, params=None):
        if path not in ALLOWED and not ORDER.fullmatch(path):
            raise ValueError('Endpoint is not read-allowlisted')
        query = '?' + urllib.parse.urlencode(params) if params else ''
        req = urllib.request.Request(self.base+path+query, method='GET', headers={
            'APCA-API-KEY-ID': self.account['key'], 'APCA-API-SECRET-KEY': self.account['secret'],
            'Accept': 'application/json', 'User-Agent': 'BotMonitor/1.0'})
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'Alpaca HTTP {exc.code}; response body withheld') from None
        except urllib.error.URLError:
            raise RuntimeError('Alpaca network/DNS connection failed') from None

    def snapshot(self):
        account = self.get('/v2/account')
        positions = self.get('/v2/positions')
        # The real identity is used only in memory for deduplication, never as a credential.
        return dict(identity=account['id'], equity=float(account['equity']), cash=float(account['cash']),
                    currency=account.get('currency', 'USD'), positions=[dict(
                        symbol=p['symbol'], quantity=float(p['qty']), entry=float(p['avg_entry_price']),
                        current_price=float(p['current_price']) if p.get('current_price') else None,
                        unrealized_pl=float(p['unrealized_pl']) if p.get('unrealized_pl') else None,
                        asset_class=p.get('asset_class')) for p in positions],
                    observed_at=datetime.now(timezone.utc).isoformat())

    def fills(self, after, max_pages=100):
        return self.activities('FILL', after, max_pages)

    def activities(self, kind, after, max_pages=100):
        if kind not in ('FILL','CFEE'):
            raise ValueError('Activity type is not read-allowlisted')
        rows, token = [], None
        for _ in range(max_pages):
            params = dict(after=after, direction='asc', page_size=100)
            if token:
                params['page_token'] = token
            page = self.get('/v2/account/activities/'+kind, params)
            if not isinstance(page, list):
                raise ValueError('Unexpected fill response')
            rows.extend(page)
            if len(page) < 100:
                return rows
            new_token = page[-1]['id']
            if new_token == token:
                raise ValueError('Alpaca pagination repeated a page')
            token = new_token
        raise ValueError('Alpaca pagination limit reached; history is incomplete')
