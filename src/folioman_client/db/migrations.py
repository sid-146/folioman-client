"""Lightweight schema initialization and version tracking."""

from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from folioman_client.db.models import Base, SchemaVersion

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 1


async def init_schema(engine: AsyncEngine) -> int:
    """Ensure database schema is created and up to date.

    Idempotently creates all tables if they do not exist and registers the initial
    schema version.

    Args:
        engine: The target SQLAlchemy AsyncEngine.

    Returns:
        The active schema version integer.
    """
    async with engine.begin() as conn:
        # Create all declared tables
        await conn.run_sync(Base.metadata.create_all)

        # Check existing schema version
        stmt = select(SchemaVersion.version).where(SchemaVersion.id == 1)
        result = await conn.execute(stmt)
        current_version = result.scalar_one_or_none()

        if current_version is None:
            # First initialization
            await conn.execute(
                SchemaVersion.__table__.insert().values(
                    id=1,
                    version=CURRENT_SCHEMA_VERSION,
                )
            )
            logger.info(
                "Initialized Folioman database schema to version %d",
                CURRENT_SCHEMA_VERSION,
            )
            return CURRENT_SCHEMA_VERSION

        if current_version < CURRENT_SCHEMA_VERSION:
            logger.info(
                "Upgrading database schema from version %d to %d",
                current_version,
                CURRENT_SCHEMA_VERSION,
            )
            # Future version patches will be executed here incrementally
            await conn.execute(
                SchemaVersion.__table__.update()
                .where(SchemaVersion.id == 1)
                .values(version=CURRENT_SCHEMA_VERSION)
            )

        return CURRENT_SCHEMA_VERSION


async def get_schema_version(engine: AsyncEngine) -> int | None:
    """Return the currently recorded schema version or None if uninitialized."""
    async with engine.connect() as conn:
        try:
            stmt = select(SchemaVersion.version).where(SchemaVersion.id == 1)
            result = await conn.execute(stmt)
            return result.scalar_one_or_none()
        except Exception:
            return None


__all__ = ["CURRENT_SCHEMA_VERSION", "init_schema", "get_schema_version"]
