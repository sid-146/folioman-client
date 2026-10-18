"""SQLAlchemy 2.0 Async Engine and Session factory."""

from __future__ import annotations

import logging
from typing import Any, Self

from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from folioman_client.config import settings
from folioman_client.db.reporting import report_database_error, sanitize_url
from folioman_client.errors import FoliomanDatabaseError

logger = logging.getLogger(__name__)


class FoliomanAsyncConnection(AsyncConnection):
    """AsyncConnection that intercepts and reports database connection failures."""

    async def __aenter__(self) -> Self:
        try:
            return await super().__aenter__()
        except SQLAlchemyError as exc:
            dialect_name = getattr(getattr(self.engine, "dialect", None), "name", None)
            report_database_error(
                exc, backend=dialect_name, operation="Database connection"
            )
            raise

    def __await__(self) -> Any:
        async def _await_connect() -> FoliomanAsyncConnection:
            try:
                return await self.start()  # type: ignore[return-value]
            except SQLAlchemyError as exc:
                dialect_name = getattr(
                    getattr(self.engine, "dialect", None), "name", None
                )
                report_database_error(
                    exc, backend=dialect_name, operation="Database connection"
                )
                raise

        return _await_connect().__await__()


class FoliomanAsyncEngine(AsyncEngine):
    """AsyncEngine with integrated diagnostic error handling and connection tracking."""

    _connection_cls = FoliomanAsyncConnection


class FoliomanAsyncSession(AsyncSession):
    """AsyncSession that ensures database errors are reported cleanly and transactions rolled back."""

    async def execute(
        self,
        statement: Any,
        params: Any = None,
        execution_options: Any = None,
        bind_arguments: Any = None,
        **kw: Any,
    ) -> Any:
        try:
            return await super().execute(
                statement,
                params=params,
                execution_options=execution_options,
                bind_arguments=bind_arguments,
                **kw,
            )
        except SQLAlchemyError as exc:
            backend = (
                self.bind.dialect.name
                if self.bind and hasattr(self.bind, "dialect")
                else None
            )
            report_database_error(exc, backend=backend, statement=statement)
            raise

    async def commit(self) -> None:
        try:
            await super().commit()
        except SQLAlchemyError as exc:
            backend = (
                self.bind.dialect.name
                if self.bind and hasattr(self.bind, "dialect")
                else None
            )
            try:
                await self.rollback()
            except (SQLAlchemyError, OSError, RuntimeError):
                pass
            report_database_error(exc, backend=backend, operation="Transaction commit")
            raise

    async def flush(self, objects: Any = None) -> None:
        try:
            await super().flush(objects=objects)
        except SQLAlchemyError as exc:
            backend = (
                self.bind.dialect.name
                if self.bind and hasattr(self.bind, "dialect")
                else None
            )
            try:
                await self.rollback()
            except (SQLAlchemyError, OSError, RuntimeError):
                pass
            report_database_error(exc, backend=backend, operation="Transaction flush")
            raise


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

            base_engine = create_async_engine(db_url, **sqlite_kwargs)

            @event.listens_for(base_engine.sync_engine, "connect")
            def set_sqlite_pragmas(
                dbapi_connection: Any, connection_record: Any
            ) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                except Exception:  # noqa: BLE001, S110
                    pass
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            engine = FoliomanAsyncEngine(base_engine.sync_engine)
        else:
            # PostgreSQL / MySQL engine with pooling
            base_engine = create_async_engine(
                db_url,
                echo=False,
                pool_pre_ping=True,
                pool_size=10,
                max_overflow=20,
            )
            engine = FoliomanAsyncEngine(base_engine.sync_engine)

        @event.listens_for(engine.sync_engine, "handle_error")
        def on_handle_error(ctx: Any) -> None:
            dialect_name = getattr(getattr(ctx, "engine", None), "dialect", None)
            name = getattr(dialect_name, "name", None)
            report_database_error(
                ctx.sqlalchemy_exception,
                backend=name,
                statement=getattr(ctx, "statement", None),
            )

        return engine

    except Exception as exc:
        clean_url = sanitize_url(db_url)
        raise FoliomanDatabaseError(
            f"Failed to create database engine for '{clean_url}': {exc}"
        ) from exc


def create_sessionmaker(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Create an async sessionmaker bound to the provided engine."""
    return async_sessionmaker(
        bind=engine,
        class_=FoliomanAsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )


__all__ = [
    "FoliomanAsyncConnection",
    "FoliomanAsyncEngine",
    "FoliomanAsyncSession",
    "create_folioman_engine",
    "create_sessionmaker",
]
