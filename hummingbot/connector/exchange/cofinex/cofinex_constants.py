"""
Cofinex Exchange Constants and Configuration

This file contains all the constants, endpoints, and configuration
needed for the Cofinex exchange connector.

TODO: Update these values based on actual Cofinex API documentation
"""

import sys

from hummingbot.core.api_throttler.data_types import RateLimit

EXCHANGE_NAME = "cofinex"
DEFAULT_DOMAIN = "main"

# Base URLs - TODO: Update with actual Cofinex API endpoints
BASE_PATH_URL = {
    "main": "https://api.cofinex.com",
    # Add testnet if available
    # "testnet": "https://api-testnet.cofinex.com",
}

# WebSocket URLs
WS_BASE_URL = {
    "main": "wss://api.cofinex.com/ws",
    # "testnet": "wss://api-testnet.cofinex.com/ws",
}

# OAuth 2.0 / OpenID Connect Configuration
OAUTH_TOKEN_URL = "https://auth.cofinex.io/realms/cofinex/protocol/openid-connect/token"
OAUTH_CLIENT_ID = "cofinex-exchange"
OAUTH_SCOPE = "openid"
OAUTH_GRANT_TYPE = "password"
TOKEN_REFRESH_BUFFER_SECONDS = 300  # Refresh 5 minutes before expiry (tokens last 5 hours)

# REST API Endpoints - TODO: Update with actual Cofinex Trade Engine API endpoints
# Note: These are placeholder paths - need actual Cofinex Trade Engine API paths
SERVER_TIME_PATH_URL = "/api/v1/time"
SYMBOLS_PATH_URL = "/api/v1/symbols"
TICKER_PATH_URL = "/api/v1/ticker"
ORDER_BOOK_PATH_URL = "/api/v1/depth"
TRADES_PATH_URL = "/api/v1/trades"
EXCHANGE_INFO_PATH_URL = "/api/v1/exchangeInfo"

# Private API Endpoints (require Bearer token)
ACCOUNTS_PATH_URL = "/api/v1/account"
ORDERS_PATH_URL = "/api/v1/orders"
ORDER_PATH_URL = "/api/v1/order"
OPEN_ORDERS_PATH_URL = "/api/v1/openOrders"
MY_TRADES_PATH_URL = "/api/v1/myTrades"

# Order Book Tracker
HBOT_ORDER_ID_PREFIX = "cofinex"
MAX_ORDER_ID_LEN = 32

# WebSocket
WS_HEARTBEAT_TIME_INTERVAL = 30
WS_PING_MESSAGE = "ping"
WS_PONG_MESSAGE = "pong"

# Rate Limit IDs
WS_CONNECTION_LIMIT_ID = "WSConnection"
WS_SUBSCRIPTION_LIMIT_ID = "WSSubscription"
GET_ORDER_LIMIT_ID = "GetOrder"
POST_ORDER_LIMIT_ID = "PostOrder"
DELETE_ORDER_LIMIT_ID = "DeleteOrder"

# =============================================================================
# SUPPORTED TRADING PAIRS
# =============================================================================
# TODO: Get the complete list of supported trading pairs from Cofinex API
# You can usually find this by calling their /symbols or /trading-pairs endpoint
SUPPORTED_TRADING_PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "ADAUSDT",
    "SOLUSDT",
    "SUIUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "MATICUSDT",
    "AVAXUSDT"
]

# =============================================================================
# ORDER TYPES
# =============================================================================
# TODO: Verify these order types with Cofinex API documentation
# Different exchanges support different order types
ORDER_TYPES = {
    "LIMIT": "LIMIT",           # Limit order
    "MARKET": "MARKET",         # Market order
    "STOP_LIMIT": "STOP_LIMIT",  # Stop limit order
    "STOP_MARKET": "STOP_MARKET",  # Stop market order
    "OCO": "OCO"                # One-Cancels-Other order
}

# =============================================================================
# ORDER SIDES
# =============================================================================
ORDER_SIDES = {
    "BUY": "BUY",
    "SELL": "SELL"
}

# =============================================================================
# ORDER STATUS
# =============================================================================
# TODO: Map these to actual Cofinex order status values
# Check Cofinex API docs for exact status strings
ORDER_STATUS = {
    "NEW": "NEW",                           # Order placed but not filled
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",  # Order partially filled
    "FILLED": "FILLED",                     # Order completely filled
    "CANCELED": "CANCELED",                 # Order canceled by user
    "REJECTED": "REJECTED",                 # Order rejected by exchange
    "EXPIRED": "EXPIRED",                   # Order expired
    "PENDING_CANCEL": "PENDING_CANCEL"      # Order pending cancellation
}

# =============================================================================
# RATE LIMITS
# =============================================================================
# TODO: Get actual rate limits from Cofinex API documentation
# Rate limits are crucial for avoiding API bans
NO_LIMIT = sys.maxsize
ONE_MINUTE = 60
ONE_SECOND = 1

RATE_LIMITS = [
    # OAuth token endpoint - limit token requests
    RateLimit(limit_id=OAUTH_TOKEN_URL, limit=10, time_interval=ONE_MINUTE),  # Max 10 token requests per minute

    # WebSocket limits
    RateLimit(limit_id=WS_CONNECTION_LIMIT_ID, limit=5, time_interval=ONE_MINUTE),
    RateLimit(limit_id=WS_SUBSCRIPTION_LIMIT_ID, limit=200, time_interval=ONE_SECOND),

    # Public endpoints - TODO: Update with actual limits
    RateLimit(limit_id=SERVER_TIME_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=SYMBOLS_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=TICKER_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=ORDER_BOOK_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=TRADES_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=EXCHANGE_INFO_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),

    # Private endpoints (require Bearer token) - TODO: Update with actual limits
    RateLimit(limit_id=ACCOUNTS_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=GET_ORDER_LIMIT_ID, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=POST_ORDER_LIMIT_ID, limit=10, time_interval=ONE_SECOND),  # Conservative limit
    RateLimit(limit_id=DELETE_ORDER_LIMIT_ID, limit=10, time_interval=ONE_SECOND),  # Conservative limit
    RateLimit(limit_id=ORDERS_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=OPEN_ORDERS_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
    RateLimit(limit_id=MY_TRADES_PATH_URL, limit=NO_LIMIT, time_interval=ONE_SECOND),
]

# =============================================================================
# ERROR CODES
# =============================================================================
# TODO: Get actual error codes from Cofinex API documentation
# These help with proper error handling and user feedback
ERROR_CODES = {
    # Authentication errors
    1001: "Invalid API key",
    1002: "Invalid signature",
    1003: "Invalid timestamp",
    1004: "API key not found",
    1005: "API key expired",

    # Trading errors
    2001: "Invalid trading pair",
    2002: "Insufficient balance",
    2003: "Order not found",
    2004: "Invalid order size",
    2005: "Invalid order price",
    2006: "Order size too small",
    2007: "Order size too large",
    2008: "Price too high",
    2009: "Price too low",
    2010: "Market closed",

    # System errors
    3001: "Rate limit exceeded",
    3002: "Server error",
    3003: "Service unavailable",
    3004: "Invalid request format",
    3005: "Missing required parameter",

    # Account errors
    4001: "Account not found",
    4002: "Account suspended",
    4003: "Insufficient permissions",
    4004: "Withdrawal disabled",
    4005: "Trading disabled"
}

# =============================================================================
# TRADING RULES
# =============================================================================
# TODO: Get actual trading rules from Cofinex API
# These define minimum/maximum order sizes, price precision, etc.
DEFAULT_TRADING_RULES = {
    "min_order_size": 0.001,        # Minimum order size
    "max_order_size": 1000000,      # Maximum order size
    "min_price_increment": 0.0001,  # Minimum price increment
    "min_quantity_increment": 0.001,  # Minimum quantity increment
    "max_price_precision": 8,       # Maximum decimal places for price
    "max_quantity_precision": 8,    # Maximum decimal places for quantity
    "trading_fee": 0.001,           # Default trading fee (0.1%)
    "maker_fee": 0.001,             # Maker fee
    "taker_fee": 0.001              # Taker fee
}

# =============================================================================
# WEBSOCKET MESSAGE TYPES
# =============================================================================
# TODO: Define actual WebSocket message types from Cofinex documentation
WS_MESSAGE_TYPES = {
    "ORDER_BOOK_UPDATE": "orderbook.update",
    "TRADE_UPDATE": "trade.update",
    "ORDER_UPDATE": "order.update",
    "BALANCE_UPDATE": "balance.update",
    "TICKER_UPDATE": "ticker.update",
    "KLINE_UPDATE": "kline.update",
    "ERROR": "error",
    "PING": "ping",
    "PONG": "pong"
}

# =============================================================================
# API VERSIONS
# =============================================================================
# TODO: Check what API versions Cofinex supports
API_VERSIONS = {
    "REST": "v1",
    "WS": "v1"
}

# =============================================================================
# TIMEOUTS
# =============================================================================
# Network timeouts for API calls
TIMEOUTS = {
    "REST_REQUEST": 30,      # 30 seconds for REST requests
    "WS_CONNECT": 10,        # 10 seconds for WebSocket connection
    "WS_MESSAGE": 5,         # 5 seconds for WebSocket message timeout
    "HEARTBEAT": 30          # 30 seconds for heartbeat interval
}

# =============================================================================
# RETRY CONFIGURATION
# =============================================================================
# Retry configuration for failed requests
RETRY_CONFIG = {
    "max_retries": 3,        # Maximum number of retries
    "retry_delay": 1,        # Initial delay between retries (seconds)
    "backoff_factor": 2,     # Exponential backoff factor
    "max_delay": 60          # Maximum delay between retries (seconds)
}

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
# Logging levels and configuration
LOGGING_CONFIG = {
    "level": "INFO",
    "log_requests": True,
    "log_responses": False,  # Set to True for debugging
    "log_errors": True,
    "log_trades": True,
    "log_orders": True
}
