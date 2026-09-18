"""BotMonitor settings. Bot repositories are input only; never imported."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
BOT_ROOT = Path(os.getenv('BOTMONITOR_BOT_ROOT', str(ROOT.parent))).expanduser().resolve()
DATA_DIR = ROOT / 'data'
BOTS = ('ccexchange', 'ETFEnhancer', 'ETFEnhancerLT', 'momentum_master',
        'options_covered', 'options_secured', 'options_inverted', 'options_direct')
HOST = '127.0.0.1'
PORT = int(os.getenv('BOTMONITOR_PORT', '8765'))
REFRESH_SECONDS = max(5, int(os.getenv('BOTMONITOR_REFRESH_SECONDS', '10')))
SNAPSHOT_SECONDS = max(60, int(os.getenv('BOTMONITOR_SNAPSHOT_SECONDS', '120')))
ACCOUNT_SECONDS = max(30, int(os.getenv('BOTMONITOR_ACCOUNT_SECONDS', '60')))
STALE_SECONDS = max(60, int(os.getenv('BOTMONITOR_STALE_SECONDS', '86400')))
TIMEZONE = ZoneInfo(os.getenv('BOTMONITOR_TIMEZONE', 'America/New_York'))
SOURCE_TIMEZONE = ZoneInfo(os.getenv('BOTMONITOR_SOURCE_TIMEZONE', 'America/Detroit'))
ALPACA_ENABLED = os.getenv('BOTMONITOR_ALPACA', '1').lower() in ('1', 'true', 'yes')
