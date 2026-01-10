"""
Cofinex Web Utilities

This module provides utilities for making HTTP requests to the Cofinex API,
including rate limiting, time synchronization, and API factory creation.
"""

from typing import Callable, Optional

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.connector.utils import TimeSynchronizerRESTPreProcessor
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.utils.tracking_nonce import get_tracking_nonce
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


def public_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN, rest_api_base_url: Optional[str] = None) -> str:
    """
    Creates a full URL for provided REST endpoint

    :param path_url: a public REST endpoint
    :param domain: the domain to connect to ("main" or "testnet"). The default value is "main"
    :param rest_api_base_url: Optional override for REST API base URL (for local testing)

    :return: the full URL to the endpoint
    """
    # Market data endpoints (trading pairs, order book) use MARKET_DATA_BASE_URL
    # Trade engine endpoints use BASE_PATH_URL (or configured rest_api_base_url)
    if path_url.startswith("/spot/v1/"):
        return CONSTANTS.MARKET_DATA_BASE_URL[domain] + path_url
    # Use configured base URL if provided, otherwise use default from constants
    base_url = rest_api_base_url or CONSTANTS.BASE_PATH_URL.get(domain, CONSTANTS.BASE_PATH_URL["main"])
    return base_url + path_url


def private_rest_url(path_url: str, domain: str = CONSTANTS.DEFAULT_DOMAIN, rest_api_base_url: Optional[str] = None) -> str:
    """
    Creates a full URL for provided REST endpoint

    :param path_url: a private REST endpoint
    :param domain: the domain to connect to ("main" or "testnet"). The default value is "main"
    :param rest_api_base_url: Optional override for REST API base URL (for local testing)

    :return: the full URL to the endpoint
    """
    return public_rest_url(path_url=path_url, domain=domain, rest_api_base_url=rest_api_base_url)


def build_api_factory(
        throttler: Optional[AsyncThrottler] = None,
        time_synchronizer: Optional[TimeSynchronizer] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
        time_provider: Optional[Callable] = None,
        auth: Optional[AuthBase] = None,
        rest_api_base_url: Optional[str] = None,
) -> WebAssistantsFactory:
    """
    Creates a WebAssistantsFactory configured for Cofinex API

    :param throttler: Optional throttler for rate limiting
    :param time_synchronizer: Optional time synchronizer
    :param domain: Domain to connect to
    :param time_provider: Optional time provider function
    :param auth: Optional authentication handler

    :return: Configured WebAssistantsFactory
    """
    throttler = throttler or create_throttler()
    time_synchronizer = time_synchronizer or TimeSynchronizer()
    time_provider = time_provider or (lambda: get_current_server_time(
        throttler=throttler,
        domain=domain,
    ))
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        auth=auth,
        rest_pre_processors=[
            TimeSynchronizerRESTPreProcessor(synchronizer=time_synchronizer, time_provider=time_provider),
        ])
    return api_factory


def build_api_factory_without_time_synchronizer_pre_processor(throttler: AsyncThrottler) -> WebAssistantsFactory:
    """
    Creates a WebAssistantsFactory without time synchronizer pre-processor

    :param throttler: Throttler for rate limiting

    :return: WebAssistantsFactory
    """
    api_factory = WebAssistantsFactory(throttler=throttler)
    return api_factory


def create_throttler() -> AsyncThrottler:
    """
    Creates an AsyncThrottler configured with Cofinex rate limits

    :return: Configured AsyncThrottler
    """
    return AsyncThrottler(CONSTANTS.RATE_LIMITS)


async def get_current_server_time(
        throttler: Optional[AsyncThrottler] = None,
        domain: str = CONSTANTS.DEFAULT_DOMAIN,
) -> float:
    """
    Gets the current server time from Cofinex API

    :param throttler: Optional throttler for rate limiting
    :param domain: Domain to connect to

    :return: Server timestamp as float
    """
    throttler = throttler or create_throttler()
    api_factory = build_api_factory_without_time_synchronizer_pre_processor(throttler=throttler)
    rest_assistant = await api_factory.get_rest_assistant()

    try:
        response = await rest_assistant.execute_request(
            url=public_rest_url(path_url=CONSTANTS.SERVER_TIME_PATH_URL, domain=domain),
            method=RESTMethod.GET,
            throttler_limit_id=CONSTANTS.SERVER_TIME_PATH_URL,
        )
        # TODO: Adjust based on actual Cofinex API response format
        # Common formats: {"serverTime": 1234567890} or {"timestamp": 1234567890} or {"data": 1234567890}
        if isinstance(response, dict):
            # Try different possible keys
            server_time = response.get("serverTime") or response.get("timestamp") or response.get("data")
            if server_time is None:
                # If response is just a number
                server_time = response
            return float(server_time) / 1000.0  # Convert to seconds if in milliseconds
        return float(response) / 1000.0
    except Exception:
        # Fallback to local time if server time unavailable
        import time
        return time.time()


def next_message_id() -> str:
    """
    Generates a unique message ID for WebSocket messages

    :return: Unique message ID string
    """
    return str(get_tracking_nonce())
