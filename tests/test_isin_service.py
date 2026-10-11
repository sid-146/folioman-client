"""Tests for ISINService reference master catalog ingestion, search, and resolution."""

from __future__ import annotations

from decimal import Decimal
import pytest

from folioman_client.db.engine import create_folioman_engine
from folioman_client.services.isin_service import ISINService


@pytest.fixture
async def isin_service():
    """Provides an ISINService instance backed by an isolated in-memory SQLite database."""
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    service = ISINService(engine=engine)
    yield service
    await engine.dispose()


@pytest.mark.asyncio
async def test_reference_status_unseeded(isin_service: ISINService) -> None:
    status = await isin_service.get_reference_status()
    assert status["is_seeded"] is False
    assert status["schemes_count"] == 0
    assert status["isins_count"] == 0
    assert status["grandfathering_count"] == 0
    assert status["version"] is None


@pytest.mark.asyncio
async def test_seed_reference_data_and_idempotency(isin_service: ISINService) -> None:
    # 1. Initial seed
    res1 = await isin_service.seed_reference_data()
    assert res1["seeded"] is True
    assert res1["schemes_count"] > 20_000
    assert res1["isins_count"] > 200_000
    assert res1["grandfathering_count"] > 10_000
    assert res1["version"] is not None

    status = await isin_service.get_reference_status()
    assert status["is_seeded"] is True
    assert status["schemes_count"] == res1["schemes_count"]

    # 2. Second seed without force should be a fast no-op
    res2 = await isin_service.seed_reference_data(force=False)
    assert res2["seeded"] is False
    assert res2["schemes_count"] == res1["schemes_count"]

    # 3. Third seed with force should re-populate
    res3 = await isin_service.seed_reference_data(force=True)
    assert res3["seeded"] is True
    assert res3["schemes_count"] == res1["schemes_count"]


@pytest.mark.asyncio
async def test_resolve_isin_mutual_fund(isin_service: ISINService) -> None:
    await isin_service.seed_reference_data()

    # Resolve HDFC Arbitrage Fund (INF179K01319)
    result = await isin_service.resolve_isin("INF179K01319")
    assert result is not None
    assert result["isin"] == "INF179K01319"
    assert "HDFC" in result["name"]
    assert result["security_type"] == "MF"
    assert result["rta"] in ("CAMS", "KFINTECH", "FT")
    assert result["amfi_code"] != ""


@pytest.mark.asyncio
async def test_resolve_isin_case_and_whitespace_insensitivity(isin_service: ISINService) -> None:
    await isin_service.seed_reference_data()

    res_lower = await isin_service.resolve_isin("  inf179k01319  ")
    assert res_lower is not None
    assert res_lower["isin"] == "INF179K01319"


@pytest.mark.asyncio
async def test_resolve_isin_not_found_returns_none(isin_service: ISINService) -> None:
    await isin_service.seed_reference_data()

    assert await isin_service.resolve_isin("IN9999999999") is None
    assert await isin_service.resolve_isin("") is None
    assert await isin_service.resolve_isin("   ") is None


@pytest.mark.asyncio
async def test_resolve_amfi_code(isin_service: ISINService) -> None:
    await isin_service.seed_reference_data()

    # Resolve AMFI code 106796 (HDFC Arbitrage Fund)
    scheme = await isin_service.resolve_amfi_code("106796")
    assert scheme is not None
    assert scheme["amfi_code"] == "106796"
    assert "HDFC" in scheme["name"]
    assert scheme["isin"] == "INF179K01319"

    # Nonexistent AMFI code
    assert await isin_service.resolve_amfi_code("999999999") is None
    assert await isin_service.resolve_amfi_code("") is None


@pytest.mark.asyncio
async def test_search_schemes(isin_service: ISINService) -> None:
    await isin_service.seed_reference_data()

    # Search by text
    results = await isin_service.search_schemes("Arbitrage", limit=5)
    assert len(results) > 0
    assert len(results) <= 5
    for r in results:
        assert "ARBITRAGE" in r["name"].upper()

    # Search by AMFI code
    results_amfi = await isin_service.search_schemes("106796", limit=1)
    assert len(results_amfi) == 1
    assert results_amfi[0]["amfi_code"] == "106796"

    # Empty search
    assert await isin_service.search_schemes("") == []


@pytest.mark.asyncio
async def test_get_grandfathering_nav(isin_service: ISINService) -> None:
    await isin_service.seed_reference_data()

    # INF209KA1LH3 is in the 2018-01-31 grandfathering NAV list with value 216.86
    nav = await isin_service.get_grandfathering_nav("INF209KA1LH3")
    assert nav is not None
    assert isinstance(nav, Decimal)
    assert nav == Decimal("216.860000")

    # Nonexistent ISIN
    assert await isin_service.get_grandfathering_nav("IN0000000000") is None
    assert await isin_service.get_grandfathering_nav("") is None
