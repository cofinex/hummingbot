from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import ConfigDict, Field, SecretStr, field_validator

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.core.data_type.trade_fee import TradeFeeSchema

CENTRALIZED = True
EXAMPLE_PAIR = "BTC-USDT"
USE_ETHEREUM_WALLET = False
USE_ETH_GAS_LOOKUP = False

DEFAULT_FEES = TradeFeeSchema(
    maker_percent_fee_decimal=Decimal("0.001"),
    taker_percent_fee_decimal=Decimal("0.001"),
    buy_percent_fee_deducted_from_returns=True
)


class CofinexConfigMap(BaseConnectorConfigMap):
    connector: str = "cofinex"

    cofinex_username: Optional[SecretStr] = Field(
        default="",
        json_schema_extra={
            "prompt": "Enter your Cofinex account email/username (leave empty for paper trading)",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )

    cofinex_password: Optional[SecretStr] = Field(
        default="",
        json_schema_extra={
            "prompt": "Enter your Cofinex account password (leave empty for paper trading)",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )

    domain: str = Field(
        default="main",
        json_schema_extra={
            "prompt": "Enter your Cofinex environment (main or testnet)",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": True,
        },
    )

    cofinex_ws_prefix: Optional[str] = Field(
        default="",
        json_schema_extra={
            "prompt": "Enter WebSocket namespace prefix for local testing (e.g., 'dev:santosh'). Leave empty for production.",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": False,
        }
    )

    cofinex_rest_api_base_url: Optional[str] = Field(
        default="",
        json_schema_extra={
            "prompt": "Enter REST API base URL for local testing (e.g., 'http://localhost:8001'). Leave empty for production (https://tradeapi1.cofinex.io).",
            "is_secure": False,
            "is_connect_key": False,
            "prompt_on_new": False,
        }
    )

    # Override parent's extra="forbid" to allow optional fields
    model_config = ConfigDict(
        title="cofinex",
        extra="allow",  # Allow extra fields for optional config like ws_prefix and rest_api_base_url
        validate_assignment=True,
        json_encoders={
            datetime: lambda dt: dt.strftime("%Y-%m-%d %H:%M:%S"),  # Preserve parent's json_encoders
        }
    )

    @field_validator("cofinex_username", mode="before")
    @classmethod
    def validate_username(cls, v):
        """Validate username format (should be email)
        Allows empty string or None for paper trading mode.
        Skips validation for encrypted values (they will be validated after decryption)."""
        # Allow empty string or None for paper trading (credentials not needed)
        if v is None or (isinstance(v, str) and len(v.strip()) == 0):
            return ""  # Return empty string instead of raising error

        # Convert SecretStr to string if needed
        if hasattr(v, 'get_secret_value'):
            v = v.get_secret_value()

        v_str = str(v)

        # Skip validation if value appears to be encrypted
        # Encrypted values are typically:
        # - JSON strings starting with '{'
        # - Long hex-encoded strings (like '7b22...')
        # - Very long strings (>100 chars, normal emails are much shorter)
        # - Base64-like strings
        if (v_str.startswith('{') or
            v_str.startswith('7b') or
            len(v_str) > 100 or
                (len(v_str) > 50 and all(c in '0123456789abcdef' for c in v_str.lower()))):
            # Likely encrypted, skip validation - will be validated after decryption
            return v

        # Basic email validation (only for decrypted/plain values)
        if "@" not in v_str:
            raise ValueError("Username should be an email address")
        return v

    @field_validator("cofinex_password", mode="before")
    @classmethod
    def validate_password(cls, v):
        """Validate password
        Allows empty string or None for paper trading mode.
        Skips validation for encrypted values (they will be validated after decryption)."""
        # Allow empty string or None for paper trading (credentials not needed)
        if v is None or (isinstance(v, str) and len(v.strip()) == 0):
            return ""  # Return empty string instead of raising error

        # Convert SecretStr to string if needed
        if hasattr(v, 'get_secret_value'):
            v = v.get_secret_value()

        v_str = str(v)

        # Skip validation if value appears to be encrypted
        # Encrypted values are typically:
        # - JSON strings starting with '{'
        # - Long hex-encoded strings
        # - Very long strings (>100 chars)
        if (v_str.startswith('{') or
            v_str.startswith('7b') or
            len(v_str) > 100 or
                (len(v_str) > 50 and all(c in '0123456789abcdef' for c in v_str.lower()))):
            # Likely encrypted, skip validation - will be validated after decryption
            return v

        return v

    @field_validator("domain", mode="before")
    @classmethod
    def validate_domain(cls, v: str):
        """Validate domain is valid"""
        valid_domains = ["main", "testnet"]
        if v not in valid_domains:
            raise ValueError(f"Domain must be one of: {', '.join(valid_domains)}")
        return v


KEYS = CofinexConfigMap.model_construct()
