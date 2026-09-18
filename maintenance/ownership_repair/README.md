# Ownership repair — September 17, 2026

Policy: one bot owns an exact instrument within a broker account while it has a position, open order or unresolved submission. Different accounts and different option contracts remain independent. Trader IDs are the eight repository names.

The independent `~/MyBotz/trading_ownership` package wraps the Alpaca client at each bot's execution boundary. It has no imports, paths or calls into BotMonitor. A shared file lock serializes account/instrument checks and submission reservations. SQLite persists ownership and unresolved requests before a broker action. Failed reads and ambiguous submissions block further conflicting actions. Ownership can transfer after broker-confirmed flat inventory, no open orders and resolution of the previous request.

Position and order reads are filtered to the bot. Native prefixes and explicitly verified legacy order IDs establish ownership. Broker fills since the audited baseline must explain held quantities; unexpected activity fails closed. Crypto fee quantities are included. Order submission, replacement and cancellation check ownership; bulk close/cancel and generic write methods are unavailable through the wrapper. Strategy signals, scheduling, credentials and capital settings are unchanged.

| Trader ID | Client order ID prefixes |
|---|---|
| ccexchange | `ccexchange-` |
| ETFEnhancer | `etfenhancer-paper-`, `etfenhancer-live-` |
| ETFEnhancerLT | `etfenhancerlt-` |
| momentum_master | `momentum_master-` |
| options_covered | `covered_call_`, `covered_stock_` |
| options_secured | `cash_secured_put_`, legacy `os-` |
| options_inverted | `long_put_`, legacy `oi-` |
| options_direct | `long_call_` |

## Verified holdings

Account 1: Momentum owns CRWD 1.175472088 and NVDA 1.096147069, verified against its native entry records, broker order IDs and broker quantities/basis. ETFEnhancer owns SCHD, SPY and XLB, verified against its state entry order IDs. ccexchange owns no remaining BTC: its 0.000479421 BTC gross fill remainder exactly equals three broker crypto fee debits. ETFEnhancerLT has no attributable holdings; its old live position files are account-wide. Account 2: the remaining XBI short put belongs to options_secured. Current quantities are rechecked during deployment.

Momentum's legacy SCHD and XLB protective-stop records concern ETFEnhancer holdings. Those orders were not open at audit. No order was cancelled or replaced during this work. Future guarded reads and actions exclude those foreign instruments.

## Monitor behavior and limitations

BotMonitor reads a copy of the audit baseline and reads the trading ownership database with SQLite `mode=ro` and `query_only`. It never writes trading ownership. Reconciled positions show 0 / 2 / 0 for ccexchange / momentum_master / ETFEnhancerLT at audit. New registered fills update the expected quantities. Unknown fills, inconsistent inventory, unavailable registry data and incomplete broker history leave N/A.

Historical Momentum trade imports still mix accounts; old counts and realized P/L remain N/A. ETFEnhancerLT's backtests are still excluded. ccexchange's displayed realized P/L is gross; fee-adjusted realized/combined P/L and bot return percentages are not invented. Corporate actions, adjusted options and ambiguous crypto-fee attribution require explicit reconciliation. Manual trades and other programs are outside this wrapper; unexplained effects on registered holdings block management until reconciled.

The changed bot imports take effect on the next normal cron restart. No trading bot is started or stopped by the deployment script. Until then, old running processes retain their old clients and cannot be described as protected by the new guard.

## Review and validation

- `manifest.json`: eight import replacements and eight new local identity loaders, with before/after SHA-256 hashes.
- `trading_ownership/`: complete independent guard and audited baseline.
- `broker_evidence.json`: private local GET-only broker evidence, no API credentials.
- `test_guard.py`: isolated mocked ownership, concurrency, unknown-activity and crypto-fee tests; no real broker mutations.
- `test_staged.py`: existing bot suites in temporary copies, dummy credentials and socket connections denied.
- `test_results.json`, `*_tests.log`: integration results.
- `live_preflight.json`, `deployment.json`: read-only preflight and installation evidence.
- `deploy.py --install`: checks unchanged source hashes and tests, validates every current holding/open order, backs up files under `~/MyBotz/ownership_backups`, then installs. Never overwrites an existing registry.

No bot code depends on the monitor. Stopping or deleting BotMonitor cannot interrupt trading. Keep the independent trading ownership package and its SQLite registry with the bots.
