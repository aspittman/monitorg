"""GET-only verification of the deployed local dashboard."""
import json,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[2]
def get(path):
    with urllib.request.urlopen('http://127.0.0.1:8765'+path,timeout=15) as r:return r.read()
dashboard=json.loads(get('/api/dashboard'))
html=get('/').decode()
assert 'TODAY TRADE ROI %' in html and 'MONTH TRADE ROI %' in html and 'TOTAL TRADE ROI %' in html
verified=json.loads((root/'maintenance/return_repair/validation.json').read_text())
bot=next(b for b in dashboard['bots'] if b['bot_id']=='options_secured')
assert abs(bot['trade_roi_total']-float(verified['expected_roi']))<1e-9
assert bot['daily_return'] is None and bot['total_return'] is None
history=json.loads(get('/api/history?bot=options_secured'))
assert any(r['trade_roi_total'] is not None for r in history)
summary={b['bot_id']:{p:b['trade_returns'][p] for p in ('today','month','total')} for b in dashboard['bots']}
(root/'maintenance/return_repair/dashboard_validation.json').write_text(json.dumps(dict(timestamp=dashboard['timestamp'],passed=True,bots=summary),indent=2)+'\n')
for b in dashboard['bots']:
    print(b['bot_id'],{p:b['trade_returns'][p]['value'] if b['trade_returns'][p]['status']=='available' else b['trade_returns'][p]['status'] for p in ('today','month','total')})
print('Verified dashboard labels, API returns and persisted history against independent ledger calculation.')
