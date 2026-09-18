#!/bin/bash
set -euo pipefail
BASE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--check" ]]; then
    exec /usr/bin/python3 "$BASE/market_bot_scheduler.py" check
fi
if (( $# )); then echo "Usage: $0 [--check]" >&2; exit 2; fi
exec /usr/bin/python3 "$BASE/market_bot_scheduler.py" start
