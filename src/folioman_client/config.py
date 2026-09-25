"""Configuration settings for Folioman Client."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FoliomanSettings(BaseSettings):
    """Folioman client configuration backed by environment variables.

    Attributes:
        base_url: The base URL of the Folioman REST API service.
            Defaults to "http://localhost:8000".
        username: The username used for HTTP basic or JWT token retrieval.
            Defaults to "".
        password: The password used for HTTP basic or JWT token retrieval.
            Defaults to "".
        timeout: The request timeout in seconds.
            Defaults to 30.0.
    """

    model_config = SettingsConfigDict(
        env_prefix="FOLIOMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    base_url: str = Field(
        default="http://localhost:8000",
        description="Base URL of the Folioman REST API service.",
    )
    username: str = Field(
        default="",
        description="Username or advisor identifier for authentication.",
    )
    password: str = Field(
        default="",
        description="Password or secret credential for authentication.",
    )
    timeout: float = Field(
        default=30.0,
        description="HTTP request timeout in seconds.",
    )

    @property
    def folioman_url(self) -> str:
        """Alias for base_url."""
        return self.base_url

    @property
    def folioman_username(self) -> str:
        """Alias for username."""
        return self.username

    @property
    def folioman_password(self) -> str:
        """Alias for password."""
        return self.password


settings = FoliomanSettings()
