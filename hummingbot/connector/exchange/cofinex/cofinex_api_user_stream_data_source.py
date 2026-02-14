"""
Cofinex API User Stream Data Source (REST-only)

This module provides a REST API-based user stream data source.
Instead of using WebSocket, it polls the REST API at regular intervals
to get account updates (balances, orders, trades).

This is simpler to implement and more reliable than WebSocket,
but has slightly higher latency (1-10 seconds depending on poll interval).
"""

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS, cofinex_web_utils as web_utils
from hummingbot.connector.exchange.cofinex.cofinex_auth import CofinexAuth
from hummingbot.core.data_type.in_flight_order import OrderState
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger

if TYPE_CHECKING:
    from hummingbot.connector.exchange.cofinex.cofinex_exchange import CofinexExchange


class CofinexAPIUserStreamDataSource(UserStreamTrackerDataSource):
    """
    REST API-based user stream data source for Cofinex.

    This implementation polls the REST API instead of using WebSocket.
    It fetches:
    - Account balances
    - Open orders
    - Order status updates
    - Trade history (optional)
    """

    _logger: Optional[HummingbotLogger] = None

    # Polling interval in seconds
    # Adjust based on rate limits and needs
    POLL_INTERVAL = 5.0  # Poll every 5 seconds
    BALANCE_POLL_INTERVAL = 10.0  # Poll balances less frequently
    ORDER_POLL_INTERVAL = 3.0  # Poll orders more frequently

    def __init__(
            self,
            auth: CofinexAuth,
            trading_pairs: List[str],
            connector: "CofinexExchange",
            api_factory: WebAssistantsFactory,
            domain: str = CONSTANTS.DEFAULT_DOMAIN,
    ):
        super().__init__()
        self._auth = auth
        self._trading_pairs = trading_pairs
        self._connector = connector
        self._domain = domain
        self._api_factory = api_factory

        # Ensure auth has API factory for token requests
        if self._auth and not self._auth._api_factory:
            self._auth.set_api_factory(api_factory)

        self._last_recv_time = 0.0
        self._last_balance_poll = 0.0
        self._last_order_poll = 0.0
        self._last_known_balances: Dict[str, Any] = {}
        self._last_known_orders: Dict[str, Any] = {}

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    @property
    def last_recv_time(self) -> float:
        """
        Returns the time of the last received message.
        For REST polling, this is updated whenever we successfully poll.
        """
        return self._last_recv_time

    async def listen_for_user_stream(self, output: asyncio.Queue):
        """
        Polls REST API for user account updates instead of using WebSocket.

        This method continuously polls:
        - Account balances
        - Open orders
        - Order status updates

        :param output: the queue to use to store the received messages
        """
        # Emit a normal log so it shows up in the main logs (stderr prints are not captured)
        self.logger().info(f"[USER_STREAM] listen_for_user_stream coroutine started at {self._time()}")

        try:
            self.logger().info("=== listen_for_user_stream ENTRY ===")
            self.logger().info(f"listen_for_user_stream called with output queue: {output}, auth: {self._auth}, api_factory: {self._api_factory}")
            self.logger().info("Starting REST-based user stream polling...")

            # One-time sync at script start - do not call sync on every poll
            await self._sync_balances_once()

            while True:
                try:
                    current_time = self._time()

                    # Poll balances less frequently
                    if current_time - self._last_balance_poll >= self.BALANCE_POLL_INTERVAL:
                        await self._poll_balances(output)
                        self._last_balance_poll = current_time

                    # Poll orders more frequently
                    if current_time - self._last_order_poll >= self.ORDER_POLL_INTERVAL:
                        await self._poll_orders(output)
                        self._last_order_poll = current_time

                    # Update last received time
                    self._last_recv_time = current_time

                    # Sleep for a short interval before next poll
                    await self._sleep(1.0)

                except asyncio.CancelledError:
                    self.logger().info("listen_for_user_stream cancelled")
                    raise
                except Exception as e:
                    self.logger().exception(
                        f"Unexpected error while polling user stream. Retrying after 5 seconds... Error: {e}"
                    )
                    await self._sleep(5.0)
        except Exception as e:
            self.logger().error(f"FATAL ERROR in listen_for_user_stream: {e}", exc_info=True)
            raise

    async def _sync_balances_once(self):
        """
        Call POST /balances/sync once at script start.
        Do not call on every poll - sync is expensive.
        """
        try:
            rest_assistant = await self._api_factory.get_rest_assistant()
            rest_api_base_url = getattr(self._connector, "_rest_api_base_url", None) if self._connector else None
            sync_url = web_utils.private_rest_url(
                path_url=CONSTANTS.BALANCES_SYNC_PATH_URL,
                domain=self._domain,
                rest_api_base_url=rest_api_base_url,
            )
            await rest_assistant.execute_request(
                url=sync_url,
                method=RESTMethod.POST,
                data={},  # Send empty JSON body - user_id is extracted from token for regular users
                is_auth_required=True,
                throttler_limit_id=CONSTANTS.BALANCES_SYNC_PATH_URL,
            )
            self.logger().info("[USER_STREAM] One-time balance sync completed at start")
        except Exception as e:
            self.logger().warning(f"[USER_STREAM] Error during one-time balance sync: {e}")

    async def _poll_balances(self, output: asyncio.Queue):
        """
        Poll account balances and detect changes.

        Only GET /balances - sync is called once at script start, not on every poll.
        """
        try:
            start_ts = self._time()
            self.logger().info("[USER_STREAM] _poll_balances start")
            response = None
            rest_assistant = await self._api_factory.get_rest_assistant()
            rest_api_base_url = getattr(self._connector, "_rest_api_base_url", None) if self._connector else None

            # Step 1: Sync balances - DISABLED: we call sync once at script start only
            # try:
            #     sync_url = web_utils.private_rest_url(
            #         path_url=CONSTANTS.BALANCES_SYNC_PATH_URL,
            #         domain=self._domain,
            #         rest_api_base_url=rest_api_base_url,
            #     )
            #     await rest_assistant.execute_request(
            #         url=sync_url,
            #         method=RESTMethod.POST,
            #         data={},  # Send empty JSON body - user_id is extracted from token for regular users
            #         is_auth_required=True,
            #         throttler_limit_id=CONSTANTS.BALANCES_SYNC_PATH_URL,
            #     )
            # except Exception as e:
            #     self.logger().warning(f"[USER_STREAM] Error syncing balances: {e}")

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

            try:
                balances = self._parse_balances_response(response)
            except Exception as e:
                self.logger().warning(
                    "[USER_STREAM] Error parsing balances response: %s response=%s",
                    e,
                    self._shorten_for_log(response),
                )
                return
            self.logger().info(
                "[USER_STREAM] _poll_balances received %s balances in %.2fs",
                len(balances),
                self._time() - start_ts,
            )

            # Detect changes and emit events
            for currency, balance_data in balances.items():
                last_balance = self._last_known_balances.get(currency)

                # Check if balance changed
                if last_balance is None or last_balance != balance_data:
                    # Emit balance update event
                    event_message = {
                        "event_type": "balance_update",
                        "data": {
                            "currency": currency,
                            "available": balance_data.get("available", "0"),
                            "locked": balance_data.get("locked", "0"),
                            "total": balance_data.get("total", "0"),
                        },
                        "timestamp": self._time(),
                    }
                    output.put_nowait(event_message)
                    self._last_known_balances[currency] = balance_data

        except Exception as e:
            self.logger().warning(
                "[USER_STREAM] Error polling balances: %s response=%s",
                e,
                self._shorten_for_log(response),
            )

    async def _poll_orders(self, output: asyncio.Queue):
        """
        Poll open orders and detect status changes.

        :param output: Queue to put order update messages
        """
        try:
            start_ts = self._time()
            self.logger().info("[USER_STREAM] _poll_orders start")
            response = None
            rest_assistant = await self._api_factory.get_rest_assistant()

            # Poll open orders
            # TODO: Adjust endpoint based on actual Cofinex API
            rest_api_base_url = getattr(self._connector, "_rest_api_base_url", None) if self._connector else None
            response = await rest_assistant.execute_request(
                url=web_utils.private_rest_url(
                    path_url=CONSTANTS.OPEN_ORDERS_PATH_URL,
                    domain=self._domain,
                    rest_api_base_url=rest_api_base_url,
                ),
                method=RESTMethod.GET,
                is_auth_required=True,
                throttler_limit_id=CONSTANTS.OPEN_ORDERS_PATH_URL,
            )

            # Parse response based on actual Cofinex API format:
            # {
            #     "user_id": 1120,
            #     "orders": [...],
            #     "timestamp": "2026-01-10T20:14:36.748759"
            # }
            try:
                orders = self._parse_orders_response(response)
            except Exception as e:
                self.logger().warning(
                    "[USER_STREAM] Error parsing orders response: %s response=%s",
                    e,
                    self._shorten_for_log(response),
                )
                return
            self.logger().info(
                "[USER_STREAM] _poll_orders received %s orders in %.2fs",
                len(orders),
                self._time() - start_ts,
            )

            # Track current orders
            current_order_ids = set()

            for order in orders:
                # Handle order_id (can be number or string)
                order_id_raw = order.get("order_id") or order.get("orderId") or order.get("id")
                order_id = str(order_id_raw) if order_id_raw is not None else None
                if not order_id:
                    continue
                current_order_ids.add(order_id)

                # Normalize status (exchange uses "OPEN", Hummingbot uses "NEW")
                raw_status = order.get("status", "").upper()
                normalized_status = raw_status
                if raw_status == "OPEN":
                    normalized_status = "NEW"

                # Create a normalized order dict for comparison
                normalized_order = {
                    **order,
                    "status": normalized_status,
                    "order_id": order_id,  # Ensure order_id is always a string
                }

                # Check if order status changed
                last_order = self._last_known_orders.get(order_id)

                if last_order is None or last_order.get("status") != normalized_status:
                    # Emit order update event with normalized status
                    event_message = {
                        "event_type": "order_update",
                        "data": normalized_order,
                        "timestamp": self._time(),
                    }
                    output.put_nowait(event_message)
                    self._last_known_orders[order_id] = normalized_order

            # Check for orders that were filled/cancelled (no longer in open orders)
            known_order_ids = set(self._last_known_orders.keys())
            closed_order_ids = known_order_ids - current_order_ids

            for order_id in closed_order_ids:
                last_order = self._last_known_orders.get(order_id)
                if last_order and last_order.get("status") not in ["FILLED", "CANCELED"]:
                    # Order disappeared - need to determine if it was FILLED or CANCELLED
                    # First, check if Hummingbot cancelled it (it would be in order tracker)
                    actual_status = None
                    tracked_order = None

                    # Check if connector has order tracker and try to find tracked order
                    if self._connector and hasattr(self._connector, '_order_tracker'):
                        # Try to find tracked order by exchange_order_id in all possible locations
                        # First try updatable orders
                        for client_id, in_flight_order in self._connector._order_tracker.all_updatable_orders.items():
                            if in_flight_order.exchange_order_id == order_id:
                                tracked_order = in_flight_order
                                break

                        # If not found, try lost orders
                        if tracked_order is None:
                            for client_id, in_flight_order in self._connector._order_tracker.lost_orders.items():
                                if in_flight_order.exchange_order_id == order_id:
                                    tracked_order = in_flight_order
                                    break

                        # If still not found, try cached orders
                        if tracked_order is None:
                            for client_id, in_flight_order in self._connector._order_tracker.cached_orders.items():
                                if in_flight_order.exchange_order_id == order_id:
                                    tracked_order = in_flight_order
                                    break

                        # Even if order is marked as CANCELED locally, verify with exchange
                        # because order might have been filled during/after cancellation attempt
                        # Only trust local CANCELED state if we can't query exchange
                        if tracked_order and tracked_order.current_state == OrderState.CANCELED:
                            # Don't set actual_status yet - query exchange first to verify
                            pass

                    # Always query order status from exchange to get the truth
                    # This catches cases where order was filled despite being marked as cancelled locally
                    order_status_data = None
                    if self._connector and tracked_order:
                        try:
                            # Query actual order status from exchange
                            order_status_data = await self._connector._request_order_status(tracked_order)
                            if order_status_data:
                                status_str = order_status_data.get("status", "").upper()
                                if status_str in ["FILLED", "CANCELED", "CANCELLED"]:
                                    actual_status = "CANCELED" if status_str in ["CANCELED", "CANCELLED"] else "FILLED"

                                    # NEW: If FILLED, create and process TradeUpdate to trigger OrderFilledEvent
                                    if actual_status == "FILLED" and hasattr(self._connector, '_create_trade_update_from_order_status'):
                                        try:
                                            from decimal import Decimal

                                            # Set executed amounts FIRST (before processing TradeUpdate)
                                            executed_qty = Decimal(str(order_status_data.get("executedQuantity", "0")))
                                            price = Decimal(str(order_status_data.get("price", "0")))
                                            if executed_qty > 0 and price > 0:
                                                tracked_order.executed_amount_base = executed_qty
                                                tracked_order.executed_amount_quote = executed_qty * price
                                                tracked_order.check_filled_condition()

                                            # Create and process TradeUpdate (triggers OrderFilledEvent)
                                            trade_update = self._connector._create_trade_update_from_order_status(tracked_order, order_status_data)
                                            if trade_update:
                                                self._connector._order_tracker.process_trade_update(trade_update)
                                                self.logger().info(f"[USER_STREAM] Processed TradeUpdate for FILLED order {order_id} from polling.")
                                        except Exception as trade_error:
                                            self.logger().warning(
                                                f"[USER_STREAM] Error creating TradeUpdate for {order_id}: {trade_error}"
                                            )
                        except Exception as e:
                            self.logger().warning(
                                f"[USER_STREAM] Error querying order status for {order_id}: {e}"
                            )

                    # If we couldn't query exchange or query failed, use fallback logic
                    if actual_status is None:
                        # If order is marked as CANCELED locally but we couldn't verify with exchange,
                        # still default to FILLED (conservative - exchange is source of truth)
                        # This handles cases where cancellation succeeded locally but order was actually filled
                        if tracked_order and tracked_order.current_state == OrderState.CANCELED:
                            # Order was marked cancelled locally, but we couldn't verify with exchange
                            # Default to FILLED since exchange is source of truth
                            actual_status = "FILLED"
                            self.logger().warning(
                                f"[USER_STREAM] Order {order_id} was marked CANCELED locally but "
                                f"could not verify with exchange. Assuming FILLED (exchange is source of truth)."
                            )
                        else:
                            # No local state or unknown - default to FILLED
                            actual_status = "FILLED"
                            self.logger().info(
                                f"[USER_STREAM] Order {order_id} disappeared from open orders, "
                                f"assuming {actual_status} (could not determine actual status)"
                            )

                    # Emit order update event with determined status
                    event_message = {
                        "event_type": "order_update",
                        "data": {
                            **last_order,
                            "status": actual_status,
                        },
                        "timestamp": self._time(),
                    }
                    output.put_nowait(event_message)
                    # Remove from tracking
                    self._last_known_orders.pop(order_id, None)

        except Exception as e:
            self.logger().warning(
                "[USER_STREAM] Error polling orders: %s response=%s",
                e,
                self._shorten_for_log(response),
            )

    def _shorten_for_log(self, obj: Any, limit: int = 500) -> str:
        if obj is None:
            return "None"
        try:
            if isinstance(obj, str):
                text = obj
            else:
                text = json.dumps(obj, default=str, ensure_ascii=True)
        except Exception:
            text = repr(obj)
        if len(text) > limit:
            return text[:limit] + "...(truncated)"
        return text

    def _parse_balances_response(self, response: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        """
        Parse balance response from Cofinex API.

        Expected format:
        {
            "user_id": 1120,
            "balances": {
                "USDT": {"balance": 6.775, "available": 6.775, "locked": 0.0},
                "CNX": {"balance": 60.0, "available": 60.0, "locked": 0.0}
            },
            "timestamp": "2026-01-10T14:59:54.989630"
        }

        :param response: API response
        :return: Dictionary mapping currency to balance data
        """
        balances = {}

        # Handle new format: balances is a dictionary mapping currency to balance info
        balances_data = None
        if "balances" in response:
            balances_data = response["balances"]
        elif "data" in response and "balances" in response["data"]:
            balances_data = response["data"]["balances"]
        elif "account" in response and "balances" in response["account"]:
            balances_data = response["account"]["balances"]

        if balances_data:
            # New format: balances is a dict like {"USDT": {"balance": 6.775, ...}, ...}
            if isinstance(balances_data, dict):
                for currency, balance_info in balances_data.items():
                    if isinstance(balance_info, dict):
                        # Extract available, locked, and balance
                        available = str(balance_info.get("available", balance_info.get("balance", "0")))
                        locked = str(balance_info.get("locked", "0"))
                        balance_total = str(balance_info.get("balance", str(float(available) + float(locked))))

                        balances[currency.upper()] = {
                            "available": available,
                            "locked": locked,
                            "total": balance_total,
                        }
                return balances

        # Fallback: Try old format (list of balances)
        balance_list = None
        if isinstance(response, list):
            balance_list = response
        elif "balances" in response and isinstance(response["balances"], list):
            balance_list = response["balances"]
        elif "data" in response and isinstance(response["data"], list):
            balance_list = response["data"]

        if balance_list:
            for balance in balance_list:
                # Old formats:
                # {"currency": "BTC", "free": "1.0", "locked": "0.0"}
                # {"asset": "BTC", "available": "1.0", "locked": "0.0"}
                currency = balance.get("currency") or balance.get("asset") or balance.get("coin")
                if currency:
                    free = balance.get("free") or balance.get("available") or "0"
                    locked = balance.get("locked") or balance.get("frozen") or "0"
                    total = str(float(free) + float(locked))

                    balances[currency.upper()] = {
                        "available": free,
                        "locked": locked,
                        "total": total,
                    }

        return balances

    def _parse_orders_response(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse orders response from Cofinex API.

        Expected format:
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

        :param response: API response
        :return: List of order dictionaries
        """
        # Handle actual exchange format
        if isinstance(response, dict):
            if "orders" in response:
                orders = response["orders"]
                if isinstance(orders, list):
                    return orders
                return []
            elif "data" in response:
                data = response["data"]
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and "orders" in data:
                    return data["orders"] if isinstance(data["orders"], list) else []

        # Fallback: try other formats
        if isinstance(response, list):
            return response

        # Try legacy formats for compatibility
        if "result" in response:
            result = response["result"]
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "orders" in result:
                return result["orders"] if isinstance(result["orders"], list) else []

        return []

    def _time(self) -> float:
        """Get current time in seconds"""
        return time.time()

    async def _sleep(self, delay: float):
        """Sleep for specified delay"""
        await asyncio.sleep(delay)
