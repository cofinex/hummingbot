"""
Cofinex Exchange Authentication - OAuth 2.0 / OpenID Connect

Cofinex uses OAuth 2.0 password grant type with Bearer tokens.
This is different from most exchanges that use HMAC signatures.

Authentication Flow:
1. Get access token from OAuth endpoint using username/password
2. Use Bearer token in Authorization header for all authenticated API requests
3. Automatically refresh token when it expires (tokens last 5 hours)
"""

import asyncio
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

from hummingbot.connector.exchange.cofinex import cofinex_constants as CONSTANTS
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSRequest
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory
from hummingbot.logger import HummingbotLogger


class CofinexAuth(AuthBase):
    """
    Cofinex API authentication using OAuth 2.0 / OpenID Connect

    Authentication flow:
    1. Get access token from OAuth endpoint using username/password
    2. Use Bearer token in Authorization header for all API requests
    3. Refresh token when it expires (tokens last 5 hours, refresh 5 min before expiry)

    Token Response Format:
    {
        "access_token": "eyJhbGci...",
        "expires_in": 18000,  # 5 hours in seconds
        "refresh_expires_in": 86400,  # 24 hours
        "refresh_token": "eyJhbGci...",
        "token_type": "Bearer",
        ...
    }
    """

    _logger: Optional[HummingbotLogger] = None

    def __init__(
        self,
        username: str,
        password: str,
        client_id: str = CONSTANTS.OAUTH_CLIENT_ID,
        scope: str = CONSTANTS.OAUTH_SCOPE,
        api_factory: Optional[WebAssistantsFactory] = None,
    ):
        """
        Initialize Cofinex OAuth authentication

        Args:
            username: Cofinex account email/username
            password: Cofinex account password
            client_id: OAuth client ID (default: "cofinex-exchange")
            scope: OAuth scope (default: "openid")
            api_factory: WebAssistantsFactory for making token requests
        """
        self.username = username
        self.password = password
        self.client_id = client_id
        self.scope = scope
        self._api_factory = api_factory

        # Token management
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = HummingbotLogger(cls.__name__)
        return cls._logger

    def set_api_factory(self, api_factory: WebAssistantsFactory):
        """
        Set the API factory for making token requests

        Args:
            api_factory: WebAssistantsFactory instance
        """
        self._api_factory = api_factory

    async def get_access_token(self) -> str:
        """
        Get valid access token, refreshing if necessary

        Returns:
            Valid access token

        Raises:
            ValueError: If API factory is not set
            Exception: If token request fails
        """
        if not self._api_factory:
            raise ValueError("API factory not set. Cannot request token. Call set_api_factory() first.")

        async with self._token_lock:
            # Check if token is valid and not expired
            current_time = time.time()
            buffer_time = CONSTANTS.TOKEN_REFRESH_BUFFER_SECONDS

            if self._access_token and current_time < (self._token_expires_at - buffer_time):
                return self._access_token

            # Token expired or doesn't exist
            # Try to refresh if we have refresh_token, otherwise get new token
            if self._refresh_token and current_time < (self._token_expires_at + 86400):  # refresh_token valid for 24h
                try:
                    await self._refresh_access_token()
                    return self._access_token
                except Exception as e:
                    self.logger().warning(f"Token refresh failed, requesting new token: {e}")

            # Get new token with username/password
            await self._request_new_token()
            return self._access_token

    async def _request_new_token(self):
        """
        Request new access token from OAuth endpoint

        Raises:
            Exception: If token request fails
        """
        try:
            # Create a temporary API factory without auth for token requests
            # (we can't use auth to get auth token!)
            from hummingbot.connector.exchange.cofinex import cofinex_web_utils
            temp_throttler = cofinex_web_utils.create_throttler()
            temp_api_factory = cofinex_web_utils.build_api_factory_without_time_synchronizer_pre_processor(
                temp_throttler
            )
            rest_assistant = await temp_api_factory.get_rest_assistant()

            # Prepare form data for OAuth token request (x-www-form-urlencoded)
            form_data = {
                "username": self.username,
                "password": self.password,
                "client_id": self.client_id,
                "scope": self.scope,
                "grant_type": CONSTANTS.OAUTH_GRANT_TYPE,
            }

            # OAuth token endpoint expects x-www-form-urlencoded
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }

            self.logger().info("Requesting new access token from OAuth endpoint...")

            response = await rest_assistant.execute_request(
                url=CONSTANTS.OAUTH_TOKEN_URL,
                method=RESTMethod.POST,
                data=urlencode(form_data),
                headers=headers,
                throttler_limit_id=CONSTANTS.OAUTH_TOKEN_URL,
            )

            # Parse OAuth response
            # Expected format based on actual Cofinex response:
            # {
            #     "access_token": "...",
            #     "expires_in": 18000,  # 5 hours
            #     "refresh_expires_in": 86400,  # 24 hours
            #     "refresh_token": "...",
            #     "token_type": "Bearer",
            #     ...
            # }
            self._access_token = response.get("access_token")
            self._refresh_token = response.get("refresh_token")

            if not self._access_token:
                raise ValueError("No access_token in OAuth response")

            # Calculate expiration time
            expires_in = response.get("expires_in", 18000)  # Default 5 hours if not provided
            self._token_expires_at = time.time() + expires_in

            self.logger().info(
                f"Successfully obtained access token. Expires in {expires_in} seconds "
                f"({expires_in / 3600:.1f} hours)"
            )

        except Exception as e:
            self.logger().error(f"Failed to obtain access token: {e}")
            raise

    async def _refresh_access_token(self) -> bool:
        """
        Refresh access token using refresh_token

        Returns:
            True if refresh successful, False otherwise
        """
        if not self._refresh_token:
            self.logger().warning("No refresh token available, requesting new token")
            await self._request_new_token()
            return True

        try:
            # Create a temporary API factory without auth for refresh requests
            from hummingbot.connector.exchange.cofinex import cofinex_web_utils
            temp_throttler = cofinex_web_utils.create_throttler()
            temp_api_factory = cofinex_web_utils.build_api_factory_without_time_synchronizer_pre_processor(
                temp_throttler
            )
            rest_assistant = await temp_api_factory.get_rest_assistant()

            # Prepare refresh token request
            form_data = {
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }

            self.logger().info("Refreshing access token...")

            response = await rest_assistant.execute_request(
                url=CONSTANTS.OAUTH_TOKEN_URL,
                method=RESTMethod.POST,
                data=urlencode(form_data),
                headers=headers,
                throttler_limit_id=CONSTANTS.OAUTH_TOKEN_URL,
            )

            # Update tokens
            self._access_token = response.get("access_token")
            self._refresh_token = response.get("refresh_token", self._refresh_token)  # Keep old if not provided

            if not self._access_token:
                raise ValueError("No access_token in refresh response")

            expires_in = response.get("expires_in", 18000)
            self._token_expires_at = time.time() + expires_in

            self.logger().info(f"Successfully refreshed access token. Expires in {expires_in} seconds")
            return True

        except Exception as e:
            self.logger().warning(f"Failed to refresh token, requesting new token: {e}")
            # Fall back to requesting new token with username/password
            await self._request_new_token()
            return True

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        """
        Add Bearer token to REST request headers

        Args:
            request: The REST request to authenticate

        Returns:
            Authenticated REST request with Bearer token
        """
        # Get valid access token (will refresh if needed)
        access_token = await self.get_access_token()

        # Add Bearer token to Authorization header
        headers = request.headers or {}
        headers["Authorization"] = f"Bearer {access_token}"

        # Ensure Content-Type is set (if not already)
        if "Content-Type" not in headers:
            if request.data:
                headers["Content-Type"] = "application/json"
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"

        request.headers = headers

        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        WebSocket authentication (if required)

        Note: User mentioned WebSocket is public, so this may not be needed
        But if private WebSocket channels require auth, add Bearer token here

        Args:
            request: The WebSocket request to authenticate

        Returns:
            Authenticated WebSocket request
        """
        # If WebSocket requires auth, add Bearer token here
        # For now, return as-is since WebSocket is public
        return request

    def is_token_valid(self) -> bool:
        """
        Check if current token is valid (not expired)

        Returns:
            True if token is valid, False otherwise
        """
        if not self._access_token:
            return False

        current_time = time.time()
        buffer_time = CONSTANTS.TOKEN_REFRESH_BUFFER_SECONDS

        return current_time < (self._token_expires_at - buffer_time)

    async def ensure_valid_token(self):
        """
        Ensure we have a valid token, refreshing if necessary

        This is a convenience method that can be called before making requests
        """
        if not self.is_token_valid():
            await self.get_access_token()
