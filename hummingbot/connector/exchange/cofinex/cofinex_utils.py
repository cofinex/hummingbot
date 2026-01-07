"""
Cofinex Connector Utils

This module provides metadata constants required for Hummingbot to discover
and register the Cofinex connector. This file is automatically scanned by
Hummingbot's connector discovery system.

The actual connector implementation is in other files:
- cofinex_exchange.py - Main connector class
- cofinex_auth.py - OAuth 2.0 authentication
- cofinex_config_map.py - Configuration fields
- cofinex_web_utils.py - HTTP utilities
"""

from decimal import Decimal

from hummingbot.connector.exchange.cofinex.cofinex_config_map import CofinexConfigMap
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

# Required constants for connector discovery
CENTRALIZED = True
EXAMPLE_PAIR = "BTC-USDT"  # TODO: Update with actual Cofinex trading pair format
USE_ETHEREUM_WALLET = False
USE_ETH_GAS_LOOKUP = False

# Default trading fees
# TODO: Update with actual Cofinex fees when known
# These are placeholder values - should be updated based on Cofinex fee structure
DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.001"),  # 0.1% maker fee (placeholder)
    taker_percent_fee_decimal=Decimal("0.001"),   # 0.1% taker fee (placeholder)
    buy_percent_fee_deducted_from_returns=True
)

# Config map reference - points to CofinexConfigMap for credential management
# This tells Hummingbot which fields to prompt for when connecting
KEYS = CofinexConfigMap

# Optional: If Cofinex has multiple domains (main, testnet, etc.)
# Uncomment and configure if needed:
# OTHER_DOMAINS = ["cofinex_testnet"]
# OTHER_DOMAINS_EXAMPLE_PAIR = {"cofinex_testnet": "BTC-USDT"}
# OTHER_DOMAINS_DEFAULT_FEES = {"cofinex_testnet": DEFAULT_FEES}
# OTHER_DOMAINS_KEYS = {"cofinex_testnet": CofinexTestnetConfigMap}
