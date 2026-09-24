# BotMonitor

A local, read-only dashboard for the eight neighboring trading bots. The project root is **`/home/stardustbreaker/MyBotz/monitorg`**. The application name is BotMonitor; no nested `BotMonitor/` directory is needed.

## Start

The virtual environment has already been created. Python 3.10+ is sufficient; no third-party packages, npm build, or CDN is required.

```bash
cd /home/stardustbreaker/MyBotz/monitorg
./venv/bin/python app.py
```

Open **http://127.0.0.1:8765**. Stop **BotMonitor only** with Ctrl+C in its terminal. Cron and trading bots operate independently.

On a fresh copy:

```bash
python3 -m venv venv
./venv/bin/python app.py
```

For local files/process inspection without Alpaca network requests:

```bash
BOTMONITOR_ALPACA=0 ./venv/bin/python app.py
```

The server deliberately binds to `127.0.0.1`. It does not offer a public bind option. Run it as the same Linux user as the bots so `/proc` inspection and ledger reads work. A PID-isolated container cannot report host bot processes accurately; run this application on the host alongside the repositories.

## What the dashboard shows

- Eight bot rows with process status, owned position count, executions today/month, and return columns.
- Selection by bot name or dropdown, with PIDs, source files, coverage, detailed positions, option metadata, executions, gross realized/unrealized/combined dollar P/L, and round trips where reconstructable.
- Separate, deduplicated Alpaca account cards, including positions whose bot ownership is uncertain.
- A real fill activity feed, automatic refresh, data-quality warnings, and actual monitoring history charts.
- N/A when ownership, quantity, capital history, or cost basis is not sufficiently reliable. A zero means an actual zero in the covered ledger, not missing data.

Summary counts are **N/A if any bot is unknown**. Each card also exposes a clearly labelled known subtotal and coverage count. Running bots is a process count, not a health or profitability score. Portfolio P/L is not aggregated because bot coverage is incomplete and periods differ. Percentages are never summed.

See [REPORT.md](REPORT.md) for the repository inspection, current limitations, verified metrics, and all 15 requested report items.

## Read-only isolation

BotMonitor never imports or invokes any trading repository's Python modules. It never launches, stops, signals, or schedules bots. It reads source files with stable-read checks. SQLite database and WAL files are copied to a temporary BotMonitor directory; only those copies are opened by SQLite with `query_only` enabled. No lock, schema migration, or write is issued against a bot database. Active source changes trigger bounded retries and then a visible error.

Only BotMonitor's own `data/` and temporary copies are written. Its GET-only Alpaca transport has fixed HTTPS hosts and an endpoint allowlist: account, positions, FILL activity, and individual order lookup for validation. Redirects are refused. There are no submit/replace/cancel/close methods or trading-action web endpoints. POST, PUT, PATCH, and DELETE return 405. Local Host validation, no CORS permission, output escaping, and a restrictive Content Security Policy protect the local UI.

Existing `.env` files are parsed as text, never sourced or executed. Credential names follow the inspected bot configurations. Exported environment variables take precedence, as they do in the bot configurations. Credentials are held in memory and never returned by the dashboard, written to the account registry, or printed in validation output. Bot-specific environment variables exported by a separate cron job are not visible to BotMonitor; use equivalent configuration when running it.

## Counting and performance definitions

**Execution count:** one distinct order ID with positive confirmed filled quantity, counted at its first confirmed fill time. BUY + SELL = **2**. Partial fills of one order count once, including a partly filled order that later cancels. Signal, SKIP, submission, rejected/unfilled order, snapshot, synthetic legacy adoption, backtest, and expiration/assignment events are not executions. Detail rows can show individual incremental fill records, so their row count need not equal the headline order count.

Each order uses its earliest recorded fill timestamp, upgraded to broker activity time when order ID, symbol, side, and complete filled quantity match. `sell_short` activities normalize to `sell`. Verified activity records are cached locally and deduplicated by account identity plus activity ID. Broker records verify local ownership; they are never imported wholesale as a bot's trades. Unresolved estimated timestamps make day/month counts N/A but do not erase known total order counts.

Periods use **America/New_York** by default for every asset, including crypto. Timestamp offsets are honored; naive legacy timestamps are interpreted as America/Detroit based on this host and the inspected logging code. Ambiguous DST wall times fail closed. There is no trading-day/weekend filter. Configure the source timezone if the original logging host used another timezone.

**Gross realized P/L:** for an attributable long closing fill, `(exit premium/price − average entry premium/price) × quantity × multiplier`; for a short closing fill, `(average opening credit − closing premium) × quantity × multiplier`. The multiplier is 100 for standard OCC option contracts and 1 for shares/crypto. Weighted average cost matches the options event-ledger convention. Unmatched closing quantities invalidate reconstructed P/L. options_secured's durable `pnl` table supplies realized results, including confirmed lifecycle events.

**Unrealized P/L:** `(broker current price − bot entry price) × signed owned quantity × multiplier`. The denominator for a position's unrealized percentage is `abs(entry price × quantity × multiplier)`. This is a position cost-basis return, **not** a bot daily/monthly return. Prices are used only when broker holdings support the local quantity; overlapping bot claims are flagged. No missing position is assumed worthless. A known empty ownership ledger has zero unrealized P/L.

**Combined P/L:** gross realized + unrealized, only when both are known and their coverage is compatible. ETFEnhancer's older retained entry bases do not establish a clean 2026-08-21 equity baseline, so its combined P/L is withheld. Fees, dividends, deposits, assignments, and external position changes require explicit ledger support; gross execution P/L is not an audited net account return.

**Completed round trips:** a reconstructed symbol position returns to zero after matched opening/closing fills. Partial exits do not increment this count. This is available-ledger coverage, not guaranteed lifetime history.

**Today/month/total Trade ROI:** the dashboard now shows gross returns on matched closing quantities, as requested. Formula: `100 × sum(gross realized P/L) / sum(matched entry capital)` for closes in the selected Eastern-time calendar period. Stock, crypto and long-option capital is the cost of the quantity closed; standard options include the 100 multiplier. Cash-secured puts use `strike × contracts closed × 100` as gross collateral. Covered calls require matched underlying stock cost basis, which the current adapter does not establish; those returns remain unavailable. Partial closes contribute only the quantity closed. This is a capital-weighted return on closed trades, not a sum/average of trade percentages, a compounded portfolio return or a return on account equity. Reused capital counts again for each subsequent trade. Fees, unrealized P/L and cash distributions are excluded.

`—` means no matched closing executions in that period, so there is no return denominator. `0.00%` means a verified break-even close. `N/A` means attribution, cost basis, lifecycle or timestamps are insufficient. Total covers the adapter's stated ledger window, not guaranteed lifetime history. Detail views show the P/L numerator and capital denominator. Old mixed Momentum imports and ETFEnhancerLT backtests still do not produce returns.

**Whole-bot portfolio returns:** remain separate and unavailable without verified bot-level equity/cash-flow history. The API/SQLite `daily_return`, `monthly_return` and `total_return` fields retain their original portfolio meaning. New `trade_roi_today`, `trade_roi_month`, `trade_roi_total` fields hold the displayed Trade ROI; `trade_returns` contains per-period status and calculation evidence. Existing snapshots are preserved and are not relabeled as trade returns.

## Settings

Set these environment variables before launching:

| Variable | Default | Meaning |
|---|---|---|
| `BOTMONITOR_BOT_ROOT` | Parent of this project | Directory containing the eight repositories |
| `BOTMONITOR_PORT` | `8765` | Local HTTP port |
| `BOTMONITOR_REFRESH_SECONDS` | `10` | Process/source refresh; minimum 5 seconds |
| `BOTMONITOR_ACCOUNT_SECONDS` | `60` | Account/price/activity polling; minimum 30 seconds |
| `BOTMONITOR_SNAPSHOT_SECONDS` | `120` | Historical snapshot interval; minimum 60 seconds |
| `BOTMONITOR_STALE_SECONDS` | `86400` | File-age warning threshold; configurable for cron/weekends |
| `BOTMONITOR_TIMEZONE` | `America/New_York` | Dashboard day/month boundaries |
| `BOTMONITOR_SOURCE_TIMEZONE` | `America/Detroit` | Zone for naive source timestamps |
| `BOTMONITOR_ALPACA` | `1` | Use `0` for offline/local-only operation |

Local and account polling run separately. Network failures do not block process inspection. Erroring account reads clear current broker marks; stale readings older than three account intervals are not used for bot valuation. Configuration/credential changes take effect after restarting BotMonitor. Source file content is cached until its signature changes. Large SQLite databases are copied only when their database/WAL signatures change.

## Storage and history

`data/botmonitor.db` holds actual monitoring snapshots and verified broker fill activities. Snapshots contain timestamp, bot ID, positions, realized/unrealized P/L, equity if known, return fields, execution counts, and detailed provenance/warnings. Unknowns remain SQLite NULL / JSON null. `data/account_registry.json` contains account aliases and memberships, not credentials. `data/inspection.json` is generated by the one-shot check; `data/validation.json` records the independent options_secured audit.

History starts when this monitor runs. Existing backtests are not backfilled. A first snapshot can contain cumulative P/L from the current ledger, but is dated at observation time. Charts offer cumulative realized/unrealized P/L, equity where known, execution count, and daily/monthly **observed realized P/L changes**. Those changes are last minus first valid snapshot within the selected calendar bucket, require at least two samples, and are not a claim of full-day/month performance. Empty/unknown data produces gaps. Charts display at most the latest 2,000 snapshots per bot; storage is retained until you explicitly manage this monitor's database.

## Verification

```bash
./venv/bin/python -m unittest discover -v
./venv/bin/python app.py --check
./venv/bin/python scripts/verify.py
```

The check collects a single dashboard snapshot without opening a server. The audit script independently compares options_secured's SQLite rows against GET-only Alpaca order, fill, and position responses and saves its checks in `data/validation.json`. Its SPY option example is `(6.13 − 5.28) × 1 × 100 = $85` gross. Network access is required for these two online checks; failures are visible, not replaced with dummy values.

In Alpaca's paper dashboard, select the account belonging to the **options bots**, filter activity to FILL for September 2026, and check SPY261016P00741000 (sell 1 @ 6.13; buy 1 @ 5.28), XBI261016P00145000 (sell 1 @ 1.53), and XLF261016P00055000 (sell 1 @ 0.36). There are four execution orders and two remaining short contracts. Compare each immutable order ID and client-order prefix, not just symbols. Account activity may also contain other bots' orders; do not use its whole count as a bot count.

Alpaca reference: [account activities and pagination](https://docs.alpaca.markets/us/docs/account-activities), [Trading API activity endpoint](https://docs.alpaca.markets/us/reference/getaccountactivities-2). The broker response verified here uses `sell_short` for opening short-option activities.

## Known limits

Status proves a matching process exists; it does not prove the strategy loop is healthy. PID reuse is avoided by checking live command lines and paths, not trusting a stale PID file. A stopped bot is not labelled an unexpected crash without evidence about the cron schedule. A detected RUNNING→STOPPED transition is warned about, with scheduled intent left unknown. Data errors have a separate ERROR badge so a running trading process is not misrepresented as stopped.

No adjusted/nonstandard option deliverable is inferred: parsed OCC contracts use the standard multiplier 100. Unexpected adjusted contracts require an adapter extension with explicit deliverable/multiplier data before trusting exposure/P&L. New option settlement/assignment or stock-disposition records unsupported by an adapter produce unknowns and warnings. Full flow-adjusted returns, fee attribution, and complete lifetime history are deliberately deferred until the required evidence exists.


## Ownership reconciliation update

The September 17 broker audit resolves positions for ccexchange (0; BTC fee debits explain the fill remainder), momentum_master (2; verified CRWD/NVDA entries), and ETFEnhancerLT (0 attributable holdings). BotMonitor reads the audit baseline and the independent trading ownership registry read-only, and checks subsequent fills against broker quantities. Unreconciled changes remain N/A.

Unique trader IDs and account/instrument guards are installed in the eight bot repositories and `~/MyBotz/trading_ownership`. They load on the next cron restart. Trading has no dependency on BotMonitor. Details, backups and validation are in [the ownership repair report](maintenance/ownership_repair/README.md). Historic mixed trade imports and missing return baselines are not replaced with estimates.

## Additive strategy explainability

Bot Detail now also offers Trade Journal, Trade Inspector, and Signals / Decisions, while preserving the existing Overview and performance views. See [EXPLAINABILITY.md](EXPLAINABILITY.md) for delivered scope, all changed files, APIs, telemetry integration for the eight bots, historical limits, tests, and rollback. Optional bot-local decision events are stored separately in `data/explainability.db`; `BOTMONITOR_EXPLAIN=0` disables this layer.
