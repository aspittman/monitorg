"""GET-only broker evidence collection. Credentials are never persisted."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from config import BOT_ROOT,BOTS
from services.account_registry import discover
from services.alpaca_reader import AlpacaReader,ALLOWED
ALLOWED.update({'/v2/orders','/v2/account/activities'})
result=[]
for account in discover(BOT_ROOT,BOTS)[0]:
    reader=AlpacaReader(account)
    snap=reader.snapshot()
    orders=[]; until=None
    for _ in range(50):
        params=dict(status='all',limit=500,direction='desc',after='2026-08-01T00:00:00Z')
        if until: params['until']=until
        page=reader.get('/v2/orders',params)
        orders.extend(page)
        if len(page)<500: break
        nxt=page[-1]['submitted_at']
        if nxt==until: raise RuntimeError('Order pagination stalled')
        until=nxt
    else: raise RuntimeError('Incomplete order history')
    activities=[]; token=None
    for _ in range(100):
        params=dict(after='2026-08-01T00:00:00Z',direction='asc',page_size=100)
        if token: params['page_token']=token
        page=reader.get('/v2/account/activities',params)
        activities.extend(page)
        if len(page)<100: break
        nxt=page[-1]['id']
        if nxt==token: raise RuntimeError('Activity pagination stalled')
        token=nxt
    else: raise RuntimeError('Incomplete activity history')
    result.append(dict(label=account['label'],bots=account['bots'],snapshot=snap,orders=orders,activities=activities))
out=Path(__file__).with_name('broker_evidence.json');out.write_text(json.dumps(result,indent=2));out.chmod(0o600)
for a in result:
    print(a['label'],a['bots'],'positions',a['snapshot']['positions'],'orders',len(a['orders']),'activities',len(a['activities']))
    print('Non-fill activities:',[r for r in a['activities'] if r.get('activity_type')!='FILL'])
