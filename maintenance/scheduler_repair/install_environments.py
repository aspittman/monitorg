"""Create only the three absent venvs, using each bot's existing requirements."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import venv

BASE=Path('/home/stardustbreaker/MyBotz')
LOGS=Path(__file__).resolve().parent
BOTS=('options_covered','options_secured','options_inverted')


def install(bot):
    root=BASE/bot
    target=root/'venv'
    if target.exists():raise RuntimeError(f'{target} already exists; refusing to overwrite')
    print(f'{bot}: creating isolated environment',flush=True)
    venv.create(target,with_pip=True)
    with (LOGS/f'{bot}-install.log').open('w') as output:
        subprocess.run([str(target/'bin/python'),'-m','pip','install','--disable-pip-version-check',
                        '--no-cache-dir','-r',str(root/'requirements.txt')],stdout=output,stderr=subprocess.STDOUT,check=True)
        subprocess.run([str(target/'bin/python'),'-m','pip','check'],stdout=output,stderr=subprocess.STDOUT,check=True)
    print(f'{bot}: requirements installed and pip check passed',flush=True)


if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(install,BOTS))
