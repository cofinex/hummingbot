"""
Cofinex Exchange Connector

This is the main connector class for the Cofinex exchange.
It implements all the necessary methods for trading, order management,
and data retrieval.

TODO: Implement all the methods based on Cofinex API documentation
"""

import asyncio
import decimal
import os
import sys
import threading
import time
import traceback
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from bidict import bidict

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS, cofinex_web_utils as web_utils
from hummingbot.connector.exchange.cofinex.cofinex_api_order_book_data_source import CofinexAPIOrderBookDataSource
from hummingbot.connector.exchange.cofinex.cofinex_auth import CofinexAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import combine_to_hb_trading_pair
from hummingbot.core.data_type.cancellation_result import CancellationResult
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder
from hummingbot.core.data_type.limit_order import LimitOrder
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_tracker import OrderBookTracker
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    pass


class CofinexExchange(ExchangePyBase):
    """
    Cofinex Exchange Connector

    This class implements the main exchange connector interface for Cofinex.
    It handles:
    - Order placement and cancellation
    - Order book management
    - Account balance tracking
    - Trade execution
    - WebSocket data streaming

    TODO: Implement all methods based on Cofinex API documentation
    """

    web_utils = web_utils

    def __init__(
        self,
        trading_pairs: List[str],
        trading_required: bool = True,
        cofinex_username: Optional[str] = None,
        cofinex_password: Optional[str] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
        balance_asset_limit: Optional[Dict[str, Dict[str, Decimal]]] = None,
        rate_limits_share_pct: Decimal = Decimal("100"),
        ws_prefix: Optional[str] = None,
        **kwargs,  # Accept extra params like cofinex_ws_prefix, cofinex_rest_api_base_url (handled from config map)
    ):
        """
        Initialize Cofinex exchange connector

        Args:
            trading_pairs: List of trading pairs to track
            trading_required: Whether trading functionality is required
            cofinex_username: Cofinex username (email) - optional for non-trading instances
            cofinex_password: Cofinex password - optional for non-trading instances
            domain: Domain to connect to ("main" or "testnet")
            balance_asset_limit: Optional balance limits
            rate_limits_share_pct: Rate limit share percentage
            ws_prefix: Optional WebSocket namespace prefix for local testing (e.g., "dev:santosh")
        """
        # Set instance variables before calling super (matching Binance pattern)
        self._trading_pairs = trading_pairs
        self._trading_required = trading_required
        self._domain = domain
        # Handle empty strings from config (convert to None)
        self._cofinex_username = cofinex_username if cofinex_username and cofinex_username.strip() else None
        self._cofinex_password = cofinex_password if cofinex_password and cofinex_password.strip() else None

        # Handle WebSocket prefix and REST API base URL
        # Priority: 1) Parameter, 2) kwargs (from config map), 3) Config map, 4) Environment variable
        from hummingbot.client.config.security import Security

        # Check kwargs first (when passed from config map initialization)
        if ws_prefix is None and "cofinex_ws_prefix" in kwargs:
            ws_prefix = kwargs.pop("cofinex_ws_prefix")
            if ws_prefix:
                ws_prefix = ws_prefix.strip() if isinstance(ws_prefix, str) else None
                if not ws_prefix:
                    ws_prefix = None

        # Try to read from config map (for both "cofinex" and "cofinex_paper_trade", config is under "cofinex")
        connector_config = Security.decrypted_value("cofinex") if ws_prefix is None else None
        if ws_prefix is None and connector_config is not None:
            ws_prefix = getattr(connector_config.hb_config, "cofinex_ws_prefix", None)
            if ws_prefix:
                ws_prefix = ws_prefix.strip() if isinstance(ws_prefix, str) else None
                if not ws_prefix:
                    ws_prefix = None
        # Fallback to environment variable
        if ws_prefix is None:
            ws_prefix = os.getenv("COFINEX_WS_PREFIX") or os.getenv("DEV_NAMESPACE")
            if ws_prefix:
                ws_prefix = ws_prefix.strip()
                if not ws_prefix:
                    ws_prefix = None

        self._ws_prefix = ws_prefix  # Store it (can be None)
        self._last_user_stream_init_log = 0.0

        # Handle REST API base URL
        # Priority: 1) kwargs (from config map), 2) Config map, 3) Environment variable, 4) Default production URL
        rest_api_base_url = None
        if "cofinex_rest_api_base_url" in kwargs:
            rest_api_base_url = kwargs.pop("cofinex_rest_api_base_url")
            if rest_api_base_url:
                rest_api_base_url = rest_api_base_url.strip() if isinstance(rest_api_base_url, str) else None
                if not rest_api_base_url:
                    rest_api_base_url = None

        if rest_api_base_url is None:
            if connector_config is None:
                connector_config = Security.decrypted_value("cofinex")
            if connector_config is not None:
                rest_api_base_url = getattr(connector_config.hb_config, "cofinex_rest_api_base_url", None)
                if rest_api_base_url:
                    rest_api_base_url = rest_api_base_url.strip() if isinstance(rest_api_base_url, str) else None
                    if not rest_api_base_url:
                        rest_api_base_url = None
        # Fallback to environment variable
        if rest_api_base_url is None:
            rest_api_base_url = os.getenv("COFINEX_REST_API_BASE_URL")
            if rest_api_base_url:
                rest_api_base_url = rest_api_base_url.strip()
                if not rest_api_base_url:
                    rest_api_base_url = None
        # Use default production URL if not configured
        if rest_api_base_url is None:
            rest_api_base_url = CONSTANTS.BASE_PATH_URL.get(domain, CONSTANTS.BASE_PATH_URL["main"])

        self._rest_api_base_url = rest_api_base_url

        # Call super with both parameters (ExchangePyBase pattern)
        super().__init__(balance_asset_limit, rate_limits_share_pct)

        # CRITICAL: If we have trading pairs, ensure symbol map will be initialized
        # The trading_pair_symbol_map() property will call _initialize_trading_pair_symbol_map()
        # when accessed, but we need to make sure it's called with the correct trading pairs
        if self._trading_pairs and len(self._trading_pairs) > 0:
            self.logger().info(f"Trading pairs configured in __init__: {self._trading_pairs}")
            # Reset symbol map to None so it will be re-initialized when accessed
            self._trading_pair_symbol_map = None

            # Force immediate initialization if we have trading pairs
            # This ensures the per-pair API is used instead of waiting for property access
            from hummingbot.core.utils.async_utils import safe_ensure_future
            try:
                # Schedule initialization as a background task
                # This will use the per-pair endpoint since self._trading_pairs is now set
                safe_ensure_future(self._initialize_trading_pair_symbol_map())
                self.logger().info("Scheduled symbol map initialization with per-pair API")
            except Exception as e:
                self.logger().warning(f"Could not schedule symbol map initialization: {e}")

        # Authentication - Will be created by authenticator property when needed
        # Note: Base class will set self._auth = self.authenticator in __init__, so don't overwrite it

        # Data storage
        self._order_books: Dict[str, OrderBook] = {}
        self._trading_rules: Dict[str, TradingRule] = {}
        self._in_flight_orders: Dict[str, LimitOrder] = {}
        self._account_balances: Dict[str, Decimal] = {}

        # Network tasks
        # Note: _web_assistants_factory is created by base class __init__ via _create_web_assistants_factory()
        # Note: _user_stream_tracker is created by base class __init__ via _create_user_stream_tracker()
        # Do NOT overwrite them here!
        self._status_polling_task: Optional[asyncio.Task] = None
        # DO NOT set _user_stream_tracker to None - it's already created by super().__init__()
        # self._user_stream_tracker is already initialized by ExchangePyBase.__init__()
        self._order_book_tracker: Optional[OrderBookTracker] = None

        # Rate limiting
        self._last_request_time = 0
        self._request_count = 0

        # Event loop watchdog
        self._loop_watchdog_task: Optional[asyncio.Task] = None
        self._loop_watchdog_thread: Optional[threading.Thread] = None
        self._loop_watchdog_stop: Optional[threading.Event] = None
        self._loop_heartbeat: float = 0.0
        self._loop_watchdog_dumped: bool = False

        self.logger().info("Cofinex connector initialized")

    # =============================================================================
    # PROPERTIES
    # =============================================================================

    @property
    def name(self) -> str:
        """Exchange name"""
        return "cofinex"

    @property
    def authenticator(self):
        """Return authenticator instance (cached)"""
        # For paper trading, return None
        if not self._trading_required:
            return None

        # Cache the authenticator instance to avoid creating new ones each time
        # Note: Base class sets self._auth = self.authenticator in __init__
        # If it's already set and valid, reuse it
        if hasattr(self, '_auth') and self._auth is not None:
            return self._auth

        # If we have credentials, create auth instance
        if self._cofinex_username and self._cofinex_password:
            # Convert SecretStr to cleartext string (handles encrypted credentials from config)
            username = self._cofinex_username
            password = self._cofinex_password

            # Extract cleartext from SecretStr (handles encrypted credentials)
            if hasattr(username, 'get_secret_value'):
                username = username.get_secret_value()
            if hasattr(password, 'get_secret_value'):
                password = password.get_secret_value()

            # Convert to string if not already (handles edge cases)
            username = str(username) if username else None
            password = str(password) if password else None

            if username and password:
                # Note: api_factory will be set later in start_network
                # For now, create auth without api_factory (it will be set later)
                auth = CofinexAuth(
                    username=username,
                    password=password,
                )
                # Cache it
                self._auth = auth
                return auth
        return None

    @property
    def rate_limits_rules(self):
        """Return rate limits rules"""
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self):
        """Return domain"""
        return self._domain

    @property
    def client_order_id_max_length(self):
        """Return max order ID length"""
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self):
        """Return order ID prefix"""
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_rules_request_path(self):
        """Return trading rules request path"""
        return CONSTANTS.TRADING_PAIRS_PATH_URL

    @property
    def trading_pairs_request_path(self):
        """Return trading pairs request path"""
        return CONSTANTS.TRADING_PAIRS_PATH_URL

    @property
    def check_network_request_path(self):
        """Return network check request path"""
        return CONSTANTS.SERVER_TIME_PATH_URL

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        """Return whether cancel requests are synchronous"""
        return True

    @property
    def is_trading_required(self) -> bool:
        """Return whether trading is required"""
        return self._trading_required

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        """Create web assistants factory"""
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
            auth=self.authenticator,
            rest_api_base_url=getattr(self, "_rest_api_base_url", None),
        )

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        """Create order book data source"""
        return CofinexAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self._domain,
            ws_prefix=self._ws_prefix,
        )

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        """Create user stream data source"""
        from hummingbot.connector.exchange.cofinex.cofinex_api_user_stream_data_source import (
            CofinexAPIUserStreamDataSource,
        )
        return CofinexAPIUserStreamDataSource(
            auth=self.authenticator,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self._domain,
        )

    def _is_user_stream_initialized(self):
        """
        Check if user stream is initialized.

        Override to handle the case where _user_stream_tracker might be None
        (e.g., during initialization or if authentication fails).
        """
        now = time.time()
        if now - self._last_user_stream_init_log >= 2.0:
            # Check last receive time for logging (commented out verbose logging)
            # _last_recv = (
            #     None if self._user_stream_tracker is None else self._user_stream_tracker.data_source.last_recv_time
            # )
            # Commented out verbose logging - fires too frequently
            # self.logger().info(
            #     "User stream init check: tracker=%s last_recv_time=%s trading_required=%s",
            #     self._user_stream_tracker,
            #     last_recv,
            #     self.is_trading_required,
            # )
            self._last_user_stream_init_log = now

        if self._user_stream_tracker is None:
            # If tracker is None, check if trading is required
            # If not required, we can proceed without user stream
            return not self.is_trading_required
        # Normal check: tracker exists and has received data, or trading not required
        return self._user_stream_tracker.data_source.last_recv_time > 0 or not self.is_trading_required

    # =============================================================================
    # REQUIRED ABSTRACT METHODS (stub implementations for now)
    # =============================================================================

    def supported_order_types(self):
        """Return supported order types"""
        return [OrderType.LIMIT, OrderType.MARKET]

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception) -> bool:
        """Check if exception is related to time synchronizer"""
        # TODO: Implement based on Cofinex error codes
        return False

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        """Check if exception indicates order not found during status update"""
        # TODO: Implement based on Cofinex error codes
        return False

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        """Check if exception indicates order not found during cancellation"""
        error_str = str(cancelation_exception)
        # Check for 404 HTTP status or "Order not found" message
        return "404" in error_str or "Order not found" in error_str or "not found" in error_str.lower()

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = None,
                 is_maker: Optional[bool] = None) -> TradeFeeBase:
        """Calculate trading fee"""
        from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee
        is_maker = order_type is OrderType.LIMIT_MAKER if is_maker is None else is_maker
        return DeductedFromReturnsTradeFee(percent=self.estimate_fee_pct(is_maker))

    async def _request_order_status(self, tracked_order) -> Any:
        """
        Request order status from exchange.

        Endpoint: GET /order/{orderId}

        Response format:
        {
            "order": {
                "order_id": 1768058112362,
                "symbol_id": 12,
                "symbol": "CNX/USDT",
                "side": "SELL",
                "order_type": "GTC",
                "price": "0.1",
                "size": "10",
                "filled": "0",
                "reserve_bid_price": 0.1,
                "timestamp": 1768038316000,
                "status": "OPEN"
            },
            "timestamp": "2026-01-10T20:45:32.729858"
        }
        """
        exchange_order_id = tracked_order.exchange_order_id
        if not exchange_order_id or exchange_order_id == "UNKNOWN":
            self.logger().warning(f"Cannot request status for order {tracked_order.client_order_id} without exchange_order_id")
            return None

        try:
            rest_assistant = await self._web_assistants_factory.get_rest_assistant()

            # Make API request: GET /order/{orderId}
            rest_api_base_url = getattr(self, "_rest_api_base_url", None)
            url = web_utils.private_rest_url(
                path_url=f"{CONSTANTS.ORDER_STATUS_PATH_URL}/{exchange_order_id}",
                domain=self._domain,
                rest_api_base_url=rest_api_base_url,
            )

            response = await rest_assistant.execute_request(
                url=url,
                method=RESTMethod.GET,
                is_auth_required=True,
                throttler_limit_id=CONSTANTS.GET_ORDER_LIMIT_ID,
            )

            # Parse response
            if not isinstance(response, dict):
                self.logger().error(f"Invalid order status response format: {type(response)}")
                return None

            order_data = response.get("order")
            if not order_data:
                self.logger().warning(f"No order data in response for order_id: {exchange_order_id}")
                return None

            # Return order data in format expected by order tracker
            # Convert to standard format
            return {
                "orderId": str(order_data.get("order_id", "")),
                "clientOrderId": tracked_order.client_order_id,
                "symbol": order_data.get("symbol", ""),
                "side": order_data.get("side", ""),
                "type": "LIMIT" if order_data.get("order_type") == "GTC" else order_data.get("order_type", "LIMIT"),
                "quantity": order_data.get("size", "0"),
                "price": order_data.get("price", "0"),
                "executedQuantity": order_data.get("filled", "0"),
                "status": self._parse_order_status(order_data.get("status", "")),
                "timestamp": order_data.get("timestamp", 0),
            }

        except Exception as e:
            self.logger().error(f"Error requesting order status for {exchange_order_id}: {e}", exc_info=True)
            return None

    def _parse_order_status(self, status: str) -> str:
        """
        Convert exchange order status to Hummingbot format.

        Exchange statuses: "OPEN", "FILLED", "CANCELED", etc.
        Hummingbot statuses: "NEW", "FILLED", "CANCELED", "PARTIALLY_FILLED", etc.
        """
        status_upper = status.upper() if status else ""

        # Map exchange statuses to Hummingbot statuses
        status_map = {
            "OPEN": "NEW",
            "NEW": "NEW",
            "FILLED": "FILLED",
            "CANCELED": "CANCELED",
            "CANCELLED": "CANCELED",
            "PARTIALLY_FILLED": "PARTIALLY_FILLED",
            "REJECTED": "REJECTED",
            "EXPIRED": "EXPIRED",
        }

        return status_map.get(status_upper, status_upper)

    def _parse_order_status_to_state(self, status: str):
        """
        Convert order status string to OrderState enum.

        Args:
            status: Status string (e.g., "FILLED", "CANCELED", "NEW")

        Returns:
            OrderState enum value
        """
        from hummingbot.core.data_type.in_flight_order import OrderState

        status_upper = status.upper() if status else ""

        # Map status strings to OrderState enum
        status_to_state = {
            "NEW": OrderState.OPEN,
            "OPEN": OrderState.OPEN,
            "FILLED": OrderState.FILLED,
            "CANCELED": OrderState.CANCELED,
            "CANCELLED": OrderState.CANCELED,
            "PARTIALLY_FILLED": OrderState.PARTIALLY_FILLED,
            "REJECTED": OrderState.FAILED,
            "EXPIRED": OrderState.CANCELED,
        }

        return status_to_state.get(status_upper, OrderState.OPEN)

    def _create_trade_update_from_order_status(self, tracked_order: InFlightOrder, order_status_data: Dict[str, Any]):
        """
        Create a TradeUpdate from order status data when order is filled.

        Args:
            tracked_order: The InFlightOrder being tracked
            order_status_data: Order status data from _request_order_status

        Returns:
            TradeUpdate object or None if data is insufficient
        """
        from hummingbot.core.data_type.in_flight_order import TradeUpdate

        try:
            executed_qty = Decimal(str(order_status_data.get("executedQuantity", "0")))
            price = Decimal(str(order_status_data.get("price", "0")))

            if executed_qty <= 0 or price <= 0:
                return None

            # Calculate fill amounts
            fill_base_amount = executed_qty
            fill_quote_amount = executed_qty * price

            # Get fee (use estimated fee since order status doesn't provide fee details)
            # For limit orders, assume maker fee
            is_maker = tracked_order.order_type in [OrderType.LIMIT, OrderType.LIMIT_MAKER]
            fee = self._get_fee(
                base_currency=tracked_order.base_asset,
                quote_currency=tracked_order.quote_asset,
                order_type=tracked_order.order_type,
                order_side=tracked_order.trade_type,
                amount=fill_base_amount,
                price=price,
                is_maker=is_maker
            )

            # Use exchange_order_id as trade_id if we don't have a specific trade ID
            # This is a fallback - ideally we'd get actual trade IDs from the exchange
            trade_id = f"{tracked_order.exchange_order_id}_fill"

            # Use timestamp from order status, or current time as fallback
            timestamp_ms = order_status_data.get("timestamp", 0)
            fill_timestamp = float(timestamp_ms) / 1000.0 if timestamp_ms > 0 else time.time()

            trade_update = TradeUpdate(
                trade_id=trade_id,
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=tracked_order.exchange_order_id,
                trading_pair=tracked_order.trading_pair,
                fill_timestamp=fill_timestamp,
                fill_price=price,
                fill_base_amount=fill_base_amount,
                fill_quote_amount=fill_quote_amount,
                fee=fee,
                is_taker=not is_maker,
            )

            return trade_update

        except Exception as e:
            self.logger().error(f"Error creating TradeUpdate from order status: {e}", exc_info=True)
            return None

    async def _all_trade_updates_for_order(self, order) -> List[Any]:
        """Get all trade updates for an order"""
        # Try to get trade updates from order status
        try:
            order_status_data = await self._request_order_status(order)
            if order_status_data:
                trade_update = self._create_trade_update_from_order_status(order, order_status_data)
                if trade_update:
                    return [trade_update]
        except Exception as e:
            self.logger().debug(f"Could not get trade updates for order {order.client_order_id}: {e}")

        return []

    def _convert_to_exchange_symbol(self, trading_pair: str) -> str:
        """
        Convert Hummingbot trading pair format (CNX-USDT) to exchange format (CNX/USDT).

        Args:
            trading_pair: Trading pair in Hummingbot format (e.g., "CNX-USDT")

        Returns:
            Trading pair in exchange format (e.g., "CNX/USDT")
        """
        return trading_pair.replace("-", "/")

    async def _update_balances(self):
        """Update account balances from exchange"""
        try:
            rest_assistant = await self._web_assistants_factory.get_rest_assistant()

            # Step 1: Sync balances first (POST /balances/sync)
            rest_api_base_url = getattr(self, "_rest_api_base_url", None)
            sync_url = web_utils.private_rest_url(
                path_url=CONSTANTS.BALANCES_SYNC_PATH_URL,
                domain=self._domain,
                rest_api_base_url=rest_api_base_url,
            )

            try:
                await rest_assistant.execute_request(
                    url=sync_url,
                    method=RESTMethod.POST,
                    is_auth_required=True,
                    throttler_limit_id=CONSTANTS.BALANCES_SYNC_PATH_URL,
                )
                # Don't process response - just trigger sync
            except Exception as e:
                self.logger().warning(f"Error syncing balances: {e}")

            # Step 2: Get balances (GET /balances)
            balances_url = web_utils.private_rest_url(
                path_url=CONSTANTS.BALANCES_PATH_URL,
                domain=self._domain,
                rest_api_base_url=rest_api_base_url,
            )

            response = await rest_assistant.execute_request(
                url=balances_url,
                method=RESTMethod.GET,
                is_auth_required=True,
                throttler_limit_id=CONSTANTS.BALANCES_PATH_URL,
            )

            # Parse response format:
            # {
            #     "user_id": 1120,
            #     "balances": {
            #         "USDT": {"balance": 6.775, "available": 6.775, "locked": 0.0},
            #         "CNX": {"balance": 60.0, "available": 60.0, "locked": 0.0}
            #     },
            #     "timestamp": "2026-01-10T14:59:54.989630"
            # }

            if not isinstance(response, dict):
                self.logger().error(f"Invalid balance response format: {type(response)}")
                return

            balances_data = response.get("balances", {})
            if not balances_data:
                self.logger().warning("No balances found in response")
                return

            # Update balances
            for currency, balance_info in balances_data.items():
                currency_upper = currency.upper()
                available = Decimal(str(balance_info.get("available", "0")))
                locked = Decimal(str(balance_info.get("locked", "0")))
                total = available + locked

                self._account_balances[currency_upper] = total
                self._account_available_balances[currency_upper] = available

            self.logger().info(f"Updated balances: {dict(self._account_balances)}")

        except Exception as e:
            self.logger().error(f"Error updating balances: {e}", exc_info=True)

    async def _update_trading_fees(self):
        """Update trading fees from exchange"""
        # TODO: Implement fee update
        pass

    async def _user_stream_event_listener(self):
        """
        Listen to user stream events and process balance updates, order updates, etc.

        This method processes events from the user stream data source (REST polling)
        and updates the connector's internal state (balances, orders, etc.).
        """
        async for event_message in self._iter_user_event_queue():
            try:
                event_type = event_message.get("event_type", "")

                if event_type == "balance_update":
                    # Process balance update event
                    # Format: {
                    #     "event_type": "balance_update",
                    #     "data": {
                    #         "currency": "USDT",
                    #         "available": "6.775",
                    #         "locked": "0.0",
                    #         "total": "6.775"
                    #     },
                    #     "timestamp": 1768069347.880
                    # }
                    data = event_message.get("data", {})
                    currency = data.get("currency", "").upper()
                    if currency:
                        available = Decimal(str(data.get("available", "0")))
                        locked = Decimal(str(data.get("locked", "0")))
                        total = available + locked

                        self._account_balances[currency] = total
                        self._account_available_balances[currency] = available

                        self.logger().debug(
                            f"Balance updated from user stream: {currency} = "
                            f"available={available}, locked={locked}, total={total}"
                        )

                elif event_type == "order_update":
                    # Process order update event
                    data = event_message.get("data", {})
                    order_id_str = str(data.get("order_id", ""))
                    status = data.get("status", "").upper()

                    # Find the tracked order by exchange_order_id
                    tracked_order = None
                    for client_id, in_flight_order in self._order_tracker.all_updatable_orders.items():
                        if str(in_flight_order.exchange_order_id) == order_id_str:
                            tracked_order = in_flight_order
                            break

                    if tracked_order:
                        # Convert status to OrderState
                        new_state = self._parse_order_status_to_state(status)

                        # Create OrderUpdate
                        from hummingbot.core.data_type.in_flight_order import OrderState, OrderUpdate
                        order_update = OrderUpdate(
                            trading_pair=tracked_order.trading_pair,
                            update_timestamp=event_message.get("timestamp", time.time()),
                            new_state=new_state,
                            client_order_id=tracked_order.client_order_id,
                            exchange_order_id=order_id_str,
                        )

                        # If order is FILLED, create and process TradeUpdate first
                        if new_state == OrderState.FILLED:
                            # Query order status to get fill details
                            try:
                                order_status_data = await self._request_order_status(tracked_order)
                                if order_status_data:
                                    trade_update = self._create_trade_update_from_order_status(tracked_order, order_status_data)
                                    if trade_update:
                                        self._order_tracker.process_trade_update(trade_update)
                                        self.logger().info(f"Order {tracked_order.client_order_id} (exchange_order_id: {order_id_str}) - processed trade fill event from user stream")
                            except Exception as e:
                                self.logger().warning(f"Could not create TradeUpdate for order {order_id_str}: {e}")

                        # Process order update
                        self._order_tracker.process_order_update(order_update)
                        self.logger().debug(f"Order update processed: {tracked_order.client_order_id} -> {new_state.name}")
                    else:
                        self.logger().debug(f"Order update event for unknown order: {order_id_str}")

                else:
                    self.logger().debug(f"Unknown event type: {event_type}, message: {event_message}")

            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error in user stream listener loop.", exc_info=True)
                await self._sleep(5.0)

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):
        """Initialize trading pair symbol map from exchange info"""
        # This is already implemented in _initialize_trading_pair_symbol_map
        # But we need this method for ExchangePyBase compatibility
        mapping = bidict()
        pairs = exchange_info.get("data", {}).get("pairs", [])
        for pair_data in pairs:
            symbol = pair_data.get("symbol", "").upper()
            data = pair_data.get("data", {})
            base_coin = data.get("baseCoin", "").upper()
            quote_coin = data.get("quoteCoin", "").upper()
            if not symbol or not base_coin or not quote_coin:
                continue
            hb_trading_pair = combine_to_hb_trading_pair(base=base_coin, quote=quote_coin)
            mapping[symbol] = hb_trading_pair
        self._set_trading_pair_symbol_map(mapping)

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        """
        Format trading rules from Cofinex API response.

        Expected response format:
        {
            "code": "200",
            "msg": "success",
            "data": {
                "total": 725,
                "pairs": [
                    {
                        "symbol": "MASUSDT",
                        "exchange": "bitget",
                        "data": {
                            "symbol": "MASUSDT",
                            "baseCoin": "MAS",
                            "quoteCoin": "USDT",
                            "minTradeAmount": "0",
                            "maxTradeAmount": "900000000000000000000",
                            "takerFeeRate": "0.001",
                            "makerFeeRate": "0.001",
                            "status": "online",
                            "minTradeUSDT": "1",
                            "pricePrecision": "5",
                            "quantityPrecision": "2",
                            "quotePrecision": "7",
                            ...
                        }
                    },
                    ...
                ]
            }
        }
        """
        trading_rules = []

        # Handle Cofinex API response format
        if exchange_info_dict.get("code") != "200":
            error_msg = exchange_info_dict.get("msg", "Unknown error")
            self.logger().error(f"Trading pairs API returned error: {error_msg}")
            return trading_rules

        pairs = exchange_info_dict.get("data", {}).get("pairs", [])

        for pair_data in pairs:
            try:
                symbol = pair_data.get("symbol", "").upper()
                data = pair_data.get("data", {})

                if not symbol or not data:
                    continue

                base_coin = data.get("baseCoin", "").upper()
                quote_coin = data.get("quoteCoin", "").upper()

                if not base_coin or not quote_coin:
                    continue

                hb_trading_pair = combine_to_hb_trading_pair(base=base_coin, quote=quote_coin)

                # Safely parse Decimal values - handle None and invalid values
                def safe_decimal(value, default="0"):
                    if value is None:
                        return Decimal(default)
                    try:
                        return Decimal(str(value))
                    except (ValueError, TypeError, decimal.InvalidOperation):
                        return Decimal(default)

                def safe_int(value, default=0):
                    if value is None:
                        return default
                    try:
                        return int(value)
                    except (ValueError, TypeError):
                        return default

                min_order_size = safe_decimal(data.get("minTradeAmount"), "0")
                max_order_size = safe_decimal(data.get("maxTradeAmount"), "900000000000000000000")
                price_precision = safe_int(data.get("pricePrecision"), 0)
                quantity_precision = safe_int(data.get("quantityPrecision"), 0)
                quote_precision = safe_int(data.get("quotePrecision"), 0)
                min_notional_size = safe_decimal(data.get("minTradeUSDT"), "0")

                min_price_increment = Decimal("10") ** Decimal(-price_precision) if price_precision > 0 else Decimal("0")
                min_base_amount_increment = Decimal("10") ** Decimal(-quantity_precision) if quantity_precision > 0 else Decimal("0")
                min_quote_amount_increment = Decimal("10") ** Decimal(-quote_precision) if quote_precision > 0 else Decimal("0")

                supports_limit_orders = data.get("status") == "online"
                supports_market_orders = data.get("status") == "online"

                trading_rules.append(TradingRule(
                    trading_pair=hb_trading_pair,
                    min_order_size=min_order_size,
                    max_order_size=max_order_size,
                    min_price_increment=min_price_increment,
                    min_base_amount_increment=min_base_amount_increment,
                    min_quote_amount_increment=min_quote_amount_increment,
                    min_notional_size=min_notional_size,
                    supports_limit_orders=supports_limit_orders,
                    supports_market_orders=supports_market_orders,
                ))

                # Log the parsed precision values
                self.logger().info(
                    f"Parsed trading rule for {hb_trading_pair}: "
                    f"pricePrecision={price_precision} → min_price_increment={min_price_increment}, "
                    f"quantityPrecision={quantity_precision} → min_base_amount_increment={min_base_amount_increment}, "
                    f"quotePrecision={quote_precision} → min_quote_amount_increment={min_quote_amount_increment}"
                )
            except Exception:
                self.logger().exception(f"Error parsing trading pair rule {pair_data.get('symbol', 'unknown')}. Skipping.")
                continue

        return trading_rules

    async def _update_trading_rules(self):
        """
        Update trading rules from Cofinex API.

        Override to use per-pair endpoint instead of bulk endpoint.
        This only fetches trading rules for configured trading pairs.
        """
        self.logger().info(f"Updating trading rules for {len(self._trading_pairs)} configured pairs: {self._trading_pairs}")

        try:
            # Check if we have configured trading pairs
            if not self._trading_pairs or len(self._trading_pairs) == 0:
                # No configured pairs - create default trading rules for paper trading
                self.logger().warning("No trading pairs configured - creating default trading rules for paper trading")
                self._trading_rules.clear()
                # For paper trading, we can continue without trading rules
                # The order validation will use defaults
                return

            # Use per-pair endpoint to fetch only configured pairs
            pairs_data = await self._fetch_trading_pairs_for_configured_pairs()

            if not pairs_data:
                self.logger().warning("No trading pairs data fetched - creating default trading rules")
                self._trading_rules.clear()
                return

            # Build exchange_info dict in the format expected by _format_trading_rules
            # Convert list of pairs to the format expected by _format_trading_rules
            exchange_info = {
                "code": "200",
                "msg": "success",
                "data": {
                    "total": len(pairs_data),
                    "pairs": pairs_data
                }
            }

            # Format trading rules using existing method
            trading_rules_list = await self._format_trading_rules(exchange_info)

            # Update trading rules dict
            self._trading_rules.clear()
            for trading_rule in trading_rules_list:
                self._trading_rules[trading_rule.trading_pair] = trading_rule
                # Log each trading rule that was loaded
                self.logger().info(
                    f"Loaded trading rule for {trading_rule.trading_pair}: "
                    f"min_price_increment={trading_rule.min_price_increment}, "
                    f"min_base_amount_increment={trading_rule.min_base_amount_increment}, "
                    f"min_quote_amount_increment={trading_rule.min_quote_amount_increment}, "
                    f"min_order_size={trading_rule.min_order_size}, "
                    f"min_notional_size={trading_rule.min_notional_size}"
                )

            self.logger().info(f"Updated trading rules. Total rules: {len(self._trading_rules)}")
            # Log all trading pair keys
            if self._trading_rules:
                self.logger().info(f"Trading rules loaded for pairs: {list(self._trading_rules.keys())}")

        except Exception as e:
            self.logger().error(f"Error updating trading rules: {e}", exc_info=True)
            # For paper trading, don't raise - create default rules
            if not self.is_trading_required:
                self.logger().warning("Paper trading mode: Continuing with empty trading rules")
                self._trading_rules.clear()
            else:
                raise

    @property
    def trading_pairs(self) -> List[str]:
        """Get list of trading pairs"""
        return self._trading_pairs if hasattr(self, '_trading_pairs') else []

    @property
    def order_books(self) -> Dict[str, OrderBook]:
        """Get all order books"""
        if self._order_book_tracker:
            return self._order_book_tracker.order_books
        return self._order_books

    @property
    def ready(self) -> bool:
        """Override to add logging, while keeping base readiness logic."""
        result = super().ready
        # status = self.status_dict  # Unused variable
        # Commented out verbose logging - fires too frequently
        # import sys
        # print(f"[COFINEX] ready property called: {result}, status_dict: {status}", file=sys.stderr, flush=True)
        # self.logger().info(f"Connector ready status: {result}, details: {status}")
        return result

    @property
    def trading_rules(self) -> Dict[str, TradingRule]:
        """Get trading rules for all pairs"""
        return self._trading_rules

    # =============================================================================
    # NETWORK MANAGEMENT
    # =============================================================================

    async def start_network(self):
        """
        Start the exchange connector

        Initialization sequence:
        1. Initialize trading pair symbol map (needed for all operations)
        2. Update trading rules (needed for order validation)
        3. Initialize authentication (if trading required)
        4. Call parent start_network() to start order book tracker and polling tasks
        """
        # CRITICAL: Print immediately - this MUST be the first line
        # Write to file FIRST - even before print
        try:
            with open("/tmp/cofinex_start_network.txt", "a") as f:
                f.write(f"\n{'=' * 80}\n")
                f.write(f"[{time.time()}] start_network() METHOD ENTRY\n")
                f.write(f"[{time.time()}] type(self) = {type(self)}\n")
                f.write(f"[{time.time()}] self.__class__ = {self.__class__}\n")
                f.write(f"[{time.time()}] self.__class__.__name__ = {self.__class__.__name__}\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception:
            pass  # Ignore file errors

        self.logger().info("Starting Cofinex connector...")
        self.logger().info(f"Trading pairs: {self._trading_pairs}")
        self.logger().info(f"Trading required: {self._trading_required}")

        try:
            self._start_event_loop_watchdog()

            # Initialize trading pair symbol map (needed for all operations)
            self.logger().info("Initializing trading pair symbol map...")
            self.logger().info(f"Trading pairs available: {self._trading_pairs}")

            # Force re-initialization if we have trading pairs (in case it was called earlier with empty pairs)
            if self._trading_pairs and len(self._trading_pairs) > 0:
                # Reset the map to None so it will be re-initialized
                self._trading_pair_symbol_map = None
                await self._initialize_trading_pair_symbol_map()
            else:
                self.logger().warning("No trading pairs configured - skipping symbol map initialization")

            symbol_map = await self.trading_pair_symbol_map()
            self.logger().info(f"Trading pair symbol map initialized. Total pairs: {len(symbol_map)}")

            # Update trading rules (needed for order validation)
            self.logger().info("Updating trading rules...")
            await self._update_trading_rules()
            self.logger().info(f"Trading rules updated. Total rules: {len(self._trading_rules)}")

            # Initialize authentication (if trading required)
            if self._trading_required:
                self.logger().info("Initializing authentication...")
                await self._initialize_auth()
                self.logger().info("Authentication initialized")
            else:
                self.logger().info("Paper trading mode: Skipping authentication")

            # Ensure trading rules are initialized before starting network
            # This is critical because orders might be placed before the network fully starts
            if len(self._trading_rules) == 0:
                self.logger().warning("Trading rules not initialized - initializing now...")
                await self._update_trading_rules()

            # Call parent start_network() which will:
            # - Start the order book tracker (already created in __init__)
            # - Start trading rules polling
            # - Start trading fees polling
            # - Start status polling
            # - Start user stream tracker and event listener
            import time
            step4_start = time.time()
            self.logger().info("Starting parent network components (order book tracker, polling tasks)...")
            await super().start_network()
            step4_elapsed = time.time() - step4_start
            self.logger().info(f"Parent network started in {step4_elapsed:.2f}s")

            self.logger().info("Cofinex connector started successfully")

        except Exception as e:
            self.logger().error(f"Failed to start Cofinex connector: {e}", exc_info=True)
            raise

    async def check_network(self) -> NetworkStatus:
        """
        Check network connectivity

        Override to add logging and timeout
        """
        import asyncio
        self.logger().info("Checking network connectivity...")
        try:
            # Add timeout to prevent hanging
            result = await asyncio.wait_for(super().check_network(), timeout=10.0)
            self.logger().info(f"Network check result: {result}")
            return result
        except asyncio.TimeoutError:
            self.logger().error("Network check timed out after 10 seconds")
            return NetworkStatus.NOT_CONNECTED
        except Exception as e:
            self.logger().error(f"Network check failed: {e}", exc_info=True)
            return NetworkStatus.NOT_CONNECTED

    async def stop_network(self):
        """
        Stop the exchange connector

        Calls parent stop_network() which handles:
        - Stopping order book tracker
        - Cancelling all polling tasks
        - Stopping user stream tracker
        """
        self.logger().info("Stopping Cofinex connector...")
        self._stop_event_loop_watchdog()
        await super().stop_network()
        self.logger().info("Cofinex connector stopped")

    async def _watchdog_heartbeat(self):
        """Update a heartbeat timestamp from the event loop."""
        while not self._loop_watchdog_stop.is_set():
            self._loop_heartbeat = time.monotonic()
            await asyncio.sleep(1.0)

    def _start_event_loop_watchdog(self):
        if self._loop_watchdog_thread is not None and self._loop_watchdog_thread.is_alive():
            return
        self._loop_watchdog_stop = threading.Event()
        self._loop_heartbeat = time.monotonic()
        self._loop_watchdog_dumped = False
        self._loop_watchdog_task = safe_ensure_future(self._watchdog_heartbeat())
        self._loop_watchdog_thread = threading.Thread(
            target=self._watchdog_thread_fn,
            name="cofinex_loop_watchdog",
            daemon=True,
        )
        self._loop_watchdog_thread.start()
        self.logger().info("Event loop watchdog started (threshold: 15s).")

    def _stop_event_loop_watchdog(self):
        if self._loop_watchdog_stop is not None:
            self._loop_watchdog_stop.set()
        if self._loop_watchdog_task is not None:
            self._loop_watchdog_task.cancel()
        if self._loop_watchdog_thread is not None and self._loop_watchdog_thread.is_alive():
            self._loop_watchdog_thread.join(timeout=1.0)
        self._loop_watchdog_task = None
        self._loop_watchdog_thread = None
        self._loop_watchdog_stop = None
        self._loop_watchdog_dumped = False

    def _watchdog_thread_fn(self):
        threshold_seconds = 15.0
        check_interval = 2.0
        while not self._loop_watchdog_stop.is_set():
            time.sleep(check_interval)
            gap = time.monotonic() - self._loop_heartbeat
            if gap > threshold_seconds:
                if not self._loop_watchdog_dumped:
                    self._loop_watchdog_dumped = True
                    self.logger().error(
                        "Event loop heartbeat stalled for %.2fs (threshold %.2fs). Dumping stacks.",
                        gap,
                        threshold_seconds,
                    )
                    thread_names = {t.ident: t.name for t in threading.enumerate()}
                    for thread_id, frame in sys._current_frames().items():
                        thread_name = thread_names.get(thread_id, "unknown")
                        stack = "".join(traceback.format_stack(frame))
                        self.logger().error(
                            "Thread %s (id=%s) stack:\n%s",
                            thread_name,
                            thread_id,
                            stack,
                        )
            else:
                if self._loop_watchdog_dumped:
                    self.logger().info(
                        "Event loop heartbeat recovered after stall (gap %.2fs).",
                        gap,
                    )
                self._loop_watchdog_dumped = False

    # =============================================================================
    # AUTHENTICATION
    # =============================================================================

    async def _initialize_auth(self):
        """
        Initialize OAuth 2.0 authentication

        Gets username and password from instance variables or config and creates CofinexAuth instance.
        The auth object will handle token requests automatically.
        """
        # Get credentials from instance variables or config
        # Note: Cofinex uses OAuth 2.0, so we need username/password, not API key/secret
        username = self._cofinex_username
        password = self._cofinex_password

        # Convert SecretStr to string if needed
        if username and hasattr(username, 'get_secret_value'):
            username = username.get_secret_value()
        if password and hasattr(password, 'get_secret_value'):
            password = password.get_secret_value()

        # Try to get from client_config_map if not set in instance
        if not username or not password:
            try:
                from hummingbot.client.config.config_helpers import get_client_config
                client_config = get_client_config()
                if hasattr(client_config, 'cofinex_username') and hasattr(client_config, 'cofinex_password'):
                    username_val = client_config.cofinex_username
                    password_val = client_config.cofinex_password
                    if username_val:
                        username = username_val.get_secret_value() if hasattr(username_val, 'get_secret_value') else username_val
                    if password_val:
                        password = password_val.get_secret_value() if hasattr(password_val, 'get_secret_value') else password_val
            except (AttributeError, ImportError):
                pass

        # For paper trading, credentials are not required
        # Check if this is paper trade mode by checking if trading_required is False
        # or if credentials are empty (paper trade allows empty credentials)
        if not self.is_trading_required:
            # Paper trading mode - skip authentication
            self.logger().info("Paper trading mode: Skipping OAuth authentication")
            return

        if not username or not password:
            raise Exception(
                "Cofinex credentials not configured. "
                "Please run 'connect cofinex' to configure username and password."
            )

        # Create auth instance
        # Note: OAuth token URL is always production (same for local and production testing)
        # Note: api_factory will be set after web_assistants_factory is created
        self._auth = CofinexAuth(
            username=username,
            password=password,
            # oauth_token_url defaults to CONSTANTS.OAUTH_TOKEN_URL (production)
        )

        # Set API factory for token requests (optional - auth creates its own for token requests)
        # The _web_assistants_factory is created in __init__() before start_network()
        if hasattr(self, '_web_assistants_factory') and self._web_assistants_factory is not None:
            # Set the API factory so auth can use it for throttling/configuration consistency
            # Note: The auth will create its own factory for token requests to avoid circular dependency
            self._auth.set_api_factory(self._web_assistants_factory)
            self.logger().info("API factory set on auth instance for token requests")

        self.logger().info("Cofinex OAuth authentication initialized")

    # =============================================================================
    # ORDER BOOK MANAGEMENT
    # =============================================================================

    # Note: _start_order_book_tracking() is no longer needed
    # The order book tracker is created in ExchangePyBase.__init__() and started in super().start_network()
    # This method is kept for reference but not used

    def get_order_book(self, trading_pair: str) -> OrderBook:
        """
        Get order book for a trading pair

        Args:
            trading_pair: Trading pair symbol

        Returns:
            OrderBook instance

        Raises:
            ValueError: If order book doesn't exist for the trading pair
        """
        if trading_pair not in self.order_book_tracker.order_books:
            raise ValueError(f"No order book exists for '{trading_pair}'.")
        return self.order_book_tracker.order_books[trading_pair]

    # =============================================================================
    # USER STREAM MANAGEMENT
    # =============================================================================

    async def _start_user_stream_tracking(self):
        """
        Start tracking user account data

        TODO: Implement user stream tracking:
        1. Connect to user WebSocket stream
        2. Subscribe to account updates
        3. Subscribe to order updates
        4. Subscribe to trade updates
        5. Handle authentication for user stream
        """
        # TODO: Implement user stream tracking
        # This typically involves:
        # 1. Connecting to user WebSocket endpoint
        # 2. Authenticating the connection
        # 3. Subscribing to relevant channels
        # 4. Handling incoming messages

        self.logger().info("User stream tracking started")

    # =============================================================================
    # ACCOUNT MANAGEMENT
    # =============================================================================

    async def get_balance(self, currency: str) -> Decimal:
        """
        Get account balance for a currency

        TODO: Implement balance retrieval:
        1. Make API call to get account balances
        2. Parse response and extract currency balance
        3. Cache balance for performance
        4. Handle errors appropriately

        Args:
            currency: Currency symbol (e.g., "BTC", "USDT")

        Returns:
            Account balance as Decimal
        """
        # TODO: Implement actual balance retrieval
        # Example implementation:
        # try:
        #     response = await self._api_request("GET", "/account/balance")
        #     balances = response.get("balances", [])
        #     for balance in balances:
        #         if balance["currency"] == currency:
        #             return Decimal(balance["free"]) + Decimal(balance["locked"])
        #     return Decimal("0")
        # except Exception as e:
        #     self.logger().error(f"Failed to get balance for {currency}: {e}")
        #     return Decimal("0")

        # For now, return cached balance or default
        return self._account_balances.get(currency, Decimal("0"))

    def get_all_balances(self) -> Dict[str, Decimal]:
        """
        Get all account balances

        Returns:
            Dictionary of currency balances
        """
        # TODO: Implement actual balance retrieval for all currencies
        return self._account_balances.copy()

    # =============================================================================
    # ORDER MANAGEMENT
    # =============================================================================

    async def _create_order(self,
                            trade_type: TradeType,
                            order_id: str,
                            trading_pair: str,
                            amount: Decimal,
                            order_type: OrderType,
                            price: Optional[Decimal] = None,
                            **kwargs):
        """
        Override _create_order to handle missing trading rules for paper trading.
        """
        try:
            self.logger().info(f"[COFINEX OVERRIDE] _create_order called for {trading_pair}, order_id={order_id}")

            # Ensure trading rules exist - try to update them if missing
            if trading_pair not in self._trading_rules:
                self.logger().warning(f"Trading rules not found for {trading_pair} - attempting to update...")
                try:
                    await self._update_trading_rules()
                except Exception as e:
                    self.logger().warning(f"Failed to update trading rules: {e} - creating default rule")

                # If still not found, create default rule for paper trading
                if trading_pair not in self._trading_rules:
                    self.logger().warning(f"Trading rules still not found for {trading_pair} - creating default rule")
                    from hummingbot.connector.trading_rule import TradingRule
                    default_rule = TradingRule(
                        trading_pair=trading_pair,
                        min_order_size=Decimal("0.001"),
                        max_order_size=Decimal("900000000000000000000"),
                        min_price_increment=Decimal("0.01"),
                        min_base_amount_increment=Decimal("0.001"),
                        min_notional_size=Decimal("1"),
                    )
                    self._trading_rules[trading_pair] = default_rule
                    self.logger().info(f"Created default trading rule for {trading_pair}")

            # Call parent _create_order which will validate and place the order
            await super()._create_order(
                trade_type=trade_type,
                order_id=order_id,
                trading_pair=trading_pair,
                amount=amount,
                order_type=order_type,
                price=price,
                **kwargs
            )

        except Exception as e:
            self.logger().error(f"Exception in _create_order: {e}", exc_info=True)
            raise

    async def _place_order(
        self,
        order_id: str,
        trading_pair: str,
        amount: Decimal,
        trade_type: TradeType,
        order_type: OrderType,
        price: Optional[Decimal] = None,
        **kwargs,
    ) -> Tuple[str, float]:
        """
        Place an order on Cofinex.

        This is the abstract method required by ExchangePyBase.
        It is called by _place_order_and_process_update after order validation.

        For paper trading, this returns a generated exchange order ID and timestamp.
        For live trading, this should make an actual API call to place the order.

        Args:
            order_id: Client order ID (assigned by Hummingbot)
            trading_pair: Trading pair symbol (e.g., "BTC-USDT")
            amount: Order quantity
            trade_type: BUY or SELL
            order_type: LIMIT, MARKET, etc.
            price: Order price (required for LIMIT orders)
            **kwargs: Additional parameters

        Returns:
            Tuple of (exchange_order_id, timestamp)
        """
        try:
            self.logger().info(f"Placing {trade_type.name} {order_type.name} order: {order_id} for {amount} {trading_pair} at {price}")

            # For paper trading, we don't need authentication
            # For live trading, check authentication here
            if self.is_trading_required and not self._auth:
                raise Exception("Not authenticated for live trading")

            # Generate exchange order ID
            # For paper trading, use the client order ID as exchange order ID
            # For live trading, this should come from the API response
            if not self.is_trading_required:
                # Paper trading mode - return immediately with generated ID
                exchange_order_id = f"PAPER_{order_id}"
                # Use time.time() instead of current_timestamp in case it's not initialized yet
                timestamp = float(time.time())
                self.logger().info(f"Paper trading order {order_id} placed with exchange_order_id {exchange_order_id}")
                return exchange_order_id, timestamp
        except Exception as e:
            self.logger().error(f"Exception in _place_order: {e}", exc_info=True)
            raise

        # Implement actual API call for live trading
        rest_assistant = await self._web_assistants_factory.get_rest_assistant()

        # Convert trading pair to exchange symbol format (CNX-USDT -> CNX/USDT)
        exchange_symbol = self._convert_to_exchange_symbol(trading_pair)

        # Build order data according to API specification
        order_data = {
            "symbol": exchange_symbol,
            "side": "BUY" if trade_type == TradeType.BUY else "SELL",
            "order_type": "LIMIT" if order_type == OrderType.LIMIT else "MARKET",
            "quantity": float(amount),  # API expects number, not string
            "price": float(price) if price else None,  # API expects number, not string
            "time_in_force": "GTC"
        }

        # Remove None values
        order_data = {k: v for k, v in order_data.items() if v is not None}

        # Make API request
        rest_api_base_url = getattr(self, "_rest_api_base_url", None)
        url = web_utils.private_rest_url(
            path_url=CONSTANTS.ORDERS_PATH_URL,
            domain=self._domain,
            rest_api_base_url=rest_api_base_url,
        )

        response = await rest_assistant.execute_request(
            url=url,
            method=RESTMethod.POST,
            data=order_data,
            is_auth_required=True,
            throttler_limit_id=CONSTANTS.POST_ORDER_LIMIT_ID,
        )

        # Parse response:
        # {
        #     "order_id": "1768048527086",
        #     "status": "SUCCESS",
        #     "message": "Order placed successfully",
        #     "timestamp": "2026-01-10T18:05:32.295813"
        # }

        if not isinstance(response, dict):
            raise ValueError(f"Invalid response format: {type(response)}")

        if response.get("status") != "SUCCESS":
            error_msg = response.get("message", "Unknown error")
            raise Exception(f"Order placement failed: {error_msg}")

        exchange_order_id = str(response.get("order_id"))
        if not exchange_order_id:
            raise ValueError("No order_id in response")

        # Parse timestamp from ISO format
        timestamp_str = response.get("timestamp", "")
        if timestamp_str:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                timestamp = dt.timestamp()
            except (ValueError, AttributeError):
                timestamp = self.current_timestamp
        else:
            timestamp = self.current_timestamp

        self.logger().info(f"Order placed successfully: exchange_order_id={exchange_order_id}, timestamp={timestamp}")
        return exchange_order_id, timestamp

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder) -> bool:
        """
        Cancel an order on Cofinex.

        This is the abstract method required by ExchangePyBase.
        It is called by the order cancellation flow.

        For paper trading, this returns True immediately.
        For live trading, this should make an actual API call to cancel the order.

        Args:
            order_id: Client order ID
            tracked_order: InFlightOrder object tracking the order

        Returns:
            True if cancellation was successful, False otherwise
        """
        import time

        from hummingbot.core.data_type.in_flight_order import OrderState, OrderUpdate

        self.logger().info(f"Canceling order: {order_id} (exchange_order_id: {tracked_order.exchange_order_id})")

        # For paper trading, we don't need authentication
        if not self.is_trading_required:
            # Paper trading mode - return immediately
            self.logger().info(f"Paper trading order {order_id} canceled successfully")
            return True

        # For live trading, check authentication
        if not self._auth:
            raise Exception("Not authenticated for live trading")

        # Implement actual API call for live trading
        exchange_order_id = tracked_order.exchange_order_id
        if not exchange_order_id or exchange_order_id == "UNKNOWN":
            self.logger().warning(f"Cannot cancel order {order_id} without exchange_order_id")
            return False

        rest_assistant = await self._web_assistants_factory.get_rest_assistant()

        # Make API request to cancel order: DELETE /orders/{orderId}
        rest_api_base_url = getattr(self, "_rest_api_base_url", None)
        url = web_utils.private_rest_url(
            path_url=f"{CONSTANTS.ORDER_PATH_URL}/{exchange_order_id}",
            domain=self._domain,
            rest_api_base_url=rest_api_base_url,
        )

        try:
            response = await rest_assistant.execute_request(
                url=url,
                method=RESTMethod.DELETE,
                is_auth_required=True,
                throttler_limit_id=CONSTANTS.DELETE_ORDER_LIMIT_ID,
            )

            # Parse response:
            # {
            #     "order_id": "1768048599757",
            #     "status": "SUCCESS",
            #     "message": "Order cancelled successfully",
            #     "timestamp": "2026-01-10T18:08:05.304423"
            # }

            if not isinstance(response, dict):
                self.logger().error(f"Invalid cancel response format: {type(response)}")
                return False

            if response.get("status") == "SUCCESS":
                # Even if cancellation reports success, verify actual order status
                # There could be a race condition where order was filled during cancellation
                self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) cancellation reported success. Verifying actual status...")

                try:
                    order_status_data = await self._request_order_status(tracked_order)
                    if order_status_data:
                        status_str = order_status_data.get("status", "")
                        new_state = self._parse_order_status_to_state(status_str)

                        if new_state == OrderState.FILLED:
                            # Order was actually filled, not cancelled - update status
                            # Create TradeUpdate to trigger OrderFilledEvent (for fill counters)
                            trade_update = self._create_trade_update_from_order_status(tracked_order, order_status_data)

                            # Set executed amounts FIRST
                            executed_qty = Decimal(str(order_status_data.get("executedQuantity", "0")))
                            price = Decimal(str(order_status_data.get("price", "0")))
                            if executed_qty > 0 and price > 0:
                                tracked_order.executed_amount_base = executed_qty
                                tracked_order.executed_amount_quote = executed_qty * price
                                tracked_order.check_filled_condition()

                            # Process trade update FIRST (triggers OrderFilledEvent)
                            if trade_update:
                                self._order_tracker.process_trade_update(trade_update)
                                self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) - processed trade fill event")

                            # Process order update (triggers BuyOrderCompletedEvent/SellOrderCompletedEvent)
                            order_update = OrderUpdate(
                                trading_pair=tracked_order.trading_pair,
                                update_timestamp=time.time(),
                                new_state=OrderState.FILLED,
                                client_order_id=tracked_order.client_order_id,
                                exchange_order_id=exchange_order_id,
                            )
                            future = self._order_tracker.process_order_update(order_update)
                            if future:
                                await future

                            self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) was FILLED (not cancelled). Updated order status.")
                            # Return False to prevent base class from emitting OrderCancelledEvent
                            # The order is FILLED, not cancelled, so we don't want a cancellation event
                            return False
                        elif new_state == OrderState.CANCELED:
                            # Order was actually cancelled - this is expected
                            self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) confirmed as cancelled.")
                            return True
                        else:
                            # Order status is something else - log and treat as cancelled
                            self.logger().warning(f"Order {order_id} (exchange_order_id: {exchange_order_id}) has unexpected status after cancellation: {status_str}. Treating as cancelled.")
                            return True
                    else:
                        # Could not get order status - assume cancellation succeeded
                        self.logger().warning(f"Could not verify order status for {order_id} (exchange_order_id: {exchange_order_id}) after cancellation. Assuming cancelled.")
                        return True
                except Exception as status_error:
                    # Error querying order status - assume cancellation succeeded
                    self.logger().warning(f"Error verifying order status for {order_id} (exchange_order_id: {exchange_order_id}) after cancellation: {status_error}. Assuming cancelled.")
                    return True
            else:
                error_msg = response.get("message", "Unknown error")
                self.logger().warning(f"Order cancellation returned unexpected status: {response.get('status')}, message: {error_msg}")
                return False

        except IOError as e:
            # Check if order not found (404 error)
            if self._is_order_not_found_during_cancelation_error(e):
                self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) not found during cancellation. Querying order status...")

                # Query order status to determine if it was filled or canceled
                try:
                    order_status_data = await self._request_order_status(tracked_order)
                    if order_status_data:
                        # Get status string and convert to OrderState enum
                        status_str = order_status_data.get("status", "")
                        new_state = self._parse_order_status_to_state(status_str)

                        import time

                        from hummingbot.core.data_type.in_flight_order import OrderState, OrderUpdate

                        if new_state == OrderState.FILLED:
                            # Order was filled - create TradeUpdate to trigger OrderFilledEvent
                            trade_update = self._create_trade_update_from_order_status(tracked_order, order_status_data)

                            # Update executed amounts
                            executed_qty = Decimal(str(order_status_data.get("executedQuantity", "0")))
                            price = Decimal(str(order_status_data.get("price", "0")))
                            if executed_qty > 0 and price > 0:
                                tracked_order.executed_amount_base = executed_qty
                                tracked_order.executed_amount_quote = executed_qty * price
                                tracked_order.check_filled_condition()

                            # Process trade update FIRST (triggers OrderFilledEvent)
                            if trade_update:
                                self._order_tracker.process_trade_update(trade_update)
                                self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) - processed trade fill event")

                            # Process order update (triggers BuyOrderCompletedEvent/SellOrderCompletedEvent)
                            order_update = OrderUpdate(
                                trading_pair=tracked_order.trading_pair,
                                update_timestamp=time.time(),
                                new_state=OrderState.FILLED,
                                client_order_id=tracked_order.client_order_id,
                                exchange_order_id=exchange_order_id,
                            )
                            future = self._order_tracker.process_order_update(order_update)
                            if future:
                                await future

                            self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) was FILLED. Updated order status.")
                            # Return False to prevent base class from emitting OrderCancelledEvent
                            # The order is FILLED, not cancelled, so we don't want a cancellation event
                            return False
                        elif new_state == OrderState.CANCELED:
                            # Order was already canceled
                            order_update = OrderUpdate(
                                trading_pair=tracked_order.trading_pair,
                                update_timestamp=time.time(),
                                new_state=OrderState.CANCELED,
                                client_order_id=tracked_order.client_order_id,
                                exchange_order_id=exchange_order_id,
                            )
                            future = self._order_tracker.process_order_update(order_update)
                            if future:
                                await future
                            self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) was already CANCELED.")
                            return True
                        else:
                            # Order status is something else (OPEN, etc.)
                            order_update = OrderUpdate(
                                trading_pair=tracked_order.trading_pair,
                                update_timestamp=time.time(),
                                new_state=new_state,
                                client_order_id=tracked_order.client_order_id,
                                exchange_order_id=exchange_order_id,
                            )
                            future = self._order_tracker.process_order_update(order_update)
                            if future:
                                await future
                            self.logger().info(f"Order {order_id} (exchange_order_id: {exchange_order_id}) has status: {status_str} (state: {new_state.name}). Updated order status.")
                            return True
                    else:
                        # Could not get order status - treat as not found
                        self.logger().warning(f"Could not retrieve order status for {order_id} (exchange_order_id: {exchange_order_id}). Treating as not found.")
                        await self._order_tracker.process_order_not_found(order_id)
                        return True
                except Exception as status_error:
                    # Error querying order status - treat as not found
                    self.logger().warning(f"Error querying order status for {order_id} (exchange_order_id: {exchange_order_id}): {status_error}. Treating as not found.")
                    await self._order_tracker.process_order_not_found(order_id)
                    return True
            raise
        except Exception as e:
            self.logger().error(f"Error cancelling order {order_id}: {e}", exc_info=True)
            raise

    async def cancel_all(self, timeout_seconds: float) -> List[CancellationResult]:
        """
        Cancels all currently active orders. The cancellations are performed sequentially
        (one after another) to avoid overwhelming the API during shutdown.

        :param timeout_seconds: the maximum time (in seconds) the cancel logic should run
        :return: a list of CancellationResult instances, one for each of the orders to be cancelled
        """
        from async_timeout import timeout

        incomplete_orders = [o for o in self.in_flight_orders.values() if not o.is_done]
        order_id_set = set([o.client_order_id for o in incomplete_orders])
        successful_cancellations = []

        if not incomplete_orders:
            self.logger().info("No orders to cancel")
            return []

        # Calculate dynamic timeout: at least 1 second per order, minimum 20 seconds
        # This ensures we have enough time for sequential cancellation
        calculated_timeout = max(timeout_seconds, len(incomplete_orders) * 1.0, 20.0)
        self.logger().info(
            f"Cancelling {len(incomplete_orders)} orders with timeout {calculated_timeout}s. "
            f"Orders: {[f'{o.client_order_id[:20]}...({o.exchange_order_id})' for o in incomplete_orders[:10]]}"
            + (f" ... and {len(incomplete_orders) - 10} more" if len(incomplete_orders) > 10 else "")
        )

        try:
            async with timeout(calculated_timeout):
                # Cancel orders sequentially (one after another) with rate limit delay
                # API limit is 10 DELETE requests per second, so add 100ms delay between cancellations
                for i, order in enumerate(incomplete_orders):
                    try:
                        client_order_id = await self._execute_cancel(order.trading_pair, order.client_order_id)
                        if client_order_id is not None:
                            order_id_set.discard(client_order_id)
                            successful_cancellations.append(CancellationResult(client_order_id, True))

                        # Add delay between cancellations to respect rate limit (10 req/sec = 100ms delay)
                        # Skip delay for last order
                        if i < len(incomplete_orders) - 1:
                            await asyncio.sleep(0.1)
                    except Exception as e:
                        # Log error but continue with next order
                        self.logger().warning(f"Error cancelling order {order.client_order_id}: {e}")
                        # Still add delay even on error to respect rate limit
                        if i < len(incomplete_orders) - 1:
                            await asyncio.sleep(0.1)
        except asyncio.TimeoutError:
            self.logger().warning(
                f"Timeout while cancelling orders after {calculated_timeout}s. "
                f"Remaining orders: {len(order_id_set)}"
            )
            # Continue canceling remaining orders even after timeout (with individual timeouts)
            remaining_orders = [o for o in incomplete_orders if o.client_order_id in order_id_set]
            self.logger().info(f"Attempting to cancel {len(remaining_orders)} remaining orders...")
            for i, order in enumerate(remaining_orders):
                try:
                    # Use individual timeout of 2 seconds per order
                    async with timeout(2.0):
                        client_order_id = await self._execute_cancel(order.trading_pair, order.client_order_id)
                        if client_order_id is not None:
                            order_id_set.discard(client_order_id)
                            successful_cancellations.append(CancellationResult(client_order_id, True))

                        # Add delay between cancellations to respect rate limit
                        if i < len(remaining_orders) - 1:
                            await asyncio.sleep(0.1)
                except (asyncio.TimeoutError, Exception) as exc:
                    self.logger().warning(f"Failed to cancel remaining order {order.client_order_id}: {exc}")
                    # Still add delay even on error to respect rate limit
                    if i < len(remaining_orders) - 1:
                        await asyncio.sleep(0.1)
        except Exception:
            self.logger().network(
                "Unexpected error cancelling orders.",
                exc_info=True,
                app_warning_msg="Failed to cancel orders. Check API key and network connection."
            )
        failed_cancellations = [CancellationResult(oid, False) for oid in order_id_set]

        if failed_cancellations:
            self.logger().warning(f"Failed to cancel {len(failed_cancellations)} orders: {[r.order_id for r in failed_cancellations]}")

        return successful_cancellations + failed_cancellations

    async def cancel_order(self, trading_pair: str, order_id: str) -> bool:
        """
        Cancel an order

        TODO: Implement order cancellation:
        1. Validate order exists
        2. Make API call to cancel order
        3. Handle response and errors
        4. Update order status
        5. Remove from tracking if successful

        Args:
            trading_pair: Trading pair symbol
            order_id: Order ID to cancel

        Returns:
            True if cancellation was successful
        """
        if order_id not in self._in_flight_orders:
            self.logger().warning(f"Order {order_id} not found")
            return False

        # TODO: Make actual API call to cancel order
        # Example implementation:
        # try:
        #     response = await self._api_request("DELETE", f"/order/{order_id}")
        #     if response.get("status") == "CANCELED":
        #         del self._in_flight_orders[order_id]
        #         return True
        #     return False
        # except Exception as e:
        #     self.logger().error(f"Failed to cancel order {order_id}: {e}")
        #     return False

        # For now, just remove from tracking
        del self._in_flight_orders[order_id]
        self.logger().info(f"Canceled order: {order_id}")
        return True

    async def get_open_orders(self, trading_pair: str = None) -> List[LimitOrder]:
        """
        Get open orders from exchange.

        Endpoint: GET /orders

        Response format:
        {
            "user_id": 1120,
            "orders": [
                {
                    "order_id": 1768056258031,
                    "symbol_id": 12,
                    "symbol": "CNX/USDT",
                    "side": "SELL",
                    "order_type": "GTC",
                    "price": "0.1",
                    "size": "10",
                    "filled": "0",
                    "reserve_bid_price": 0.1,
                    "timestamp": 1768036462000,
                    "status": "OPEN"
                }
            ],
            "timestamp": "2026-01-10T20:14:36.748759"
        }

        Args:
            trading_pair: Optional trading pair filter (Hummingbot format: "CNX-USDT")

        Returns:
            List of LimitOrder objects
        """
        try:
            rest_assistant = await self._web_assistants_factory.get_rest_assistant()

            # Make API request: GET /orders
            rest_api_base_url = getattr(self, "_rest_api_base_url", None)
            url = web_utils.private_rest_url(
                path_url=CONSTANTS.OPEN_ORDERS_PATH_URL,
                domain=self._domain,
                rest_api_base_url=rest_api_base_url,
            )

            # Optional: Add symbol filter if specified
            params = {}
            if trading_pair:
                # Convert Hummingbot format to exchange format
                exchange_symbol = self._convert_to_exchange_symbol(trading_pair)
                params["symbol"] = exchange_symbol

            response = await rest_assistant.execute_request(
                url=url,
                method=RESTMethod.GET,
                params=params if params else None,
                is_auth_required=True,
                throttler_limit_id=CONSTANTS.OPEN_ORDERS_PATH_URL,
            )

            # Parse response
            if not isinstance(response, dict):
                self.logger().error(f"Invalid open orders response format: {type(response)}")
                return []

            orders_list = response.get("orders", [])
            if not isinstance(orders_list, list):
                self.logger().warning("No orders array in response")
                return []

            # Convert to LimitOrder objects
            limit_orders = []
            for order_data in orders_list:
                try:
                    # Convert exchange order data to LimitOrder
                    order = self._parse_order_data_to_limit_order(order_data)
                    if order:
                        # Filter by trading pair if specified
                        if trading_pair and order.trading_pair != trading_pair:
                            continue
                        limit_orders.append(order)
                except Exception as e:
                    self.logger().warning(f"Error parsing order data: {order_data}, error: {e}")
                    continue

            self.logger().info(f"Retrieved {len(limit_orders)} open orders from exchange")
            return limit_orders

        except Exception as e:
            self.logger().error(f"Failed to get open orders: {e}", exc_info=True)
            # Fallback to locally tracked orders if API call fails
        if trading_pair:
            return [order for order in self._in_flight_orders.values()
                    if order.trading_pair == trading_pair]  # noqa: E128
        return list(self._in_flight_orders.values())

    # =============================================================================
    # TRADING RULES
    # =============================================================================
    # Note: _update_trading_rules() is inherited from ExchangePyBase
    # It calls _make_trading_rules_request() -> _format_trading_rules() -> _initialize_trading_pair_symbols_from_exchange_info()

    async def get_trading_rules(self, trading_pair: str) -> Optional[TradingRule]:
        """
        Get trading rules for a trading pair

        Args:
            trading_pair: Trading pair symbol in Hummingbot format (e.g., "BTC-USDT")

        Returns:
            TradingRule object or None if not found
        """
        # Ensure trading rules are loaded
        if not self._trading_rules:
            await self._update_trading_rules()

        return self._trading_rules.get(trading_pair)

    # =============================================================================
    # FEE CALCULATION
    # =============================================================================

    def get_fee(self,
                base_currency: str,
                quote_currency: str,
                order_type: OrderType,
                order_side: TradeType,
                amount: Decimal,
                price: Decimal = Decimal("NaN")) -> TradeFeeBase:
        """
        Get trading fee for an order

        TODO: Implement fee calculation:
        1. Get fee structure from exchange
        2. Calculate fee based on order type and side
        3. Apply any discounts or promotions
        4. Return proper fee object

        Args:
            base_currency: Base currency symbol
            quote_currency: Quote currency symbol
            order_type: Order type
            order_side: Order side (BUY/SELL)
            amount: Order amount
            price: Order price

        Returns:
            TradeFeeBase object with fee information
        """
        # TODO: Implement actual fee calculation
        # This should get real fee rates from the exchange
        # and calculate fees based on:
        # - Order type (maker vs taker)
        # - Trading volume
        # - VIP level
        # - Promotions

        # For now, use default fees
        fee_rate = Decimal("0.001")  # 0.1%

        return TradeFeeBase.new_spot_fee(
            fee_schema=TradeFeeBase.new_spot_fee_schema(),
            trade_type=order_side,
            percent=fee_rate,
            flat_fees=[]
        )

    # =============================================================================
    # STATUS POLLING
    # =============================================================================

    async def _status_polling_loop(self):
        """
        Main status polling loop

        TODO: Implement status polling:
        1. Poll account balances
        2. Poll open orders
        3. Poll order book updates
        4. Handle network errors
        5. Implement rate limiting
        """
        while True:
            try:
                # TODO: Implement actual status polling
                # This should poll:
                # - Account balances
                # - Open orders
                # - Order book updates
                # - System status

                await asyncio.sleep(1)  # Poll every second

            except Exception as e:
                self.logger().error(f"Error in status polling: {e}")
                await asyncio.sleep(5)  # Wait longer on error

    # =============================================================================
    # API REQUEST HELPERS
    # =============================================================================
    # Note: _api_request is inherited from ExchangePyBase and uses the correct signature
    # It calls _api_request_url() which uses web_utils.public_rest_url() or private_rest_url()

    async def _api_request_url(self, path_url: str, is_auth_required: bool = False) -> str:
        """
        Build the full URL for an API request.

        This method is called by the base class _api_request() to construct URLs.
        It uses web_utils to handle domain-specific URL construction and local testing overrides.

        Args:
            path_url: API endpoint path (e.g., "/api/v1/time")
            is_auth_required: Whether the endpoint requires authentication

        Returns:
            Full URL string
        """
        rest_api_base_url = getattr(self, "_rest_api_base_url", None)
        if is_auth_required:
            return web_utils.private_rest_url(
                path_url=path_url,
                domain=self._domain,
                rest_api_base_url=rest_api_base_url,
            )
        else:
            return web_utils.public_rest_url(
                path_url=path_url,
                domain=self._domain,
                rest_api_base_url=rest_api_base_url,
            )

    # =============================================================================
    # TRADING PAIR SYMBOL MAPPING
    # =============================================================================

    async def _initialize_trading_pair_symbol_map(self):
        """
        Initialize the mapping between exchange symbols and Hummingbot trading pairs.

        Fetches trading pairs from Cofinex API and builds a bidirectional mapping:
        - Exchange symbol (e.g., "MASUSDT") -> Hummingbot trading pair (e.g., "MAS-USDT")

        Optimized to only fetch the pairs we actually need instead of all 725 pairs.
        """
        try:
            self.logger().info(f"_initialize_trading_pair_symbol_map called. Trading pairs: {getattr(self, '_trading_pairs', 'NOT SET')}")

            # Check if we have configured trading pairs
            # If we do, use the per-pair endpoint (faster, only fetches what we need)
            # If we don't (e.g., during autocompletion), skip initialization - don't use bulk endpoint
            if not self._trading_pairs or len(self._trading_pairs) == 0:
                # No configured pairs - this is likely autocompletion or early initialization
                # Don't fetch anything - the symbol map will be built when pairs are configured
                # Don't set an empty map - leave it as None so it will be retried when pairs are available
                self.logger().debug("No configured trading pairs yet - skipping initialization (will retry when pairs are set)")
                # Don't set the map - leave it as None so trading_pair_symbol_map_ready() returns False
                # This allows it to be called again later when trading pairs are available
                return

            # IMPORTANT: We have trading pairs now - use per-pair endpoint
            self.logger().info(f"Using per-pair endpoint for {len(self._trading_pairs)} configured pairs: {self._trading_pairs}")

            # We have configured pairs - use the optimized per-pair endpoint
            trading_pairs_data = await self._fetch_trading_pairs_for_configured_pairs()

            if not trading_pairs_data:
                self.logger().warning("No trading pairs data fetched - setting empty symbol map")
                self._set_trading_pair_symbol_map(bidict())
                return

            # Build the mapping
            mapping = bidict()
            for pair_data in trading_pairs_data:
                symbol = pair_data.get("symbol", "").upper()
                data = pair_data.get("data", {})
                base_coin = data.get("baseCoin", "").upper()
                quote_coin = data.get("quoteCoin", "").upper()

                if not symbol or not base_coin or not quote_coin:
                    continue

                # Build Hummingbot trading pair format: BASE-QUOTE
                hb_trading_pair = combine_to_hb_trading_pair(base=base_coin, quote=quote_coin)

                # Check for duplicates
                if symbol in mapping:
                    self.logger().warning(
                        f"Duplicate symbol {symbol} found. "
                        f"Existing: {mapping[symbol]}, New: {hb_trading_pair}. Skipping."
                    )
                    continue
                elif hb_trading_pair in mapping.inverse:
                    self.logger().warning(
                        f"Duplicate trading pair {hb_trading_pair} found. "
                        f"Existing symbol: {mapping.inverse[hb_trading_pair]}, New symbol: {symbol}. Skipping."
                    )
                    continue

                mapping[symbol] = hb_trading_pair

            # Set the mapping
            self._set_trading_pair_symbol_map(mapping)
            self.logger().info(f"Initialized trading pair symbol map with {len(mapping)} pairs")

        except Exception as e:
            self.logger().error(f"Error initializing trading pair symbol map: {e}", exc_info=True)
            raise

    async def _fetch_trading_pairs_for_configured_pairs(self) -> List[Dict[str, Any]]:
        """
        Fetch trading pair info only for the configured trading pairs.
        Uses the per-pair endpoint /spot/v1/tradepair/{SYMBOL} instead of fetching all 725 pairs.

        Returns:
            List of trading pair dictionaries from the API response
        """
        try:
            # Create a simple API factory for public endpoints (no auth needed)
            from hummingbot.connector.exchange.cofinex.cofinex_web_utils import (
                build_api_factory_without_time_synchronizer_pre_processor,
                create_throttler,
            )

            throttler = create_throttler()
            api_factory = build_api_factory_without_time_synchronizer_pre_processor(throttler)
            rest_assistant = await api_factory.get_rest_assistant()

            # Use domain from connector if available, otherwise default to "main"
            domain = getattr(self, '_domain', CONSTANTS.DEFAULT_DOMAIN)
            base_url = CONSTANTS.MARKET_DATA_BASE_URL.get(domain, CONSTANTS.MARKET_DATA_BASE_URL["main"])

            # Fetch only the pairs we actually need
            pairs = []
            import asyncio

            # Use trading_pairs property - it returns self._trading_pairs
            trading_pairs_to_fetch = self.trading_pairs

            if not trading_pairs_to_fetch:
                # This should not happen since we check before calling this method
                # But if it does, return empty list
                self.logger().warning("No trading pairs to fetch - this method should only be called when pairs are configured")
                return []

            self.logger().info(f"Fetching pair info for {len(trading_pairs_to_fetch)} configured pairs: {trading_pairs_to_fetch}")

            for trading_pair in trading_pairs_to_fetch:
                # Convert Hummingbot format (BTC-USDT) to API format (BTC_USDT)
                api_symbol = trading_pair.replace("-", "_").upper()
                url = f"{base_url}/spot/v1/tradepair/{api_symbol}"

                self.logger().info(f"Fetching pair info for {trading_pair} from {url}")
                try:
                    response = await asyncio.wait_for(
                        rest_assistant.execute_request(
                            url=url,
                            method=RESTMethod.GET,
                            throttler_limit_id=CONSTANTS.TRADING_PAIRS_PATH_URL,
                        ),
                        timeout=5.0  # 5 seconds per pair should be enough
                    )

                    # Log the raw response for debugging
                    self.logger().debug(f"Raw response for {trading_pair}: {response}")

                    # Parse response
                    # Expected format: {
                    #   "code": "200",
                    #   "msg": "success",
                    #   "data": {
                    #       "symbol": "BTC_USDT",
                    #       "exchange": "bitget",
                    #       "data": {
                    #           "symbol": "BTCUSDT",
                    #           "baseCoin": "BTC",
                    #           "quoteCoin": "USDT",
                    #           ...
                    #       }
                    #   }
                    # }
                    if not isinstance(response, dict):
                        self.logger().warning(f"Invalid response type for {trading_pair}: {type(response)}")
                        continue

                    response_code = response.get("code")
                    if response_code != "200":
                        error_msg = response.get("msg", "Unknown error")
                        self.logger().warning(f"API error for {trading_pair}: code={response_code}, msg={error_msg}")
                        continue

                    # Get outer data object
                    outer_data = response.get("data", {})
                    if not outer_data:
                        self.logger().warning(f"No outer data in response for {trading_pair}, response: {response}")
                        continue

                    # Get inner data object which contains the actual pair information
                    pair_data = outer_data.get("data", {})
                    if not pair_data:
                        self.logger().warning(f"No inner data in response for {trading_pair}, outer_data: {outer_data}")
                        continue

                    # Extract symbol from the inner data object
                    # The inner data has "symbol": "BTCUSDT" (no underscore)
                    symbol = pair_data.get("symbol", "")
                    if not symbol:
                        # Fallback: convert BTC_USDT to BTCUSDT
                        symbol = api_symbol.replace("_", "").upper()
                    else:
                        symbol = symbol.upper()

                    # Wrap in the same format as the bulk endpoint
                    # The bulk endpoint format is: {"symbol": "BTCUSDT", "data": {...}}
                    pairs.append({
                        "symbol": symbol,  # Should be "BTCUSDT" format to match bulk endpoint
                        "data": pair_data  # The inner data object with baseCoin, quoteCoin, etc.
                    })
                    self.logger().info(f"Successfully fetched pair info for {trading_pair} (URL: {api_symbol}) -> symbol: {symbol}")

                except asyncio.TimeoutError:
                    self.logger().warning(f"Timeout (5s) fetching pair info for {trading_pair}, skipping")
                except Exception as e:
                    self.logger().error(f"Error fetching pair info for {trading_pair}: {e}", exc_info=True)

            if not pairs:
                self.logger().warning("No trading pairs fetched from API")
                return []

            self.logger().info(f"Fetched {len(pairs)} trading pairs from Cofinex API (only configured pairs)")
            return pairs

        except Exception as e:
            self.logger().error(f"Error fetching trading pairs: {e}", exc_info=True)
            # Re-raise to let caller handle it
            raise

    async def _fetch_trading_pairs(self) -> List[Dict[str, Any]]:
        """
        Fetch ALL trading pairs from Cofinex Market Data API.
        This is the original method that fetches all 725 pairs - kept for backward compatibility.

        Returns:
            List of trading pair dictionaries from the API response
        """
        try:
            # Create a simple API factory for public endpoints (no auth needed)
            from hummingbot.connector.exchange.cofinex.cofinex_web_utils import (
                build_api_factory_without_time_synchronizer_pre_processor,
                create_throttler,
            )

            throttler = create_throttler()
            api_factory = build_api_factory_without_time_synchronizer_pre_processor(throttler)
            rest_assistant = await api_factory.get_rest_assistant()

            # Build URL for market data API
            # Use domain from connector if available, otherwise default to "main"
            domain = getattr(self, '_domain', CONSTANTS.DEFAULT_DOMAIN)
            url = CONSTANTS.MARKET_DATA_BASE_URL.get(domain, CONSTANTS.MARKET_DATA_BASE_URL["main"]) + CONSTANTS.TRADING_PAIRS_PATH_URL

            # Make the API request with timeout
            # Note: API can sometimes take 5+ seconds, so we use a generous timeout
            import asyncio
            self.logger().info(f"Fetching trading pairs from {url} (this may take 5+ seconds)...")
            try:
                response = await asyncio.wait_for(
                    rest_assistant.execute_request(
                        url=url,
                        method=RESTMethod.GET,
                        throttler_limit_id=CONSTANTS.TRADING_PAIRS_PATH_URL,
                    ),
                    timeout=20.0  # Increased to 20 seconds to handle slow API responses
                )
                self.logger().info("Successfully fetched trading pairs from Cofinex API")
            except asyncio.TimeoutError:
                self.logger().error("Timeout (20s) fetching trading pairs from Cofinex API")
                raise Exception("Timeout fetching trading pairs from Cofinex API")

            # Parse response
            # Expected format: {"code": "200", "msg": "success", "data": {"pairs": [...]}}
            if not isinstance(response, dict):
                raise Exception(f"Unexpected response type: {type(response)}")

            if response.get("code") != "200":
                error_msg = response.get("msg", "Unknown error")
                raise Exception(f"API returned error: {error_msg}")

            data = response.get("data", {})
            if not isinstance(data, dict):
                raise Exception(f"Unexpected data type: {type(data)}")

            pairs = data.get("pairs", [])

            if not pairs:
                self.logger().warning("No trading pairs returned from API")
                return []

            self.logger().info(f"Fetched {len(pairs)} trading pairs from Cofinex API")
            # Log first few pairs as examples
            if pairs:
                sample_pairs = pairs[:5]
                for pair in sample_pairs:
                    symbol = pair.get("symbol", "unknown")
                    data = pair.get("data", {})
                    base = data.get("baseCoin", "?")
                    quote = data.get("quoteCoin", "?")
                    self.logger().debug(f"Sample pair: {symbol} -> {base}-{quote}")
            return pairs

        except Exception as e:
            self.logger().error(f"Error fetching trading pairs: {e}", exc_info=True)
            # Re-raise to let caller handle it
            raise

    # =============================================================================
    # UTILITY METHODS
    # =============================================================================

    @classmethod
    def logger(cls) -> HummingbotLogger:
        """Get logger instance - use parent class logger"""
        return ExchangePyBase.logger()

    async def _make_network_check_request(self):
        """
        Override to add timeout and logging to prevent hangs
        """
        import asyncio
        self.logger().info("Making network check request...")
        try:
            # Add timeout to prevent hanging
            result = await asyncio.wait_for(
                super()._make_network_check_request(),
                timeout=5.0
            )
            return result
        except asyncio.TimeoutError:
            self.logger().error("Network check request timed out after 5 seconds")
            raise
        except Exception as e:
            self.logger().error(f"Network check request failed: {e}", exc_info=True)
            raise

    def _parse_order_data_to_limit_order(self, order_data: Dict[str, Any]) -> Optional[LimitOrder]:
        """
        Parse order data from exchange API response to LimitOrder.

        Handles the actual exchange format:
        {
            "order_id": 1768056258031,
            "symbol": "CNX/USDT",
            "side": "SELL",
            "order_type": "GTC",
            "price": "0.1",
            "size": "10",
            "filled": "0",
            "status": "OPEN"
        }

        Args:
            order_data: Raw order data from exchange API

        Returns:
            LimitOrder object or None if parsing fails
        """
        try:
            # Extract fields from exchange format
            order_id = str(order_data.get("order_id", ""))
            if not order_id:
                self.logger().warning(f"Order data missing order_id: {order_data}")
                return None

            symbol = order_data.get("symbol", "")
            if not symbol:
                self.logger().warning(f"Order data missing symbol: {order_data}")
                return None

            # Convert exchange symbol format (CNX/USDT) to Hummingbot format (CNX-USDT)
            trading_pair = symbol.replace("/", "-")

            # Extract side
            side = order_data.get("side", "").upper()
            is_buy = side == "BUY"

            # Extract price and quantity
            price_str = order_data.get("price", "0")
            size_str = order_data.get("size", "0")
            filled_str = order_data.get("filled", "0")

            try:
                price = Decimal(str(price_str))
                quantity = Decimal(str(size_str))
                filled_quantity = Decimal(str(filled_str))
            except (ValueError, TypeError) as e:
                self.logger().warning(f"Error parsing order amounts: {e}, order_data: {order_data}")
                return None

            # Parse status (exchange uses "OPEN", Hummingbot uses "NEW")
            status_str = order_data.get("status", "OPEN").upper()
            status = self._parse_order_status(status_str)

            # Extract order type (exchange uses "GTC" but means LIMIT with GTC)
            order_type_str = order_data.get("order_type", "GTC").upper()
            if order_type_str in ["GTC", "LIMIT"]:
                order_type = OrderType.LIMIT
            elif order_type_str == "MARKET":
                order_type = OrderType.MARKET
            else:
                order_type = OrderType.LIMIT  # Default to LIMIT

            # Extract base and quote currencies from trading pair
            parts = trading_pair.split("-")
            base_currency = parts[0] if len(parts) >= 1 else ""
            quote_currency = parts[1] if len(parts) >= 2 else ""

            # Create LimitOrder
            limit_order = LimitOrder(
                client_order_id=order_id,  # Use exchange order_id as client_order_id (will be mapped later)
                trading_pair=trading_pair,
                is_buy=is_buy,
                base_currency=base_currency,
                quote_currency=quote_currency,
                price=price,
                quantity=quantity,
                filled_quantity=filled_quantity,
                status=status,
                order_type=order_type,
                time_in_force="GTC"
            )

            return limit_order

        except Exception as e:
            self.logger().error(f"Error parsing order data: {e}, order_data: {order_data}", exc_info=True)
            return None

    def _parse_order_data(self, order_data: Dict[str, Any]) -> LimitOrder:
        """
        Parse order data from API response (legacy method for compatibility).

        This method expects a different format (standardized format).
        For actual exchange responses, use _parse_order_data_to_limit_order instead.

        Args:
            order_data: Raw order data from API

        Returns:
            LimitOrder object
        """
        # Try to parse using the new method first (handles exchange format)
        limit_order = self._parse_order_data_to_limit_order(order_data)
        if limit_order:
            return limit_order

        # Fallback to old format parsing (for compatibility)
        return LimitOrder(
            client_order_id=order_data.get("orderId", order_data.get("order_id", "")),
            trading_pair=order_data.get("symbol", "").replace("/", "-"),
            is_buy=order_data.get("side", "").upper() == "BUY",
            base_currency="",
            quote_currency="",
            price=Decimal(str(order_data.get("price", "0"))),
            quantity=Decimal(str(order_data.get("origQty", order_data.get("size", "0")))),
            filled_quantity=Decimal(str(order_data.get("executedQty", order_data.get("filled", "0")))),
            status=self._parse_order_status(order_data.get("status", "NEW")),
            order_type=OrderType.LIMIT,
            time_in_force="GTC"
        )
