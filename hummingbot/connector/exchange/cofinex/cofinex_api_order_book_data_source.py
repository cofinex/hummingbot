"""
Cofinex API Order Book Data Source

This module provides the data source for order book tracking via REST API.
It handles fetching order book snapshots and can be extended with WebSocket support.
"""

import asyncio
import json
import logging
import math
import os
import sys
import threading
import time
import traceback
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage, OrderBookMessageType
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, WSJSONRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.core.web_assistant.ws_assistant import WSAssistant
from hummingbot.logger import HummingbotLogger


def _log_with_timestamp(msg: str, level: str = "INFO"):
    """Helper to log with timestamp"""
    logger = logging.getLogger(__name__)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    payload = f"[{timestamp}] {msg}"
    level_upper = level.upper()
    if level_upper in ("ERROR", "EXCEPTION"):
        logger.error(payload)
    elif level_upper in ("WARNING", "WARN"):
        logger.warning(payload)
    else:
        logger.info(payload)


if TYPE_CHECKING:
    from hummingbot.connector.exchange.cofinex.cofinex_exchange import CofinexExchange


class CofinexAPIOrderBookDataSource(OrderBookTrackerDataSource):
    """
    Order book data source for Cofinex exchange.
    Fetches order book snapshots via REST API.
    """

    _logger: Optional[HummingbotLogger] = None

    def __init__(
            self,
            trading_pairs: List[str],
            connector: "CofinexExchange",
            api_factory: WebAssistantsFactory,
            domain: str = CONSTANTS.DEFAULT_DOMAIN,
            ws_prefix: Optional[str] = None,
    ):
        _log_with_timestamp(f"[COFINEX OBS] __init__ called with {len(trading_pairs)} pairs: {trading_pairs}")
        super().__init__(trading_pairs)
        self._connector = connector
        self._domain = domain
        self._api_factory = api_factory

        # Store WebSocket prefix (with environment variable fallback if not provided)
        if ws_prefix is None:
            ws_prefix = os.getenv("COFINEX_WS_PREFIX") or os.getenv("DEV_NAMESPACE")
        if ws_prefix:
            ws_prefix = ws_prefix.strip()
            if not ws_prefix:
                ws_prefix = None
        self._ws_prefix = ws_prefix

        self._snapshot_watchdog_task: Optional[asyncio.Task] = None
        self._snapshot_watchdog_thread: Optional[threading.Thread] = None
        self._snapshot_watchdog_stop: Optional[threading.Event] = None
        self._snapshot_heartbeat: float = 0.0
        self._snapshot_watchdog_dumped: bool = False
        self._last_snapshot_top: Dict[str, Dict[str, Any]] = {}
        self._snapshot_static_count: Dict[str, int] = {}
        self._ws_last_message_time: float = 0.0
        self._ws_first_message_logged: bool = False
        self._ws_subscribed: bool = False
        _log_with_timestamp(f"[COFINEX OBS] __init__ completed with ws_prefix={ws_prefix}")

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = HummingbotLogger(cls.__name__)
        return cls._logger

    async def get_last_traded_prices(
            self,
            trading_pairs: List[str],
            domain: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Get last traded prices for trading pairs

        :param trading_pairs: List of trading pairs
        :param domain: Optional domain override

        :return: Dictionary mapping trading pairs to last traded prices
        """
        # TODO: Implement actual price fetching from Cofinex API
        # This typically involves calling a ticker endpoint
        # Commented out verbose logging - fires too frequently
        # _log_with_timestamp(f"[COFINEX OBS] get_last_traded_prices ENTRY for {len(trading_pairs)} pairs: {trading_pairs}")
        prices: Dict[str, float] = {}
        order_books = {}
        if self._connector is not None:
            order_books = self._connector.order_books
        now = time.perf_counter()
        for trading_pair in trading_pairs:
            try:
                order_book = order_books.get(trading_pair)
                if order_book is None:
                    continue
                bid = order_book.get_price(is_buy=False)
                ask = order_book.get_price(is_buy=True)
                if not math.isnan(bid) and not math.isnan(ask):
                    prices[trading_pair] = (bid + ask) / 2.0
                elif not math.isnan(bid):
                    prices[trading_pair] = bid
                elif not math.isnan(ask):
                    prices[trading_pair] = ask
                if trading_pair in prices:
                    order_book.last_trade_price_rest_updated = now
                else:
                    # Avoid tight loops when no usable price is available yet.
                    order_book.last_trade_price_rest_updated = now
            except Exception as e:
                self.logger().warning(f"Error computing last price for {trading_pair}: {e}")
        if not prices:
            await asyncio.sleep(1.0)
        # Commented out verbose logging - fires too frequently
        # _log_with_timestamp(f"[COFINEX OBS] get_last_traded_prices EXIT with {len(prices)} prices")
        return prices

    async def get_new_order_book(self, trading_pair: str) -> OrderBook:
        order_book = await super().get_new_order_book(trading_pair)
        now = time.perf_counter()
        try:
            order_book.last_applied_trade = now
            order_book.last_trade_price_rest_updated = now
            bid = order_book.get_price(is_buy=False)
            ask = order_book.get_price(is_buy=True)
            if not math.isnan(bid) and not math.isnan(ask):
                order_book.last_trade_price = (bid + ask) / 2.0
        except Exception:
            pass
        return order_book

    async def _order_book_snapshot(self, trading_pair: str) -> OrderBookMessage:
        """
        Fetches order book snapshot for a trading pair

        :param trading_pair: The trading pair in Hummingbot format (e.g., "CNX-USDT")

        :return: OrderBookMessage with snapshot data
        """
        start_time = time.time()
        _log_with_timestamp(f"[COFINEX OBS] _order_book_snapshot ENTRY for {trading_pair}")
        self.logger().info(f"[ORDER BOOK] _order_book_snapshot called for {trading_pair}")

        try:
            _log_with_timestamp(f"[COFINEX OBS] _order_book_snapshot calling _request_order_book_snapshot for {trading_pair}")
            snapshot_response: Dict[str, Any] = await self._request_order_book_snapshot(trading_pair)
            elapsed = time.time() - start_time
            _log_with_timestamp(f"[COFINEX OBS] _order_book_snapshot received response for {trading_pair} in {elapsed:.2f}s")
            self.logger().info(f"[ORDER BOOK] Successfully received snapshot response for {trading_pair} in {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - start_time
            _log_with_timestamp(f"[COFINEX OBS] _order_book_snapshot ERROR for {trading_pair} after {elapsed:.2f}s: {e}")
            self.logger().error(f"[ORDER BOOK] Error in _order_book_snapshot for {trading_pair} after {elapsed:.2f}s: {e}", exc_info=True)
            raise

        # Parse Cofinex API response format:
        # {
        #     "code": "200",
        #     "msg": "success",
        #     "data": {
        #         "bids": [[price, qty], ...],
        #         "asks": [[price, qty], ...],
        #         "timestamp": 1767784189002
        #     }
        # }

        if snapshot_response.get("code") != "200":
            error_msg = snapshot_response.get("msg", "Unknown error")
            raise Exception(f"Order book API returned error: {error_msg}")

        data = snapshot_response.get("data", {})
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        bid_top = bids[0][0] if bids else None
        ask_top = asks[0][0] if asks else None
        timestamp_ms = data.get("timestamp", 0)
        timestamp = float(timestamp_ms) / 1000.0
        _log_with_timestamp(
            f"[COFINEX OBS] snapshot depth for {trading_pair}: bids={len(bids)} asks={len(asks)} "
            f"top_bid={bid_top} top_ask={ask_top}"
        )
        self._log_snapshot_staleness(
            trading_pair=trading_pair,
            bid_top=bid_top,
            ask_top=ask_top,
            exchange_timestamp=timestamp,
        )

        # Timestamp is in milliseconds, convert to seconds

        # Use timestamp as update_id if no sequence number is available
        update_id = int(timestamp_ms)

        order_book_message_content = {
            "trading_pair": trading_pair,
            "update_id": update_id,
            "bids": bids,
            "asks": asks
        }

        snapshot_msg: OrderBookMessage = OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            order_book_message_content,
            timestamp
        )

        return snapshot_msg

    async def _request_order_book_snapshot(self, trading_pair: str) -> Dict[str, Any]:
        """
        Retrieves a copy of the full order book from the exchange, for a particular trading pair.

        :param trading_pair: the trading pair in Hummingbot format (e.g., "BTC-USDT")

        :return: the response from the exchange (JSON dictionary)
        """
        # Convert trading pair to order book API format
        # Order book API format: {BASE}_{QUOTE} (e.g., "BTC_USDT")
        # Hummingbot format: "BTC-USDT" -> API format: "BTC_USDT"
        # Note: The trading pairs API returns symbols like "BTCUSDT" (no separator),
        # but the order book API specifically requires underscore format
        url_symbol = trading_pair.replace("-", "_").upper()
        self.logger().debug(f"Converted {trading_pair} to order book symbol: {url_symbol}")

        # Build URL: /spot/v1/orderbook/{SYMBOL}?depth=50&level=3
        path_url = f"{CONSTANTS.ORDER_BOOK_PATH_URL}/{url_symbol}"
        params = {
            "depth": 50,  # Number of price levels
            "level": 3    # Order book aggregation level
        }

        import aiohttp
        start_time = time.time()
        _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot ENTRY for {trading_pair}")

        # Use market data base URL (not trade engine API)
        url = CONSTANTS.MARKET_DATA_BASE_URL[self._domain] + path_url

        # Build full URL with params
        full_url = f"{url}?depth={params['depth']}&level={params['level']}"

        _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot URL: {full_url}")
        self.logger().info(f"Fetching order book from: {full_url} (this may take 5+ seconds)...")

        # Try direct aiohttp call as fallback if rest_assistant hangs
        try:
            _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot getting rest_assistant for {trading_pair}")

            # First try with rest_assistant
            try:
                get_assistant_start = time.time()
                rest_assistant = await asyncio.wait_for(
                    self._api_factory.get_rest_assistant(),
                    timeout=5.0
                )
                get_assistant_elapsed = time.time() - get_assistant_start
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot got rest_assistant in {get_assistant_elapsed:.2f}s")

                execute_start = time.time()
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot calling execute_request for {trading_pair}")
                data = await asyncio.wait_for(
                    rest_assistant.execute_request(
                        url=url,
                        params=params,
                        method=RESTMethod.GET,
                        throttler_limit_id=CONSTANTS.ORDER_BOOK_PATH_URL,
                    ),
                    timeout=20.0
                )
                execute_elapsed = time.time() - execute_start
                total_elapsed = time.time() - start_time
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot completed via rest_assistant for {trading_pair} in {total_elapsed:.2f}s (execute: {execute_elapsed:.2f}s)")
                self.logger().info(f"Order book API response for {trading_pair} via rest_assistant in {total_elapsed:.2f}s: {type(data)}")
            except (asyncio.TimeoutError, Exception) as e:
                elapsed = time.time() - start_time
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot rest_assistant failed after {elapsed:.2f}s: {e}, trying direct aiohttp")
                self.logger().warning(f"rest_assistant failed after {elapsed:.2f}s, trying direct aiohttp: {e}")
                # Fallback to direct aiohttp call
                aiohttp_start = time.time()
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot trying direct aiohttp for {trading_pair}")
                async with aiohttp.ClientSession() as session:
                    async with session.get(full_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                        if response.status == 200:
                            data = await response.json()
                            aiohttp_elapsed = time.time() - aiohttp_start
                            total_elapsed = time.time() - start_time
                            _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot completed via direct aiohttp for {trading_pair} in {total_elapsed:.2f}s (aiohttp: {aiohttp_elapsed:.2f}s)")
                            self.logger().info(f"Order book API response for {trading_pair} via direct aiohttp in {total_elapsed:.2f}s")
                        else:
                            error_text = await response.text()
                            raise Exception(f"HTTP {response.status}: {error_text}")

            total_elapsed = time.time() - start_time
            _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot EXIT for {trading_pair} in {total_elapsed:.2f}s")
            return data
        except asyncio.TimeoutError:
            elapsed = time.time() - start_time
            _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot TIMEOUT for {trading_pair} after {elapsed:.2f}s")
            self.logger().error(f"Timeout ({elapsed:.2f}s) fetching order book for {trading_pair} from {full_url}")
            raise Exception(f"Timeout fetching order book snapshot for {trading_pair}")
        except Exception as e:
            elapsed = time.time() - start_time
            _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshot ERROR for {trading_pair} after {elapsed:.2f}s: {e}")
            self.logger().error(f"Error fetching order book for {trading_pair} from {full_url} after {elapsed:.2f}s: {e}", exc_info=True)
            raise

        return data

    def _log_snapshot_staleness(
        self,
        trading_pair: str,
        bid_top: Optional[float],
        ask_top: Optional[float],
        exchange_timestamp: float,
    ) -> None:
        now = time.time()
        prev = self._last_snapshot_top.get(trading_pair)
        if prev is None:
            self._last_snapshot_top[trading_pair] = {
                "bid": bid_top,
                "ask": ask_top,
                "ts": exchange_timestamp,
                "local_ts": now,
            }
            self._snapshot_static_count[trading_pair] = 0
            _log_with_timestamp(
                f"[COFINEX OBS] snapshot timing for {trading_pair}: exchange_ts={exchange_timestamp} "
                f"local_ts={now:.3f}"
            )
            return

        prev_bid = prev.get("bid")
        prev_ask = prev.get("ask")
        prev_local_ts = prev.get("local_ts", now)
        if bid_top == prev_bid and ask_top == prev_ask:
            count = self._snapshot_static_count.get(trading_pair, 0) + 1
            self._snapshot_static_count[trading_pair] = count
            if count >= 3:
                elapsed = now - prev_local_ts
                _log_with_timestamp(
                    f"[COFINEX OBS] snapshot static for {trading_pair}: "
                    f"count={count} elapsed={elapsed:.1f}s top_bid={bid_top} top_ask={ask_top} "
                    f"exchange_ts={exchange_timestamp}",
                    level="WARNING",
                )
        else:
            self._snapshot_static_count[trading_pair] = 0
            _log_with_timestamp(
                f"[COFINEX OBS] snapshot moved for {trading_pair}: "
                f"prev_bid={prev_bid} prev_ask={prev_ask} "
                f"new_bid={bid_top} new_ask={ask_top} exchange_ts={exchange_timestamp}"
            )
            self._last_snapshot_top[trading_pair] = {
                "bid": bid_top,
                "ask": ask_top,
                "ts": exchange_timestamp,
                "local_ts": now,
            }

    async def _request_order_book_snapshots(self, output: asyncio.Queue):
        """
        Request order book snapshots for all trading pairs and add them to the output queue.
        This method is called by the base class after a timeout, or can be called directly.

        :param output: Queue to add snapshot messages to
        """
        start_time = time.time()
        _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshots ENTRY for {len(self._trading_pairs)} pairs: {self._trading_pairs}")
        self.logger().info(f"[ORDER BOOK] _request_order_book_snapshots called for {len(self._trading_pairs)} pairs")

        # Fetch snapshots for each pair with individual timeouts
        for idx, trading_pair in enumerate(self._trading_pairs):
            pair_start = time.time()
            _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshots processing pair {idx + 1}/{len(self._trading_pairs)}: {trading_pair}")
            try:
                self.logger().info(f"[ORDER BOOK] Fetching snapshot for {trading_pair} (may take 5+ seconds)...")

                # Each snapshot has its own 20-second timeout
                snapshot_msg = await asyncio.wait_for(
                    self._order_book_snapshot(trading_pair),
                    timeout=20.0
                )
                output.put_nowait(snapshot_msg)
                pair_elapsed = time.time() - pair_start
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshots queued snapshot for {trading_pair} in {pair_elapsed:.2f}s")
                self.logger().info(f"[ORDER BOOK] Successfully queued snapshot for {trading_pair} in {pair_elapsed:.2f}s")
            except asyncio.TimeoutError:
                pair_elapsed = time.time() - pair_start
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshots TIMEOUT for {trading_pair} after {pair_elapsed:.2f}s")
                self.logger().warning(f"[ORDER BOOK] Timeout ({pair_elapsed:.2f}s) fetching snapshot for {trading_pair}")
                # Continue with other pairs even if one times out
            except Exception as e:
                pair_elapsed = time.time() - pair_start
                _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshots ERROR for {trading_pair} after {pair_elapsed:.2f}s: {e}")
                self.logger().error(f"[ORDER BOOK] Error fetching snapshot for {trading_pair} after {pair_elapsed:.2f}s: {e}", exc_info=True)
                # Continue with other pairs even if one fails

        total_elapsed = time.time() - start_time
        _log_with_timestamp(f"[COFINEX OBS] _request_order_book_snapshots EXIT after {total_elapsed:.2f}s")

    async def listen_for_order_book_snapshots(
        self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue
    ):
        """
        Periodically fetch order book snapshots for trading pairs.
        This method runs continuously and requests full order book content from the exchange.

        :param ev_loop: the event loop the method will run in
        :param output: a queue to add the created snapshot messages
        """
        self.logger().info("=" * 60)
        self.logger().info("ORDER BOOK SNAPSHOT LISTENER STARTED")
        self.logger().info(f"Trading pairs: {len(self._trading_pairs)} - {self._trading_pairs}")
        self.logger().info("=" * 60)
        _log_with_timestamp("[COFINEX OBS] listen_for_order_book_snapshots started (ws+rest)")

        self._start_snapshot_watchdog()
        message_queue = self._message_queue[self._snapshot_messages_queue_key]

        try:
            while True:
                try:
                    try:
                        snapshot_event = await asyncio.wait_for(
                            message_queue.get(),
                            timeout=self.FULL_ORDER_BOOK_RESET_DELTA_SECONDS,
                        )
                        await self._parse_order_book_snapshot_message(
                            raw_message=snapshot_event,
                            message_queue=output,
                        )
                    except asyncio.TimeoutError:
                        await self._request_order_book_snapshots(output=output)
                except asyncio.CancelledError:
                    _log_with_timestamp("[COFINEX OBS] listen_for_order_book_snapshots CANCELLED")
                    raise
                except Exception as e:
                    _log_with_timestamp(f"[COFINEX OBS] listen_for_order_book_snapshots ERROR in loop: {e}")
                    self.logger().error("[ORDER BOOK] Error in snapshot loop", exc_info=True)
                    await asyncio.sleep(5.0)
        finally:
            self._stop_snapshot_watchdog()

    async def listen_for_order_book_diffs(
        self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue
    ):
        """
        Cofinex WebSocket sends full snapshots on the Books channel.
        This method is intentionally left empty.

        :param ev_loop: the event loop the method will run in
        :param output: a queue to add the created diff messages
        """
        # REST-only implementation: no diffs, only snapshots
        pass

    async def listen_for_trades(
        self, ev_loop: asyncio.AbstractEventLoop, output: asyncio.Queue
    ):
        """
        Reads the trade events queue from WebSocket. For each event creates a trade message instance
        and adds it to the output queue.

        :param ev_loop: the event loop the method will run in
        :param output: a queue to add the created trade messages
        """
        # Use the base class implementation which reads from _trade_messages_queue_key
        message_queue = self._message_queue[self._trade_messages_queue_key]
        while True:
            try:
                trade_event = await message_queue.get()
                await self._parse_trade_message(raw_message=trade_event, message_queue=output)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error when processing public trade updates from exchange")

    async def listen_for_subscriptions(self):
        """
        Connects to the public WebSocket and subscribes to order book channels.
        """
        _log_with_timestamp("[COFINEX OBS] listen_for_subscriptions START")
        ws: Optional[WSAssistant] = None
        while True:
            try:
                self._ws_subscribed = False
                ws = await self._connected_websocket_assistant()
                _log_with_timestamp("[COFINEX OBS] WS connected")

                # Try subscribing immediately after connection (like Postman might do)
                # But also handle subscription in message loop if connection_established comes first
                _log_with_timestamp("[COFINEX OBS] Attempting immediate subscription after connect")
                try:
                    await asyncio.wait_for(self._subscribe_channels(ws), timeout=2.0)
                    _log_with_timestamp("[COFINEX OBS] Immediate subscription completed")
                except asyncio.TimeoutError:
                    _log_with_timestamp("[COFINEX OBS] Immediate subscription timed out, will retry after connection_established")
                except Exception as e:
                    _log_with_timestamp(f"[COFINEX OBS] Immediate subscription failed: {e}, will retry after connection_established", level="WARNING")

                await self._process_websocket_messages(websocket_assistant=ws)
            except asyncio.CancelledError:
                raise
            except ConnectionError as connection_exception:
                self.logger().warning(f"The websocket connection was closed ({connection_exception})")
            except Exception:
                self.logger().exception(
                    "Unexpected error occurred when listening to order book streams. Retrying in 5 seconds...",
                )
                await self._sleep(1.0)
            finally:
                await self._on_order_stream_interruption(websocket_assistant=ws)

    async def _parse_order_book_snapshot_message(self, raw_message: Any, message_queue: asyncio.Queue):
        payload = raw_message[0] if isinstance(raw_message, list) and raw_message else raw_message
        if not isinstance(payload, dict):
            self.logger().warning(f"[COFINEX OBS] Unexpected snapshot payload type: {type(payload)}")
            _log_with_timestamp(f"[COFINEX OBS] Unexpected payload type: {type(payload)}, data: {payload}", level="WARNING")
            return

        trading_pair = self._trading_pair_from_ws_payload(payload)
        if trading_pair is None:
            self.logger().warning(f"[COFINEX OBS] Unable to determine trading pair from WS payload: {payload}")
            _log_with_timestamp(f"[COFINEX OBS] Unable to determine trading pair from payload: {payload}", level="WARNING")
            return

        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        timestamp_ms_raw = payload.get("ts", 0)
        # Handle both string and numeric timestamps
        if isinstance(timestamp_ms_raw, str):
            timestamp_ms = int(timestamp_ms_raw)
        else:
            timestamp_ms = int(timestamp_ms_raw) if timestamp_ms_raw else 0
        timestamp = float(timestamp_ms) / 1000.0 if timestamp_ms else time.time()

        seq_raw = payload.get("seq", timestamp_ms or int(time.time() * 1000))
        # Handle both string and numeric sequence numbers
        if isinstance(seq_raw, str):
            update_id = int(seq_raw)
        else:
            update_id = int(seq_raw)

        # Reduced logging - commented out to reduce log clutter
        # _log_with_timestamp(
        #     f"[COFINEX OBS] Parsing snapshot for {trading_pair}: bids={len(bids)} asks={len(asks)} "
        #     f"ts={timestamp_ms} seq={update_id}"
        # )
        # self.logger().info(
        #     f"Parsing orderbook snapshot for {trading_pair}: {len(bids)} bids, {len(asks)} asks, "
        #     f"timestamp={timestamp}, update_id={update_id}"
        # )

        order_book_message_content = {
            "trading_pair": trading_pair,
            "update_id": update_id,
            "bids": [(float(bid[0]), float(bid[1])) for bid in bids],
            "asks": [(float(ask[0]), float(ask[1])) for ask in asks],
        }
        snapshot_msg = OrderBookMessage(
            OrderBookMessageType.SNAPSHOT,
            order_book_message_content,
            timestamp,
        )
        message_queue.put_nowait(snapshot_msg)
        # Reduced logging - only log periodically to avoid clutter
        # _log_with_timestamp(f"[COFINEX OBS] Snapshot message queued for {trading_pair}")
        # self.logger().info(f"Orderbook snapshot message queued for {trading_pair}")

    def _trading_pair_from_ws_payload(self, payload: Dict[str, Any]) -> Optional[str]:
        symbol = payload.get("symbol")
        base = payload.get("base")
        if symbol and base:
            return f"{symbol}-{base}"
        if len(self._trading_pairs) == 1:
            return self._trading_pairs[0]
        return None

    async def _parse_trade_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Create an instance of OrderBookMessage of type OrderBookMessageType.TRADE
        from a Cofinex WebSocket trade message.

        Actual Cofinex trade message format:
        {
            "channel": "Trade",
            "symbol": "BTC",
            "base": "USDT",
            "data": [
                {
                    "t": "1767867360725",  # timestamp (milliseconds)
                    "p": "3110.25",        # price
                    "s": "0.06",          # size/quantity
                    "d": "buy",           # direction: "buy" or "sell"
                    "i": "1393102170561986560"  # trade id
                }
            ]
        }

        :param raw_message: the JSON dictionary of the public trade event
        :param message_queue: queue where the parsed messages should be stored
        """
        try:
            # Extract trading pair
            trading_pair = self._trading_pair_from_ws_payload(raw_message)
            if trading_pair is None:
                self.logger().warning(f"Unable to determine trading pair from trade message: {raw_message}")
                return

            # Extract trade data from "data" field
            trade_data_list = raw_message.get("data", [])
            if not trade_data_list:
                self.logger().debug(f"No trade data found in message: {raw_message}")
                return

            # Process each trade in the message
            for trade_data in trade_data_list:
                # Extract trade fields using Cofinex field names
                # t = timestamp, p = price, s = size, d = direction, i = trade_id
                price = trade_data.get("p")
                quantity = trade_data.get("s")
                side = trade_data.get("d")
                timestamp_raw = trade_data.get("t")
                trade_id = trade_data.get("i")

                if not price or not quantity:
                    self.logger().warning(f"Missing price or quantity in trade data: {trade_data}")
                    continue

                # Convert timestamp from milliseconds to seconds
                if timestamp_raw:
                    try:
                        if isinstance(timestamp_raw, str):
                            # Handle simple numeric string
                            timestamp_ms = int(timestamp_raw)
                        else:
                            timestamp_ms = int(timestamp_raw)
                        timestamp = float(timestamp_ms) / 1000.0
                    except (ValueError, TypeError):
                        # Handle unexpected formats (e.g., "48-0-1768113862502-1768113852654-0")
                        # Try to extract the largest numeric value which is likely the timestamp
                        self.logger().warning(f"Unexpected timestamp format: {timestamp_raw}, attempting to parse")
                        try:
                            if isinstance(timestamp_raw, str):
                                # Extract all numeric parts and use the largest one (likely the timestamp)
                                parts = timestamp_raw.split("-")
                                numeric_parts = [int(p) for p in parts if p.isdigit()]
                                if numeric_parts:
                                    timestamp_ms = max(numeric_parts)  # Use the largest value
                                    timestamp = float(timestamp_ms) / 1000.0
                                else:
                                    raise ValueError("No numeric parts found")
                            else:
                                timestamp_ms = int(timestamp_raw)
                                timestamp = float(timestamp_ms) / 1000.0
                        except (ValueError, TypeError) as e:
                            self.logger().warning(f"Failed to parse timestamp '{timestamp_raw}': {e}, using current time")
                            timestamp = time.time()
                else:
                    timestamp = time.time()

                # Determine trade type from direction field
                if side:
                    side_lower = str(side).lower()
                    if side_lower == "buy":
                        trade_type = float(TradeType.BUY.value)
                    elif side_lower == "sell":
                        trade_type = float(TradeType.SELL.value)
                    else:
                        # Default to buy if unclear
                        trade_type = float(TradeType.BUY.value)
                        self.logger().debug(f"Unknown trade side '{side}', defaulting to BUY")
                else:
                    # Default to buy if side is not provided
                    trade_type = float(TradeType.BUY.value)

                message_content = {
                    "trade_id": str(trade_id) if trade_id else str(int(time.time() * 1000)),
                    "trading_pair": trading_pair,
                    "trade_type": trade_type,
                    "amount": str(quantity),
                    "price": str(price),
                }

                trade_message = OrderBookMessage(
                    message_type=OrderBookMessageType.TRADE,
                    content=message_content,
                    timestamp=timestamp
                )

                message_queue.put_nowait(trade_message)
                self.logger().info(f"[WS] Trade message parsed and queued: {trading_pair} @ {price} x {quantity} ({side}), TradeID={trade_id}")

        except Exception as e:
            self.logger().error(f"Error parsing trade message: {raw_message}, error: {e}", exc_info=True)

    async def _subscribe_channels(self, ws: WSAssistant):
        try:
            _log_with_timestamp(f"[COFINEX OBS] WS subscribe start for {len(self._trading_pairs)} pairs")
            self.logger().info(f"Starting subscription for {len(self._trading_pairs)} pairs: {self._trading_pairs}")

            # Get prefix (can be None, which means no prefix in production)
            prefix = self._ws_prefix

            for trading_pair in self._trading_pairs:
                base, quote = trading_pair.split("-")

                # Subscribe to order book
                books_payload = {
                    "type": "subscribe",
                    "channel": "Books",
                    "productType": "SPOT",
                    "symbol": base,
                    "base": quote,
                }
                # Add prefix if configured (for local development/testing)
                if prefix:
                    books_payload["prefix"] = prefix

                self.logger().info(f"[WS] Subscribing to orderbook for {trading_pair} with payload: {books_payload}")
                subscribe_books_request = WSJSONRequest(payload=books_payload)
                await ws.send(subscribe_books_request)
                await asyncio.sleep(0.2)  # Small delay between subscriptions

                # Subscribe to trades (channel is "Trade" singular, not "Trades")
                trades_payload = {
                    "type": "subscribe",
                    "channel": "Trade",
                    "productType": "SPOT",
                    "symbol": base,
                    "base": quote,
                }
                if prefix:
                    trades_payload["prefix"] = prefix

                self.logger().info(f"[WS] Subscribing to trades for {trading_pair} with payload: {trades_payload}")
                subscribe_trades_request = WSJSONRequest(payload=trades_payload)
                await ws.send(subscribe_trades_request)
                await asyncio.sleep(0.2)  # Small delay between subscriptions

                # Subscribe to ticker (symbol must be an array)
                ticker_payload = {
                    "type": "subscribe",
                    "channel": "Ticker",
                    "symbol": [base],  # Symbol is an array
                    "productType": "SPOT",
                    "base": quote,
                }
                if prefix:
                    ticker_payload["prefix"] = prefix

                self.logger().info(f"[WS] Subscribing to ticker for {trading_pair} with payload: {ticker_payload}")
                subscribe_ticker_request = WSJSONRequest(payload=ticker_payload)
                await ws.send(subscribe_ticker_request)
                await asyncio.sleep(0.2)  # Small delay between subscriptions

            self._ws_subscribed = True
            self.logger().info(f"[WS] Subscribed to Cofinex channels{' with prefix ' + prefix if prefix else ''}...")
            _log_with_timestamp("[COFINEX OBS] WS subscription completed successfully")
        except asyncio.CancelledError:
            _log_with_timestamp("[COFINEX OBS] WS subscription cancelled", level="WARNING")
            raise
        except Exception as e:
            _log_with_timestamp(f"[COFINEX OBS] WS subscription error: {e}", level="ERROR")
            self.logger().exception("Unexpected error subscribing to Cofinex channels")
            raise

    async def _process_websocket_messages(self, websocket_assistant: WSAssistant):
        message_count = 0
        last_heartbeat = time.time()
        loop_start_time = time.time()
        _log_with_timestamp("[COFINEX OBS] _process_websocket_messages started")
        self.logger().info("Starting to process websocket messages")

        # Start a separate heartbeat task to confirm the loop is running
        async def heartbeat_task():
            while True:
                await asyncio.sleep(10.0)
                elapsed = time.time() - loop_start_time
                # _log_with_timestamp(f"[COFINEX OBS] WS heartbeat: loop running for {elapsed:.1f}s, {message_count} messages received")
                self.logger().debug(f"WebSocket heartbeat: loop running for {elapsed:.1f}s, {message_count} messages received")

        heartbeat_task_handle = asyncio.create_task(heartbeat_task())

        # Start a ping task to keep connection alive (ping every 30 seconds)
        async def ping_task():
            while True:
                await asyncio.sleep(30.0)
                try:
                    ping_payload = {"type": "ping"}
                    ping_request = WSJSONRequest(payload=ping_payload)
                    await websocket_assistant.send(ping_request)
                    # _log_with_timestamp("[COFINEX OBS] WS ping sent")
                    self.logger().debug("WebSocket ping sent")
                except Exception as e:
                    _log_with_timestamp(f"[COFINEX OBS] WS ping failed: {e}", level="WARNING")
                    self.logger().warning(f"Failed to send WebSocket ping: {e}")

        ping_task_handle = asyncio.create_task(ping_task())

        try:
            async for ws_response in websocket_assistant.iter_messages():
                message_count += 1
                raw_data = ws_response.data

                # Log raw messages to see what we're receiving
                if message_count <= 5 or message_count % 20 == 0:
                    _log_with_timestamp(f"[COFINEX OBS] WS message #{message_count} RAW: type={type(raw_data)}, data={str(raw_data)[:300]}")

                data = raw_data
                if isinstance(data, bytes):
                    try:
                        data_str = data.decode("utf-8")
                        # _log_with_timestamp(f"[COFINEX OBS] WS message #{message_count} decoded from bytes: {data_str}")
                        # self.logger().debug(f"WebSocket message #{message_count} decoded from bytes: {data_str}")
                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            # If it's not JSON, keep it as string
                            data = data_str
                    except Exception as e:
                        self.logger().warning(f"[COFINEX OBS] WS message decode failed (bytes): {e}")
                        _log_with_timestamp(f"[COFINEX OBS] WS message decode failed: {e}", level="WARNING")
                        continue
                elif isinstance(data, str):
                    # _log_with_timestamp(f"[COFINEX OBS] WS message #{message_count} is string: {data}")
                    # self.logger().debug(f"WebSocket message #{message_count} is string: {data}")
                    try:
                        data = json.loads(data)
                        # _log_with_timestamp(f"[COFINEX OBS] WS message #{message_count} parsed from JSON string")
                    except json.JSONDecodeError:
                        # If it's not JSON, keep it as string
                        # _log_with_timestamp(f"[COFINEX OBS] WS message #{message_count} is non-JSON string, keeping as string")
                        pass
                    except Exception as e:
                        self.logger().warning(f"[COFINEX OBS] Invalid WS message: {data}, error: {e}")
                        _log_with_timestamp(f"[COFINEX OBS] Invalid WS JSON: {e}", level="WARNING")
                        continue

                # Log parsed messages to see what we're receiving
                if message_count <= 5 or message_count % 20 == 0:
                    _log_with_timestamp(f"[COFINEX OBS] WS message #{message_count} PARSED: type={type(data)}, data={str(data)[:300]}")

                now = time.time()
                if self._ws_last_message_time == 0.0:
                    _log_with_timestamp(f"[COFINEX OBS] WS first message received: type={type(data)}")
                if not self._ws_first_message_logged:
                    self._ws_first_message_logged = True
                    _log_with_timestamp(f"[COFINEX OBS] WS first message content: {data}")
                    self.logger().info(f"[WS] First websocket message received: type={type(data)}, data={data}")
                self._ws_last_message_time = now

                # Log every message for debugging (can be reduced later)
                if message_count <= 10 or message_count % 50 == 0:
                    self.logger().info(f"[WS] Message #{message_count} received: type={type(data)}, preview={str(data)[:200] if isinstance(data, (dict, list, str)) else data}")

                if isinstance(data, dict) and data.get("type") in ("ping", "pong"):
                    # _log_with_timestamp(f"[COFINEX OBS] WS ping/pong message: {data.get('type')}, full_data={data}")
                    self.logger().debug(f"WebSocket ping/pong message: {data.get('type')}")
                    # If we receive a ping, respond with pong
                    if data.get("type") == "ping":
                        try:
                            pong_payload = {"type": "pong"}
                            pong_request = WSJSONRequest(payload=pong_payload)
                            await websocket_assistant.send(pong_request)
                            # _log_with_timestamp("[COFINEX OBS] WS pong sent in response to ping")
                            self.logger().debug("WebSocket pong sent in response to ping")
                        except Exception as e:
                            _log_with_timestamp(f"[COFINEX OBS] WS pong send failed: {e}", level="WARNING")
                            self.logger().warning(f"Failed to send WebSocket pong: {e}")
                    continue
                # Also handle string "ping" or "pong" messages
                if isinstance(data, str) and data.lower() in ("ping", "pong"):
                    # _log_with_timestamp(f"[COFINEX OBS] WS ping/pong string message: {data}")
                    self.logger().debug(f"WebSocket ping/pong string message: {data}")
                    if data.lower() == "ping":
                        try:
                            pong_payload = {"type": "pong"}
                            pong_request = WSJSONRequest(payload=pong_payload)
                            await websocket_assistant.send(pong_request)
                            # _log_with_timestamp("[COFINEX OBS] WS pong sent in response to string ping")
                            self.logger().debug("WebSocket pong sent in response to string ping")
                        except Exception as e:
                            _log_with_timestamp(f"[COFINEX OBS] WS pong send failed: {e}", level="WARNING")
                            self.logger().warning(f"Failed to send WebSocket pong: {e}")
                    continue
                if isinstance(data, dict) and data.get("type") == "connection_established":
                    _log_with_timestamp(
                        f"[COFINEX OBS] WS connection established: {data} (ws_subscribed={self._ws_subscribed})"
                    )
                    self.logger().info(f"Connection established, ws_subscribed={self._ws_subscribed}")
                    if not self._ws_subscribed:
                        _log_with_timestamp("[COFINEX OBS] WS subscribe trigger after connection established")
                        self.logger().info("Triggering subscription after connection established")
                        # Subscribe synchronously to ensure it completes before continuing
                        try:
                            await self._subscribe_channels(websocket_assistant)
                            _log_with_timestamp("[COFINEX OBS] WS subscribe completed synchronously")
                            self.logger().info("Subscription completed successfully")
                        except Exception as e:
                            _log_with_timestamp(
                                f"[COFINEX OBS] WS subscribe failed: {e}",
                                level="ERROR",
                            )
                            self.logger().error(f"Subscription failed: {e}", exc_info=True)
                    continue
                if isinstance(data, dict) and data.get("type") in ("subscribe", "subscribed", "subscription", "subscribed_successfully"):
                    _log_with_timestamp(f"[COFINEX OBS] WS subscribe ack: {data}")
                    self.logger().info(f"Subscription acknowledgment: {data}")
                    # Check if there's an error in the ack
                    if data.get("error") or data.get("status") == "error":
                        _log_with_timestamp(f"[COFINEX OBS] WS subscription error in ack: {data}", level="ERROR")
                        self.logger().error(f"Subscription error in acknowledgment: {data}")
                    continue
                if isinstance(data, dict) and data.get("type") == "error":
                    _log_with_timestamp(f"[COFINEX OBS] WS error message: {data}", level="ERROR")
                    self.logger().error(f"WebSocket error message: {data}")
                    continue

                # Handle messages - Cofinex sends lists for all data types
                if isinstance(data, list) and len(data) > 0:
                    first_item = data[0]

                    # Debug: Log first item keys for troubleshooting
                    if message_count <= 5 or message_count % 50 == 0:
                        if isinstance(first_item, dict):
                            _log_with_timestamp(f"[COFINEX OBS] WS message #{message_count} first_item keys: {list(first_item.keys())}")

                    # Check if it's an orderbook snapshot (has "bids" and "asks")
                    if isinstance(first_item, dict) and "bids" in first_item and "asks" in first_item:
                        # Orderbook snapshot
                        bids_count = len(first_item.get("bids", []))
                        asks_count = len(first_item.get("asks", []))
                        self.logger().info(f"[WS] Orderbook snapshot received: {bids_count} bids, {asks_count} asks")
                        self._message_queue[self._snapshot_messages_queue_key].put_nowait(data)
                    # Check if it's a trade message (has "t", "p", "s", "d", "i" fields)
                    elif isinstance(first_item, dict) and "t" in first_item and "p" in first_item and "s" in first_item and "d" in first_item:
                        # Trade messages: [{"t": timestamp, "p": price, "s": size, "d": direction, "i": trade_id}]
                        # Log trade details
                        for trade in data:
                            self.logger().info(f"[WS] Trade received: Price={trade.get('p')}, Size={trade.get('s')}, Direction={trade.get('d')}, TradeID={trade.get('i')}")
                        # Wrap in dict with channel info for processing
                        trade_message = {
                            "channel": "Trade",
                            "data": data,
                            "symbol": self._trading_pairs[0].split("-")[0] if self._trading_pairs else None,
                            "base": self._trading_pairs[0].split("-")[1] if self._trading_pairs else None,
                        }
                        self._message_queue[self._trade_messages_queue_key].put_nowait(trade_message)
                        self.logger().info(f"[WS] Trade message queued: {len(data)} trade(s)")
                    # Check if it's a ticker message (has "i", "l", "o", "h", "lo", "c" fields)
                    elif isinstance(first_item, dict) and "i" in first_item and "l" in first_item and "o" in first_item:
                        # Ticker messages: [{"i": instrument, "l": last, "o": open, "h": high, "lo": low, "c": change, ...}]
                        ticker = first_item
                        self.logger().info(
                            f"[WS] Ticker update: Instrument={ticker.get('i')}, "
                            f"Last={ticker.get('l')}, Open={ticker.get('o')}, "
                            f"High={ticker.get('h')}, Low={ticker.get('lo')}, "
                            f"Change={ticker.get('c')}, BestBid={ticker.get('b')}, BestAsk={ticker.get('a')}"
                        )
                    else:
                        # Unknown list format - try as orderbook snapshot (fallback)
                        self.logger().warning(f"[WS] Unknown list format, treating as orderbook snapshot. First item keys: {list(first_item.keys()) if isinstance(first_item, dict) else 'not a dict'}")
                        self._message_queue[self._snapshot_messages_queue_key].put_nowait(data)
                # Handle dict messages (subscription acks, etc.)
                elif isinstance(data, dict) and data.get("channel") in ("Trade", "Trades"):
                    # Trade messages in dict format (if exchange sends them this way)
                    self.logger().info(f"[WS] Trade message received (dict format): {data}")
                    self._message_queue[self._trade_messages_queue_key].put_nowait(data)
                elif isinstance(data, dict) and data.get("channel") == "Ticker":
                    # Ticker messages in dict format
                    self.logger().info(f"[WS] Ticker update received (dict format): {data}")
                else:
                    # Log unhandled messages for debugging
                    if isinstance(data, dict):
                        self.logger().info(f"[WS] Unhandled dict message #{message_count}: {data}")
                    else:
                        self.logger().info(f"[WS] Unhandled message #{message_count}: type={type(data)}, preview={str(data)[:200]}")

                # Reduced heartbeat logging - only log every 60 seconds instead of 10
                now = time.time()
                if now - last_heartbeat > 60.0:
                    last_heartbeat = now
                    # _log_with_timestamp(f"[COFINEX OBS] WS message processing heartbeat: {message_count} messages processed so far")
                    self.logger().debug(f"WebSocket message processing heartbeat: {message_count} messages processed")
        except asyncio.CancelledError:
            heartbeat_task_handle.cancel()
            ping_task_handle.cancel()
            _log_with_timestamp(f"[COFINEX OBS] _process_websocket_messages cancelled after {message_count} messages")
            self.logger().info(f"WebSocket message processing cancelled after {message_count} messages")
            raise
        except Exception as e:
            heartbeat_task_handle.cancel()
            ping_task_handle.cancel()
            _log_with_timestamp(f"[COFINEX OBS] _process_websocket_messages ERROR after {message_count} messages: {e}", level="ERROR")
            self.logger().error(f"Error in websocket message processing after {message_count} messages: {e}", exc_info=True)
            raise
        finally:
            heartbeat_task_handle.cancel()
            ping_task_handle.cancel()

    async def _connected_websocket_assistant(self) -> WSAssistant:
        ws: WSAssistant = await self._api_factory.get_ws_assistant()
        _log_with_timestamp(f"[COFINEX OBS] WS connecting to {CONSTANTS.WS_BASE_URL[self._domain]}")
        await ws.connect(
            ws_url=CONSTANTS.WS_BASE_URL[self._domain],
            ping_timeout=CONSTANTS.WS_HEARTBEAT_TIME_INTERVAL,
        )
        _log_with_timestamp("[COFINEX OBS] WS connected")
        return ws

    async def _snapshot_watchdog_heartbeat(self):
        """Update heartbeat from the event loop."""
        while not self._snapshot_watchdog_stop.is_set():
            self._snapshot_heartbeat = time.monotonic()
            await asyncio.sleep(1.0)

    def _start_snapshot_watchdog(self):
        if self._snapshot_watchdog_thread is not None and self._snapshot_watchdog_thread.is_alive():
            return
        self._snapshot_watchdog_stop = threading.Event()
        self._snapshot_heartbeat = time.monotonic()
        self._snapshot_watchdog_dumped = False
        self._snapshot_watchdog_task = asyncio.create_task(self._snapshot_watchdog_heartbeat())
        self._snapshot_watchdog_thread = threading.Thread(
            target=self._snapshot_watchdog_thread_fn,
            name="cofinex_snapshot_watchdog",
            daemon=True,
        )
        self._snapshot_watchdog_thread.start()
        _log_with_timestamp("[COFINEX OBS] Snapshot watchdog started (threshold: 20s).")

    def _stop_snapshot_watchdog(self):
        if self._snapshot_watchdog_stop is not None:
            self._snapshot_watchdog_stop.set()
        if self._snapshot_watchdog_task is not None:
            self._snapshot_watchdog_task.cancel()
        if self._snapshot_watchdog_thread is not None and self._snapshot_watchdog_thread.is_alive():
            self._snapshot_watchdog_thread.join(timeout=1.0)
        self._snapshot_watchdog_task = None
        self._snapshot_watchdog_thread = None
        self._snapshot_watchdog_stop = None
        self._snapshot_watchdog_dumped = False

    def _snapshot_watchdog_thread_fn(self):
        threshold_seconds = 20.0
        check_interval = 2.0
        while not self._snapshot_watchdog_stop.is_set():
            time.sleep(check_interval)
            gap = time.monotonic() - self._snapshot_heartbeat
            if gap > threshold_seconds:
                if not self._snapshot_watchdog_dumped:
                    self._snapshot_watchdog_dumped = True
                    _log_with_timestamp(
                        f"[COFINEX OBS] Snapshot loop heartbeat stalled for {gap:.2f}s "
                        f"(threshold {threshold_seconds:.2f}s). Dumping stacks.",
                        level="ERROR",
                    )
                    logger = logging.getLogger(__name__)
                    thread_names = {t.ident: t.name for t in threading.enumerate()}
                    for thread_id, frame in sys._current_frames().items():
                        thread_name = thread_names.get(thread_id, "unknown")
                        stack = "".join(traceback.format_stack(frame))
                        logger.error(
                            "Thread %s (id=%s) stack:\n%s",
                            thread_name,
                            thread_id,
                            stack,
                        )
            else:
                if self._snapshot_watchdog_dumped:
                    _log_with_timestamp(
                        f"[COFINEX OBS] Snapshot loop heartbeat recovered after stall (gap {gap:.2f}s)."
                    )
                self._snapshot_watchdog_dumped = False

    async def _parse_order_book_diff_message(self, raw_message: Dict[str, Any], message_queue: asyncio.Queue):
        """
        Parse order book diff message from WebSocket (if implemented)

        :param raw_message: Raw message from WebSocket
        :param message_queue: Queue to put parsed messages
        """
        # Cofinex WebSocket sends full snapshots, not diffs
        # This method is intentionally left empty
        pass
