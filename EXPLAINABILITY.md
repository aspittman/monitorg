# MonitorG explainability upgrade — phase 1 / 2 with selected phase 3 features

This is an additive upgrade to the existing BotMonitor/MonitorG application. Bot Overview, its click-to-select workflow, the bot dropdown, all existing Bot Detail metrics/positions/executions, performance history, shared-account cards, and the activity feed remain. No trading repository, strategy, broker permissions, scheduler, or running service was changed or restarted by this upgrade.

## Architecture inspected

- `app.py`: Python standard-library threaded HTTP server, localhost only; existing GET dashboard, bootstrap, monitoring history, health, and static routes. Mutations remain HTTP 405.
- `config.py`, `adapters/registry.py`: eight explicit bot IDs, not filesystem auto-discovery. `account_registry.py` groups credential configurations; `process_monitor.py` inspects matching same-user processes.
- `services/monitor.py`: local adapter refresh and independent GET-only Alpaca polling. Ownership reconciliation precedes presentation. Unreliable histories stay excluded.
- `adapters/*`: CSV, JSON, and copied SQLite/WAL source readers. Bot Python modules are never imported or executed. Existing source caching, account reconciliation, and performance formulas remain.
- `services/performance_service.py`: existing average-cost matched-close P/L and capital-weighted Trade ROI; snapshots are actual observations, not historical market bars.
- `services/snapshot_store.py`: existing `data/botmonitor.db`, snapshots and broker-fill cache. This upgrade does not migrate or relabel those tables.
- `templates/index.html`, `static/app.js`, `static/style.css`: existing plain JavaScript UI and canvas performance chart; no frontend framework or build dependency.
- Existing tests and maintenance/ownership/return-repair reports were consulted. Pre-existing uncommitted changes were preserved.

## Delivered functionality

Four tabs inside existing Bot Detail: **Overview**, **Trade Journal**, **Trade Inspector**, **Signals / Decisions**. The bot dropdown is retained. The original detail DOM remains the Overview; existing charts/analytics remain in their original locations.

- Journal includes attributable position cycles, partial exits, and current owned positions with missing historical entries. Newest/oldest, exact symbol, entry-date UTC range, and winners/losers filters; 50-row pages. Outcomes use realized gross P/L, including partial closes; they are not mark-to-market outcomes. No reason filter yet.
- Cycles use the established average-cost convention, grouped by bot and instrument, not fictitious individual lots. Multiple setups sharing an instrument may be pooled. Entry/exit prices are weighted averages; markers use individual actual fills. Short puts use strike collateral; covered-call percentage returns remain unavailable without underlying capital basis.
- Inspector provides recorded entry/exit reasons where available, all reported conditions including failures and optional rules, actual/threshold values, risk, current ownership/marks, underlying/option information, contract-selection evidence, and raw event evidence.
- Timeline and step-through replay are paginated. Charts show discrete price samples, actual fills, explicitly scoped stop steps, and only indicators explicitly designated by the bot for a price overlay. No synthetic candles or interpolated market price path. Snapshot timestamps remain visible; a current broker mark does not refresh old strategy indicators.
- `RECORDED`, `RECONSTRUCTED`, and `INCOMPLETE` provenance. Ledger-derived trade grouping is identified as fill-ledger reconstruction, not a reconstructed historical strategy decision. Reconstructed event points are hollow on charts.
- Conservative audits validate the bot's exported rules, not a second strategy implementation. `VALID` means the displayed recorded snapshot is internally consistent; it does not independently certify the strategy, broker execution, or complete trade. Incomplete or reconstructed rules cannot yield a rule-violation finding. Audits explicitly cover the loaded event page.
- A possible missed trade requires explicit completed-evaluation, capital, risk, and no-submission evidence. Missing events alone are never evidence that an order failed or a trade was missed. Explicit rejected/cancelled/expired order outcomes are shown without assuming zero partial fills.
- Existing direct/inverted option SKIP/order/fill reasons are imported incrementally. A legacy SKIP is not proof that a valid signal existed. Legacy row timestamps are logging times. Identical legacy CSV rows are content-deduplicated because those formats have no stable event IDs.
- Telemetry-only `POSITION_OPENED`/`POSITION_CLOSED` lifecycles are displayed as **REPORTED OPEN/CLOSED**, without manufacturing broker fills, P/L, or verified ownership.

Use **Refresh detail** to reload a journal, signal page, or inspector. Existing dashboard auto-refresh continues independently so replay selection and filters are not reset every refresh. Switching bots returns to familiar Overview and clears the previous inspector. Slow legacy imports show progress.

## Files added

| File | Purpose |
|---|---|
| `models/decision_event.py` | Version 1 event validation and supported lifecycle types |
| `services/explain_store.py` | Separate SQLite storage, indexes, bounded JSONL ingestion, pagination |
| `services/explain_service.py` | Journal reconstruction, legacy event adapter, explicit-ID linkage, audits and evidence checks |
| `static/explain.js` | Additive detail tabs, journal filters, inspector, signals, chart/replay |
| `telemetry/monitor_event.py` | Standalone optional nonblocking bot-side writer |
| `tests/test_explainability.py` | Schema, ingestion, journal, audit, isolation, lifecycle, HTTP tests |
| `tests/explain_ui.cjs` | DOM rendering/navigation tests using the host's installed jsdom |
| `EXPLAINABILITY.md` | Integration contract, implementation scope, validation and rollback |

## Files modified by this upgrade

- `app.py`: three read-only endpoints and the explainability script route.
- `config.py`: `BOTMONITOR_EXPLAIN` feature switch (default `1`).
- `services/monitor.py`: initialize isolated storage; bounded event ingestion and cached journal updates after final ownership checks; isolate errors per step.
- `adapters/etf_enhancer.py`: retain the existing CSV's entry/exit `reason` alongside a fill.
- `static/app.js`: notify the added UI when selected-bot detail renders.
- `templates/index.html`: script include, detail navigation, separate added content container.
- `static/style.css`: scoped styles using the existing palette and controls.
- `README.md`: link to this upgrade guide.

Other modified/untracked files already present in the working tree, including return and ownership repairs, are not part of this upgrade. Do not use a whole-tree reset to roll it back.

## Storage and APIs

New runtime file: **`data/explainability.db`** (with SQLite WAL/SHM sidecars). It is separate from `botmonitor.db` and ignored by Git. Tables:

- `events`: immutable `(bot_id, event_id)` uniqueness; trade/decision/order IDs, symbol, normalized UTC timestamp, event type, original validated snapshot payload. Indexes on bot plus trade, decision, order, symbol, timestamp, and event type.
- `cursors`: JSONL inode/offset and rejected count; oversized-record continuation state.
- `legacy_cursors`: CSV inode/offset, header, rejected count.
- `journal`: rebuildable position-cycle summaries and fill evidence, keyed by bot/trade; bot/time and bot/symbol/time indexes.

Initialization is idempotent. Exact duplicates are ignored; conflicting duplicate IDs are rejected without overwriting the original. Ingestion progress and accepted events commit together. Partial final records are retried. JSONL reads are capped at 500 chunks and approximately 1 MiB per refresh per bot; records are limited to 64 KiB. Legacy CSV imports are capped at 500 records and approximately 1 MiB, with quoted-newline support. An oversized legacy record fails that optional import visibly, while journal and normal monitoring continue. Initial imports may take many refreshes. Source truncation/rename rotation resets the cursor, with event deduplication preserving history. Use rename rotation, not in-place rewriting of previously imported content. Retain rotated files until MonitorG has caught up; unread events in removed rotations cannot be recovered automatically.

Journal updates are fingerprint-cached and transactional; requests are paginated (default 50, maximum 200). Retention is explicit: there is no automatic event deletion. The phase does not promise constant-time ingestion of arbitrarily large trade ledgers; existing adapters still read/cache their own full ledgers. Monitor disk usage and archive deliberately.

New GET endpoints, all retaining localhost Host validation and existing CSP:

- `/api/journal?bot=options_direct&limit=50&offset=0&sort=newest&symbol=SPY261016C00741000&from=2026-09-01&to=2026-09-30&outcome=winners`
- `/api/inspector?bot=options_direct&trade=<journal trade_id>&limit=50&offset=0`
- `/api/decisions?bot=options_direct&limit=50&offset=0`

Unknown bots/invalid pagination return 400; unknown trades return 404; unavailable explainability returns 503. Existing APIs continue operating. There is **no telemetry HTTP POST endpoint**, broker mutation endpoint, or new trading authority.

## Bot telemetry contract and exact integration steps

MonitorG reads `<BOTMONITOR_BOT_ROOT>/<configured_bot_id>/logs/monitor_events.jsonl` as an optional input. Bots append locally; MonitorG does not write to bot directories. Old bots need no changes.

For each upgraded bot:

1. Copy `telemetry/monitor_event.py` into that bot's repository; never import MonitorG as a runtime dependency. Construct `MonitorEvents` once using an absolute bot-local log path, the exact configured bot ID, and the implemented strategy/version name. Wrap optional construction/calls so telemetry failure cannot alter the trading path.
2. Allocate a unique `decision_id` per evaluation and durable `trade_id` per position lifecycle; persist the latter in the bot's own position state and restore it on restart. Reuse them through contract selection, order attempts, partial fills, management, and exit. Include actual immutable broker `order_id` once known. Do not generate a new event ID when retrying delivery of the same event.
3. At the existing rule evaluation, export the already-computed actual values, thresholds, required/optional classification, **including failed and unknown conditions**, strategy/config version, market timestamp, regime, capital/risk gates, and the actual decision/reason. Export stop and sizing snapshots at this point, not current values reconstructed later. Do not independently recompute rules for MonitorG.
4. Emit order-submitted/accepted/rejected/cancelled/expired and incremental fill events at the actual existing execution callbacks. Submission is not acceptance or fill. Preserve order/fill identity and quantity semantics in extra fields.
5. Emit position-opened, meaningful position/stop updates, exit evaluation/decision/order/fill and closed events. For options include underlying and premium as distinct snapshots; record original quote/Greek timestamps and actual selection/rejection evidence. Missing fields remain omitted/null.
6. Only set `conditions_complete: true` if the snapshot contains the full applicable rule set. Only declare pipeline `evaluation_complete` when evaluation and submission handling actually finished. If an exit uses “any trigger”, explicitly report `exit_policy: "ANY_TRIGGER"`; other exit-policy audits remain incomplete in this phase.
7. Keep telemetry best-effort: the helper uses a bounded nonblocking queue, a daemon writer and a public `dropped` counter. It does not call MonitorG or Alpaca, retry orders, or wait for delivery. Queue-full, filesystem and serialization failures return false/drop telemetry. Graceful shutdown delivery is not guaranteed. Log/sample the drop counter through the bot's own existing logger if desired; never make trading wait for a telemetry flush. One writer per bot log is recommended.

Example **synthetic integration example, not a historical trade**:

```python
from monitor_event import MonitorEvents
telemetry = MonitorEvents('/absolute/bot/path/logs/monitor_events.jsonl',
                          'ETFEnhancer', 'implemented-strategy-version')

# Values below must come from this exact execution's existing evaluation.
telemetry.emit(
    'ENTRY_DECISION', symbol,
    trade_id=persisted_trade_id, decision_id=evaluation_id,
    decision=actual_decision, reason=actual_reason,
    conditions=exported_existing_rule_results,
    conditions_complete=complete_snapshot,
    market={'symbol': symbol, 'price': decision_price,
            'observed_at': market_data_timestamp},
    risk={'initial_stop': initial_stop, 'price_basis': 'underlying',
          'capital_available': available_capital},
)
```

The helper supplies `schema_version: 1`, a UUID event ID, bot/strategy identity, offset-aware UTC timestamp, and `RECORDED` provenance. Explicit timestamps can preserve the actual decision time. Rich snapshots are JSON objects; do not include credentials, account secrets, entire dataframes, or per-second market dumps.

Condition contract:

```json
{"name":"implemented_rule_name","label":"Bot's rule label","required":true,
 "passed":false,"actual":123.4,"threshold":125.0}
```

`required`/`passed` accept true, false, or null; missing classification is unknown, not optional. Optional metadata objects: `market`, `risk`, `indicators`, `position`, `option`, `contract_selection`, `pipeline`. Names/fields inside these are strategy-specific. `risk.price_basis` is `underlying` or `option` when charting `initial_stop`/`current_stop`. An indicator is plotted only if its object has `overlay: true`, a matching `price_basis`, and a numeric `value`; oscillators stay in the snapshot rather than sharing a price axis.

Example indicator metadata: `{"ema20":{"value":245.1,"overlay":true,"price_basis":"underlying"}}`. An options snapshot may contain bid/ask/mid/spread, strike, expiration, DTE-at-entry, side, quantity, Greeks, IV, volume and open interest **only when recorded**. Contract selection may include candidate count, selected contract, each rule's result, and rejected candidates/reasons; the generic details view preserves this data. It is not a dedicated ranked-candidate comparison UI yet.

Externally reconstructed events must use `provenance: "RECONSTRUCTED"` and a `source` describing the historical inputs/method. MonitorG does not currently fetch historical market bars or reconstruct indicators. Allowed event types are defined in `models/decision_event.py`; unrecognized versions/types or wrong bot identities are rejected.

## Current bot coverage and required hooks

Read-only local inspection on September 22, 2026; these are capabilities, not claims of complete lifetime history. All eight need richer decision telemetry for full rule audits.

| Bot | Existing usable evidence | Exact future instrumentation points |
|---|---|---|
| `ccexchange` | Attributable `paper_data/fills.csv`, current state, existing audit JSONL. Crypto fees can leave ledger remnants unreconciled; no fabricated close. | Export actual rules/scores/regime/risk decisions in `src/ccexchange/runtime.py:run_cycle` and `_risk_block`; lifecycle events at execution/reconciliation in `execution.py` / `runtime.py:_reconcile`; persist trade IDs in state and record crypto-fee effects separately. Existing `audit.py` can forward normalized snapshots. |
| `ETFEnhancer` | Post-isolation `logs/trades_<mode>.csv`, entry/exit reason, current position/pivot state. This upgrade retains its CSV reason. | Export rules from `strategy.py:signal_from_row`/`check_signal`; entry/exit snapshots in `trader.py:place_trade`; actual stop changes in `check_atr_trailing_stop`, `check_dynamic_midpoint_stop`, `check_structural_midpoint_stop`; correlate `wait_for_order_fill` and persisted position entry IDs. Never present current pivot state as old entry state. |
| `ETFEnhancerLT` | Adapter deliberately excludes account-wide live CSV and backtests; audited ownership may provide current positions when online. | Add bot-owned fill/order history and durable lifecycle IDs at `brokerage/alpaca_client.py` and the live strategy/monitor loop; export actual implemented entry/exit/structural rules there. Do not feed backtest output into execution telemetry. |
| `momentum_master` | Rich `trade_logger.py` schema includes reasons, scores, EMA/MACD/relative-strength/volume/ATR and execution quality, but mixed-account legacy attribution remains unsafe. Current positions may be verified by existing ownership reconciliation. | Instrument `strategy.py:evaluate_prepared_symbol` before early returns so failed conditions survive; export existing `signals.py:momentum_exit_decision` result; correlate `trader.py` entry/exit/protective-stop and reconciliation callbacks; persist owned quantity/trade IDs. First ensure imported historical rows have immutable bot ownership; rich fields alone do not make them attributable. |
| `options_covered` | Owned SQLite fills, stock allocations, lifecycle/settlement limitations; no full decision snapshots. | Instrument actual `strategy.py:signal`/`sideways`, contract selection and `broker.py` execution callbacks; include stock/call leg linkage, covered-stock basis, collateral, quote and stop snapshots. Preserve settlement/assignment semantics. |
| `options_secured` | Owned SQLite fills/lots/P&L, short-put metadata and collateral; some fill timestamps need existing broker verification. | Export `strategy.py:entry_at`, `regime_at`, `exit_reason` and actual risk/contract decisions in `options_trader.py`; record premium, strike collateral, liquidity/capital gates, all rejected candidates if evaluated, fill IDs, and settlement/assignment events without pretending assignment is a sale. |
| `options_inverted` | Active owned long-put event ledger; skip/submission/fill reasons are now incrementally visible. No complete required/optional rule set. | Extend `analytics.py:record_event`; emit normalized snapshots from `options_trader.py:get_option_contract`, `buy_option_contract`, `close_strategy_lot` and position/stop management; include candidate outcomes, low-water underlying stop and separate option stop, actual strategy-variant IDs. |
| `options_direct` | Active owned long-call event ledger; same incremental reason/order coverage. Rejected-trade CSV and rich selection text exist but are not treated as complete snapshots. | Extend `analytics.py:record_event` and existing option-selection/entry/exit/management code in `options_trader.py`; carry actual strategy variant, stable trade/decision/order IDs, high-water underlying/option stops, candidates, quotes, Greeks, capital/risk gates. |

No bot instrumentation was installed as part of this phase. None currently emits this new standard merely because MonitorG was upgraded. MonitorG remains useful without it.

## Historical limits and deferred work

Never-recorded decision-time indicators, failed rules, changing stops, option quotes/Greeks/candidate sets, capital/risk state, market regime, and exact entry time of an adopted position cannot be recovered from fills or today's values. Logging time is not automatically broker fill time. Backtests and shared-account history are not bot executions. Existing historical missing-data warnings are retained.

Deferred: dedicated reason/outcome aggregate analytics, performance by decision type, general sequence/timeout/quantity/duplicate-entry/stop-direction anomaly engine, complete cross-page trade audit, native adapters for every legacy rich log, a dedicated options-candidate comparison view, historical market-data reconstruction, and external bot instrumentation/deployment. These require better coverage and/or additional strategy-specific semantics; this phase does not claim to complete priorities 3 and 4.

## Verification and rollback

Run from the MonitorG root:

```bash
python3 -m unittest discover -v
node --harmony-optional-chaining --harmony-nullish tests/explain_ui.cjs
```

The Node flags support the host's Node 12 parser; current Node versions can run the script without them. UI tests use the already-installed `jsdom`; this is a test dependency only, not a new runtime dependency. Python HTTP tests need localhost socket access. No tests submit orders or use live broker credentials.

Validation on September 22, 2026: **65 Python tests passed**, DOM rendering and combined-production-script integration checks passed, Python compilation/JavaScript syntax checks passed, and `git diff --check` passed. The DOM harness includes a test-only callback-identity compatibility shim for mismatched components in this host's installed jsdom; no production event handling was changed for it. An offline read-only smoke check of all eight bot adapters completed without explainability errors; a subsequent refresh with bounded imports took about 0.26 seconds on this host.

The verification covers old bots, rich telemetry, malformed/partial/oversize records, duplicate conflicts, log rotation, pagination, long/short options, partial closes, uncertain ownership, no fake old explanations, rule/exit audits, rejected/unfilled outcomes, stop timeline/linkage, conservative missed-trade evidence, optional writer failures, original metric stability when telemetry fails, rendering/escaping and existing UI sections. A DOM test is not a visual browser/screenshot test; visual appearance should be checked in the running local UI.

Manual check: start `BOTMONITOR_ALPACA=0 python3 app.py` on an unused local port (set `BOTMONITOR_PORT` if necessary), select bots in Overview, retain original detail metrics, open Journal and Inspector, use filters/pages, and inspect Signals. For rich synthetic fixtures use a temporary bot root/data directory as in tests; do not append made-up trades/events to production logs. Current broker prices require the existing optional read-only Alpaca connection. Live broker behavior was not revalidated in this offline upgrade.

Fast rollback: stop/restart **MonitorG only** with `BOTMONITOR_EXPLAIN=0`. Existing monitoring works without the new database; added tabs report disabled. Do not stop trading bots. The implementation has not restarted your current MonitorG process; it takes effect on its next start.

To restore the exact old UI, remove the `static/explain.js` include, new detail nav/container, event notification and appended scoped CSS. Remove only this upgrade's server/service hooks and ETF reason retention if desired. Preserve pre-existing working-tree changes. Back up the independent `explainability.db` and its WAL while stopped (or use SQLite backup) before moving it aside. Keep `botmonitor.db`, ownership files, and all bot ledgers untouched. This layer has no migration to undo in the existing performance database.
