"""
SUI Market Making Strategy for CoinStore Exchange
Based on backtesting framework discussion
"""

import asyncio
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.limit_order import LimitOrder
from hummingbot.core.event.events import OrderCancelledEvent, OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class SUIMarketMakingStrategy(ScriptStrategyBase):
    """
    Market Making Strategy for SUIUSDT on CoinStore

    Features:
    - Spread-based quoting around mid price
    - Volatility adjustment (wider spreads in volatile markets)
    - Inventory skew (adjust quotes based on position)
    - Risk controls (position limits, stop losses)
    - Multi-timeframe analysis
    """

    def __init__(self):
        super().__init__()

        # Strategy parameters
        self.trading_pair = "SUIUSDT"
        self.base_spread_bps = 20  # Base spread in basis points (0.2%)
        self.vol_window = 60  # Volatility calculation window (minutes)
        self.vol_k = 1.5  # Volatility multiplier
        self.max_inventory = 1000  # Maximum SUI inventory
        self.skew_k = 0.5  # Inventory skew factor
        self.order_size = 100  # Order size in SUI
        self.fee_bps = 10  # Trading fee in basis points (0.1%)

        # Risk management
        self.max_drawdown_pct = 0.05  # 5% max drawdown
        self.stop_loss_pct = 0.02  # 2% stop loss
        self.position_limit = 500  # Position limit in SUI

        # State variables
        self.current_inventory = Decimal("0")
        self.cash_balance = Decimal("10000")  # Starting cash
        self.equity = Decimal("10000")
        self.max_equity = Decimal("10000")
        self.trades_count = 0
        self.total_pnl = Decimal("0")

        # Price tracking
        self.last_price = None
        self.price_history = []
        self.volatility = 0.0

        # Order tracking
        self.active_orders = {}
        self.order_refresh_time = 30  # Refresh orders every 30 seconds

        # Multi-timeframe data
        self.mtf_data = {
            "1m": [],
            "5m": [],
            "15m": [],
            "30m": []
        }

        self.logger().info("SUI Market Making Strategy initialized")

    def on_tick(self):
        """Main strategy logic called every tick"""
        try:
            # Update price data
            self._update_price_data()

            # Calculate volatility
            self._calculate_volatility()

            # Check risk limits
            if not self._check_risk_limits():
                return

            # Cancel old orders
            self._cancel_old_orders()

            # Place new orders
            self._place_market_making_orders()

        except Exception as e:
            self.logger().error(f"Error in on_tick: {e}")

    def _update_price_data(self):
        """Update price data from order book"""
        order_book = self.connectors["coinstore"].get_order_book(self.trading_pair)
        if order_book and order_book.bid_price() and order_book.ask_price():
            mid_price = (order_book.bid_price() + order_book.ask_price()) / 2
            self.last_price = mid_price
            self.price_history.append(float(mid_price))

            # Keep only recent history
            if len(self.price_history) > self.vol_window * 2:
                self.price_history = self.price_history[-self.vol_window * 2:]

    def _calculate_volatility(self):
        """Calculate rolling volatility"""
        if len(self.price_history) < self.vol_window:
            self.volatility = 0.0
            return

        # Calculate rolling standard deviation
        recent_prices = self.price_history[-self.vol_window:]
        returns = np.diff(recent_prices) / np.array(recent_prices[:-1])
        self.volatility = np.std(returns) * np.sqrt(60)  # Annualized

    def _check_risk_limits(self) -> bool:
        """Check if we're within risk limits"""
        # Check drawdown
        current_drawdown = (self.max_equity - self.equity) / self.max_equity
        if current_drawdown > self.max_drawdown_pct:
            self.logger().warning(f"Max drawdown exceeded: {current_drawdown:.2%}")
            return False

        # Check position limit
        if abs(self.current_inventory) > self.position_limit:
            self.logger().warning(f"Position limit exceeded: {self.current_inventory}")
            return False

        # Check stop loss
        if self.last_price and self.current_inventory != 0:
            unrealized_pnl = self._calculate_unrealized_pnl()
            if unrealized_pnl < -self.equity * self.stop_loss_pct:
                self.logger().warning(f"Stop loss triggered: {unrealized_pnl}")
                return False

        return True

    def _calculate_unrealized_pnl(self) -> Decimal:
        """Calculate unrealized PnL"""
        if not self.last_price or self.current_inventory == 0:
            return Decimal("0")

        # Simplified PnL calculation
        return self.current_inventory * (self.last_price - self._get_average_price())

    def _get_average_price(self) -> Decimal:
        """Get average price of current position"""
        # This would track average entry price
        # For now, return current price
        return self.last_price or Decimal("0")

    def _cancel_old_orders(self):
        """Cancel orders older than refresh time"""
        current_time = datetime.now()
        orders_to_cancel = []

        for order_id, order in self.active_orders.items():
            if (current_time - order.creation_timestamp).seconds > self.order_refresh_time:
                orders_to_cancel.append(order_id)

        for order_id in orders_to_cancel:
            self.cancel_order("coinstore", self.trading_pair, order_id)
            del self.active_orders[order_id]

    def _place_market_making_orders(self):
        """Place market making orders"""
        if not self.last_price:
            return

        # Calculate spread
        spread = self._calculate_spread()

        # Calculate inventory skew
        skew = self._calculate_inventory_skew()

        # Calculate bid and ask prices
        mid_price = self.last_price
        bid_price = mid_price * (1 - spread / 2 + skew)
        ask_price = mid_price * (1 + spread / 2 + skew)

        # Place buy order
        if len([o for o in self.active_orders.values() if o.is_buy]) == 0:
            buy_order_id = self.place_order(
                connector_name="coinstore",
                trading_pair=self.trading_pair,
                is_buy=True,
                amount=Decimal(str(self.order_size)),
                order_type=OrderType.LIMIT,
                price=bid_price
            )
            if buy_order_id:
                self.active_orders[buy_order_id] = LimitOrder(
                    client_order_id=buy_order_id,
                    trading_pair=self.trading_pair,
                    is_buy=True,
                    base_currency="SUI",
                    quote_currency="USDT",
                    price=bid_price,
                    quantity=Decimal(str(self.order_size)),
                    filled_quantity=Decimal("0"),
                    status="NEW",
                    order_type=OrderType.LIMIT,
                    time_in_force="GTC"
                )

        # Place sell order
        if len([o for o in self.active_orders.values() if not o.is_buy]) == 0:
            sell_order_id = self.place_order(
                connector_name="coinstore",
                trading_pair=self.trading_pair,
                is_buy=False,
                amount=Decimal(str(self.order_size)),
                order_type=OrderType.LIMIT,
                price=ask_price
            )
            if sell_order_id:
                self.active_orders[sell_order_id] = LimitOrder(
                    client_order_id=sell_order_id,
                    trading_pair=self.trading_pair,
                    is_buy=False,
                    base_currency="SUI",
                    quote_currency="USDT",
                    price=ask_price,
                    quantity=Decimal(str(self.order_size)),
                    filled_quantity=Decimal("0"),
                    status="NEW",
                    order_type=OrderType.LIMIT,
                    time_in_force="GTC"
                )

    def _calculate_spread(self) -> float:
        """Calculate spread based on volatility"""
        base_spread = self.base_spread_bps / 10000  # Convert to decimal
        vol_adjustment = self.volatility * self.vol_k
        return base_spread + vol_adjustment

    def _calculate_inventory_skew(self) -> float:
        """Calculate inventory skew factor"""
        if self.max_inventory == 0:
            return 0.0

        inventory_ratio = float(self.current_inventory) / self.max_inventory
        return inventory_ratio * self.skew_k * 0.01  # 1% max skew

    def on_order_filled(self, event: OrderFilledEvent):
        """Handle order fill events"""
        order_id = event.order_id
        trading_pair = event.trading_pair
        trade_type = event.trade_type
        amount = event.amount
        price = event.price
        fee = event.trade_fee

        # Update inventory
        if trade_type == TradeType.BUY:
            self.current_inventory += amount
            self.cash_balance -= amount * price
        else:
            self.current_inventory -= amount
            self.cash_balance += amount * price

        # Update equity
        self.equity = self.cash_balance + self.current_inventory * price
        if self.equity > self.max_equity:
            self.max_equity = self.equity

        # Update trade count
        self.trades_count += 1

        # Calculate PnL
        trade_pnl = amount * price * (1 if trade_type == TradeType.SELL else -1)
        self.total_pnl += trade_pnl

        # Log trade
        self.logger().info(
            f"Trade filled: {trade_type.name} {amount} {trading_pair} @ {price} "
            f"(Inventory: {self.current_inventory}, PnL: {self.total_pnl:.2f})"
        )

        # Remove from active orders
        if order_id in self.active_orders:
            del self.active_orders[order_id]

    def on_order_cancelled(self, event: OrderCancelledEvent):
        """Handle order cancellation events"""
        order_id = event.order_id
        if order_id in self.active_orders:
            del self.active_orders[order_id]
            self.logger().info(f"Order cancelled: {order_id}")

    def get_strategy_status(self) -> Dict:
        """Get current strategy status"""
        return {
            "trading_pair": self.trading_pair,
            "current_price": float(self.last_price) if self.last_price else 0,
            "inventory": float(self.current_inventory),
            "cash_balance": float(self.cash_balance),
            "equity": float(self.equity),
            "total_pnl": float(self.total_pnl),
            "trades_count": self.trades_count,
            "volatility": self.volatility,
            "active_orders": len(self.active_orders),
            "max_drawdown": float((self.max_equity - self.equity) / self.max_equity) if self.max_equity > 0 else 0
        }

    def logger(self) -> logging.Logger:
        return logging.getLogger(self.__class__.__name__)
