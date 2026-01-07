"""
Cofinex Connector Configuration Map

This module defines the configuration structure for the Cofinex connector.
It uses OAuth 2.0 authentication, so it requires username and password
instead of API key and secret key.
"""

from pydantic import ConfigDict, Field, SecretStr, field_validator

from hummingbot.client.config.config_data_types import BaseConnectorConfigMap
from hummingbot.client.config.config_helpers import validate_with_regex


class CofinexConfigMap(BaseConnectorConfigMap):
    """
    Configuration map for Cofinex connector

    Uses OAuth 2.0 authentication with username/password credentials.
    """
    connector: str = "cofinex"

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

    model_config = ConfigDict(title="cofinex")

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
