# BotMonitor implementation and inspection report

Implemented in `/home/stardustbreaker/MyBotz/monitorg`. Inspection and broker validation: **2026-09-16**, with the independent options_secured audit recorded at **21:53 UTC**. Figures below are observations, not promised future values. This is the original September 16 inspection. Later scheduling and ownership repairs are described below; historical figures remain dated observations.

## September 17 ownership repair update

The three previously unknown position counts now reconcile to **ccexchange 0, momentum_master 2 (CRWD/NVDA), and ETFEnhancerLT 0**. BTC fee activity exactly explains the 0.000479421 BTC remainder. Momentum entry order IDs, quantities and basis match the two broker holdings. All other account-1 holdings belong to ETFEnhancer; ETFEnhancerLT's account-wide CSV is not used as its inventory.

All eight bots now have an explicit trader identity and a shared-account ownership guard installed at their Alpaca client boundary. Existing strategy signals and capital settings were preserved. The guard is an independent `~/MyBotz/trading_ownership` package, so trading does not depend on BotMonitor. Bot source changes take effect at the next cron restart; no trading process was restarted or order modified during installation. Backups: `~/MyBotz/ownership_backups/20260917T170158Z`.

The guard excludes foreign holdings/orders, serializes reservations by exact instrument and account, preserves unique client-order prefixes, and blocks conflicting submits/replacements/cancellations. Different option contracts on the same underlying are allowed. Unknown intervening fills or unreliable broker data fail closed. This controls these eight bots; manual trading and other programs must be reconciled if they change their holdings.

Historical mixed Momentum counts/P&L and ETFEnhancerLT backtests remain excluded. Returns still require verified bot equity/cash-flow history. ccexchange realized P/L remains gross and combined P/L is withheld pending fee-adjusted accounting.

Validation: 619 existing bot tests in isolated copies with network connections disabled, 20 new guard tests, and 26 BotMonitor tests. Read-only deployment preflight assigned every current account holding and open order uniquely. See [ownership repair documentation](maintenance/ownership_repair/README.md), `deployment.json` and `dashboard_validation.json` in that directory.

The sections below preserve the original inspection and explain the source limitations; their September 16 N/A position observations are superseded by this update.


## 1. Existing logging/data formats

All eight repositories were inspected before adapter implementation, including launcher behavior, configuration, logging code, ledger files, and position/performance code.

| Bot | Existing source and meaning |
|---|---|
| ccexchange | `paper_data/fills.csv`: confirmed broker orders, deduplicated by order ID; `paper_data/orders.csv`, `order_updates.csv`, and `round_trips.csv`: order/research reporting; `state/bot_state.json`: owned crypto state; `logs/events.jsonl`: event audit; `paper_data/equity.csv`: **account** equity. `execution.py` filters broker orders using `ccexchange-`. |
| ETFEnhancer | `logs/trades_paper.csv`: headered environment/order-ID execution CSV; `logs/position_state_paper.json`: owned quantities, entry IDs/prices, stops; pivot-state JSON. Legacy `logs/trades.csv` is headerless and old state lacks quantities. Pre-isolation paper CSV includes option sales with stock-style P/L, so those rows are excluded. |
| ETFEnhancerLT | `logs/trades.csv`, `portfolio_history.csv`, benchmark/dividend/strategy CSVs are **2015–2025 backtest output**. `logs/live_portfolio_history.csv` and `live_positions.csv` are real but describe the **entire shared account**. Monitor-state JSON records decision scheduling, not bot inventory. |
| momentum_master | `logs/trades.csv`: rich execution CSV including IDs, fill times, entry/exit/P&L and signal metadata. `state/bot_state.json`: entry metadata, stops and pending exits, without owned quantities. `paper_trades.py` reconciles broker orders by allowed symbol, not bot order identity; imported account trades cannot safely establish bot ownership. Separate backtest CSV/JSON outputs are excluded. |
| options_covered | Authoritative `logs/trades.sqlite3`, with WAL: orders, incremental fills, events, explicit stock allocations/dispositions, settlements, equity samples and metadata. `trade_analytics.csv` is an export; `options_bot.log` is text. The currently deployed database predates the optional stock_orders/stock_fills tables present in newer code; the adapter accommodates that schema. |
| options_secured | `logs/options_secured.sqlite3`, with WAL: orders, incremental fills, short-put lots, realized `pnl`, settlements, events and equity samples. `trade_analytics.csv` exports closed results, so it is **not** the execution ledger. JSON performance reports and text logs also exist. One migrated fill is timestamped with its order creation time and marked `estimated_time=1`. |
| options_inverted | `logs/trade_analytics.csv`: event CSV with bot/strategy identity, order lifecycle, option symbol, quantity/premium and P/L fields. Text bot logs and JSON performance/research summaries. At inspection the active ledger contains 383 SKIP rows and no fills. |
| options_direct | `logs/trade_analytics.csv`: event CSV with `bot_id=long_call`, strategy variants, submissions/fills/snapshots/skips. Text logs, backtest/research CSVs, JSON baseline, and a capacity-research SQLite database. Only active attributable `ORDER_FILL` events contribute to counts. Archived ledgers and synthetic legacy adoption are excluded. |

## 2. Shared Alpaca accounts

Both groups were first detected by matching configured API keys without exposing them, then **confirmed by matching account IDs returned by Alpaca GET requests**:

- **alpaca_paper_1:** ccexchange, ETFEnhancer, ETFEnhancerLT, momentum_master.
- **alpaca_paper_2:** options_covered, options_secured, options_inverted, options_direct.

The account registry contains aliases/memberships only. Credentials stay in existing configuration files and application memory. One account is displayed once, regardless of the number of bots. Separate keys resolving to the same actual account are merged in the live view.

## 3. Currently reliable metrics

Counts mean orders with positive confirmed fills in the stated source coverage. P/L is **gross USD**, not a percentage. Quotes and running status can change immediately after inspection.

| Bot | Observed status | Owned positions | Today executions | September executions | Source-window total | Gross realized P/L |
|---|---|---:|---:|---:|---:|---:|
| ccexchange | STOPPED | N/A | 0 | 2 | 2 | −$336.92, matched quantities only; fees excluded |
| ETFEnhancer | RUNNING | 3 | 0 | 14 | 22 since 2026-08-21 | +$0.33 since 2026-08-21 |
| ETFEnhancerLT | STOPPED | N/A | N/A | N/A | N/A | N/A |
| momentum_master | RUNNING | N/A | N/A | N/A | N/A | N/A |
| options_covered | STOPPED | 0 | 0 | 0 | 0 | $0.00 in current ledger |
| options_secured | STOPPED | 2 | 0 | 4 | 4 | +$85.00 |
| options_inverted | STOPPED | 0 | 0 | 0 | 0 | $0.00 in active ledger |
| options_direct | RUNNING | 0 | 10 | 22 | 26 | +$16.00 in active ledger |

Unrealized P/L is available for ETFEnhancer's locally owned quantities when supported by broker positions/marks, and for options_secured's two short-put lots. It is zero for a known empty ledger. During the online check, options_secured unrealized P/L was **−$156.00**, making its gross combined P/L **−$71.00**; these are market-dependent observations, unlike the closed $85 result. ETFEnhancer combined P/L is withheld because realized coverage and retained entry bases differ.

Local-only mode leaves options_secured's period counts N/A until its estimated timestamp is verified online. Broker activity cached by a successful online refresh retains that evidence across month changes. Existing source coverage is never described as complete bot lifetime history.

## 4. Metrics still unavailable

- **Daily, MTD, and total bot return percentages for all eight bots:** complete period-aligned bot equity and cash-flow history is missing. Virtual capital settings and account snapshots are not adequate substitutes.
- **ETFEnhancerLT:** all bot execution, position and P/L metrics; existing live CSVs are account-wide and trades.csv is a backtest.
- **momentum_master:** all primary bot counts and P/L; account order imports, symbol overlap and absent owned quantities make attribution unsafe.
- **ccexchange current positions/unrealized/combined P/L:** state is flat, while fills retain `0.000479421 BTC` before explicit fee/dust reconciliation. This is flagged instead of declaring zero positions or attributing all account crypto.
- **True net P/L/lifetime returns:** incomplete fee/dividend/capital/lifecycle history and ledger cutoffs prevent audited lifetime calculations.
- **ETFEnhancer combined P/L:** legacy retained cost bases and the post-2026-08-21 realized window are not a common performance baseline.
- **Aggregate portfolio P/L:** incomplete ownership and differing source windows prevent a valid total. Percentages are never summed.

## 5. Suggested small logging improvements

These are recommendations only; no bot files were changed.

1. Give momentum_master and ETFEnhancerLT a unique client-order prefix and a durable bot-owned order/fill ledger. Reconciliation should preserve immutable order ownership rather than infer it from a symbol universe.
2. Persist signed owned quantity, basis, broker order/activity IDs, and acquisition time for every bot lot. Distinguish externally allocated positions from execution history.
3. Log actual broker fill timestamps, unique activity IDs, incremental quantities, fees and corrections; keep account reconciliation separate from bot logs. Preserve explicit offset-aware UTC timestamps.
4. Record bot-level cash allocation, external flows, realized P/L, marked holdings and valuation time at inception and period boundaries. Keep virtual allocation assumptions versioned and explicit.
5. For crypto, record asset-denominated fees/dust adjustments. For options, record confirmed assignments, expirations, exercises and any resulting stock lots, with multiplier/deliverable metadata.
6. Preserve environment and bot identity across rotations and archives; maintain a coverage/inception marker. Store a heartbeat/last successful cycle independently of trade activity so a quiet strategy is not mistaken for a stale process.

## 6. Files created

- Entry/configuration: `app.py`, `config.py`, `requirements.txt`, `.gitignore`.
- Documentation: `README.md`, `REPORT.md`.
- Normalized models: `models/__init__.py`, `models/records.py`.
- Adapters: `adapters/__init__.py`, `base.py`, `registry.py`, `ccexchange.py`, `etf_enhancer.py`, `etf_enhancer_lt.py`, `momentum_master.py`, `options_covered.py`, `options_secured.py`, `options_inverted.py`, `options_direct.py`, `options_events.py`.
- Services: `services/__init__.py`, `account_registry.py`, `alpaca_reader.py`, `source_reader.py`, `process_monitor.py`, `trade_service.py`, `performance_service.py`, `snapshot_store.py`, `monitor.py`.
- Interface: `templates/index.html`, `static/style.css`, `static/app.js`.
- Validation: `tests/__init__.py`, `tests/test_monitor.py`, `scripts/verify.py`.
- Local runtime: `venv/`, `data/.gitkeep`, `data/botmonitor.db`, `data/account_registry.json`, `data/inspection.json`, `data/validation.json`. Runtime data and the virtual environment are ignored by Git.

## 7. Exact startup command

```bash
cd /home/stardustbreaker/MyBotz/monitorg
./venv/bin/python app.py
```

## 8. Local dashboard address

**http://127.0.0.1:8765**

BotMonitor binds to loopback only. No bot-control or trading endpoints exist.

## 9. RUNNING status determination

Inspect Linux `/proc` for same-user, non-zombie Python processes executing `launcher.py`, `main.py`, or `monitor.py` in the exact bot repository. Relative script paths are resolved against that process's working directory. Backtest commands, arbitrary Python `-c`/`-m` commands, unrelated paths and incidental arguments are excluded. Both launcher and child PIDs can be shown.

A matching process means RUNNING. No match means STOPPED when inspection is complete; inaccessible process details mean UNKNOWN. Monitoring/parsing failures have a separate ERROR badge rather than incorrectly claiming that a live trading process is stopped. RUNNING→STOPPED transitions are flagged, but expected cron timing is not invented. Stale crash logs are not treated as proof of a current crash. No PID file is trusted without checking the actual process.

## 10. Trade attribution

Adapters use each repository's actual authoritative sources. ccexchange's fill CSV originates from its `ccexchange-` broker filter. ETFEnhancer uses its environment-scoped post-isolation order ledger. Options SQLite fills must reference owned orders with matching bot prefixes (`covered_call_`, `covered_stock_`, `cash_secured_put_`, or the verified legacy `os-`). Long-call/long-put CSV events must have compatible identity and contract type. Unknown/foreign/legacy synthetic records are excluded or flagged.

Alpaca activity verifies an already attributed immutable order ID; it never turns every account fill into a bot trade. Duplicate IDs across purportedly reliable owners make attribution unknown. momentum_master account imports and ETFEnhancerLT backtests do not enter the activity feed or bot aggregates.

## 11. Position attribution

ETFEnhancer uses explicit local state quantities and entry IDs. options_secured uses its SQLite short-put lots. options_covered uses reconstructed option fills and explicit stock allocations. Long-call/put strategies reconstruct net signed quantities from their own events; unconfirmed missing positions are not invented sales/expirations. ccexchange's contradictory state/fill inventory is currently unknown. momentum_master and ETFEnhancerLT have no safe quantity attribution.

Where broker data is available, local claimed quantities must fit the broker position's sign and size before it supplies marks. Multiple bots claiming the same account symbol trigger uncertainty. Unattributed account positions remain visible separately. Offline local positions are explicitly labelled last-known local state, with source times and stale-data warnings.

## 12. Exact definition of “trade”

**One distinct order with positive confirmed filled quantity**, dated at its first recorded/verified fill. A buy followed by a sell is **two execution orders**, not one. Multiple partial fills of the same order count once. Completed round trips are a separate matched-inventory statistic. Signals, submissions, failed/unfilled orders, snapshots, backtests, synthetic adoptions, assignments and expirations are not order executions.

Period boundaries use the configured timezone for equities, options and crypto consistently. Legacy local timestamps are interpreted in America/Detroit; explicit offsets take precedence. Unresolved estimated/ambiguous timestamps do not populate period counts.

## 13. Exact daily/monthly/total return formulas

**No return percentage is currently populated.** Each active adapter returns N/A because it lacks verified bot-specific period boundary equity and complete flow history.

The guarded no-flow helper is `100 × (E_end / E_start − 1)`, requiring `E_start > 0`. Daily would use the start of the current local day, MTD the start of the local month, and total a verified bot inception baseline. A nonzero external flow invalidates this helper. Neither that helper nor any account-equity ratio is used to manufacture current dashboard values. Time-weighted/flow-adjusted return calculation is deferred pending the required data.

Dollar P/L formulas are implemented: long realized `(exit − average entry) × qty × multiplier`; short realized `(average credit − exit) × qty × multiplier`; unrealized `(current − entry) × signed qty × multiplier`. Standard options use 100, stock/crypto use 1. Adjusted option roots require explicit deliverable metadata and fail closed. Position unrealized percentage is `100 × unrealized dollars / abs(entry × qty × multiplier)` and is labelled separately from bot returns.

## 14. Double-counting and data-quality problems discovered

- Two shared accounts must not be summed once for every associated bot.
- ETFEnhancerLT live snapshots contain **other bots' holdings**, and its trades.csv is a backtest.
- momentum_master's reconciler can import foreign orders by symbol. Its stop state includes **SCHD/XLB**, which are also in ETFEnhancer state. A symbol match does not prove exclusive ownership.
- Old ETFEnhancer logs contain option rows and stock-style option P/L. The pre-isolation records are not trusted for current bot performance.
- Options event files contain many SKIP, snapshot and submission rows. Counting CSV rows would wildly inflate executions. options_secured's one-row CSV export represents a closed result, whereas its database contains four execution orders.
- Partial fills, repeated observations, archives, synthetic adoption, cumulative order quantities, and settlement events can inflate counts if mixed. These are handled separately.
- ccexchange bought `0.191768020 BTC` and sold `0.191288599 BTC`; silently rounding away the difference or assuming the residual is an open owned position would be unsafe without fee reconciliation.
- Different ledger start dates and retained older position bases do not support a single aggregate “total return.”

## 15. Manual verification against Alpaca

The independent script reads SQLite copies and makes **GET-only** account, positions, individual-order and paginated FILL requests. It compares immutable client/broker identities, side, quantity, price and position ownership. Run:

```bash
./venv/bin/python scripts/verify.py
```

The recorded audit passed every check:

| options_secured transaction | Quantity | Broker premium |
|---|---:|---:|
| SELL SPY261016P00741000 | 1 | $6.13 |
| BUY SPY261016P00741000 | 1 | $5.28 |
| SELL XBI261016P00145000 | 1 | $1.53 |
| SELL XLF261016P00055000 | 1 | $0.36 |

Alpaca labels opening short activities `sell_short`; order-side metadata is `sell`. The adapter explicitly normalizes this verified difference. September has **4** execution orders, September 16 has **0**, and the broker confirms remaining quantities **−1 XBI put and −1 XLF put**. Closed SPY gross P/L is `(6.13 − 5.28) × 100 = $85`, matching the SQLite `pnl` record. Results are saved in `data/validation.json`.

For a visual check, open the options paper account in Alpaca, filter activity to the same timezone/date range and FILL events, and match these symbols and order IDs. Do not count every account order as options_secured activity. For other bots, use the same order-ID comparison with their authoritative local ledger and its documented coverage. Network or attribution failures remain visible as N/A.

All **20 automated tests passed**. Tests cover option multipliers/adjusted contracts, short and partial-close P/L, crypto, duplicate orders, timezone/month boundaries, ambiguous DST, fractional broker timestamps, estimated dates, read-only WAL copying, malformed CSV, process path matching, null snapshots, synthetic-event exclusion, and HTTP mutation/Host rejection. The live dashboard was also checked with actual host process visibility and read-only broker data.

## September 18 monitoring repair

An unresolved Momentum NVDA request returned HTTP 404 from the client-order lookup. The monitor incorrectly converted that lookup failure into an account-wide ownership error, blanking position reconciliation for ccexchange, ETFEnhancerLT and momentum_master. Lookup failures now produce an owner-specific warning; positions still require independently matching fills, registry ownership and broker quantities. Trading reservations are not removed or altered.

The live read-only check verifies Momentum's two positions and ETFEnhancerLT's zero positions. ccexchange's registered LINK buy is now included from broker fill activities while its hourly CSV catches up: five partial fills count as one order (one execution today, three this month at validation). Its gross LINK fills total 781.102370935, versus broker inventory 779.149615007. Both crypto fee endpoints returned no new fee records. The monitor explicitly reports that discrepancy and leaves its position attribution N/A until documented fees or other activity reconcile it; it does not assume a fee percentage.

Historical Momentum/ETFEnhancerLT trade counts and returns remain unavailable for the reasons documented above. Snapshot storage now uses WAL and closes connections explicitly to prevent chart reads blocking monitoring writes. Validation: 32 monitoring tests passed, followed by live GET-only verification. Only BotMonitor was restarted; no orders, trading strategies or trading reservations were changed.

## Completed-trade return display — September 18

At the user's request, the primary percentage columns now display **Today / Month / Total Trade ROI** where completed-trade data is reliable. The calculation is `100 × summed gross realized P/L / summed matched entry capital`. Long stocks, crypto and options use the cost of the quantity closed, including option multipliers; cash-secured puts use gross strike collateral. Partial closes count only their matched quantity. Unmatched covered-call collateral, unreliable history and unresolved lifecycle accounting remain N/A. No closes displays a dash; verified break-even closes display 0.00%.

These metrics exclude fees and unrealized P/L. They are not whole-bot portfolio returns, and capital reused across trades is counted for each trade. Total means the available ledger window. The detail view exposes the P/L numerator and capital denominator. Original portfolio-return fields retain their meaning; three separate Trade ROI snapshot columns are migrated without relabeling or deleting old history. A Trade ROI history chart is available.

Independent manual validation of options_secured: the SPY close earned $85 on $74,100 strike collateral; the XLF close lost $34 on $5,500 collateral. Total gross closed-trade ROI is $51 / $79,600 × 100 = 0.0640703518%. See `maintenance/return_repair/validation.json`. Tests cover weighted aggregation, partial closes, option multipliers/collateral, timestamp corrections, no-close versus break-even periods, missing basis and migration of historical snapshots.
