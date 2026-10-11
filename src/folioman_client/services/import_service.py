"""CAS statement import service: parses CAMS/KFintech MF CAS and NSDL/CDSL eCAS PDFs

Persists immutable transactions, creates holding snapshots for incomplete history,
deduplicates identical lines, and isolates malformed blocks into quarantines.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from folioman_client.core.cas_reader import ParsedCas, read_cas
from folioman_client.core.models.cas import (
    MfCasLineItem,
)
from folioman_client.core.models.investor import normalize_folio_number
from folioman_client.core.parser import (
    _HISTORY_TOLERANCE,
    CASParseError,
    CASPasswordError,
    scheme_history_gap,
)
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    AMC,
    Folio,
    Holding,
    ImportJob,
    ImportQuarantine,
    Investor,
    PartialBlock,
    Security,
    Transaction,
)
from folioman_client.errors import (
    FoliomanParseError,
    FoliomanPasswordError,
)
from folioman_client.security.pan import encrypt_pan, pan_hash
from folioman_client.services.reconciliation_service import ReconciliationService

logger = logging.getLogger(__name__)

_ZERO = Decimal("0")


def _canon_decimal(value: Decimal | None) -> str:
    """Canonical fixed-point string for a Decimal to ensure stable dedup hashing."""
    if value is None:
        return ""
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _dedup_key(security_identity: str, folio_number: str, line: MfCasLineItem) -> str:
    """Generate a deterministic content hash for transaction deduplication."""
    parts = [
        security_identity,
        folio_number,
        line.date.isoformat(),
        line.transaction_type.value,
        _canon_decimal(line.units),
        _canon_decimal(line.nav),
        _canon_decimal(line.amount),
        _canon_decimal(line.balance),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


class CASImportService:
    """High-level service for importing and reconciling CAS statements."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = create_sessionmaker(self.engine)
        self._reconcile_service = ReconciliationService(engine=self.engine)

    async def _resolve_or_create_investor(
        self,
        session: AsyncSession,
        *,
        user_id: str,
        investor_id: int | None,
        pan: str,
        name: str,
        email: str,
    ) -> Investor:
        """Find an existing investor by ID or PAN hash, or create a new investor record."""
        if investor_id is not None:
            investor = await session.get(Investor, investor_id)
            if investor:
                return investor

        norm_pan = pan.strip().upper()
        if norm_pan:
            p_hash = pan_hash(norm_pan)
            stmt = select(Investor).where(
                Investor.user_id == user_id,
                Investor.pan_hash == p_hash,
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                return existing

            # Create new investor with encrypted PAN and HMAC hash
            investor = Investor(
                user_id=user_id,
                name=name or "Investor",
                email=email or "",
                pan_encrypted=encrypt_pan(norm_pan),
                pan_hash=p_hash,
            )
            session.add(investor)
            await session.flush()
            return investor

        # Statement has no PAN — fallback to finding by user_id and name
        stmt = select(Investor).where(
            Investor.user_id == user_id,
            Investor.name == (name or "Investor"),
        )
        existing = (await session.execute(stmt)).scalar_one_or_none()
        if existing:
            return existing

        investor = Investor(
            user_id=user_id,
            name=name or "Investor",
            email=email or "",
        )
        session.add(investor)
        await session.flush()
        return investor

    async def _upsert_amc(
        self, session: AsyncSession, name: str, code: str = ""
    ) -> AMC | None:
        if not name and not code:
            return None
        search_name = name or code
        stmt = select(AMC).where(AMC.name == search_name)
        amc = (await session.execute(stmt)).scalar_one_or_none()
        if amc is None:
            amc = AMC(name=search_name, code=code)
            session.add(amc)
            await session.flush()
        elif code and not amc.code:
            amc.code = code
        return amc

    async def _upsert_security(
        self, session: AsyncSession, core_sec, amc_id: int | None = None
    ) -> Security:
        """Find or create a Security row matching by AMFI code, ISIN, or symbol."""
        existing: Security | None = None
        if core_sec.amfi_code:
            stmt = select(Security).where(Security.amfi_code == core_sec.amfi_code)
            existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is None and core_sec.isin:
            stmt = select(Security).where(Security.isin == core_sec.isin)
            existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is None and core_sec.symbol:
            stmt = select(Security).where(
                Security.symbol == core_sec.symbol,
                Security.security_type == core_sec.type.value.upper(),
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()

        if existing is None:
            sec_type = (
                "MF"
                if core_sec.type.value.lower() == "mf"
                else core_sec.type.value.upper()
            )
            existing = Security(
                security_type=sec_type,
                name=core_sec.name,
                isin=core_sec.isin or "",
                symbol=core_sec.symbol or "",
                exchange=core_sec.exchange or "",
                currency=core_sec.currency or "INR",
                amfi_code=core_sec.amfi_code or "",
                metadata_json=dict(core_sec.metadata or {}),
                amc_id=amc_id,
            )
            session.add(existing)
            await session.flush()
            return existing

        # Update missing attributes if discovered in this statement
        if core_sec.amfi_code and not existing.amfi_code:
            existing.amfi_code = core_sec.amfi_code
        if core_sec.isin and not existing.isin:
            existing.isin = core_sec.isin
        if core_sec.name and not existing.name:
            existing.name = core_sec.name
        if amc_id and not existing.amc_id:
            existing.amc_id = amc_id
        if core_sec.metadata:
            existing.metadata_json = {
                **(existing.metadata_json or {}),
                **core_sec.metadata,
            }

        return existing

    async def _upsert_folio(
        self,
        session: AsyncSession,
        investor_id: int,
        core_folio,
    ) -> Folio:
        """Find or create a Folio row using canonical normalized numbering."""
        norm_number = normalize_folio_number(core_folio.number)
        stmt = select(Folio).where(
            Folio.investor_id == investor_id,
            Folio.number == norm_number,
            Folio.amc_code == (core_folio.amc_code or ""),
        )
        folio = (await session.execute(stmt)).scalar_one_or_none()
        if folio is None:
            folio = Folio(
                investor_id=investor_id,
                number=norm_number,
                amc_code=core_folio.amc_code or "",
                folio_type=core_folio.folio_type.value,
                broker=core_folio.broker or "",
                pan_kyc=core_folio.pan_kyc,
            )
            session.add(folio)
            await session.flush()
        return folio

    async def _prior_ledger_balance(
        self,
        session: AsyncSession,
        investor_id: int,
        security_id: int,
        folio_id: int,
        before_date: date | None,
    ) -> Decimal:
        """Calculate net units already on the ledger for (security, folio) before before_date."""
        if before_date is None:
            return _ZERO

        from sqlalchemy import case

        stmt = select(
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
                            Transaction.transaction_type.in_(["SELL", "TRANSFER_OUT"]),
                            -Transaction.units,
                        ),
                        else_=_ZERO,
                    )
                ),
                _ZERO,
            )
        ).where(
            Transaction.investor_id == investor_id,
            Transaction.security_id == security_id,
            Transaction.folio_id == folio_id,
            Transaction.cost_basis_complete.is_(True),
            Transaction.date < before_date,
        )
        val = await session.scalar(stmt)
        return Decimal(str(val or 0))

    async def _upgrade_chained_partials(
        self, session: AsyncSession, investor_id: int
    ) -> set[int]:
        """Upgrade previously incomplete partial blocks if prior statements completed the chain."""
        from sqlalchemy import case

        affected: set[int] = set()
        while True:
            progressed = False
            stmt = select(PartialBlock).where(PartialBlock.investor_id == investor_id)
            blocks = (await session.execute(stmt)).scalars().all()
            for pb in blocks:
                # Check if ledger reaches opening units
                prior = await self._prior_ledger_balance(
                    session, investor_id, pb.security_id, pb.folio_id, pb.statement_from
                )
                if abs(prior - pb.opening_units) <= _HISTORY_TOLERANCE:
                    # Calculate net units from incomplete rows
                    stmt_net = select(
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
                        Transaction.security_id == pb.security_id,
                        Transaction.folio_id == pb.folio_id,
                        Transaction.cost_basis_complete.is_(False),
                    )
                    net = Decimal(str(await session.scalar(stmt_net) or 0))

                    if (
                        pb.closing_units is not None
                        and abs(pb.opening_units + net - pb.closing_units)
                        <= _HISTORY_TOLERANCE
                    ):
                        # Upgrade rows to complete cost basis
                        await session.execute(
                            update(Transaction)
                            .where(
                                Transaction.investor_id == investor_id,
                                Transaction.security_id == pb.security_id,
                                Transaction.folio_id == pb.folio_id,
                                Transaction.cost_basis_complete.is_(False),
                            )
                            .values(cost_basis_complete=True)
                        )
                        # Remove holding snapshot and partial block
                        await session.execute(
                            delete(Holding).where(
                                Holding.investor_id == investor_id,
                                Holding.security_id == pb.security_id,
                                Holding.folio_id == pb.folio_id,
                                Holding.source == "cas_pdf",
                            )
                        )
                        await session.delete(pb)
                        affected.add(pb.security_id)
                        progressed = True
            if not progressed:
                return affected

    async def import_cas(
        self,
        file_path_or_bytes: str | Path | bytes | io.IOBase,
        password: str,
        *,
        user_id: str = "default",
        investor_id: int | None = None,
        source_ref: str = "",
    ) -> dict[str, Any]:
        """Import a CAMS/KFintech MF CAS or NSDL/CDSL eCAS PDF into the database.

        Args:
            file_path_or_bytes: Path to PDF file or in-memory byte buffer.
            password: PDF opening password (case-sensitive).
            user_id: Multi-tenant user or portfolio identifier.
            investor_id: Optional existing investor ID to assign statements to.
            source_ref: Optional source tracking reference string.

        Returns:
            Dictionary summary of imported entities, transactions, and quarantines.
        """
        await init_schema(self.engine)

        # 1. Read and parse CAS PDF
        filename = ""
        if isinstance(file_path_or_bytes, (str, Path)):
            p = Path(file_path_or_bytes)
            filename = p.name
            if not p.is_file():
                raise FoliomanParseError(f"CAS file not found: {file_path_or_bytes}")
            content = p.read_bytes()
        elif isinstance(file_path_or_bytes, bytes):
            content = file_path_or_bytes
            filename = "upload.pdf"
        elif hasattr(file_path_or_bytes, "read"):
            content = file_path_or_bytes.read()
            filename = getattr(file_path_or_bytes, "name", "upload.pdf")
        else:
            raise FoliomanParseError("Invalid file input for CAS import.")

        calc_ref = source_ref or f"sha256:{hashlib.sha256(content).hexdigest()}"

        try:
            parsed: ParsedCas = read_cas(io.BytesIO(content), password)
        except CASPasswordError as exc:
            raise FoliomanPasswordError(str(exc)) from exc
        except CASParseError as exc:
            raise FoliomanParseError(str(exc)) from exc

        summary: dict[str, Any] = {
            "file": filename,
            "is_ecas": parsed.is_ecas,
            "schemes": 0,
            "transactions_created": 0,
            "transactions_skipped": 0,
            "partial_transactions": 0,
            "holdings_snapshotted": 0,
            "quarantined": [],
            "incomplete_history": [],
        }

        async with self.session_factory() as session:
            # 2. Resolve Investor
            investor = await self._resolve_or_create_investor(
                session,
                user_id=user_id,
                investor_id=investor_id,
                pan=parsed.investor.pan,
                name=parsed.investor.name,
                email=parsed.investor.email,
            )

            # 3. Create ImportJob record
            job = ImportJob(
                investor_id=investor.id,
                kind="ecas" if parsed.is_ecas else "cas_pdf",
                status="running",
                filename=filename,
                source_ref=calc_ref,
                result_json={},
                started_at=datetime.now(timezone.utc),
            )
            session.add(job)
            await session.flush()

            affected_security_ids: set[int] = set()

            # 4. Process Mutual Fund CAS Statement
            if parsed.mf:
                for block in parsed.mf.schemes:
                    try:
                        async with session.begin_nested():
                            amc_name = (block.security.metadata or {}).get(
                                "amc"
                            ) or block.folio.amc_code
                            amc = await self._upsert_amc(
                                session, amc_name, block.folio.amc_code
                            )
                            security = await self._upsert_security(
                                session, block.security, amc.id if amc else None
                            )
                            affected_security_ids.add(security.id)
                            folio = await self._upsert_folio(
                                session, investor.id, block.folio
                            )

                            # Check history gap
                            prior_balance = await self._prior_ledger_balance(
                                session,
                                investor.id,
                                security.id,
                                folio.id,
                                parsed.mf.statement_from,
                            )
                            gap = scheme_history_gap(block, prior_balance=prior_balance)
                            is_complete = gap is None

                            sec_ident = (
                                security.amfi_code
                                or security.isin
                                or security.symbol
                                or str(security.id)
                            )
                            for line in block.transactions:
                                key = _dedup_key(sec_ident, folio.number, line)
                                # Check duplicate
                                stmt_dup = select(Transaction.id).where(
                                    Transaction.investor_id == investor.id,
                                    Transaction.dedup_key == key,
                                )
                                dup = (
                                    await session.execute(stmt_dup)
                                ).scalar_one_or_none()
                                if dup is not None:
                                    summary["transactions_skipped"] += 1
                                    continue

                                txn = Transaction(
                                    investor_id=investor.id,
                                    security_id=security.id,
                                    folio_id=folio.id,
                                    date=line.date,
                                    transaction_type=line.transaction_type.value.upper(),
                                    units=line.units,
                                    nav_or_price=line.nav,
                                    amount=line.amount,
                                    fees=line.fees,
                                    stamp_duty=line.stamp_duty,
                                    source="cas_pdf",
                                    source_ref=calc_ref,
                                    narration=line.description,
                                    dedup_key=key,
                                    cost_basis_complete=is_complete,
                                )
                                session.add(txn)
                                if is_complete:
                                    summary["transactions_created"] += 1
                                else:
                                    summary["partial_transactions"] += 1

                            if not is_complete:
                                # Record partial block and holding snapshot
                                stmt_pb = select(PartialBlock).where(
                                    PartialBlock.investor_id == investor.id,
                                    PartialBlock.security_id == security.id,
                                    PartialBlock.folio_id == folio.id,
                                )
                                pb = (
                                    await session.execute(stmt_pb)
                                ).scalar_one_or_none()
                                if pb is None:
                                    pb = PartialBlock(
                                        investor_id=investor.id,
                                        security_id=security.id,
                                        folio_id=folio.id,
                                        opening_units=block.opening_units or _ZERO,
                                        closing_units=block.closing_units,
                                        statement_from=parsed.mf.statement_from,
                                    )
                                    session.add(pb)
                                else:
                                    pb.opening_units = block.opening_units or _ZERO
                                    pb.closing_units = block.closing_units
                                    pb.statement_from = parsed.mf.statement_from

                                as_of = parsed.mf.statement_to or max(
                                    (
                                        transaction.date
                                        for transaction in block.transactions
                                    ),
                                    default=None,
                                )
                                if (
                                    block.closing_units is not None
                                    and as_of is not None
                                ):
                                    stmt_h = select(Holding).where(
                                        Holding.investor_id == investor.id,
                                        Holding.security_id == security.id,
                                        Holding.folio_id == folio.id,
                                        Holding.as_of_date == as_of,
                                    )
                                    h = (
                                        await session.execute(stmt_h)
                                    ).scalar_one_or_none()
                                    if h is None:
                                        h = Holding(
                                            investor_id=investor.id,
                                            security_id=security.id,
                                            folio_id=folio.id,
                                            as_of_date=as_of,
                                            units=block.closing_units,
                                            source="cas_pdf",
                                            source_ref=calc_ref,
                                        )
                                        session.add(h)
                                    else:
                                        h.units = block.closing_units
                                    summary["holdings_snapshotted"] += 1

                                summary["incomplete_history"].append(
                                    {
                                        "security": security.name,
                                        "folio": folio.number,
                                        "reason": gap,
                                        "opening_units": (
                                            str(block.opening_units)
                                            if block.opening_units is not None
                                            else None
                                        ),
                                        "closing_units": (
                                            str(block.closing_units)
                                            if block.closing_units is not None
                                            else None
                                        ),
                                    }
                                )

                        summary["schemes"] += 1

                    except Exception as exc:
                        logger.warning(
                            "Quarantining scheme block %s (%s): %s",
                            getattr(block.security, "name", ""),
                            getattr(block.folio, "number", ""),
                            exc,
                        )
                        q_entry = {
                            "security": getattr(block.security, "name", "") or "",
                            "isin": getattr(block.security, "isin", "") or "",
                            "folio": normalize_folio_number(
                                getattr(block.folio, "number", "")
                            ),
                            "reason": str(exc),
                        }
                        summary["quarantined"].append(q_entry)
                        quarantine_row = ImportQuarantine(
                            import_job_id=job.id,
                            investor_id=investor.id,
                            kind="cas_pdf",
                            security_name=q_entry["security"],
                            isin=q_entry["isin"],
                            folio_number=q_entry["folio"],
                            reason=q_entry["reason"],
                            raw_json={
                                "opening_units": (
                                    str(block.opening_units)
                                    if block.opening_units is not None
                                    else None
                                ),
                                "closing_units": (
                                    str(block.closing_units)
                                    if block.closing_units is not None
                                    else None
                                ),
                                "transactions": len(block.transactions),
                            },
                        )
                        session.add(quarantine_row)

                # Upgrade any older partial blocks chained by this statement
                upgraded = await self._upgrade_chained_partials(session, investor.id)
                affected_security_ids.update(upgraded)

            # 5. Process eCAS Statement (NSDL / CDSL)
            elif parsed.ecas:
                for account in parsed.ecas.accounts:
                    folio = await self._upsert_folio(
                        session, investor.id, account.folio
                    )
                    for line in account.holdings:
                        try:
                            async with session.begin_nested():
                                security = await self._upsert_security(
                                    session, line.security
                                )
                                affected_security_ids.add(security.id)
                                stmt_h = select(Holding).where(
                                    Holding.investor_id == investor.id,
                                    Holding.security_id == security.id,
                                    Holding.folio_id == folio.id,
                                    Holding.as_of_date == parsed.ecas.statement_date,
                                )
                                h = (await session.execute(stmt_h)).scalar_one_or_none()
                                if h is None:
                                    h = Holding(
                                        investor_id=investor.id,
                                        security_id=security.id,
                                        folio_id=folio.id,
                                        as_of_date=parsed.ecas.statement_date,
                                        units=line.units,
                                        value_observed=line.value_observed,
                                        avg_cost_observed=line.avg_cost_observed,
                                        source="ecas",
                                        source_ref=calc_ref,
                                    )
                                    session.add(h)
                                else:
                                    h.units = line.units
                                    h.value_observed = line.value_observed
                                    h.avg_cost_observed = line.avg_cost_observed
                                summary["holdings_snapshotted"] += 1
                        except Exception as exc:
                            logger.warning(
                                "Quarantining eCAS holding %s: %s",
                                line.security.name,
                                exc,
                            )
                            q_entry = {
                                "security": line.security.name,
                                "isin": line.security.isin,
                                "folio": folio.number,
                                "reason": str(exc),
                            }
                            summary["quarantined"].append(q_entry)
                            quarantine_row = ImportQuarantine(
                                import_job_id=job.id,
                                investor_id=investor.id,
                                kind="ecas",
                                security_name=q_entry["security"],
                                isin=q_entry["isin"],
                                folio_number=q_entry["folio"],
                                reason=q_entry["reason"],
                                raw_json={
                                    "units": str(line.units),
                                    "value_observed": str(line.value_observed),
                                },
                            )
                            session.add(quarantine_row)

            # 5b. Auto-reconcile affected securities
            for sec_id in affected_security_ids:
                try:
                    await self._reconcile_service.reconcile_security(
                        session, investor.id, sec_id
                    )
                except Exception as exc:
                    logger.warning(
                        "Auto-reconcile for security %s failed: %s", sec_id, exc
                    )

            # 6. Finalize ImportJob
            final_status = (
                "partially_reconciled"
                if summary["quarantined"] or summary["incomplete_history"]
                else "completed"
            )
            job.status = final_status
            job.result_json = summary
            job.finished_at = datetime.now(timezone.utc)
            await session.commit()

            summary["job_id"] = job.id
            summary["investor_id"] = investor.id
            summary["investor_name"] = investor.name
            summary["pan_masked"] = investor.pan_masked
            summary["status"] = final_status
            return summary


__all__ = ["CASImportService", "_canon_decimal", "_dedup_key"]
