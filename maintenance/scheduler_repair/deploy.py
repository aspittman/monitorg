"""Prepare/review or apply the scheduler-only repair with backups and guards."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

STAGE=Path(__file__).resolve().parent
BASE=Path('/home/stardustbreaker/MyBotz')
NAMES=('run_market_bots.sh','stop_market_bots.sh','market_bot_scheduler.py')


def crontab():
    return subprocess.run(['crontab','-l'],check=True,capture_output=True,text=True).stdout


def prepare():
    before=crontab()
    after=before
    for name in ('run_market_bots.sh','stop_market_bots.sh'):
        old=f'/home/aaron/MyBotz/{name}'
        if after.count(old)!=1:raise RuntimeError(f'Expected exactly one existing cron command for {name}')
        after=after.replace(old,f'{BASE}/{name} >> {BASE}/cron_logs/scheduler_cron.log 2>&1')
    (STAGE/'crontab.before').write_text(before)
    (STAGE/'crontab.proposed').write_text(after)
    print('Prepared cron changes (all other content preserved):')
    for line in after.splitlines():
        if line.strip() and not line.lstrip().startswith('#'):print(line)


def deploy():
    proposed=(STAGE/'crontab.proposed').read_text()
    before=(STAGE/'crontab.before').read_text()
    if crontab()!=before:raise RuntimeError('Crontab changed since review; refusing to overwrite')
    hashes=json.loads((STAGE/'original_hashes.json').read_text())
    for name,digest in hashes.items():
        if hashlib.sha256((BASE/name).read_bytes()).hexdigest()!=digest:
            raise RuntimeError(f'{name} changed since review; refusing to overwrite')
    if (BASE/'market_bot_scheduler.py').exists():raise RuntimeError('Scheduler helper already exists; refusing overwrite')
    spec=importlib.util.spec_from_file_location('staged_scheduler',STAGE/'market_bot_scheduler.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if module.check(BASE):raise RuntimeError('Preflight failed; scheduler was not installed')
    backup=BASE/'scheduler_backups'/datetime.now().strftime('%Y%m%dT%H%M%S')
    backup.mkdir(parents=True)
    for name in hashes:shutil.copy2(BASE/name,backup/name)
    (backup/'crontab.before').write_text(before)
    (BASE/'cron_logs').mkdir(exist_ok=True)
    changed=[]
    try:
        # Helper first, so neither wrapper can reference a missing program.
        for name in ('market_bot_scheduler.py','run_market_bots.sh','stop_market_bots.sh'):
            temporary=BASE/(name+'.repair.tmp')
            temporary.write_bytes((STAGE/name).read_bytes());temporary.chmod(0o755)
            temporary.replace(BASE/name);changed.append(name)
        subprocess.run(['crontab',str(STAGE/'crontab.proposed')],check=True)
    except Exception:
        for name in changed:
            if (backup/name).exists():shutil.copy2(backup/name,BASE/name)
            else:(BASE/name).unlink(missing_ok=True)
        raise
    result=crontab()
    if result!=proposed:raise RuntimeError('Installed crontab differs from proposal; inspect before further changes')
    print(f'Scheduler installed. Backups: {backup}')
    print('No trading bots were started or stopped by this deployment.')
    (STAGE/'deployment.json').write_text(json.dumps(dict(backup=str(backup),installed_at=datetime.now().astimezone().isoformat(),
        files=[str(BASE/n) for n in NAMES],cron_verified=True),indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','deploy'))
    action=parser.parse_args().action
    prepare() if action=='prepare' else deploy()
