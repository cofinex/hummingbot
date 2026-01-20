import asyncio
import math
import os
import random
from decimal import Decimal
from typing import Dict, List, Optional

import aiohttp
from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType, PriceType, TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase


class MultiLevelSelfTradingConfig(BaseClientModel):
    """
    Configuration for Multi-Level Self-Trading Strategy with Dynamic Price Shift
    """
    script_file_name: str = os.path.basename(__file__)
    exchange: str = Field("cofinex_paper_trade", description="Exchange connector name")
    trading_pair: str = Field("BTC-USDT", description="Trading pair to trade")

    # Order settings
    order_levels: int = Field(15, description="Number of order levels (default: 15)")
    level_spread: Decimal = Field(
        Decimal("0.002"),
        description="Spread between levels (0.2% = 0.002, default: 0.2%)"
    )

    # Level 1 order value (in USD)
    level1_order_value_usd: Decimal = Field(
        Decimal("100"),
        description="Level 1 order value in USD (amount will be calculated dynamically based on price)"
    )

    # Normal order amount ranges (in USD)
    # Used for levels 2 through (large_level_sell_start - 1) for SELL
    # Used for ALL levels 2+ for BUY
    normal_buy_min_usd: Decimal = Field(
        Decimal("10"),
        description="Minimum buy order value in USD for all levels 2+"
    )
    normal_buy_max_usd: Decimal = Field(
        Decimal("50"),
        description="Maximum buy order value in USD for all levels 2+"
    )
    normal_sell_min_usd: Decimal = Field(
        Decimal("1000"),
        description="Minimum sell order value in USD for levels 2+ up to large_level_sell_start-1"
    )
    normal_sell_max_usd: Decimal = Field(
        Decimal("5000"),
        description="Maximum sell order value in USD for levels 2+ up to large_level_sell_start-1"
    )

    # Large level SELL configuration
    # Levels from large_level_sell_start to order_levels will use these settings
    large_level_sell_start: int = Field(
        13,
        description="First level to use large spacing (e.g., 13 means levels 13+ use large spacing). Set to 0 or > order_levels to disable."
    )
    large_level_sell_spread_multiplier: Decimal = Field(
        Decimal("200"),
        description="Multiplier for level_spread on large-level sell orders (e.g., 200 = 200x = 40% per level)"
    )
    large_level_sell_min_usd: Decimal = Field(
        Decimal("5000"),
        description="Minimum sell order value in USD for large levels (from large_level_sell_start to order_levels)"
    )
    large_level_sell_max_usd: Decimal = Field(
        Decimal("10000"),
        description="Maximum sell order value in USD for large levels (from large_level_sell_start to order_levels)"
    )

    # Level 1 self-trading settings
    level1_buy_offset: Decimal = Field(
        Decimal("0.0005"),
        description="Level 1 buy offset from reference price (positive = above ref for overlap)"
    )
    level1_sell_offset: Decimal = Field(
        Decimal("-0.0005"),
        description="Level 1 sell offset from reference price (negative = below ref for overlap)"
    )

    # Dynamic price shift from Bitget
    price_shift_enabled: bool = Field(
        True,
        description="Enable dynamic price shift from Bitget change24h"
    )
    bitget_api_url: str = Field(
        "https://api.bitget.com/api/v2/spot/market/tickers",
        description="Bitget API URL for ticker data"
    )
    bitget_symbol: str = Field(
        "BTCUSDT",
        description="Bitget symbol to fetch change24h (e.g., BTCUSDT)"
    )
    price_shift_update_interval: int = Field(
        60,
        description="Update price shift from Bitget every X seconds"
    )
    price_shift_multiplier: Decimal = Field(
        Decimal("1.0"),
        description="Multiplier for price shift (e.g., 1.0 = use change24h as-is, 2.0 = double it)"
    )
    price_shift_change_threshold: Decimal = Field(
        Decimal("0.1"),
        description="Minimum shift change percentage to trigger refresh (0.1% = 0.001, default: 0.1%)"
    )

    # Strategy settings
    order_refresh_time: int = Field(300, description="Time in seconds to refresh orders if no fills")
    filled_order_delay: int = Field(30, description="Delay in seconds after fill before placing new orders (balanced: 30s)")
    price_type: str = Field("last", description="Price source: 'mid' or 'last' (use 'last' for self-trade price movement)")
    enable_self_trading: bool = Field(True, description="Enable self-trading on level 1")
    refresh_on_level1_fill: bool = Field(
        True,
        description="Refresh orders after Level 1 self-trade fills (default: True to move market price)"
    )
    refresh_on_level2_5_fill: bool = Field(
        True,
        description="Refresh orders after Levels 2+ fills (real market activity, default: True)"
    )
    cancel_orders_on_stop: bool = Field(
        False,
        description="Cancel all active orders when bot stops (default: False to keep orders active)"
    )


class MultiLevelSelfTradingStrategy(ScriptStrategyBase):
    """
    Multi-Level Self-Trading Strategy with Dynamic Price Shift from Bitget

    This strategy:
    - Places 7 levels of buy/sell orders around a reference price
    - Level 1 orders overlap for self-trading (exchange-core matches them automatically)
    - Levels 2-7 provide additional liquidity with 0.1% spread between levels
    - Dynamically adjusts price shift based on Bitget's 24h price change (change24h)
    - Automatically refreshes orders after fills or periodically

    Key Features:
    - Self-trading: Level 1 buy and sell orders overlap, allowing exchange-core to match them
    - Dynamic shift: Price shift follows Bitget's 24h price movement
    - Multi-level: 7 levels provide depth and liquidity
    - Auto-refresh: Orders refresh after fills or every 30 seconds

    Designed for: exchange-core or exchanges that support self-trading
    """

    # Class variables (will be instance-specific in __init__)
    create_timestamp = 0
    last_fill_timestamp = 0
    last_shift_update_timestamp = 0
    price_source = PriceType.MidPrice
    total_fills = 0
    level1_fills = 0
    refresh_pending = False

    @classmethod
    def init_markets(cls, config: MultiLevelSelfTradingConfig):
        """Initialize markets required for this strategy"""
        cls.markets = {config.exchange: {config.trading_pair}}
        cls.price_source = PriceType.LastTrade if config.price_type == "last" else PriceType.MidPrice

    def __init__(self, connectors: Dict[str, ConnectorBase], config: MultiLevelSelfTradingConfig):
        super().__init__(connectors)
        self.config = config
        self.current_price_shift = Decimal("0.0")
        self.previous_price_shift = Decimal("0.0")  # Track previous shift for change detection
        self.bitget_change24h = Decimal("0.0")

        # Initialize instance-specific timing variables
        self.create_timestamp = 0  # When to next refresh orders (0 = not set yet)
        self.last_fill_timestamp = 0
        self.last_shift_update_timestamp = 0
        self.refresh_pending = False

        # Track last trade price internally (for paper trading where connector doesn't track it)
        self._last_trade_price: Optional[Decimal] = None

        # Initialize precision as None - will be detected lazily when connector is ready
        self._price_precision: Optional[int] = None
        self._amount_precision: Optional[int] = None
        self._precision_detected = False  # Flag to track if we've attempted detection
        self._trading_rules_update_triggered = False  # Flag to track if we've triggered trading rules update
        self._fetch_precision_task = None  # Task for fetching precision from API

        self.logger().info("Multi-Level Self-Trading Strategy initialized")
        self.logger().info(f"Exchange: {config.exchange}, Pair: {config.trading_pair}")
        self.logger().info(f"Levels: {config.order_levels}, Level Spread: {config.level_spread}")
        self.logger().info(f"Level 1 Order Value: ${config.level1_order_value_usd} USDT (amount calculated dynamically)")
        self.logger().info(f"Normal Buy Range: ${config.normal_buy_min_usd}-${config.normal_buy_max_usd} (all levels 2+)")
        self.logger().info(f"Normal Sell Range: ${config.normal_sell_min_usd}-${config.normal_sell_max_usd} (levels 2+ up to {config.large_level_sell_start - 1 if config.large_level_sell_start > 0 else config.order_levels})")  # noqa: E226
        if config.large_level_sell_start > 0 and config.large_level_sell_start <= config.order_levels:
            self.logger().info(f"Large Level Sell: Levels {config.large_level_sell_start}-{config.order_levels}")
            self.logger().info(f"  - Range: ${config.large_level_sell_min_usd}-${config.large_level_sell_max_usd}")
            self.logger().info(f"  - Spacing Multiplier: {config.large_level_sell_spread_multiplier}x ({config.large_level_sell_spread_multiplier * config.level_spread * 100:.1f}% per level)")
        else:
            self.logger().info("Large Level Sell: Disabled")
        self.logger().info(f"Dynamic Price Shift: Enabled={config.price_shift_enabled}")
        if config.price_shift_enabled:
            self.logger().info(f"Bitget Symbol: {config.bitget_symbol}")
            self.logger().info(f"Shift Update Interval: {config.price_shift_update_interval}s")
            self.logger().info(f"Shift Change Threshold: {config.price_shift_change_threshold}% (triggers refresh)")
        self.logger().info(f"Fill Delay: {config.filled_order_delay}s | Refresh Level 1: {config.refresh_on_level1_fill} | Refresh Level 2+: {config.refresh_on_level2_5_fill}")
        self.logger().info(f"Price Type: {config.price_type} (use 'last' for self-trade price movement)")
        self.logger().info("Precision will be detected once connector is ready")

        # Fetch initial price shift
        if config.price_shift_enabled:
            asyncio.create_task(self._fetch_bitget_change24h())

        # For paper trading, fetch precision from API as fallback
        # For live trading, trading rules will be loaded via start_network() and detected automatically
        if config.exchange.endswith("_paper_trade"):
            self.logger().info("Paper trading mode: Will fetch precision from API as fallback")
            self._fetch_precision_task = asyncio.create_task(self._fetch_precision_from_api())
        else:
            self.logger().info("Live trading mode: Will use trading rules from connector (loaded via start_network())")

    @property
    def price_precision(self) -> int:
        """Lazy getter for price precision - detects if not already set"""
        if self._price_precision is None:
            # Try to detect precision if connector is ready
            self._detect_precision_if_ready()
            # If still not set, use fallback method
            if self._price_precision is None:
                self._price_precision = self._get_price_precision()
        return self._price_precision

    @property
    def amount_precision(self) -> int:
        """Lazy getter for amount precision - detects if not already set"""
        if self._amount_precision is None:
            # Try to detect precision if connector is ready
            self._detect_precision_if_ready()
            # If still not set, use fallback method
            if self._amount_precision is None:
                self._amount_precision = self._get_amount_precision()
        return self._amount_precision

    def _get_price_precision(self) -> int:
        """Get price precision from underlying connector's trading rules"""
        try:
            connector = self.connectors[self.config.exchange]

            # Log connector type
            self.logger().info(f"Getting price precision from connector: {type(connector).__name__}")

            # For PaperTradeExchange, get underlying connector from order book tracker
            real_connector = connector
            if hasattr(connector, 'order_book_tracker') and connector.order_book_tracker:
                data_source = connector.order_book_tracker.data_source
                self.logger().info(f"Data source type: {type(data_source).__name__}")
                # Try both _connector (private) and connector (public) attributes
                if hasattr(data_source, '_connector'):
                    real_connector = data_source._connector
                    self.logger().info(f"Found underlying connector via _connector: {type(real_connector).__name__}")
                elif hasattr(data_source, 'connector'):
                    real_connector = data_source.connector
                    self.logger().info(f"Found underlying connector via connector: {type(real_connector).__name__}")

            # Log trading rules availability
            if hasattr(real_connector, 'trading_rules'):
                self.logger().info(f"Trading rules dict has {len(real_connector.trading_rules)} entries")
                if real_connector.trading_rules:
                    self.logger().info(f"Trading rules keys: {list(real_connector.trading_rules.keys())}")
                trading_rule = real_connector.trading_rules.get(self.config.trading_pair)
                if trading_rule:
                    self.logger().info(
                        f"Found trading rule for {self.config.trading_pair}: "
                        f"min_price_increment={trading_rule.min_price_increment}, "
                        f"min_base_amount_increment={trading_rule.min_base_amount_increment}"
                    )
                    if trading_rule.min_price_increment > 0:
                        import math
                        precision = int(-math.log10(float(trading_rule.min_price_increment)))
                        self.logger().info(f"Detected price precision: {precision} decimals (from trading rules: min_price_increment={trading_rule.min_price_increment})")
                        return max(2, min(precision, 8))
                else:
                    self.logger().warning(f"No trading rule found for {self.config.trading_pair} in trading_rules dict")
            else:
                self.logger().warning(f"Connector {type(real_connector).__name__} does not have trading_rules attribute")

            # Fallback: test quantization with underlying connector
            self.logger().info("Falling back to quantization test for price precision")
            test_price = Decimal("0.123456789")
            quantized = real_connector.quantize_order_price(self.config.trading_pair, test_price)
            quantized_str = str(quantized)
            if '.' in quantized_str:
                decimal_part = quantized_str.split('.')[1].rstrip('0')
                precision = len(decimal_part)
                self.logger().info(f"Detected price precision: {precision} decimals (from quantization test: {test_price} -> {quantized})")
                return max(2, min(precision, 8))
        except Exception as e:
            self.logger().warning(f"Could not get price precision: {e}", exc_info=True)
        return 6  # Default to 6 decimals if not available

    def _get_amount_precision(self) -> int:
        """Get amount precision from underlying connector's trading rules"""
        try:
            connector = self.connectors[self.config.exchange]

            # For PaperTradeExchange, get underlying connector from order book tracker
            real_connector = connector
            if hasattr(connector, 'order_book_tracker') and connector.order_book_tracker:
                data_source = connector.order_book_tracker.data_source
                # Try both _connector (private) and connector (public) attributes
                if hasattr(data_source, '_connector'):
                    real_connector = data_source._connector
                elif hasattr(data_source, 'connector'):
                    real_connector = data_source.connector

            # Try to access trading rules from the real connector
            if hasattr(real_connector, 'trading_rules'):
                trading_rule = real_connector.trading_rules.get(self.config.trading_pair)
                if trading_rule:
                    self.logger().info(
                        f"Found trading rule for amount precision: "
                        f"min_base_amount_increment={trading_rule.min_base_amount_increment}"
                    )
                    if trading_rule.min_base_amount_increment > 0:
                        import math
                        precision = int(-math.log10(float(trading_rule.min_base_amount_increment)))
                        self.logger().info(f"Detected amount precision: {precision} decimals (from trading rules: min_base_amount_increment={trading_rule.min_base_amount_increment})")
                        return max(2, min(precision, 8))
                else:
                    self.logger().warning(f"No trading rule found for {self.config.trading_pair} when getting amount precision")

            # Fallback: test quantization with underlying connector
            self.logger().info("Falling back to quantization test for amount precision")
            test_amount = Decimal("0.123456789")
            quantized = real_connector.quantize_order_amount(self.config.trading_pair, test_amount)
            quantized_str = str(quantized)
            if '.' in quantized_str:
                decimal_part = quantized_str.split('.')[1].rstrip('0')
                precision = len(decimal_part)
                self.logger().info(f"Detected amount precision: {precision} decimals (from quantization test: {test_amount} -> {quantized})")
                return max(2, min(precision, 8))
        except Exception as e:
            self.logger().warning(f"Could not get amount precision: {e}", exc_info=True)
        return 4  # Default to 4 decimals if not available

    def _detect_precision_if_ready(self):
        """
        Attempt to detect precision from trading rules if connector is ready.
        This should be called once the connector has finished start_network().
        """
        if self._precision_detected:
            return  # Already attempted detection

        connector = self.connectors.get(self.config.exchange)
        if not connector:
            self.logger().debug(f"Connector {self.config.exchange} not found in connectors dict")
            return

        # Only attempt detection if connector is ready (start_network() has completed)
        if not connector.ready:
            self.logger().debug(f"Connector {self.config.exchange} not ready yet (ready={connector.ready})")
            return

        self.logger().info(f"Attempting precision detection for {self.config.exchange} (connector is ready)")

        # Try to detect precision from trading rules
        try:
            # For PaperTradeExchange, get underlying connector from order book tracker
            real_connector = connector
            if hasattr(connector, 'order_book_tracker') and connector.order_book_tracker:
                data_source = connector.order_book_tracker.data_source
                if hasattr(data_source, '_connector'):
                    real_connector = data_source._connector
                elif hasattr(data_source, 'connector'):
                    real_connector = data_source.connector

            # Try to manually trigger trading rules update if not loaded (only once)
            if hasattr(real_connector, '_update_trading_rules') and not self._trading_rules_update_triggered:
                rules_dict = getattr(real_connector, '_trading_rules', {})
                if not rules_dict or self.config.trading_pair not in rules_dict:
                    self.logger().info("Trading rules not loaded, attempting to load them...")
                    # Try to trigger update (this is async, so we'll check again next tick)
                    try:
                        # Create a task to update trading rules
                        asyncio.create_task(real_connector._update_trading_rules())
                        self.logger().info("Scheduled trading rules update task")
                        self._trading_rules_update_triggered = True
                        return  # Will check again next tick
                    except Exception as e:
                        self.logger().warning(f"Could not trigger trading rules update: {e}")
                        self._trading_rules_update_triggered = True  # Mark as attempted even if failed

            # Check if trading rules are available (try both _trading_rules and trading_rules)
            has_public = hasattr(real_connector, 'trading_rules')
            has_private = hasattr(real_connector, '_trading_rules')
            self.logger().info(
                f"Checking trading rules: hasattr(trading_rules)={has_public}, "
                f"hasattr(_trading_rules)={has_private}, "
                f"type={type(real_connector).__name__}"
            )

            # Try to get trading rules dict (prefer private attribute, fallback to property)
            rules_dict = None
            if has_private:
                rules_dict = getattr(real_connector, '_trading_rules', None)
            elif has_public:
                rules_dict = getattr(real_connector, 'trading_rules', None)

            if rules_dict is not None:
                self.logger().info(
                    f"Trading rules dict found: keys={list(rules_dict.keys()) if rules_dict else 'empty'}, "
                    f"looking for={self.config.trading_pair}, "
                    f"dict_type={type(rules_dict)}"
                )
                trading_rule = rules_dict.get(self.config.trading_pair) if rules_dict else None
                if trading_rule:
                    # Detect price precision
                    if trading_rule.min_price_increment > 0:
                        precision = int(-math.log10(float(trading_rule.min_price_increment)))
                        self._price_precision = max(2, min(precision, 8))
                        self.logger().info(
                            f"Detected price precision: {self._price_precision} decimals "
                            f"(from trading rules: min_price_increment={trading_rule.min_price_increment})"
                        )

                    # Detect amount precision
                    if trading_rule.min_base_amount_increment > 0:
                        precision = int(-math.log10(float(trading_rule.min_base_amount_increment)))
                        self._amount_precision = max(2, min(precision, 8))
                        self.logger().info(
                            f"Detected amount precision: {self._amount_precision} decimals "
                            f"(from trading rules: min_base_amount_increment={trading_rule.min_base_amount_increment})"
                        )

                    if self._price_precision and self._amount_precision:
                        self.logger().info(
                            f"Precision detection complete: Price={self._price_precision} decimals, "
                            f"Amount={self._amount_precision} decimals"
                        )
                        self._precision_detected = True
                        return

            # If we get here, trading rules aren't available yet
            self.logger().warning(
                f"Trading rules not yet available for {self.config.trading_pair}. "
                f"Will use defaults until connector is fully ready. "
                f"real_connector={type(real_connector).__name__}, "
                f"has_trading_rules={hasattr(real_connector, 'trading_rules')}"
            )
        except Exception as e:
            self.logger().warning(f"Could not detect precision yet: {e}", exc_info=True)

    async def _fetch_precision_from_api(self):
        """
        Fetch precision directly from Cofinex API.

        This is a FALLBACK method primarily for paper trading where trading rules
        may not be loaded via start_network(). For live trading, trading rules
        should be loaded via the connector's start_network() method, and this
        API fetch should not be necessary.

        However, this method can also serve as a backup if trading rules fail
        to load for any reason in live trading.
        """
        try:
            # Convert trading pair to API format (CNX-USDT -> CNX_USDT)
            api_symbol = self.config.trading_pair.replace("-", "_").upper()
            url = f"https://marketdata.cofinex.io/spot/v1/tradepair/{api_symbol}"

            self.logger().info(f"Fetching precision from Cofinex API: {url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()

                        # Parse the response format:
                        # {"code": "200", "msg": "success", "data": {"symbol": "CNX_USDT", ...,
                        #   "data": {"pricePrecision": "4", "quantityPrecision": "2", ...}}}
                        if data.get("code") == "200" and data.get("data"):
                            pair_data = data.get("data", {})
                            if isinstance(pair_data, dict) and "data" in pair_data:
                                pair_info = pair_data["data"]
                            else:
                                pair_info = pair_data

                            price_precision_str = pair_info.get("pricePrecision", "")
                            quantity_precision_str = pair_info.get("quantityPrecision", "")

                            if price_precision_str:
                                try:
                                    price_precision = int(price_precision_str)
                                    self._price_precision = max(2, min(price_precision, 8))
                                    self.logger().info(
                                        f"Fetched price precision from API: {self._price_precision} decimals "
                                        f"(pricePrecision={price_precision_str})"
                                    )
                                except (ValueError, TypeError):
                                    self.logger().warning(f"Invalid pricePrecision value: {price_precision_str}")

                            if quantity_precision_str:
                                try:
                                    quantity_precision = int(quantity_precision_str)
                                    self._amount_precision = max(2, min(quantity_precision, 8))
                                    self.logger().info(
                                        f"Fetched amount precision from API: {self._amount_precision} decimals "
                                        f"(quantityPrecision={quantity_precision_str})"
                                    )
                                except (ValueError, TypeError):
                                    self.logger().warning(f"Invalid quantityPrecision value: {quantity_precision_str}")

                            if self._price_precision and self._amount_precision:
                                self.logger().info(
                                    f"Precision fetched from API (fallback method): Price={self._price_precision} decimals, "
                                    f"Amount={self._amount_precision} decimals"
                                )
                                # Only mark as detected if we haven't already detected from trading rules
                                # This ensures trading rules take precedence for live trading
                                if not self._precision_detected:
                                    self._precision_detected = True
                                return
                            else:
                                self.logger().warning(
                                    f"Could not parse precision from API response: "
                                    f"pricePrecision={price_precision_str}, quantityPrecision={quantity_precision_str}"
                                )
                        else:
                            self.logger().warning(f"Cofinex API returned error: {data.get('msg', 'Unknown')}")
                    else:
                        self.logger().warning(f"Cofinex API request failed: HTTP {response.status}")

        except asyncio.TimeoutError:
            self.logger().warning("Cofinex API request timeout while fetching precision")
        except Exception as e:
            self.logger().error(f"Error fetching precision from Cofinex API: {e}", exc_info=True)

    def on_tick(self):
        """
        Main strategy logic - called every tick
        """
        # Try to detect precision once connector is ready (only once)
        if not self._precision_detected:
            self._detect_precision_if_ready()

        # Update price shift from Bitget if enabled
        if self.config.price_shift_enabled:
            if self.current_timestamp >= self.last_shift_update_timestamp + self.config.price_shift_update_interval:
                asyncio.create_task(self._fetch_bitget_change24h())

        # Check if we need to refresh (triggered by fill or Bitget shift change)
        if self.refresh_pending:
            if self.current_timestamp >= self.last_fill_timestamp + self.config.filled_order_delay:
                self.logger().info("Refreshing orders (triggered by fill or Bitget shift change)...")
                safe_ensure_future(self._refresh_orders())
                self.refresh_pending = False

        # Check if it's time for periodic refresh (or initial placement if create_timestamp is 0)
        elif self.create_timestamp == 0 or self.create_timestamp <= self.current_timestamp:
            self.logger().info("Initial order placement or periodic refresh triggered")
            safe_ensure_future(self._refresh_orders())
            # Note: create_timestamp is now set inside _refresh_orders() after successful placement

        # Check if orders were cancelled externally (paper trading timeout, etc.)
        # If we expected to have orders but they're missing, place new ones
        elif self.create_timestamp > 0:  # We've placed orders before
            active_orders = self.get_active_orders(self.config.exchange)
            expected_order_count = self.config.order_levels * 2  # Buy + Sell per level

            # If we have significantly fewer orders than expected, something cancelled them
            if len(active_orders) < expected_order_count * 0.5:  # Less than half of expected
                self.logger().warning(
                    f"Detected missing orders: Expected ~{expected_order_count}, found {len(active_orders)}. "
                    f"Orders may have been cancelled externally. Placing new orders..."
                )
                safe_ensure_future(self._refresh_orders())

    async def _fetch_bitget_change24h(self):
        """
        Fetch change24h from Bitget API and update price shift

        Bitget API returns change24h as a decimal (e.g., 0.00309 = 0.309%)
        We multiply by 100 to get percentage, then apply as price shift
        """
        try:
            url = f"{self.config.bitget_api_url}?symbol={self.config.bitget_symbol}"

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()

                        if data.get("code") == "00000" and data.get("data"):
                            ticker_data = data["data"][0]
                            change24h_raw = Decimal(str(ticker_data.get("change24h", "0.0")))

                            # Convert to percentage: change24h * 100
                            # Example: change24h = 0.00309 → percentage = 0.309%
                            change24h_percentage = change24h_raw * Decimal("100")

                            # Apply multiplier if configured
                            self.bitget_change24h = change24h_raw
                            new_shift = change24h_percentage * self.config.price_shift_multiplier

                            # Check if shift changed significantly (only if we have a previous value to compare)
                            # Skip check on very first update when previous_price_shift is still 0.0
                            if self.previous_price_shift != Decimal("0.0"):
                                shift_change = abs(new_shift - self.previous_price_shift)
                                if shift_change >= self.config.price_shift_change_threshold:
                                    self.logger().info(
                                        f"Bitget shift changed significantly: {self.previous_price_shift:.4f}% → {new_shift:.4f}% "
                                        f"(change: {shift_change:.4f}%) - Triggering refresh"
                                    )
                                    # Trigger refresh (unless fill-based refresh is pending)
                                    if not self.refresh_pending:
                                        self.refresh_pending = True
                                        self.last_fill_timestamp = self.current_timestamp
                                        self.logger().info(
                                            f"Bitget shift change detected, will refresh orders in "
                                            f"{self.config.filled_order_delay}s"
                                        )

                            # Update both current and previous shift (previous is used for next comparison)
                            self.current_price_shift = new_shift
                            self.previous_price_shift = new_shift
                            self.last_shift_update_timestamp = self.current_timestamp

                            self.logger().info(
                                f"Bitget change24h updated: {change24h_raw} → {change24h_percentage:.4f}% "
                                f"(Shift: {self.current_price_shift:.4f}%)"
                            )
                        else:
                            self.logger().warning(f"Bitget API returned error: {data.get('msg', 'Unknown')}")
                    else:
                        self.logger().warning(f"Bitget API request failed: HTTP {response.status}")

        except asyncio.TimeoutError:
            self.logger().warning("Bitget API request timeout")
        except Exception as e:
            self.logger().error(f"Error fetching Bitget change24h: {e}")

    async def _refresh_orders(self):
        """
        Cancel existing orders and place new multi-level orders.
        Waits for all cancellations to complete before placing new orders.
        """
        # Cancel all existing orders and wait for completion
        await self._cancel_all_orders()

        # Create multi-level order proposal with price shift
        proposal: List[OrderCandidate] = self._create_multi_level_proposal()

        if not proposal:
            self.logger().warning("No orders to place - check price source and balances")
            return

        # Log current balances for debugging
        connector = self.connectors[self.config.exchange]
        try:
            base_asset = self.config.trading_pair.split('-')[0]
            quote_asset = self.config.trading_pair.split('-')[1]
            base_balance = connector.get_available_balance(base_asset)
            quote_balance = connector.get_available_balance(quote_asset)
            self.logger().info(
                f"Current balances: {base_asset}={base_balance:.{self.amount_precision}f}, "
                f"{quote_asset}={quote_balance:.2f}"
            )
        except Exception as e:
            self.logger().debug(f"Could not log balances: {e}")

        # Adjust proposal based on available budget
        proposal_adjusted: List[OrderCandidate] = self._adjust_proposal_to_budget(proposal)

        # Place orders with 10ms delay between each to avoid Exchange-Core duplicate order ID issues
        await self._place_orders(proposal_adjusted)

        # Log order placement summary
        buy_orders = [o for o in proposal_adjusted if o.order_side == TradeType.BUY]
        sell_orders = [o for o in proposal_adjusted if o.order_side == TradeType.SELL]
        self.logger().info(
            f"Placed {len(buy_orders)} buy orders and {len(sell_orders)} sell orders "
            f"across {self.config.order_levels} levels "
            f"(Price shift: {self.current_price_shift:.4f}% from Bitget change24h)"
        )

        # Set next refresh timestamp after successful order placement
        self.create_timestamp = self.config.order_refresh_time + self.current_timestamp
        self.logger().info(f"Next periodic refresh scheduled in {self.config.order_refresh_time}s (at timestamp {self.create_timestamp})")

    def _get_reference_price(self) -> Optional[Decimal]:
        """
        Get reference price with dynamic price shift applied
        Shift is driven by Bitget's change24h value

        Formula:
        - change24h from Bitget (e.g., 0.00309)
        - Convert to percentage: 0.00309 * 100 = 0.309%
        - Apply as shift: reference = base_price * (1 + 0.309/100)

        Note: If LastTrade price is not available (e.g., no trades yet), falls back to MidPrice
        """
        connector = self.connectors[self.config.exchange]

        try:
            base_price = connector.get_price_by_type(self.config.trading_pair, self.price_source)

            # If LastTrade price is not available from connector (e.g., paper trading doesn't track it)
            # First try our internally tracked last trade price, then fall back to MidPrice
            if (base_price is None or base_price.is_nan()) and self.price_source == PriceType.LastTrade:
                if self._last_trade_price is not None:
                    self.logger().debug(f"Using internally tracked last trade price: {self._last_trade_price:.{self.price_precision}f}")
                    base_price = self._last_trade_price
                else:
                    self.logger().info(f"Last trade price not available (no fills yet), falling back to mid price for {self.config.trading_pair}")
                    base_price = connector.get_price_by_type(self.config.trading_pair, PriceType.MidPrice)

            if base_price is None or base_price.is_nan():
                self.logger().warning(f"Could not get price for {self.config.trading_pair} (tried {self.price_source})")
                return None

            # Apply dynamic price shift from Bitget
            if self.config.price_shift_enabled:
                # current_price_shift is already in percentage (change24h * 100)
                # Convert to multiplier: 1% = 0.01
                shift_multiplier = Decimal("1") + (self.current_price_shift / Decimal("100"))
                shifted_price = base_price * shift_multiplier

                # Log price details (only log if price changed significantly to avoid spam)
                if not hasattr(self, '_last_logged_base_price') or abs(base_price - self._last_logged_base_price) > Decimal("0.0001"):
                    self.logger().info(
                        f"Reference price update: Base={base_price:.{self.price_precision}f}, "
                        f"Bitget change24h={self.bitget_change24h:.6f}, "
                        f"Shift={self.current_price_shift:.4f}%, "
                        f"Shifted={shifted_price:.{self.price_precision}f}"
                    )
                    self._last_logged_base_price = base_price

                return shifted_price
            else:
                return base_price

        except Exception as e:
            self.logger().error(f"Error getting price: {e}")
            return None

    def _create_multi_level_proposal(self) -> List[OrderCandidate]:
        """
        Create multi-level order proposal with Level 1 for self-trading
        All levels calculated relative to the shifted reference price

        Level Structure:
        - Level 1: Overlapping orders (buy >= sell) for self-trading - fixed $10 amount
        - Levels 2-5: Different amounts for buy ($10-$50) and sell ($500-$1500)
        """
        orders = []

        # Get reference price (with shift applied)
        ref_price = self._get_reference_price()
        if ref_price is None:
            return []

        # Get connector for quantizing prices
        connector = self.connectors[self.config.exchange]

        # For PaperTradeExchange, try to get underlying connector from order book tracker
        quantize_connector = connector
        if hasattr(connector, 'order_book_tracker') and connector.order_book_tracker:
            # PaperTradeExchange wraps a real connector - get it from the order book tracker
            data_source = connector.order_book_tracker.data_source
            # Try both _connector (private) and connector (public) attributes
            if hasattr(data_source, '_connector'):
                underlying = data_source._connector
                # Only use underlying connector if it has trading rules for this pair
                if hasattr(underlying, 'trading_rules') and self.config.trading_pair in underlying.trading_rules:
                    quantize_connector = underlying
                    self.logger().debug(f"Using underlying connector {quantize_connector.name} for quantization")
            elif hasattr(data_source, 'connector'):
                underlying = data_source.connector
                if hasattr(underlying, 'trading_rules') and self.config.trading_pair in underlying.trading_rules:
                    quantize_connector = underlying
                    self.logger().debug(f"Using underlying connector {quantize_connector.name} for quantization")

        # Level 1: Overlapping orders for self-trading (fixed amount from config)
        level1_buy_price = ref_price * (Decimal("1") + self.config.level1_buy_offset)
        level1_sell_price = ref_price * (Decimal("1") + self.config.level1_sell_offset)

        # Quantize prices using connector's quantization method
        try:
            self.logger().debug(
                f"Quantizing Level 1 prices using {type(quantize_connector).__name__}: "
                f"buy_before={level1_buy_price}, sell_before={level1_sell_price}"
            )
            level1_buy_price = quantize_connector.quantize_order_price(self.config.trading_pair, level1_buy_price)
            level1_sell_price = quantize_connector.quantize_order_price(self.config.trading_pair, level1_sell_price)
            self.logger().debug(
                f"Quantized Level 1 prices: buy_after={level1_buy_price}, sell_after={level1_sell_price}"
            )
        except (KeyError, AttributeError) as e:
            # Trading rules not loaded yet - use PaperTradeExchange's quantization
            self.logger().warning(f"Trading rules not available, using PaperTradeExchange quantization: {e}")
            level1_buy_price = connector.quantize_order_price(self.config.trading_pair, level1_buy_price)
            level1_sell_price = connector.quantize_order_price(self.config.trading_pair, level1_sell_price)

        # Check if Level 1 will overlap
        level1_overlap = level1_buy_price >= level1_sell_price
        if level1_overlap and self.config.enable_self_trading:
            self.logger().info(
                f"Level 1 OVERLAP: Buy @ {level1_buy_price:.{self.price_precision}f} >= Sell @ {level1_sell_price:.{self.price_precision}f} "
                f"(Ref: {ref_price:.{self.price_precision}f}, Shift: {self.current_price_shift:.4f}%)"
            )
        else:
            self.logger().info(
                f"Level 1: Buy @ {level1_buy_price:.{self.price_precision}f}, Sell @ {level1_sell_price:.{self.price_precision}f} "
                f"(No overlap)"
            )

        # Create Level 1 orders (amount calculated dynamically to ensure $100 USDT value)
        # Calculate amount based on reference price to ensure it's always worth level1_order_value_usd
        level1_order_amount = self.config.level1_order_value_usd / ref_price

        # Quantize the amount using connector's quantization method
        try:
            level1_order_amount = quantize_connector.quantize_order_amount(
                self.config.trading_pair, level1_order_amount
            )
        except (KeyError, AttributeError):
            level1_order_amount = connector.quantize_order_amount(
                self.config.trading_pair, level1_order_amount
            )

        # Ensure minimum notional is met (add a small buffer)
        min_notional = Decimal("10")  # Default minimum
        try:
            if hasattr(quantize_connector, '_trading_rules') and self.config.trading_pair in quantize_connector._trading_rules:
                trading_rule = quantize_connector._trading_rules[self.config.trading_pair]
                if hasattr(trading_rule, 'min_notional_size'):
                    min_notional = trading_rule.min_notional_size
        except Exception:
            pass  # Use default if can't get trading rule

        # Verify the order value meets minimum notional
        order_value = level1_order_amount * ref_price
        if order_value < min_notional:
            # Increase amount to meet minimum notional
            level1_order_amount = (min_notional * Decimal("1.1")) / ref_price  # 10% buffer
            try:
                level1_order_amount = quantize_connector.quantize_order_amount(
                    self.config.trading_pair, level1_order_amount
                )
            except (KeyError, AttributeError):
                level1_order_amount = connector.quantize_order_amount(
                    self.config.trading_pair, level1_order_amount
                )

        self.logger().info(
            f"Level 1 order amount: {level1_order_amount:.{self.amount_precision}f} "
            f"(target: ${self.config.level1_order_value_usd} USDT, "
            f"actual: ${level1_order_amount * ref_price:.2f} USDT @ {ref_price:.{self.price_precision}f})"
        )

        orders.append(OrderCandidate(
            trading_pair=self.config.trading_pair,
            is_maker=True,
            order_type=OrderType.LIMIT,
            order_side=TradeType.BUY,
            amount=level1_order_amount,
            price=level1_buy_price
        ))

        orders.append(OrderCandidate(
            trading_pair=self.config.trading_pair,
            is_maker=True,
            order_type=OrderType.LIMIT,
            order_side=TradeType.SELL,
            amount=level1_order_amount,
            price=level1_sell_price
        ))

        # Levels 2+: Config-driven order amounts and spacing
        # Calculate relative to reference price (not Level 1) to maintain proper spacing
        # Level 1 uses special offsets for self-trading overlap, but Levels 2+ use config-driven spacing
        large_spacing_enabled = (self.config.large_level_sell_start > 0 and
                                 self.config.large_level_sell_start <= self.config.order_levels)

        for level in range(2, self.config.order_levels + 1):
            # Determine if this level uses large spacing for SELL orders
            use_large_spacing_sell = large_spacing_enabled and level >= self.config.large_level_sell_start

            # Calculate price spacing for SELL orders
            if use_large_spacing_sell:
                # Large spacing: additive from previous level (each level = previous level + increment)
                prev_level = level - 1
                # Calculate previous level's sell price
                if prev_level < self.config.large_level_sell_start:
                    # Previous level uses normal spacing
                    prev_level_offset = (prev_level - 1) * self.config.level_spread
                    prev_level_sell_price = ref_price * (Decimal("1") + prev_level_offset)
                else:
                    # Previous level is also a large level - calculate it recursively
                    # For any large level M: calculate all previous large levels
                    first_large_level_offset = (self.config.large_level_sell_start - 1) * self.config.level_spread
                    first_large_level_normal_price = ref_price * (Decimal("1") + first_large_level_offset)
                    large_spread_increment = self.config.large_level_sell_spread_multiplier * self.config.level_spread * ref_price
                    first_large_level_price = first_large_level_normal_price + large_spread_increment
                    # Previous level's price: first large level + (prev_level - large_level_sell_start) increments
                    num_prev_increments = prev_level - self.config.large_level_sell_start
                    prev_level_sell_price = first_large_level_price + (num_prev_increments * large_spread_increment)

                # Current level: previous level + increment
                large_spread_increment = self.config.large_level_sell_spread_multiplier * self.config.level_spread * ref_price
                level_sell_price = prev_level_sell_price + large_spread_increment
            else:
                # Normal spacing: cumulative offset from reference price
                level_offset = (level - 1) * self.config.level_spread
                level_sell_price = ref_price * (Decimal("1") + level_offset)

            # Buy orders always use normal spacing (go below reference price)
            level_offset = (level - 1) * self.config.level_spread
            level_buy_price = ref_price * (Decimal("1") - level_offset)

            # Quantize prices
            try:
                level_buy_price = quantize_connector.quantize_order_price(self.config.trading_pair, level_buy_price)
                level_sell_price = quantize_connector.quantize_order_price(self.config.trading_pair, level_sell_price)
            except (KeyError, AttributeError):
                level_buy_price = connector.quantize_order_price(self.config.trading_pair, level_buy_price)
                level_sell_price = connector.quantize_order_price(self.config.trading_pair, level_sell_price)

            # Calculate order amounts based on USD value ranges (config-driven)
            # Buy orders: always use normal range
            buy_usd_value = Decimal(str(random.uniform(
                float(self.config.normal_buy_min_usd),
                float(self.config.normal_buy_max_usd)
            )))
            buy_amount = buy_usd_value / level_buy_price  # Convert USD to base currency

            # Sell orders: use large range if this is a large level, otherwise normal range
            if use_large_spacing_sell:
                sell_usd_value = Decimal(str(random.uniform(
                    float(self.config.large_level_sell_min_usd),
                    float(self.config.large_level_sell_max_usd)
                )))
            else:
                sell_usd_value = Decimal(str(random.uniform(
                    float(self.config.normal_sell_min_usd),
                    float(self.config.normal_sell_max_usd)
                )))
            sell_amount = sell_usd_value / level_sell_price  # Convert USD to base currency

            # Quantize amounts to exchange precision
            try:
                buy_amount = quantize_connector.quantize_order_amount(self.config.trading_pair, buy_amount)
                sell_amount = quantize_connector.quantize_order_amount(self.config.trading_pair, sell_amount)
            except (KeyError, AttributeError):
                buy_amount = connector.quantize_order_amount(self.config.trading_pair, buy_amount)
                sell_amount = connector.quantize_order_amount(self.config.trading_pair, sell_amount)

            # Log order details
            spacing_type = "LARGE" if use_large_spacing_sell else "normal"
            self.logger().info(
                f"Level {level}: Buy {buy_amount:.{self.amount_precision}f} @ {level_buy_price:.{self.price_precision}f} "
                f"(${buy_usd_value:.2f}) | "
                f"Sell {sell_amount:.{self.amount_precision}f} @ {level_sell_price:.{self.price_precision}f} "
                f"(${sell_usd_value:.2f}) [{spacing_type}]"
            )

            orders.append(OrderCandidate(
                trading_pair=self.config.trading_pair,
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.BUY,
                amount=buy_amount,
                price=level_buy_price
            ))

            orders.append(OrderCandidate(
                trading_pair=self.config.trading_pair,
                is_maker=True,
                order_type=OrderType.LIMIT,
                order_side=TradeType.SELL,
                amount=sell_amount,
                price=level_sell_price
            ))

        return orders

    def _adjust_proposal_to_budget(self, proposal: List[OrderCandidate]) -> List[OrderCandidate]:
        """
        Adjust order amounts based on available balance
        """
        connector = self.connectors[self.config.exchange]
        adjusted = connector.budget_checker.adjust_candidates(proposal, all_or_none=False)

        # Check if any orders were reduced to zero
        zero_amount_orders = [o for o in adjusted if o.amount == 0]
        if zero_amount_orders:
            buy_zero = [o for o in zero_amount_orders if o.order_side == TradeType.BUY]
            sell_zero = [o for o in zero_amount_orders if o.order_side == TradeType.SELL]
            if buy_zero:
                self.logger().warning(
                    f"{len(buy_zero)} BUY orders reduced to zero due to insufficient USDT balance. "
                    f"Please set paper trade USDT balance."
                )
            if sell_zero:
                self.logger().warning(
                    f"{len(sell_zero)} SELL orders reduced to zero due to insufficient {self.config.trading_pair.split('-')[0]} balance. "
                    f"Please set paper trade {self.config.trading_pair.split('-')[0]} balance to enable sell orders."
                )

        return [o for o in adjusted if o.amount > 0]  # Filter out zero-amount orders

    async def _place_orders(self, proposal: List[OrderCandidate]) -> None:
        """
        Place orders from proposal with 10ms delay between each order
        to avoid Exchange-Core duplicate order ID issues
        """
        for order in proposal:
            if order.amount > 0:
                self._place_order(connector_name=self.config.exchange, order=order)
                # Add 10ms delay between orders to prevent Exchange-Core duplicate order ID bug
                # This ensures orders are placed in different milliseconds
                await asyncio.sleep(0.01)

    def _place_order(self, connector_name: str, order: OrderCandidate):
        """
        Place a single order
        """
        try:
            if order.order_side == TradeType.SELL:
                self.sell(
                    connector_name=connector_name,
                    trading_pair=order.trading_pair,
                    amount=order.amount,
                    order_type=order.order_type,
                    price=order.price
                )
            elif order.order_side == TradeType.BUY:
                self.buy(
                    connector_name=connector_name,
                    trading_pair=order.trading_pair,
                    amount=order.amount,
                    order_type=order.order_type,
                    price=order.price
                )
        except Exception as e:
            self.logger().error(f"Error placing {order.order_side.name} order: {e}")

    async def _cancel_all_orders(self):
        """
        Cancel all active orders and wait for completion.
        Uses the connector's cancel_all() method which waits for all cancellations to complete.
        """
        connector = self.connectors[self.config.exchange]
        active_orders = self.get_active_orders(connector_name=self.config.exchange)

        if active_orders:
            self.logger().info(f"Cancelling {len(active_orders)} active orders and waiting for completion...")
            try:
                # Use connector's cancel_all() which waits for all cancellations to complete
                # Timeout: at least 1 second per order, minimum 10 seconds, maximum 60 seconds
                timeout = min(max(len(active_orders) * 1.0, 10.0), 60.0)
                cancellation_results = await connector.cancel_all(timeout_seconds=timeout)

                successful = [r for r in cancellation_results if r.success]
                failed = [r for r in cancellation_results if not r.success]

                if successful:
                    self.logger().info(f"Successfully cancelled {len(successful)} orders")
                if failed:
                    self.logger().warning(f"Failed to cancel {len(failed)} orders: {[r.order_id for r in failed]}")
            except Exception as e:
                self.logger().error(f"Error during batch cancellation: {e}", exc_info=True)
                # Fallback: try individual cancellations
                self.logger().info("Falling back to individual cancellations...")
                for order in active_orders:
                    try:
                        self.cancel(self.config.exchange, order.trading_pair, order.client_order_id)
                    except Exception as cancel_error:
                        self.logger().error(f"Error cancelling order {order.client_order_id}: {cancel_error}")
                # Give some time for individual cancellations to process
                await asyncio.sleep(0.5)

    def _is_level1_fill(self, event: OrderFilledEvent) -> bool:
        """
        Determine if a fill is likely from Level 1 (self-trade)
        Checks if fill price is within Level 1 offset range from reference price
        """
        try:
            ref_price = self._get_reference_price()
            if ref_price:
                # Level 1 orders are placed at ref_price ± level1_offset
                # Check if fill price is within the Level 1 offset range
                price_diff_pct = abs(event.price - ref_price) / ref_price

                # Use the maximum of the absolute offsets to determine Level 1 range
                max_level1_offset = max(
                    abs(self.config.level1_buy_offset),
                    abs(self.config.level1_sell_offset)
                )

                # Add a small tolerance (10% of offset) to account for price quantization
                tolerance = max_level1_offset * Decimal("0.1")
                is_level1 = price_diff_pct <= (max_level1_offset + tolerance)

                return is_level1
        except Exception as e:
            self.logger().debug(f"Error checking Level 1 fill: {e}")
        return False

    def did_fill_order(self, event: OrderFilledEvent):
        """
        Called when an order is filled
        Conditionally triggers refresh based on fill level and configuration
        """
        self.total_fills += 1
        self.last_fill_timestamp = self.current_timestamp

        # Track last trade price internally (for paper trading where connector doesn't track it)
        # This allows "last" price type to work in paper trading
        if self.config.price_type == "last":
            self._last_trade_price = Decimal(str(event.price))
            self.logger().debug(f"Updated internal last trade price: {self._last_trade_price:.{self.price_precision}f}")

        # Check if this is likely a Level 1 fill (self-trade)
        is_level1 = self._is_level1_fill(event)

        if is_level1:
            self.level1_fills += 1
            self.logger().info(
                f"Level 1 fill detected (likely self-trade): "
                f"{event.trade_type.name} {round(event.amount, self.amount_precision)} @ {event.price:.{self.price_precision}f}"
            )

            # Only refresh if configured to do so
            if self.config.refresh_on_level1_fill:
                self.refresh_pending = True
                self.logger().info(
                    f"Level 1 fill - refresh_on_level1_fill=True, will refresh in {self.config.filled_order_delay}s"
                )
            else:
                self.logger().info(
                    "Level 1 fill - refresh_on_level1_fill=False, NOT refreshing (prevents price contamination)"
                )
        else:
            # Level 2+ fill (real market activity)
            if self.config.refresh_on_level2_5_fill:
                self.refresh_pending = True
                self.logger().info(
                    f"Level 2+ fill (real market activity) - will refresh in {self.config.filled_order_delay}s"
                )
            else:
                self.logger().info(
                    "Level 2+ fill - refresh_on_level2_5_fill=False, NOT refreshing"
                )

        msg = (
            f"{event.trade_type.name} {round(event.amount, self.amount_precision)} {event.trading_pair} "
            f"on {self.config.exchange} at {event.price:.{self.price_precision}f}"
        )
        self.logger().info(msg)
        self.notify_hb_app_with_timestamp(msg)

        # Log statistics
        refresh_status = "Yes" if self.refresh_pending else "No"
        self.logger().info(
            f"Fill #{self.total_fills} | Level 1 fills: {self.level1_fills} | "
            f"Price shift: {self.current_price_shift:.4f}% | "
            f"Will refresh: {refresh_status}"
        )

    def format_status(self) -> str:
        """
        Returns status string for display in UI
        """
        active_orders = self.get_active_orders(connector_name=self.config.exchange)
        buy_orders = [o for o in active_orders if o.is_buy]
        sell_orders = [o for o in active_orders if not o.is_buy]

        # Get prices
        connector = self.connectors[self.config.exchange]
        try:
            base_mid = connector.get_price_by_type(self.config.trading_pair, PriceType.MidPrice)
            ref_price = self._get_reference_price()
            base_mid_str = f"{base_mid:.2f}" if base_mid else "N/A"
            ref_price_str = f"{ref_price:.2f}" if ref_price else "N/A"
        except Exception:
            base_mid_str = "N/A"
            ref_price_str = "N/A"

        # Check Level 1 overlap
        level1_overlap = False
        if buy_orders and sell_orders:
            best_buy = max(buy_orders, key=lambda x: x.price)
            best_sell = min(sell_orders, key=lambda x: x.price)
            level1_overlap = best_buy.price >= best_sell.price

        lines = [
            "",
            f"  Exchange: {self.config.exchange}",
            f"  Trading Pair: {self.config.trading_pair}",
            f"  Base Mid Price: {base_mid_str}",
            f"  Reference Price (shifted): {ref_price_str}",
            "",
            "  Dynamic Price Shift (Bitget):",
            f"    Enabled: {self.config.price_shift_enabled}",
            f"    Bitget change24h: {self.bitget_change24h}",
            f"    Current Shift: {self.current_price_shift:.4f}%",
            f"    Last Update: {self.current_timestamp - self.last_shift_update_timestamp:.0f}s ago",
            "",
            f"  Active Orders: {len(active_orders)}",
            f"    - Buy Orders: {len(buy_orders)}",
            f"    - Sell Orders: {len(sell_orders)}",
            "",
            "  Statistics:",
            f"    Total Fills: {self.total_fills}",
            f"    Level 1 Fills: {self.level1_fills}",
        ]

        if buy_orders and sell_orders:
            best_buy = max(buy_orders, key=lambda x: x.price)
            best_sell = min(sell_orders, key=lambda x: x.price)
            lines.append(f"    Level 1 Overlap: {level1_overlap}")
            lines.append(f"    Best Buy: {best_buy.price:.2f}")
            lines.append(f"    Best Sell: {best_sell.price:.2f}")
            if level1_overlap:
                spread = ((best_buy.price - best_sell.price) / best_sell.price) * 100
                lines.append(f"    Overlap Spread: {spread:.4f}%")

        if self.refresh_pending:
            time_until_refresh = (self.last_fill_timestamp + self.config.filled_order_delay) - self.current_timestamp
            lines.append(f"    Refreshing in: {time_until_refresh:.1f}s")

        return "\n".join(lines)

    @property
    def should_cancel_orders_on_stop(self) -> bool:
        """
        Property that indicates whether orders should be cancelled when the bot stops.
        This is checked by the stop command to determine if orders should be cancelled.
        """
        return self.config.cancel_orders_on_stop

    async def on_stop(self):
        """
        Called when the bot is stopping.
        Logs whether orders will be kept or cancelled based on config.
        """
        if self.config.cancel_orders_on_stop:
            self.logger().info("Strategy configured to cancel orders on stop - orders will be cancelled")
        else:
            active_orders = self.get_active_orders(connector_name=self.config.exchange)
            if active_orders:
                self.logger().info(
                    f"Strategy configured to keep orders on stop - {len(active_orders)} orders will remain active on the exchange"
                )
            else:
                self.logger().info("Strategy configured to keep orders on stop - no active orders to keep")
