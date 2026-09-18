"""Dependency-only validation. Does not import bot code or create broker clients."""
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import subprocess

STAGE=Path(__file__).resolve().parent
BASE=Path('/home/stardustbreaker/MyBotz')
spec=importlib.util.spec_from_file_location('scheduler',STAGE/'market_bot_scheduler.py')
scheduler=importlib.util.module_from_spec(spec);spec.loader.exec_module(scheduler)


def verify(bot):
    python=scheduler.python_for(BASE/bot)
    check=subprocess.run([str(python),'-m','pip','check'],capture_output=True,text=True,timeout=60)
    modules=['alpaca','pandas','numpy','dotenv']
    if bot.startswith('options_'):modules.append('ta')
    if bot in ('options_secured','options_inverted','options_direct','ETFEnhancer','momentum_master'):modules.append('yfinance')
    if bot=='ccexchange':modules.extend(['pydantic_settings','yaml'])
    code='import importlib; '+ '; '.join(f'importlib.import_module({m!r})' for m in modules)
    imports=subprocess.run([str(python),'-I','-B','-c',code],cwd='/tmp',capture_output=True,text=True,timeout=60)
    result=dict(bot=bot,python=str(python),dependencies_ok=check.returncode==0,imports_ok=imports.returncode==0,
                details=(check.stdout+check.stderr+imports.stdout+imports.stderr).strip())
    print(bot,'PASS' if result['dependencies_ok'] and result['imports_ok'] else 'FAIL',result['details'],flush=True)
    return result


if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(verify,scheduler.BOTS))
    (STAGE/'environment_validation.json').write_text(json.dumps(results,indent=2)+'\n')
    raise SystemExit(0 if all(r['dependencies_ok'] and r['imports_ok'] for r in results) else 1)
