from decimal import Decimal
from typing import TYPE_CHECKING, Dict, Optional

import aiohttp

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS
from hummingbot.connector.utils import split_hb_trading_pair
from hummingbot.core.rate_oracle.sources.rate_source_base import RateSourceBase
from hummingbot.core.utils import async_ttl_cache

if TYPE_CHECKING:
    from hummingbot.connector.exchange.cofinex.cofinex_exchange import CofinexExchange


class CofinexRateSource(RateSourceBase):
    """
    Cofinex Rate Source for Rate Oracle

    Fetches prices from Cofinex market data API.
    Requires a ticker endpoint that returns price data for trading pairs.
    """

    def __init__(self):
        super().__init__()
        self._exchange: Optional['CofinexExchange'] = None  # delayed because of circular reference
        self._base_url = CONSTANTS.MARKET_DATA_BASE_URL[CONSTANTS.DEFAULT_DOMAIN]

    @property
    def name(self) -> str:
        return "cofinex"

    @async_ttl_cache(ttl=30, maxsize=1)
    async def get_prices(self, quote_token: Optional[str] = None) -> Dict[str, Decimal]:
        """
        Fetches prices from Cofinex API

        :param quote_token: Optional quote token filter (e.g., "USDT")
        :return: Dictionary mapping trading pairs to prices (e.g., {"CNX-USDT": Decimal("0.25")})
        """
        results = {}
        try:
            # Option 1: Use exchange connector if available (recommended)
            if self._exchange is not None:
                results = await self._get_prices_from_exchange(quote_token)
            else:
                # Option 2: Direct API call to ticker endpoint
                results = await self._get_prices_from_api(quote_token)
        except Exception as e:
            self.logger().error(
                msg=f"Unexpected error while retrieving rates from Cofinex: {e}. Check the log file for more info.",
                exc_info=True,
            )
        return results

    async def _get_prices_from_exchange(self, quote_token: Optional[str] = None) -> Dict[str, Decimal]:
        """
        Get prices using the Cofinex exchange connector
        This requires the exchange to have a get_all_pairs_prices() method
        """
        self._ensure_exchange()
        results = {}

        # Try to use exchange's built-in method if available
        if hasattr(self._exchange, 'get_all_pairs_prices'):
            try:
                pairs_prices = await self._exchange.get_all_pairs_prices()
                for pair_price in pairs_prices:
                    try:
                        # Handle different response formats
                        symbol = pair_price.get("symbol") or pair_price.get("trading_pairs") or pair_price.get("pair")
                        if not symbol:
                            continue

                        trading_pair = await self._exchange.trading_pair_associated_to_exchange_symbol(symbol=symbol)
                    except (KeyError, AttributeError):
                        continue

                    if quote_token is not None:
                        _, quote = split_hb_trading_pair(trading_pair=trading_pair)
                        if quote != quote_token:
                            continue

                    # Extract price from response (handle Cofinex format)
                    # Cofinex format: last_price, highest_bid, lowest_ask
                    last_price = pair_price.get("last_price") or pair_price.get("lastPrice") or pair_price.get("last") or pair_price.get("price")
                    highest_bid = pair_price.get("highest_bid") or pair_price.get("bidPrice") or pair_price.get("bid")
                    lowest_ask = pair_price.get("lowest_ask") or pair_price.get("askPrice") or pair_price.get("ask")

                    if last_price is not None:
                        price = Decimal(str(last_price))
                    elif highest_bid is not None and lowest_ask is not None:
                        price = (Decimal(str(highest_bid)) + Decimal(str(lowest_ask))) / Decimal("2")
                    else:
                        continue

                    if price > 0:
                        results[trading_pair] = price
            except Exception as e:
                self.logger().debug(f"Error getting prices from exchange connector: {e}")

        return results

    async def _get_prices_from_api(self, quote_token: Optional[str] = None) -> Dict[str, Decimal]:
        """
        Get prices by directly calling Cofinex API market endpoint

        ENDPOINT:
        GET https://marketdata.cofinex.io/spot/v1/market/{SYMBOL}

        Example: https://marketdata.cofinex.io/spot/v1/market/CNX_USDT

        RESPONSE FORMAT:
        {
            "code": "200",
            "msg": "success",
            "data": {
                "trading_pairs": "CNX_USDT",
                "base_currency": "CNX",
                "quote_currency": "USDT",
                "last_price": 0.21,
                "highest_bid": 0.3144,
                "lowest_ask": 0.21,
                ...
            }
        }
        """
        results = {}

        # Get list of trading pairs to fetch
        # Try to get from exchange connector if available, otherwise use common pairs
        trading_pairs_to_fetch = []

        if self._exchange is not None:
            try:
                # Get trading pairs from exchange connector
                if hasattr(self._exchange, 'trading_pairs') and self._exchange.trading_pairs:
                    # Convert Hummingbot format (CNX-USDT) to API format (CNX_USDT)
                    trading_pairs_to_fetch = [tp.replace("-", "_").upper() for tp in self._exchange.trading_pairs]
            except Exception:
                pass

        # If no pairs from connector, use common USDT pairs
        if not trading_pairs_to_fetch:
            # Common trading pairs - you can expand this list
            # Format: API format with underscore (CNX_USDT)
            common_pairs = ["CNX_USDT", "BTC_USDT", "ETH_USDT"]
            trading_pairs_to_fetch = common_pairs

        try:
            async with aiohttp.ClientSession() as session:
                # Fetch prices for each trading pair
                for symbol in trading_pairs_to_fetch:
                    try:
                        # Convert to API format (ensure underscore format)
                        api_symbol = symbol.replace("-", "_").upper()
                        market_url = f"{self._base_url}/spot/v1/market/{api_symbol}"

                        async with session.get(market_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                            if response.status != 200:
                                self.logger().debug(f"Cofinex market API returned status {response.status} for {api_symbol}")
                                continue

                            data = await response.json()

                            # Parse response
                            if not isinstance(data, dict) or data.get("code") != "200":
                                self.logger().debug(f"Invalid response format for {api_symbol}: {data}")
                                continue

                            ticker_data = data.get("data")
                            if not isinstance(ticker_data, dict):
                                continue

                            # Extract symbol (format: CNX_USDT)
                            trading_pairs_str = ticker_data.get("trading_pairs")
                            if not trading_pairs_str:
                                continue

                            # Convert to Hummingbot format (CNX-USDT)
                            trading_pair = trading_pairs_str.replace("_", "-").upper()

                            # Filter by quote token if specified
                            if quote_token is not None:
                                _, quote = split_hb_trading_pair(trading_pair=trading_pair)
                                if quote != quote_token:
                                    continue

                            # Extract price (prefer last_price, fallback to mid of bid/ask)
                            last_price = ticker_data.get("last_price")
                            highest_bid = ticker_data.get("highest_bid")
                            lowest_ask = ticker_data.get("lowest_ask")

                            if last_price is not None:
                                price = Decimal(str(last_price))
                            elif highest_bid is not None and lowest_ask is not None:
                                price = (Decimal(str(highest_bid)) + Decimal(str(lowest_ask))) / Decimal("2")
                            else:
                                continue

                            if price > 0:
                                results[trading_pair] = price

                    except (KeyError, ValueError, TypeError) as e:
                        self.logger().debug(f"Error parsing market data for {symbol}: {e}")
                        continue
                    except aiohttp.ClientError as e:
                        self.logger().debug(f"Error fetching market data for {symbol}: {e}")
                        continue

        except Exception as e:
            self.logger().error(f"Unexpected error in _get_prices_from_api: {e}", exc_info=True)

        return results

    def _ensure_exchange(self):
        """Initialize exchange connector if not already done"""
        if self._exchange is None:
            self._exchange = self._build_cofinex_connector_without_private_keys()

    @staticmethod
    def _build_cofinex_connector_without_private_keys() -> 'CofinexExchange':
        """Build Cofinex exchange connector without private keys (for public data only)"""
        from hummingbot.connector.exchange.cofinex.cofinex_exchange import CofinexExchange

        return CofinexExchange(
            cofinex_username="",
            cofinex_password="",
            trading_pairs=[],
            trading_required=False,
        )
