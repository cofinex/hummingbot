"""
Cofinex Web Utilities

This module provides utilities for making HTTP requests to the Cofinex API,
including rate limiting, time synchronization, and API factory creation.
"""

import json
from typing import Callable, Optional

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS
from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.connector.utils import TimeSynchronizerRESTPreProcessor
from hummingbot.core.api_throttler.async_throttler import AsyncThrottler
from hummingbot.core.utils.tracking_nonce import get_tracking_nonce
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest
from hummingbot.core.web_assistant.rest_pre_processors import RESTPreProcessorBase
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory


class CofinexRESTPreProcessor(RESTPreProcessorBase):
    """
    REST pre-processor for Cofinex API

    Handles form-urlencoded data by converting JSON-encoded strings back to dicts,
    allowing aiohttp to properly URL-encode them.

    Similar to BitstampRESTPreProcessor - when Content-Type is application/x-www-form-urlencoded,
    converts the JSON-encoded data back to a dict so aiohttp can URL-encode it.
    """
    CONTENT_TYPE_HEADER = "Content-Type"

    async def pre_process(self, request: RESTRequest) -> RESTRequest:
        # Check if Content-Type header indicates form-urlencoded
        content_type = request.headers.get(self.CONTENT_TYPE_HEADER, "").lower() if request.headers else ""

        # If Content-Type is form-urlencoded and we have data, convert JSON string back to dict
        if content_type == "application/x-www-form-urlencoded" and request.data:
            # rest_assistant converts the data dictionary to json but we need a urlencoded string instead
            # the actual url encoding of this is done by aiohttp.
            # Convert the JSON-encoded string back to a dict
            if isinstance(request.data, str):
                try:
                    request.data = json.loads(request.data)
                except (json.JSONDecodeError, TypeError):
                    # If it's already a dict or not JSON, leave it as is
                    pass
        return request


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
            CofinexRESTPreProcessor(),
            TimeSynchronizerRESTPreProcessor(synchronizer=time_synchronizer, time_provider=time_provider),
        ])
    return api_factory


def build_api_factory_without_time_synchronizer_pre_processor(throttler: AsyncThrottler) -> WebAssistantsFactory:
    """
    Creates a WebAssistantsFactory without time synchronizer pre-processor
    But includes CofinexRESTPreProcessor for form-urlencoded support (needed for OAuth token requests)

    :param throttler: Throttler for rate limiting

    :return: WebAssistantsFactory
    """
    api_factory = WebAssistantsFactory(
        throttler=throttler,
        rest_pre_processors=[
            CofinexRESTPreProcessor(),  # Include pre-processor for form-urlencoded support (OAuth token requests)
        ]
    )
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
        # Cofinex API response format: {"serverTime": 1768066395444}
        # serverTime is in milliseconds (Unix timestamp)
        if isinstance(response, dict):
            # Primary format: {"serverTime": 1768066395444}
            server_time = response.get("serverTime")
            if server_time is None:
                # Fallback formats (for compatibility)
                server_time = response.get("timestamp") or response.get("data")
                if server_time is None:
                    # If response is just a number (shouldn't happen with Cofinex)
                    server_time = response
            return float(server_time) / 1000.0  # Convert milliseconds to seconds
        # If response is not a dict, try to parse as number directly
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
