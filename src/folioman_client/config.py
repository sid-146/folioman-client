"""Configuration settings for Folioman Client."""

from __future__ import annotations

import os
from pathlib import Path
from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FoliomanSettings(BaseSettings):
    """Folioman client configuration backed by environment variables.

    Attributes:
        database_url: SQLAlchemy connection URL (e.g. SQLite, PostgreSQL, MySQL).
            If omitted or empty, resolves to SQLite under data_dir.
        data_dir: Base directory for local databases, encryption keys, and caches.
            Defaults to the per-OS user data directory (~/.folioman).
        fernet_key: 32-byte URL-safe base64 key for PAN encryption.
        user_id: Logical tenant/advisor scope identifier (default: "default").
        timeout: Request timeout in seconds for external market feeds.
        base_url: Legacy REST API endpoint (maintained for backwards compatibility).
        username: Legacy account username.
        password: Legacy account password.
    """

    model_config = SettingsConfigDict(
        env_prefix="FOLIOMAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="",
        description="SQLAlchemy database connection URL.",
    )
    data_dir: str = Field(
        default="",
        description="Base directory for database and reference storage.",
    )
    fernet_key: str = Field(
        default="",
        description="Symmetric encryption key for PAN protection.",
    )
    user_id: str = Field(
        default="default",
        description="Multi-tenancy user or advisor identifier.",
    )
    timeout: float = Field(
        default=30.0,
        description="HTTP request timeout in seconds for market feeds.",
    )

    # Legacy fields maintained for backward-compatibility
    base_url: str = Field(
        default="http://localhost:8000",
        description="Legacy API endpoint.",
    )
    username: str = Field(
        default="",
        description="Legacy API username.",
    )
    password: str = Field(
        default="",
        description="Legacy API password.",
    )

    @property
    def resolved_data_dir(self) -> Path:
        """Resolve the effective data directory."""
        if self.data_dir:
            p = Path(self.data_dir)
        elif os.environ.get("FOLIOMAN_DATA_DIR"):
            p = Path(os.environ["FOLIOMAN_DATA_DIR"])
        else:
            p = Path(user_data_dir("folioman", "folioman"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def resolved_database_url(self) -> str:
        """Resolve database URL, defaulting to local SQLite if unspecified."""
        if self.database_url:
            return self.database_url
        if os.environ.get("FOLIOMAN_DATABASE_URL"):
            return os.environ["FOLIOMAN_DATABASE_URL"]
        db_path = self.resolved_data_dir / "folioman.db"
        return f"sqlite+aiosqlite:///{db_path}"

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

__all__ = ["FoliomanSettings", "settings"]
