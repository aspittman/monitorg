"""Alpaca adapter. Strategy modules never import this module."""
from __future__ import annotations

import os
from dataclasses import dataclass

from portfolio.manager import Portfolio, Position


@dataclass
class AlpacaBroker:
    paper: bool = True
    dry_run: bool = True
    allow_live_trading: bool = False

    def __post_init__(self) -> None:
        if not self.paper:
            confirmed = self.allow_live_trading and os.getenv("ETFENHANCERLT_LIVE_CONFIRMATION") == "I_UNDERSTAND_LIVE_ORDERS"
            if not confirmed:
                raise RuntimeError("LIVE TRADING REFUSED: set both allow_live_trading and the explicit confirmation variable")
        try:
            from bot_ownership import TradingClient
        except ImportError as exc:
            raise RuntimeError("alpaca-py is required for brokerage access") from exc
        key = os.getenv("ALPACA_API_KEY")
        secret = os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("ALPACA_API_KEY and ALPACA_SECRET_KEY are required")
        self.client = TradingClient(key, secret, paper=self.paper)

    def get_portfolio(self, prices: dict[str, float]) -> Portfolio:
        account = self.client.get_account()
        positions = {}
        for raw in self.client.get_all_positions():
            symbol = raw.symbol
            price = prices.get(symbol, float(raw.current_price))
            positions[symbol] = Position(symbol, float(raw.qty), price, float(raw.cost_basis))
        return Portfolio(cash=float(account.cash), positions=positions)

    def get_account_snapshot(self) -> dict[str, float]:
        account = self.client.get_account()
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "last_equity": float(account.last_equity),
        }

    def get_clock(self) -> object:
        """Return Alpaca's exchange-aware market clock."""
        return self.client.get_clock()

    def has_open_orders(self) -> bool:
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest
        return bool(self.client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN)))

    def submit_notional_order(self, symbol: str, side: str, amount: float) -> object | None:
        if self.dry_run:
            print(f"DRY RUN: Would {side.upper()} {symbol} for ${amount:,.2f}")
            return None
        from alpaca.trading.enums import OrderSide, TimeInForce
        from alpaca.trading.requests import MarketOrderRequest
        request = MarketOrderRequest(symbol=symbol, notional=round(amount, 2),
                                     side=OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL,
                                     time_in_force=TimeInForce.DAY)
        return self.client.submit_order(order_data=request)
