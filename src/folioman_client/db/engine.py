"""SQLAlchemy 2.0 Async Engine and Session factory."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from folioman_client.config import settings
from folioman_client.errors import FoliomanDatabaseError

logger = logging.getLogger(__name__)


def create_folioman_engine(url: str | None = None) -> AsyncEngine:
    """Create a configured SQLAlchemy AsyncEngine.

    Automatically detects database dialect:
      - SQLite: Sets WAL mode, synchronous=NORMAL, busy_timeout=5000, and enables foreign keys.
      - PostgreSQL / MySQL: Configures connection pooling and pre-ping health checks.

    Args:
        url: Database connection URL (e.g. 'sqlite+aiosqlite:///path/to/db').
            If omitted, falls back to settings.resolved_database_url.

    Returns:
        Configured AsyncEngine instance.
    """
    db_url = (url or settings.resolved_database_url).strip()

    # Ensure correct driver prefix if caller passed raw sqlite:///
    if db_url.startswith("sqlite:///") and not db_url.startswith(
        "sqlite+aiosqlite:///"
    ):
        db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+"):
        db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)

    try:
        if db_url.startswith("sqlite"):
            from sqlalchemy.pool import StaticPool

            sqlite_kwargs: dict[str, Any] = {
                "echo": False,
                "connect_args": {"check_same_thread": False},
            }
            if ":memory:" in db_url or "mode=memory" in db_url:
                sqlite_kwargs["poolclass"] = StaticPool

            engine = create_async_engine(db_url, **sqlite_kwargs)

            @event.listens_for(engine.sync_engine, "connect")
            def set_sqlite_pragmas(
                dbapi_connection: Any, connection_record: Any
            ) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                except Exception:
                    pass
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            return engine

        # PostgreSQL / MySQL engine with pooling
        return create_async_engine(
            db_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
        )
    except Exception as exc:
        raise FoliomanDatabaseError(
            f"Failed to create database engine for '{db_url}': {exc}"
        ) from exc


def create_sessionmaker(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async sessionmaker bound to the provided engine."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


__all__ = ["create_folioman_engine", "create_sessionmaker"]
