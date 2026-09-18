"""Resolve credentials as data, never execute or source a bot's configuration."""
import hashlib
import os
import shlex


def read_env(path):
    result = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if '=' not in line or line.lstrip().startswith('#'):
                continue
            key, value = line.split('=', 1)
            key = key.strip().removeprefix('export ')
            parts = shlex.split(value, comments=True)
            result[key] = ' '.join(parts)
    # Bot configurations give exported variables precedence over .env.
    result.update(os.environ)
    return result


def discover(bot_root, bots):
    accounts, environments, membership = {}, {}, {}
    for bot in bots:
        env = read_env(bot_root/bot/'.env')
        environments[bot] = env
        if bot == 'ETFEnhancer':
            keys, secrets = ('API_KEY',), ('SECRET_KEY',)
        elif bot in ('ccexchange', 'ETFEnhancerLT', 'momentum_master'):
            keys, secrets = ('ALPACA_API_KEY',), ('ALPACA_SECRET_KEY',)
        else:
            keys = ('APCA_API_KEY_ID', 'ALPACA_API_KEY', 'API_KEY')
            secrets = ('APCA_API_SECRET_KEY', 'ALPACA_SECRET_KEY', 'SECRET_KEY')
        key = next((env[k].strip() for k in keys if env.get(k)), '')
        secret = next((env[k].strip() for k in secrets if env.get(k)), '')
        paper = env.get('PAPER_TRADING' if bot == 'ccexchange' else 'ALPACA_PAPER', 'true').lower() in ('true', '1', 'yes')
        if bot == 'ETFEnhancerLT':
            paper = env.get('ETFENHANCERLT_PAPER_TRADING', 'true').lower() in ('true', '1', 'yes')
        if not key or not secret or '${' in key or '${' in secret:
            membership[bot] = None
            continue
        fingerprint = hashlib.sha256(f'{paper}:{key}'.encode()).hexdigest()
        if fingerprint not in accounts:
            label = f"alpaca_{'paper' if paper else 'live'}_{len(accounts)+1}"
            accounts[fingerprint] = dict(label=label, paper=paper, key=key, secret=secret, bots=[])
        account = accounts[fingerprint]
        account['bots'].append(bot)
        membership[bot] = account['label']
    return list(accounts.values()), environments, membership
