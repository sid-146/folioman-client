"""Ledger service: manages investor profiles, folios, manual transactions, and opening lots."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import selectinload

from folioman_client.core.models.investor import normalize_folio_number
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    AMC,
    Folio,
    Holding,
    Investor,
    Security,
    SecurityIntegrityStatus,
    Transaction,
)
from folioman_client.security.pan import decrypt_pan, encrypt_pan, mask_pan, pan_hash
from folioman_client.services.reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


class LedgerService:
    """Service for querying and modifying investors, folios, positions, and manual transactions."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = create_sessionmaker(self.engine)
        self._reconcile_service = ReconciliationService(engine=self.engine)

    # ------------------------------------------------------------------------
    # Investor Profile Management
    # ------------------------------------------------------------------------

    async def list_investors(
        self,
        *,
        user_id: str = "default",
        family_id: int | None = None,
        unaffiliated: bool = False,
    ) -> list[dict[str, Any]]:
        """List investors scoped by user/advisor and family filter."""
        await init_schema(self.engine)

        async with self.session_factory() as session:
            stmt = (
                select(Investor)
                .where(Investor.user_id == user_id)
                .order_by(Investor.name)
            )
            if family_id is not None:
                stmt = stmt.where(Investor.family_id == family_id)
            if unaffiliated:
                stmt = stmt.where(Investor.family_id.is_(None))

            investors = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": inv.id,
                    "name": inv.name,
                    "email": inv.email,
                    "is_huf": inv.is_huf,
                    "relation": inv.relation,
                    "family_id": inv.family_id,
                    "pan_masked": inv.pan_masked,
                    "has_pan": inv.pan_encrypted is not None,
                }
                for inv in investors
            ]

    async def get_investor(self, investor_id: int) -> dict[str, Any]:
        """Get investor details including masked PAN."""
        await init_schema(self.engine)

        async with self.session_factory() as session:
            inv = await session.get(Investor, investor_id)
            if inv is None:
                raise ValueError(f"Investor {investor_id} not found.")

            return {
                "id": inv.id,
                "name": inv.name,
                "email": inv.email,
                "is_huf": inv.is_huf,
                "relation": inv.relation,
                "family_id": inv.family_id,
                "pan_masked": inv.pan_masked,
                "has_pan": inv.pan_encrypted is not None,
            }

    async def create_investor(
        self,
        *,
        user_id: str = "default",
        name: str,
        pan: str | None = None,
        email: str = "",
        family_id: int | None = None,
        is_huf: bool = False,
        relation: str = "",
    ) -> dict[str, Any]:
        """Create a new investor profile with encrypted PAN protection."""
        await init_schema(self.engine)

        norm_pan = pan.strip().upper() if pan else ""
        enc_pan = encrypt_pan(norm_pan) if norm_pan else None
        p_hash = pan_hash(norm_pan) if norm_pan else None

        async with self.session_factory() as session:
            inv = Investor(
                user_id=user_id,
                name=name,
                email=email,
                pan_encrypted=enc_pan,
                pan_hash=p_hash,
                family_id=family_id,
                is_huf=is_huf,
                relation=relation,
            )
            session.add(inv)
            await session.commit()

            return {
                "id": inv.id,
                "name": inv.name,
                "email": inv.email,
                "is_huf": inv.is_huf,
                "relation": inv.relation,
                "family_id": inv.family_id,
                "pan_masked": inv.pan_masked,
                "has_pan": bool(enc_pan),
            }

    # ------------------------------------------------------------------------
    # Folio Management
    # ------------------------------------------------------------------------

    async def list_folios(self, investor_id: int) -> list[dict[str, Any]]:
        """List all accounts and folios belonging to an investor."""
        await init_schema(self.engine)

        async with self.session_factory() as session:
            stmt = (
                select(Folio)
                .where(Folio.investor_id == investor_id)
                .order_by(Folio.number)
            )
            folios = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": f.id,
                    "investor_id": f.investor_id,
                    "number": f.number,
                    "amc_code": f.amc_code,
                    "folio_type": f.folio_type,
                    "broker": f.broker,
                    "pan_kyc": f.pan_kyc,
                }
                for f in folios
            ]

    async def create_folio(
        self,
        investor_id: int,
        number: str,
        *,
        amc_code: str = "",
        broker: str = "",
        folio_type: str = "mf",
    ) -> dict[str, Any]:
        """Create a new folio record with normalized numbering."""
        await init_schema(self.engine)

        norm_num = normalize_folio_number(number)
        async with self.session_factory() as session:
            stmt = select(Folio).where(
                Folio.investor_id == investor_id,
                Folio.number == norm_num,
                Folio.amc_code == amc_code,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing:
                return {
                    "id": existing.id,
                    "number": existing.number,
                    "amc_code": existing.amc_code,
                    "folio_type": existing.folio_type,
                    "broker": existing.broker,
                }

            folio = Folio(
                investor_id=investor_id,
                number=norm_num,
                amc_code=amc_code,
                broker=broker,
                folio_type=folio_type,
            )
            session.add(folio)
            await session.commit()
            return {
                "id": folio.id,
                "number": folio.number,
                "amc_code": folio.amc_code,
                "folio_type": folio.folio_type,
                "broker": folio.broker,
            }

    async def merge_folios(
        self, investor_id: int, source_folio_id: int, target_folio_id: int
    ) -> dict[str, Any]:
        """Merge a source folio into a target folio, moving all transactions and holdings."""
        if source_folio_id == target_folio_id:
            raise ValueError("Source and target folios must be different.")

        await init_schema(self.engine)

        async with self.session_factory() as session:
            source = await session.get(Folio, source_folio_id)
            target = await session.get(Folio, target_folio_id)
            if not source or source.investor_id != investor_id:
                raise ValueError(
                    f"Source folio {source_folio_id} not found for investor."
                )
            if not target or target.investor_id != investor_id:
                raise ValueError(
                    f"Target folio {target_folio_id} not found for investor."
                )

            # Move transactions
            tx_res = await session.execute(
                update(Transaction)
                .where(Transaction.folio_id == source_folio_id)
                .values(folio_id=target_folio_id)
            )

            # Move holdings
            hold_res = await session.execute(
                update(Holding)
                .where(Holding.folio_id == source_folio_id)
                .values(folio_id=target_folio_id)
            )

            # Delete source integrity rows and source folio
            await session.execute(
                delete(SecurityIntegrityStatus).where(
                    SecurityIntegrityStatus.folio_id == source_folio_id
                )
            )
            await session.delete(source)
            await session.commit()

        # Recompute reconciliation for target folio
        await self._reconcile_service.reconcile_investor(investor_id)

        return {
            "source_folio_id": source_folio_id,
            "target_folio_id": target_folio_id,
            "transactions_moved": tx_res.rowcount,
            "holdings_moved": hold_res.rowcount,
        }

    # ------------------------------------------------------------------------
    # Transaction Ledger Management
    # ------------------------------------------------------------------------

    async def list_transactions(
        self,
        investor_id: int,
        *,
        security_id: int | None = None,
        folio_id: int | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """List transactions for an investor ordered chronologically."""
        await init_schema(self.engine)

        async with self.session_factory() as session:
            stmt = (
                select(Transaction)
                .options(
                    selectinload(Transaction.security), selectinload(Transaction.folio)
                )
                .where(Transaction.investor_id == investor_id)
                .order_by(Transaction.date.asc(), Transaction.id.asc())
            )
            if security_id is not None:
                stmt = stmt.where(Transaction.security_id == security_id)
            if folio_id is not None:
                stmt = stmt.where(Transaction.folio_id == folio_id)
            if from_date is not None:
                stmt = stmt.where(Transaction.date >= from_date)
            if to_date is not None:
                stmt = stmt.where(Transaction.date <= to_date)

            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": t.id,
                    "date": t.date.isoformat(),
                    "type": t.transaction_type,
                    "units": str(t.units),
                    "nav": str(t.nav_or_price),
                    "amount": str(t.amount) if t.amount is not None else None,
                    "currency": t.currency,
                    "fees": str(t.fees),
                    "stamp_duty": str(t.stamp_duty),
                    "source": t.source,
                    "source_ref": t.source_ref,
                    "narration": t.narration,
                    "cost_basis_complete": t.cost_basis_complete,
                    "security_id": t.security_id,
                    "security_name": t.security.name if t.security else "",
                    "security_isin": t.security.isin if t.security else "",
                    "folio_id": t.folio_id,
                    "folio_number": t.folio.number if t.folio else "",
                }
                for t in rows
            ]

    async def create_transaction(
        self,
        *,
        investor_id: int,
        security_id: int,
        date: date,
        transaction_type: str,
        units: Decimal | str,
        nav_or_price: Decimal | str,
        amount: Decimal | str | None = None,
        folio_id: int | None = None,
        fees: Decimal | str = "0",
        stamp_duty: Decimal | str = "0",
        narration: str = "",
        source: str = "manual",
        source_ref: str = "",
    ) -> dict[str, Any]:
        """Manually record a trade transaction into the ledger."""
        await init_schema(self.engine)

        u = Decimal(str(units))
        p = Decimal(str(nav_or_price))
        amt = Decimal(str(amount)) if amount is not None else (u * p)
        f = Decimal(str(fees))
        sd = Decimal(str(stamp_duty))
        ttype = transaction_type.upper().strip()

        async with self.session_factory() as session:
            inv = await session.get(Investor, investor_id)
            if not inv:
                raise ValueError(f"Investor {investor_id} not found.")

            sec = await session.get(Security, security_id)
            if not sec:
                raise ValueError(f"Security {security_id} not found.")

            txn = Transaction(
                investor_id=investor_id,
                security_id=security_id,
                folio_id=folio_id,
                date=date,
                transaction_type=ttype,
                units=u,
                nav_or_price=p,
                amount=amt,
                fees=f,
                stamp_duty=sd,
                narration=narration,
                source=source,
                source_ref=source_ref,
                cost_basis_complete=True,
            )
            session.add(txn)
            await session.commit()
            txn_id = txn.id

        # Reconcile position after adding transaction
        if folio_id is not None:
            async with self.session_factory() as session:
                await self._reconcile_service.reconcile_security_folio(
                    session, investor_id, security_id, folio_id
                )
                await session.commit()

        return {
            "id": txn_id,
            "investor_id": investor_id,
            "security_id": security_id,
            "folio_id": folio_id,
            "date": date.isoformat(),
            "transaction_type": ttype,
            "units": str(u),
            "nav_or_price": str(p),
            "amount": str(amt),
        }

    async def create_opening_lot(
        self,
        *,
        investor_id: int,
        folio_id: int,
        security_id: int,
        units: Decimal | str,
        cost_basis: Decimal | str,
        as_of_date: date,
        classification: str = "ipo_allotment",
    ) -> dict[str, Any]:
        """Record an opening lot (e.g. IPO allotment, gift/transfer in) for a snapshot-only position."""
        u = Decimal(str(units))
        cost = Decimal(str(cost_basis))
        nav = (cost / u) if u > 0 else _ZERO
        source_ref = f"opening-lot:{folio_id}:{security_id}:{classification}"

        return await self.create_transaction(
            investor_id=investor_id,
            security_id=security_id,
            folio_id=folio_id,
            date=as_of_date,
            transaction_type="BUY",
            units=u,
            nav_or_price=nav,
            amount=cost,
            source="manual",
            source_ref=source_ref,
            narration=f"Opening lot: {classification.replace('_', ' ').title()}",
        )

    # ------------------------------------------------------------------------
    # Holdings Queries
    # ------------------------------------------------------------------------

    async def list_holdings(
        self,
        investor_id: int,
        *,
        as_of: date | None = None,
    ) -> list[dict[str, Any]]:
        """List active positions (either from observed snapshots or net ledger units)."""
        await init_schema(self.engine)

        async with self.session_factory() as session:
            # Query active securities for investor
            stmt = (
                select(Security)
                .where(
                    Security.id.in_(
                        select(Transaction.security_id)
                        .where(Transaction.investor_id == investor_id)
                        .distinct()
                    )
                    | Security.id.in_(
                        select(Holding.security_id)
                        .where(Holding.investor_id == investor_id)
                        .distinct()
                    )
                )
                .order_by(Security.name)
            )

            securities = (await session.execute(stmt)).scalars().all()
            results: list[dict[str, Any]] = []

            for sec in securities:
                # Find net units from ledger
                txns_net_stmt = select(
                    func.coalesce(
                        func.sum(
                            case(
                                (
                                    Transaction.transaction_type.in_(
                                        ["BUY", "BONUS", "TRANSFER_IN"]
                                    ),
                                    Transaction.units,
                                ),
                                (
                                    Transaction.transaction_type.in_(
                                        ["SELL", "TRANSFER_OUT"]
                                    ),
                                    -Transaction.units,
                                ),
                                else_=_ZERO,
                            )
                        ),
                        _ZERO,
                    )
                ).where(
                    Transaction.investor_id == investor_id,
                    Transaction.security_id == sec.id,
                )
                net_units = Decimal(str(await session.scalar(txns_net_stmt) or 0))

                # Check latest holding snapshot
                snap_stmt = (
                    select(Holding)
                    .where(
                        Holding.investor_id == investor_id,
                        Holding.security_id == sec.id,
                    )
                    .order_by(Holding.as_of_date.desc())
                    .limit(1)
                )
                snap = (await session.execute(snap_stmt)).scalars().first()

                effective_units = (
                    net_units if net_units > 0 else (snap.units if snap else _ZERO)
                )
                if effective_units <= 0:
                    continue  # fully redeemed / closed position

                results.append(
                    {
                        "security_id": sec.id,
                        "name": sec.name,
                        "isin": sec.isin,
                        "symbol": sec.symbol,
                        "type": sec.security_type,
                        "units": str(effective_units),
                        "source": (
                            "ledger"
                            if net_units > 0
                            else (snap.source if snap else "unknown")
                        ),
                    }
                )

            return results


__all__ = ["LedgerService"]
