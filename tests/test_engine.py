"""Tests for database engine factory, dialect configuration, and sessionmaker."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.errors import FoliomanDatabaseError


@pytest.mark.asyncio
async def test_create_engine_in_memory_sqlite() -> None:
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1

        # Check foreign keys enabled pragma
        fk_result = await conn.execute(text("PRAGMA foreign_keys"))
        assert fk_result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_engine_file_sqlite(tmp_path: Path) -> None:
    db_file = tmp_path / "test_engine.db"
    engine = create_folioman_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 42"))
        assert result.scalar() == 42

        # Check foreign keys pragma
        fk_result = await conn.execute(text("PRAGMA foreign_keys"))
        assert fk_result.scalar() == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_engine_url_normalization() -> None:
    # sqlite:/// prefix should be replaced with sqlite+aiosqlite:///
    engine = create_folioman_engine("sqlite:///:memory:")
    assert "sqlite+aiosqlite" in engine.url.drivername
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_sessionmaker_and_execute() -> None:
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    session_factory = create_sessionmaker(engine)

    async with session_factory() as session:
        result = await session.execute(text("SELECT 'folioman'"))
        assert result.scalar() == "folioman"
    await engine.dispose()


def test_create_engine_invalid_url_raises_folioman_database_error() -> None:
    with pytest.raises(FoliomanDatabaseError):
        create_folioman_engine("invalid_driver://localhost:9999/bad_db")
