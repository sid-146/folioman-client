"""Unit tests for CorporateActionService: announcement caching, listing, and application."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from folioman_client.db.engine import create_folioman_engine
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    AppliedCorporateAction,
    CorporateActionReference,
    Folio,
    Investor,
    Security,
)
from folioman_client.services.corporate_action_service import CorporateActionService


@pytest.fixture
async def ca_service():
    engine = create_folioman_engine("sqlite+aiosqlite:///:memory:")
    await init_schema(engine)
    service = CorporateActionService(engine=engine)
    yield service
    await engine.dispose()


@pytest.mark.asyncio
async def test_apply_corporate_action_bonus(ca_service: CorporateActionService):
    async with ca_service.session_factory() as session:
        inv = Investor(name="MS Dhoni")
        session.add(inv)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="DEMAT-1", folio_type="demat")
        sec = Security(
            name="Wipro Ltd",
            isin="INE075A01022",
            symbol="WIPRO",
            security_type="EQUITY",
        )
        session.add_all([fol, sec])
        await session.flush()

        ref = CorporateActionReference(
            security_id=sec.id,
            isin="INE075A01022",
            symbol="WIPRO",
            ex_date=date(2024, 12, 3),
            subject="Bonus 1:1",
            parsed_type="bonus",
            unit_multiplier=Decimal(2),
            parsed_json={"ratio": [1, 1]},
            needs_review=False,
        )
        session.add(ref)
        await session.commit()
        inv_id, fol_id, ref_id = inv.id, fol.id, ref.id

    # 1. Apply bonus action
    result = await ca_service.apply_corporate_action(inv_id, fol_id, ref_id)
    assert result["applied"] is True
    assert result["kind"] == "bonus"
    assert Decimal(result["unit_multiplier"]) == Decimal(2)

    # Verify AppliedCorporateAction row created
    async with ca_service.session_factory() as session:
        aca = await session.get(AppliedCorporateAction, result["action_id"])
        assert aca is not None
        assert aca.investor_id == inv_id
        assert aca.folio_id == fol_id
        assert aca.bonus_ratio_a == 1
        assert aca.bonus_ratio_b == 1
        assert aca.source_ref == f"ca-ref:{ref_id}"

    # 2. Applying again should be idempotent and return already_applied
    dup_result = await ca_service.apply_corporate_action(inv_id, fol_id, ref_id)
    assert dup_result["applied"] is False
    assert dup_result["reason"] == "already_applied"


@pytest.mark.asyncio
async def test_apply_corporate_action_validation_errors(
    ca_service: CorporateActionService,
):
    async with ca_service.session_factory() as session:
        inv = Investor(name="Virat Kohli")
        session.add(inv)
        await session.flush()

        fol = Folio(investor_id=inv.id, number="DEMAT-2", folio_type="demat")
        sec = Security(
            name="Infosys Ltd",
            isin="INE009A01021",
            symbol="INFY",
            security_type="EQUITY",
        )
        session.add_all([fol, sec])
        await session.flush()

        # Needs review action
        ref_review = CorporateActionReference(
            security_id=sec.id,
            isin="INE009A01021",
            symbol="INFY",
            ex_date=date(2025, 1, 1),
            subject="Bonus Scheme Review",
            parsed_type="bonus",
            unit_multiplier=Decimal(2),
            needs_review=True,
        )
        # Dividend action
        ref_dividend = CorporateActionReference(
            security_id=sec.id,
            isin="INE009A01021",
            symbol="INFY",
            ex_date=date(2025, 2, 1),
            subject="Interim Dividend Rs 10",
            parsed_type="dividend",
            amount=Decimal(10),
            needs_review=False,
        )
        session.add_all([ref_review, ref_dividend])
        await session.commit()
        inv_id, fol_id = inv.id, fol.id
        review_id, div_id = ref_review.id, ref_dividend.id

    # Test needs_review rejection
    with pytest.raises(ValueError, match="needs_review"):
        await ca_service.apply_corporate_action(inv_id, fol_id, review_id)

    # Test dividend rejection
    with pytest.raises(ValueError, match="not auto-applicable"):
        await ca_service.apply_corporate_action(inv_id, fol_id, div_id)


@pytest.mark.asyncio
async def test_list_references_filtering(ca_service: CorporateActionService):
    async with ca_service.session_factory() as session:
        r1 = CorporateActionReference(
            isin="INE001A01010",
            symbol="TCS",
            ex_date=date(2024, 5, 10),
            subject="Bonus 1:1",
            parsed_type="bonus",
            unit_multiplier=Decimal(2),
        )
        r2 = CorporateActionReference(
            isin="INE001A01010",
            symbol="TCS",
            ex_date=date(2023, 6, 15),
            subject="Stock Split From Rs.10/- to Rs.1/-",
            parsed_type="split",
            unit_multiplier=Decimal(10),
        )
        r3 = CorporateActionReference(
            isin="INE002A01018",
            symbol="RELIANCE",
            ex_date=date(2024, 10, 28),
            subject="Bonus 1:1",
            parsed_type="bonus",
            unit_multiplier=Decimal(2),
        )
        session.add_all([r1, r2, r3])
        await session.commit()

    all_refs = await ca_service.list_references()
    assert len(all_refs) == 3

    tcs_refs = await ca_service.list_references(symbol="TCS")
    assert len(tcs_refs) == 2

    splits = await ca_service.list_references(kind="split")
    assert len(splits) == 1
    assert splits[0]["symbol"] == "TCS"
