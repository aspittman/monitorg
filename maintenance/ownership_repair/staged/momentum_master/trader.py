from __future__ import annotations

import time
from datetime import datetime, timezone

from alpaca.common.exceptions import APIError
from bot_ownership import TradingClient
from alpaca.trading.enums import AssetClass, OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, ReplaceOrderRequest, StopOrderRequest

from config import settings
from state import BotState
from trade_logger import TradeLogger, execution_quality_fields


trading_client: TradingClient | None = None
bot_state = BotState(settings.state_dir)
trade_logger = TradeLogger(settings.log_dir)
PERFORMANCE_START = datetime(2026, 8, 21, tzinfo=timezone.utc)


class ConfigurationError(RuntimeError):
    """Raised when required runtime configuration is missing or invalid."""


def get_trading_client() -> TradingClient:
    global trading_client
    if trading_client is None:
        missing = [
            name
            for name, value in {
                "ALPACA_API_KEY": settings.alpaca_api_key,
                "ALPACA_SECRET_KEY": settings.alpaca_secret_key,
            }.items()
            if not value
        ]
        if missing:
            names = " and ".join(missing)
            raise ConfigurationError(f"Set {names} in {settings.env_file} before live or paper trading.")
        trading_client = TradingClient(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=settings.alpaca_paper,
        )
    return trading_client


def is_stock_position(position) -> bool:
    asset_class = getattr(position, "asset_class", None)
    value = str(getattr(asset_class, "value", asset_class)).lower()
    return value == AssetClass.US_EQUITY.value


def is_long_position(position) -> bool:
    side = getattr(position, "side", None)
    value = str(getattr(side, "value", side)).lower()
    if value:
        return value == "long"
    # Older mocks and broker payloads may omit side. Alpaca reports a signed
    # quantity in those payloads, so fail closed for zero/negative quantities.
    try:
        return float(position.qty) > 0
    except (AttributeError, TypeError, ValueError):
        return False


def get_stock_positions() -> list:
    return [position for position in get_trading_client().get_all_positions()
            if is_stock_position(position)]


def get_total_market_value() -> float:
    try:
        return sum(abs(float(position.market_value)) for position in get_stock_positions())
    except Exception as exc:
        print(f"Error getting total market value: {exc}")
        return 0.0


def get_open_positions_count() -> int:
    return len(get_stock_positions())


def get_position(symbol: str):
    try:
        return get_trading_client().get_open_position(symbol)
    except APIError as exc:
        if exc.status_code == 404:
            return None
        raise


def already_holding(symbol: str) -> bool:
    return get_position(symbol) is not None


def place_market_order(
    symbol: str,
    side: str,
    *,
    qty: float | None = None,
    notional: float | None = None,
    reason: str = "",
    score: float | str = "",
    price: float | str = "",
    log_fields: dict | None = None,
):
    order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
    # Alpaca accepts stock notional orders in whole cents only. Risk sizing uses
    # full floating-point precision, so normalize at the broker boundary.
    if notional is not None:
        notional = round(float(notional), 2)
    request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        notional=notional,
        side=order_side,
        time_in_force=TimeInForce.DAY,
    )
    request_started = time.perf_counter()
    order = get_trading_client().submit_order(request)
    # Wait briefly for a complete fill. Accepted/unfilled orders are recovered by
    # startup reconciliation instead of being written as zero-quantity trades.
    for _ in range(10):
        if getattr(order, "filled_at", None) or getattr(order, "filled_avg_price", None):
            break
        time.sleep(0.5)
        try:
            order = get_trading_client().get_order_by_id(order.id)
        except Exception:
            break
    filled_qty = getattr(order, "filled_qty", None)
    filled_price = getattr(order, "filled_avg_price", None)
    fields = dict(log_fields or {})
    submitted_at = getattr(order, "submitted_at", None)
    filled_at = getattr(order, "filled_at", None)
    fields["submitted_at"] = str(submitted_at or "")
    fields["filled_at"] = str(filled_at or "")
    if filled_at:
        fields["fill_latency_ms"] = round((time.perf_counter() - request_started) * 1000, 3)
    if filled_price:
        try:
            expected_price = float(price)
        except (TypeError, ValueError):
            expected_price = 0.0
        if expected_price > 0:
            fields.update(execution_quality_fields(
                side, float(filled_qty or qty or 0), expected_price, float(filled_price)
            ))
        fields["entry_price" if side.lower() == "buy" else "exit_price"] = filled_price
        if side.lower() == "sell" and fields.get("entry_price"):
            actual_qty = float(filled_qty or qty or 0)
            entry = float(fields["entry_price"])
            exit_price = float(filled_price)
            fields["realized_pl"] = actual_qty * (exit_price - entry)
            fields["realized_pl_percent"] = exit_price / entry - 1
    if getattr(order, "filled_at", None) and filled_qty and filled_price:
        trade_logger.log(
            symbol=symbol, side=side.lower(), qty=filled_qty,
            notional=float(filled_qty) * float(filled_price),
            order_id=getattr(order, "id", ""), **fields,
        )
        print(f"Filled {side.upper()} market order for {symbol}")
    else:
        print(f"Submitted {side.upper()} market order for {symbol}; fill is still pending.")
    return order


def has_open_order(symbol: str, side: str | None = None) -> bool:
    try:
        for order in get_trading_client().get_orders():
            order_symbol = str(getattr(order, "symbol", "")).upper()
            order_side = str(getattr(order, "side", "")).lower()
            if order_symbol == symbol.upper() and (side is None or side.lower() in order_side):
                return True
    except Exception as exc:
        print(f"Unable to verify open orders for {symbol}: {exc}; protecting against a duplicate order.")
        return True
    return False


def has_pending_exit(symbol: str) -> bool:
    pending = bot_state.pending_exit(symbol)
    if not pending:
        return False
    order_id = pending.get("order_id")
    if not order_id:
        return True
    try:
        order = get_trading_client().get_order_by_id(order_id)
        status = str(getattr(getattr(order, "status", ""), "value",
                             getattr(order, "status", ""))).lower()
        if status in {"canceled", "expired", "rejected"}:
            bot_state.clear_pending_exit(symbol)
            return False
    except Exception as exc:
        print(f"Unable to verify pending exit for {symbol}: {exc}; blocking a duplicate exit.")
    return True


def reconcile_pending_exits(open_symbols: set[str]) -> None:
    tracked = set(bot_state.data.get("pending_exits", {})) | set(
        bot_state.data.get("protective_stops", {})
    )
    for symbol in tracked:
        if symbol not in open_symbols:
            record = (bot_state.pending_exit(symbol) or bot_state.protective_stop(symbol))
            order_id = record.get("order_id")
            if order_id:
                try:
                    from paper_trades import reconcile_filled_orders
                    order = get_trading_client().get_order_by_id(order_id)
                    reconcile_filled_orders(
                        [order], trade_logger, allowed_symbols=settings.universe
                    )
                    rows = trade_logger.read()
                    for row in rows:
                        if str(row.get("order_id", "")) == str(order_id):
                            row["exit_reason"] = record.get("reason", "")
                            try:
                                expected = float(record.get("stop_price") or 0)
                                filled = float(row.get("exit_price") or 0)
                                qty = float(row.get("qty") or 0)
                            except (TypeError, ValueError):
                                expected = filled = qty = 0
                            if expected > 0 and filled > 0 and qty > 0:
                                row.update(execution_quality_fields("sell", qty, expected, filled))
                    trade_logger.replace(rows)
                except Exception as exc:
                    print(f"Unable to reconcile completed exit for {symbol}: {exc}")
            mark_recently_sold(symbol)


def ensure_protective_stop(symbol: str, qty: float, stop_price: float) -> bool:
    """Keep one session-long sell stop active, ratcheting upward but never down."""
    stop_price = round(float(stop_price), 2)
    existing = bot_state.protective_stop(symbol)
    if existing:
        order_id = existing.get("order_id")
        try:
            order = get_trading_client().get_order_by_id(order_id)
            status = str(getattr(getattr(order, "status", ""), "value",
                                 getattr(order, "status", ""))).lower()
            if status == "filled":
                # Do not replace a filled stop while the positions endpoint may
                # still be returning the pre-fill position. Reconciliation will
                # clear state once the position disappears.
                return True
            if status not in {"canceled", "expired", "rejected", "filled"}:
                if stop_price > float(existing.get("stop_price", 0)) + 0.009:
                    replacement = get_trading_client().replace_order_by_id(
                        order_id, ReplaceOrderRequest(stop_price=stop_price)
                    )
                    bot_state.set_protective_stop(symbol, getattr(replacement, "id", order_id), stop_price)
                return True
            bot_state.clear_protective_stop(symbol)
        except Exception as exc:
            print(f"Unable to verify protective stop for {symbol}: {exc}; not submitting a duplicate.")
            return False
    order = get_trading_client().submit_order(StopOrderRequest(
        symbol=symbol, qty=qty, side=OrderSide.SELL, type=OrderType.STOP,
        time_in_force=TimeInForce.DAY, stop_price=stop_price,
    ))
    bot_state.set_protective_stop(symbol, getattr(order, "id", ""), stop_price)
    print(f"Protective stop active for {symbol} at ${stop_price:.2f}")
    return True


def cancel_protective_stop(symbol: str) -> bool:
    """Cancel the safety stop before another sell; fail closed on uncertainty."""
    existing = bot_state.protective_stop(symbol)
    if not existing:
        return True
    order_id = existing.get("order_id")
    try:
        order = get_trading_client().get_order_by_id(order_id)
        status = str(getattr(getattr(order, "status", ""), "value",
                             getattr(order, "status", ""))).lower()
        if status == "filled":
            return False
        if status not in {"canceled", "expired", "rejected"}:
            get_trading_client().cancel_order_by_id(order_id)
            for _ in range(10):
                time.sleep(0.2)
                order = get_trading_client().get_order_by_id(order_id)
                status = str(getattr(getattr(order, "status", ""), "value",
                                     getattr(order, "status", ""))).lower()
                if status in {"canceled", "expired", "rejected"}:
                    break
                if status == "filled":
                    return False
            else:
                print(f"Protective stop cancellation for {symbol} is still pending; blocking another sell.")
                return False
        bot_state.clear_protective_stop(symbol)
        return True
    except Exception as exc:
        print(f"Unable to cancel protective stop for {symbol}: {exc}; blocking another sell.")
        return False


def mark_recently_sold(symbol: str) -> None:
    bot_state.mark_sold(symbol)


def is_in_cooldown(symbol: str) -> bool:
    return bot_state.is_on_cooldown(symbol, settings.cooldown_seconds)


def buy_candidate(candidate, notional: float | None = None) -> bool:
    if already_holding(candidate.symbol):
        print(f"Already holding {candidate.symbol}. Skipping.")
        return False
    if has_open_order(candidate.symbol):
        print(f"Open order exists for {candidate.symbol}. Skipping.")
        return False
    order = place_market_order(
        candidate.symbol,
        "buy",
        notional=notional if notional is not None else settings.dollars_per_trade,
        reason="momentum_entry",
        score=candidate.score,
        log_fields={
            "entry_price": candidate.price,
            "entry_score": candidate.score, "entry_reason": candidate.entry_reason,
            "atr_at_entry": candidate.atr, "ema20": candidate.ema_fast,
            "ema50": candidate.ema_slow, "macd": candidate.macd,
            "macd_signal": candidate.macd_signal, "macd_histogram": candidate.macd_hist,
            "relative_strength_score": candidate.relative_strength, "volume_ratio": candidate.volume_ratio,
        },
    )
    if getattr(order, "filled_at", None):
        fill_price = float(getattr(order, "filled_avg_price", None) or candidate.price)
        metadata = candidate.as_dict()
        metadata["price"] = fill_price
        bot_state.set_entry(candidate.symbol, fill_price, metadata)
        protected = ensure_protective_stop(
            candidate.symbol, float(getattr(order, "filled_qty", 0)),
            max(fill_price * (1 - settings.hard_stop_percent),
                fill_price - settings.atr_multiplier * candidate.atr),
        )
        if not protected:
            raise RuntimeError(
                f"filled entry for {candidate.symbol} has no verified protective stop"
            )
    return True


def sell_position(symbol: str, qty: float, reason: str, price: float, indicators: dict) -> bool:
    if has_pending_exit(symbol):
        print(f"Exit already submitted for {symbol}. Skipping duplicate exit.")
        return False
    if not cancel_protective_stop(symbol):
        return False
    if has_open_order(symbol, "sell"):
        print(f"Open sell order exists for {symbol}. Skipping duplicate exit.")
        return False
    entry = bot_state.entry_metadata(symbol)
    entry_price = float(entry.get("price", indicators.get("entry_price", price)))
    pnl = qty * (price - entry_price)
    placed = place_market_order(symbol, "sell", qty=qty, reason=reason, price=price, log_fields={
        "entry_price": entry_price, "exit_price": price,
        "realized_pl": pnl, "realized_pl_percent": (price / entry_price - 1) if entry_price else "",
        "entry_score": entry.get("score", ""), "entry_reason": entry.get("entry_reason", "momentum_entry"),
        "exit_reason": reason, "atr_at_entry": entry.get("atr", ""), "atr_at_exit": indicators.get("atr", ""),
        "ema20": indicators.get("ema_fast", ""), "ema50": indicators.get("ema_slow", ""),
        "macd": indicators.get("macd", ""), "macd_signal": indicators.get("macd_signal", ""),
        "macd_histogram": indicators.get("macd_hist", ""),
        "relative_strength_score": entry.get("relative_strength", ""), "volume_ratio": entry.get("volume_ratio", ""),
        "holding_duration": _holding_duration(entry.get("timestamp")),
    })
    # Keep the exit marker even when the order filled immediately. Broker
    # positions can be eventually consistent; reconciliation clears this only
    # after the position has actually disappeared.
    bot_state.set_pending_exit(symbol, getattr(placed, "id", ""), reason)
    return bool(placed)


def _holding_duration(timestamp) -> str:
    if not timestamp:
        return ""
    from datetime import datetime, timezone
    try:
        entered = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        return str(datetime.now(timezone.utc) - entered)
    except (TypeError, ValueError):
        return ""


def manage_position(symbol: str, frame) -> bool:
    from signals import momentum_exit_decision
    position = get_position(symbol)
    if position is None:
        return False
    if not is_long_position(position):
        raise RuntimeError(f"{symbol} is not a long position; automatic selling is disabled")
    if has_pending_exit(symbol):
        print(f"Exit already submitted for {symbol}; waiting for broker position reconciliation.")
        return False

    qty = float(position.qty)
    entry_price = float(position.avg_entry_price)
    latest = frame.iloc[-1]
    latest_price = float(latest["Close"])
    highest = bot_state.update_highest(symbol, max(entry_price, latest_price))
    proposed = highest - settings.atr_multiplier * float(latest["atr"])
    atr_stop = bot_state.update_trailing_stop(symbol, proposed)
    if not ensure_protective_stop(
        symbol, qty, max(entry_price * (1-settings.hard_stop_percent), atr_stop)
    ):
        raise RuntimeError(f"protective stop for {symbol} could not be verified")
    decision = momentum_exit_decision(frame, entry_price=entry_price, highest_price=highest,
                                      settings=settings, atr_stop_floor=atr_stop,
                                      completed_bar_offset=1 if settings.data_interval.endswith("d") else 0)

    print(
        f"{symbol}: price={latest_price:.2f}, highest={highest:.2f}, "
        f"ATR stop={atr_stop:.2f}, hard stop={entry_price * (1-settings.hard_stop_percent):.2f}"
    )
    reason = decision.reason if decision else ""
    if reason:
        return sell_position(symbol, qty, reason, latest_price, latest.to_dict())
    return False


def bot_profit_loss(positions: list | None = None) -> tuple[float, float]:
    """Return P/L since the clean-ledger baseline plus current unrealized P/L."""
    allowed = {symbol.upper() for symbol in settings.universe}
    realized = 0.0
    for row in trade_logger.read():
        if str(row.get("symbol", "")).upper() not in allowed:
            continue
        try:
            timestamp = datetime.fromisoformat(
                str(row.get("timestamp", "")).replace("Z", "+00:00")
            )
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp < PERFORMANCE_START:
                continue
        except (TypeError, ValueError):
            continue
        try:
            realized += float(row.get("realized_pl") or 0)
        except (TypeError, ValueError):
            continue

    unrealized = 0.0
    for position in positions if positions is not None else get_stock_positions():
        if str(getattr(position, "symbol", "")).upper() not in allowed:
            continue
        try:
            unrealized += float(getattr(position, "unrealized_pl", 0) or 0)
        except (TypeError, ValueError):
            continue

    total = realized + unrealized
    return_percent = total / settings.max_total_capital if settings.max_total_capital > 0 else 0.0
    return total, return_percent


def print_account_info() -> None:
    client = get_trading_client()
    account = client.get_account()
    positions = [position for position in client.get_all_positions() if is_stock_position(position)]
    bot_pl, bot_return = bot_profit_loss(positions)
    print("\n===== ACCOUNT INFO =====")
    print(f"Equity: ${account.equity}")
    print(f"Buying Power: ${account.buying_power}")
    print(f"MomentumMaster Gain/Loss Since Aug 21, 2026: {bot_return:+.2%} ({bot_pl:+.2f})")
    print("========================\n")


def print_position(symbol: str) -> None:
    position = get_position(symbol)
    if position is None:
        return
    print("----- POSITION -----")
    print(f"Symbol: {symbol}")
    print(f"Qty: {position.qty}")
    print(f"Avg Entry: ${position.avg_entry_price}")
    print(f"Current Price: ${position.current_price}")
    print(f"Unrealized P/L: ${position.unrealized_pl}")
    print("--------------------\n")
