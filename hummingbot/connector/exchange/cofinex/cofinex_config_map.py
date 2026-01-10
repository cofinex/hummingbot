"""
Cofinex Connector Configuration Map

This module defines the configuration structure for the Cofinex connector.
It uses OAuth 2.0 authentication, so it requires username and password
instead of API key and secret key.
"""

from typing import Optional

from pydantic import ConfigDict, Field, SecretStr, field_validator

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap


class CofinexConfigMap(BaseConnectorConfigMap):
    """
    Configuration map for Cofinex connector

    Uses OAuth 2.0 authentication with username/password credentials.
    """
    connector: str = Field(
        default="cofinex",
        json_schema_extra={
            "prompt": "What is your connector?",
            "prompt_on_new": True,
        },
    )

    cofinex_username: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Cofinex account email/username",
            "is_secure": True,
            "is_connect_key": True,
            "prompt_on_new": True,
        }
    )

    cofinex_password: SecretStr = Field(
        default=...,
        json_schema_extra={
            "prompt": "Enter your Cofinex account password",
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

    model_config = ConfigDict(title="cofinex")

    @field_validator("connector", mode="before")
    @classmethod
    def validate_connector(cls, v: str):
        """
        Override the base validator to avoid circular import during discovery.
        The validator only runs when actually validating a value, not during class definition.
        """
        # During discovery, AllConnectorSettings might not be ready yet
        # Skip validation if we're in discovery phase
        try:
            from hummingbot.client.settings import AllConnectorSettings

            # Try to access it - if it fails, we're in discovery phase
            _ = AllConnectorSettings.get_connector_settings()  # Check if discovery is complete
            # If we get here, discovery is complete, so validate normally
            from hummingbot.client.config.config_validators import validate_connector as base_validate
            ret = base_validate(v)
            if ret is not None:
                raise ValueError(ret)
        except (AttributeError, KeyError, RuntimeError, ImportError):
            # We're in discovery phase - skip validation
            # The connector name will be validated later when actually configuring
            pass
        return v

    @field_validator("cofinex_username", mode="before")
    @classmethod
    def validate_username(cls, v: str):
        """Validate username format (should be email)"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Username cannot be empty")
        # Basic email validation
        if "@" not in v:
            raise ValueError("Username should be an email address")
        return v

    @field_validator("cofinex_password", mode="before")
    @classmethod
    def validate_password(cls, v: str):
        """Validate password is not empty"""
        if not v or len(v.strip()) == 0:
            raise ValueError("Password cannot be empty")
        return v

    @field_validator("domain", mode="before")
    @classmethod
    def validate_domain(cls, v: str):
        """Validate domain is valid"""
        valid_domains = ["main", "testnet"]
        if v not in valid_domains:
            raise ValueError(f"Domain must be one of: {', '.join(valid_domains)}")
        return v
