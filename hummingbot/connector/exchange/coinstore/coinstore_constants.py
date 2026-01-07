"""
CoinStore Exchange Constants
"""

# API URLs
REST_URL = "https://api.coinstore.com"
WS_URL = "wss://api.coinstore.com/ws"

# Trading pairs
SUPPORTED_TRADING_PAIRS = [
    "SUIUSDT",
    "BTCUSDT",
    "ETHUSDT",
    "ADAUSDT",
    "SOLUSDT"
]

# Order types
ORDER_TYPES = {
    "LIMIT": "LIMIT",
    "MARKET": "MARKET",
    "STOP_LIMIT": "STOP_LIMIT"
}

# Order sides
ORDER_SIDES = {
    "BUY": "BUY",
    "SELL": "SELL"
}

# Order status
ORDER_STATUS = {
    "NEW": "NEW",
    "PARTIALLY_FILLED": "PARTIALLY_FILLED",
    "FILLED": "FILLED",
    "CANCELED": "CANCELED",
    "REJECTED": "REJECTED"
}

# Rate limits
RATE_LIMITS = {
    "REST": {
        "requests_per_second": 10,
        "requests_per_minute": 1200
    },
    "WS": {
        "connections_per_minute": 5
    }
}

# Error codes
ERROR_CODES = {
    1001: "Invalid API key",
    1002: "Invalid signature",
    1003: "Invalid timestamp",
    1004: "Invalid trading pair",
    1005: "Insufficient balance",
    1006: "Order not found",
    1007: "Invalid order size",
    1008: "Invalid order price",
    1009: "Market closed",
    1010: "Rate limit exceeded"
}
