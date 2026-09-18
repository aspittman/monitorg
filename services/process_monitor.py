"""Linux /proc inspection. No signals, subprocesses, or PID-file trust."""
import os
from pathlib import Path


def inspect(bot_root, bots, proc_root=Path('/proc')):
    matches = {bot: [] for bot in bots}
    denied = False
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return {bot: dict(status='UNKNOWN', pids=[], reason='Process inspection unavailable') for bot in bots}
    roots = {str((bot_root/bot).resolve()): bot for bot in bots}
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            argv = (entry/'cmdline').read_bytes().decode(errors='replace').split('\0')
            if not argv or 'python' not in Path(argv[0]).name.lower():
                continue
            stat = (entry/'stat').read_text()
            if stat.rsplit(')', 1)[1].strip().split()[0] == 'Z':
                continue
            if '-c' in argv or '-m' in argv or '--backtest' in argv:
                continue
            # First script after interpreter flags; never match arbitrary later arguments.
            script = next((a for a in argv[1:] if a and not a.startswith('-')), '')
            if Path(script).name not in ('launcher.py', 'main.py', 'monitor.py'):
                continue
            script_path = Path(script)
            if not script_path.is_absolute():
                script_path = (entry/'cwd').resolve(strict=True)/script_path
            bot = roots.get(str(script_path.resolve().parent))
            if bot:
                matches[bot].append(int(entry.name))
        except PermissionError:
            denied = True
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError:
            denied = True
    return {bot: dict(status='RUNNING' if pids else ('UNKNOWN' if denied else 'STOPPED'),
                      pids=sorted(pids), reason='Matching launcher/main/monitor Python process' if pids else
                      ('Some same-user process details inaccessible' if denied else 'No matching process; cron schedule is not inferred'))
            for bot, pids in matches.items()}
