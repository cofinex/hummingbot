"""
Cofinex API User Stream Data Source (REST-only)

This module provides a REST API-based user stream data source.
Instead of using WebSocket, it polls the REST API at regular intervals
to get account updates (balances, orders, trades).

This is simpler to implement and more reliable than WebSocket,
but has slightly higher latency (1-10 seconds depending on poll interval).
"""

import asyncio
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS, cofinex_web_utils as web_utils
from hummingbot.connector.exchange.cofinex.cofinex_auth import CofinexAuth
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
            cls._logger = HummingbotLogger(cls.__name__)
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
        self.logger().info("Starting REST-based user stream polling...")

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
                raise
            except Exception as e:
                self.logger().exception(
                    f"Unexpected error while polling user stream. Retrying after 5 seconds... Error: {e}"
                )
                await self._sleep(5.0)

    async def _poll_balances(self, output: asyncio.Queue):
        """
        Poll account balances and detect changes.

        :param output: Queue to put balance update messages
        """
        try:
            rest_assistant = await self._api_factory.get_rest_assistant()

            # TODO: Adjust endpoint based on actual Cofinex API
            rest_api_base_url = getattr(self._connector, "_rest_api_base_url", None) if self._connector else None
            response = await rest_assistant.execute_request(
                url=web_utils.private_rest_url(
                    path_url=CONSTANTS.ACCOUNTS_PATH_URL,
                    domain=self._domain,
                    rest_api_base_url=rest_api_base_url,
                ),
                method=RESTMethod.GET,
                is_auth_required=True,
                throttler_limit_id=CONSTANTS.ACCOUNTS_PATH_URL,
            )

            # TODO: Parse response based on actual Cofinex API format
            # Common formats:
            # - {"balances": [{"currency": "BTC", "free": "1.0", "locked": "0.0"}, ...]}
            # - {"data": {"balances": [...]}}
            # - {"account": {"balances": [...]}}

            balances = self._parse_balances_response(response)

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
            self.logger().warning(f"Error polling balances: {e}")

    async def _poll_orders(self, output: asyncio.Queue):
        """
        Poll open orders and detect status changes.

        :param output: Queue to put order update messages
        """
        try:
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

            # TODO: Parse response based on actual Cofinex API format
            orders = self._parse_orders_response(response)

            # Track current orders
            current_order_ids = set()

            for order in orders:
                order_id = order.get("orderId") or order.get("id")
                current_order_ids.add(order_id)

                # Check if order status changed
                last_order = self._last_known_orders.get(order_id)

                if last_order is None or last_order.get("status") != order.get("status"):
                    # Emit order update event
                    event_message = {
                        "event_type": "order_update",
                        "data": order,
                        "timestamp": self._time(),
                    }
                    output.put_nowait(event_message)
                    self._last_known_orders[order_id] = order

            # Check for orders that were filled/cancelled (no longer in open orders)
            known_order_ids = set(self._last_known_orders.keys())
            closed_order_ids = known_order_ids - current_order_ids

            for order_id in closed_order_ids:
                last_order = self._last_known_orders.get(order_id)
                if last_order and last_order.get("status") not in ["FILLED", "CANCELED"]:
                    # Order was filled or cancelled
                    event_message = {
                        "event_type": "order_update",
                        "data": {
                            **last_order,
                            "status": "FILLED",  # Assume filled, could be cancelled
                        },
                        "timestamp": self._time(),
                    }
                    output.put_nowait(event_message)
                    # Remove from tracking
                    self._last_known_orders.pop(order_id, None)

        except Exception as e:
            self.logger().warning(f"Error polling orders: {e}")

    def _parse_balances_response(self, response: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        """
        Parse balance response from Cofinex API.

        TODO: Adjust based on actual Cofinex API response format

        :param response: API response
        :return: Dictionary mapping currency to balance data
        """
        balances = {}

        # Try different possible response formats
        if "balances" in response:
            balance_list = response["balances"]
        elif "data" in response and "balances" in response["data"]:
            balance_list = response["data"]["balances"]
        elif "account" in response and "balances" in response["account"]:
            balance_list = response["account"]["balances"]
        else:
            # Assume response is a list of balances
            balance_list = response if isinstance(response, list) else []

        for balance in balance_list:
            # Common formats:
            # {"currency": "BTC", "free": "1.0", "locked": "0.0"}
            # {"asset": "BTC", "available": "1.0", "locked": "0.0"}
            currency = balance.get("currency") or balance.get("asset") or balance.get("coin")
            if currency:
                free = balance.get("free") or balance.get("available") or "0"
                locked = balance.get("locked") or balance.get("frozen") or "0"
                total = str(float(free) + float(locked))

                balances[currency] = {
                    "available": free,
                    "locked": locked,
                    "total": total,
                }

        return balances

    def _parse_orders_response(self, response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Parse orders response from Cofinex API.

        TODO: Adjust based on actual Cofinex API response format

        :param response: API response
        :return: List of order dictionaries
        """
        # Try different possible response formats
        if isinstance(response, list):
            return response
        elif "orders" in response:
            return response["orders"]
        elif "data" in response:
            data = response["data"]
            if isinstance(data, list):
                return data
            elif "orders" in data:
                return data["orders"]
        elif "result" in response:
            return response["result"] if isinstance(response["result"], list) else []

        return []

    def _time(self) -> float:
        """Get current time in seconds"""
        return time.time()

    async def _sleep(self, delay: float):
        """Sleep for specified delay"""
        await asyncio.sleep(delay)
