"""Verify deployed scheduling configuration without launching or stopping bots."""
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime

STAGE=Path(__file__).resolve().parent
BASE=Path('/home/stardustbreaker/MyBotz')

if __name__=='__main__':
    for name in ('market_bot_scheduler.py','run_market_bots.sh','stop_market_bots.sh'):
        assert (BASE/name).read_bytes()==(STAGE/name).read_bytes(),f'Deployed file differs: {name}'
    subprocess.run(['bash','-n',str(BASE/'run_market_bots.sh'),str(BASE/'stop_market_bots.sh')],check=True)
    result=subprocess.run([str(BASE/'run_market_bots.sh'),'--check'],check=True,capture_output=True,text=True)
    print(result.stdout,end='')
    cron=subprocess.run(['crontab','-l'],check=True,capture_output=True,text=True).stdout
    assert cron==(STAGE/'crontab.proposed').read_text(),'Crontab differs from reviewed proposal'
    service=subprocess.run(['systemctl','is-active','cron'],check=True,capture_output=True,text=True).stdout.strip()
    assert service=='active'
    record=dict(verified_at=datetime.now().astimezone().isoformat(),deployed_files_match=True,
        preflight=result.stdout,cron_matches=True,cron_service=service,
        timezone=Path('/etc/timezone').read_text().strip(),trading_bots_started_or_stopped=False)
    (STAGE/'installation_validation.json').write_text(json.dumps(record,indent=2)+'\n')
    print('PASS: deployed files match; wrappers pass syntax/preflight; cron entries match; cron service is active.')
