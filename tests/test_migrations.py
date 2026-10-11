"""Tests for schema initialization, table generation, and schema version tracking."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import (
    CURRENT_SCHEMA_VERSION,
    get_schema_version,
    init_schema,
)
from folioman_client.db.models import SchemaVersion


@pytest.mark.asyncio
async def test_uninitialized_database_version_is_none() -> None:
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    version = await get_schema_version(engine)
    assert version is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_init_schema_creates_tables_and_sets_version() -> None:
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")

    version = await init_schema(engine)
    assert version == CURRENT_SCHEMA_VERSION

    # Verify get_schema_version returns the active version
    recorded_version = await get_schema_version(engine)
    assert recorded_version == CURRENT_SCHEMA_VERSION

    # Verify all expected tables exist
    expected_tables = {
        "_schema_version",
        "ref_schemes",
        "ref_isins",
        "ref_grandfathering_navs",
        "ref_meta",
        "amcs",
        "securities",
        "nav_history",
        "corporate_action_references",
        "fx_rates",
        "families",
        "investors",
        "folios",
        "transactions",
        "holdings",
        "partial_blocks",
        "investor_values",
        "applied_corporate_actions",
        "security_integrity_statuses",
        "import_jobs",
        "import_quarantines",
    }

    async with engine.connect() as conn:
        tables = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
        for expected in expected_tables:
            assert (
                expected in tables
            ), f"Expected table '{expected}' not found in created schema."

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_schema_is_idempotent() -> None:
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")

    # First run
    v1 = await init_schema(engine)
    assert v1 == CURRENT_SCHEMA_VERSION

    # Second run should execute cleanly without error and return same version
    v2 = await init_schema(engine)
    assert v2 == CURRENT_SCHEMA_VERSION

    await engine.dispose()


@pytest.mark.asyncio
async def test_init_schema_upgrades_older_version() -> None:
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")

    # Initial init
    await init_schema(engine)

    # Manually downgrade recorded version to 0
    async with engine.begin() as conn:
        await conn.execute(
            SchemaVersion.__table__.update()
            .where(SchemaVersion.id == 1)
            .values(version=0)
        )

    # Verify it is 0
    downgraded = await get_schema_version(engine)
    assert downgraded == 0

    # Running init_schema should detect older version and update to CURRENT_SCHEMA_VERSION
    upgraded = await init_schema(engine)
    assert upgraded == CURRENT_SCHEMA_VERSION

    current = await get_schema_version(engine)
    assert current == CURRENT_SCHEMA_VERSION

    await engine.dispose()
