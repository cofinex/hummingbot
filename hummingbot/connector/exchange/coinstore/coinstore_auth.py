"""
CoinStore Exchange Authentication
"""

import hashlib
import hmac
import time
from typing import Any, Dict

from hummingbot.connector.exchange_base import ExchangeBase
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTRequest, WSRequest


class CoinStoreAuth(AuthBase):
    """
    CoinStore API authentication implementation
    """

    def __init__(self, api_key: str, secret_key: str, passphrase: str = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.passphrase = passphrase or ""

    def generate_signature(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        """Generate HMAC SHA256 signature for CoinStore API"""
        message = f"{timestamp}{method}{path}{body}"
        return hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def add_auth_to_rest_request(self, request: RESTRequest) -> RESTRequest:
        """Add authentication headers to REST request"""
        timestamp = str(int(time.time() * 1000))
        signature = self.generate_signature(
            timestamp=timestamp,
            method=request.method,
            path=request.url.split('?')[0].split('/')[-1] if '?' in request.url else request.url.split('/')[-1],
            body=request.data or ""
        )

        request.headers = request.headers or {}
        request.headers.update({
            "X-COINSTORE-APIKEY": self.api_key,
            "X-COINSTORE-TIMESTAMP": timestamp,
            "X-COINSTORE-SIGNATURE": signature,
            "Content-Type": "application/json"
        })

        return request

    def add_auth_to_ws_request(self, request: WSRequest) -> WSRequest:
        """Add authentication to WebSocket request"""
        # CoinStore WebSocket authentication if needed
        return request
