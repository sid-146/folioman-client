"""ISIN and Reference Master catalog ingestion, resolution, and search service."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import (
    GrandfatheringNAV,
    ISINReference,
    ReferenceMeta,
    SchemeReference,
)
from folioman_client.errors import FoliomanDatabaseError

logger = logging.getLogger(__name__)

BATCH_SIZE = 20_000


class ISINService:
    """Service for managing the central reference catalog in the active database.

    Ensures zero filesystem leakage: 100% of reference data (schemes, ISINs,
    grandfathering NAVs, and metadata) is ingested into the user's selected database.
    """

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        self.engine = engine or create_folioman_engine()
        self.session_factory = create_sessionmaker(self.engine)

    def _get_source_db_path(self, override_path: Path | None = None) -> Path:
        """Resolve the source SQLite database containing the casparser-isin bundle."""
        if override_path and override_path.is_file():
            return override_path

        try:
            from casparser_isin.utils import get_isin_db_path
            path = get_isin_db_path()
            if path.is_file():
                return path
        except ImportError as exc:
            raise FoliomanDatabaseError(
                "casparser-isin is not installed. Please install it to access reference data."
            ) from exc

        raise FoliomanDatabaseError(f"ISIN reference database file not found at {path}")

    async def get_reference_status(self) -> dict[str, Any]:
        """Return the current population status of the reference catalog."""
        try:
            async with self.session_factory() as session:
                schemes_cnt = (
                    await session.scalar(select(func.count(SchemeReference.id)))
                ) or 0
                isins_cnt = (
                    await session.scalar(select(func.count(ISINReference.id)))
                ) or 0
                gf_cnt = (
                    await session.scalar(select(func.count(GrandfatheringNAV.id)))
                ) or 0

                meta_ver = await session.scalar(
                    select(ReferenceMeta.value).where(ReferenceMeta.key == "version")
                )

                return {
                    "is_seeded": schemes_cnt > 0 and isins_cnt > 0,
                    "schemes_count": schemes_cnt,
                    "isins_count": isins_cnt,
                    "grandfathering_count": gf_cnt,
                    "version": meta_ver,
                }
        except Exception:
            return {
                "is_seeded": False,
                "schemes_count": 0,
                "isins_count": 0,
                "grandfathering_count": 0,
                "version": None,
            }

    async def seed_reference_data(
        self,
        force: bool = False,
        source_path: Path | None = None,
    ) -> dict[str, Any]:
        """Ingest the full reference master data into the target database.

        Args:
            force: If True, purges existing reference tables and re-seeds.
            source_path: Optional explicit path to a casparser-isin SQLite file.

        Returns:
            Dictionary of inserted row counts and version.
        """
        # Ensure schema tables exist
        await init_schema(self.engine)

        # Check existing data unless forced
        if not force:
            status = await self.get_reference_status()
            if status["is_seeded"]:
                logger.info(
                    "Reference catalog already seeded (%d schemes, %d ISINs, v%s).",
                    status["schemes_count"],
                    status["isins_count"],
                    status["version"],
                )
                return {
                    "seeded": False,
                    "schemes_count": status["schemes_count"],
                    "isins_count": status["isins_count"],
                    "grandfathering_count": status["grandfathering_count"],
                    "version": status["version"],
                }

        db_path = self._get_source_db_path(source_path)
        logger.info("Seeding reference catalog from %s", db_path)

        def _read_source_data() -> dict[str, list[dict[str, Any]]]:
            src_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            cur = src_conn.cursor()
            try:
                # 1. Scheme Reference
                cur.execute(
                    "SELECT rta, rta_code, name, isin, amfi_code, type, amc_code, sebi_category FROM scheme"
                )
                schemes = [
                    {
                        "rta": r[0] or "",
                        "rta_code": r[1] or "",
                        "name": r[2] or "",
                        "isin": r[3] or "",
                        "amfi_code": r[4] or "",
                        "type": r[5] or "",
                        "amc_code": r[6] or "",
                        "sebi_category": r[7] or "",
                    }
                    for r in cur.fetchall()
                ]

                # 2. ISIN Reference
                cur.execute("SELECT isin, symbol, name, exchange, type FROM isin")
                isins = [
                    {
                        "isin": r[0],
                        "symbol": r[1] or "",
                        "name": r[2] or "",
                        "exchange": r[3] or "",
                        "type": r[4] or "",
                    }
                    for r in cur.fetchall()
                ]

                # 3. Grandfathering NAVs (31-Jan-2018)
                cur.execute("SELECT isin, nav FROM nav20180131")
                gf_navs = [
                    {"isin": r[0], "nav": Decimal(str(r[1]))}
                    for r in cur.fetchall()
                ]

                # 4. Meta
                cur.execute("SELECT key, value FROM meta")
                meta = [{"key": r[0], "value": str(r[1])} for r in cur.fetchall()]

                return {
                    "schemes": schemes,
                    "isins": isins,
                    "gf_navs": gf_navs,
                    "meta": meta,
                }
            finally:
                src_conn.close()

        # Read source SQLite database in thread pool to avoid blocking async loop
        payload = await asyncio.to_thread(_read_source_data)

        async with self.engine.begin() as conn:
            if force:
                logger.info("Purging existing reference data...")
                await conn.execute(delete(SchemeReference))
                await conn.execute(delete(ISINReference))
                await conn.execute(delete(GrandfatheringNAV))
                await conn.execute(delete(ReferenceMeta))

            # 1. Bulk insert schemes
            if payload["schemes"]:
                for i in range(0, len(payload["schemes"]), BATCH_SIZE):
                    chunk = payload["schemes"][i : i + BATCH_SIZE]
                    await conn.execute(SchemeReference.__table__.insert(), chunk)

            # 2. Bulk insert ISINs
            if payload["isins"]:
                for i in range(0, len(payload["isins"]), BATCH_SIZE):
                    chunk = payload["isins"][i : i + BATCH_SIZE]
                    await conn.execute(ISINReference.__table__.insert(), chunk)

            # 3. Bulk insert Grandfathering NAVs
            if payload["gf_navs"]:
                for i in range(0, len(payload["gf_navs"]), BATCH_SIZE):
                    chunk = payload["gf_navs"][i : i + BATCH_SIZE]
                    await conn.execute(GrandfatheringNAV.__table__.insert(), chunk)

            # 4. Insert Metadata
            if payload["meta"]:
                for item in payload["meta"]:
                    await conn.execute(
                        ReferenceMeta.__table__.insert().values(
                            key=item["key"], value=item["value"]
                        )
                    )

        version = next(
            (m["value"] for m in payload["meta"] if m["key"] == "version"), None
        )
        logger.info(
            "Reference seeding complete: %d schemes, %d ISINs, %d NAVs (v%s)",
            len(payload["schemes"]),
            len(payload["isins"]),
            len(payload["gf_navs"]),
            version,
        )

        return {
            "seeded": True,
            "schemes_count": len(payload["schemes"]),
            "isins_count": len(payload["isins"]),
            "grandfathering_count": len(payload["gf_navs"]),
            "version": version,
        }

    async def update_reference_data(self) -> dict[str, Any]:
        """Check for and apply a newer casparser-isin database, updating the DB catalog."""
        try:
            from casparser_isin.cli import update_isin_db
            # Run the upstream sync which writes to the local writable ISIN file if newer
            await asyncio.to_thread(update_isin_db)
        except Exception as exc:
            logger.warning("Could not check upstream casparser-isin repository: %s", exc)

        # Compare version from SQLite file with the version currently in DB
        db_path = self._get_source_db_path()

        def _get_local_file_version() -> str | None:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                row = conn.execute(
                    "SELECT value FROM meta WHERE key = 'version'"
                ).fetchone()
                return str(row[0]) if row else None
            finally:
                conn.close()

        file_version = await asyncio.to_thread(_get_local_file_version)
        current_status = await self.get_reference_status()
        current_version = current_status.get("version")

        if not current_status["is_seeded"] or (
            file_version and file_version != current_version
        ):
            logger.info(
                "Upgrading database reference catalog from v%s to v%s",
                current_version,
                file_version,
            )
            result = await self.seed_reference_data(force=True)
            return {
                "updated": True,
                "version": file_version,
                "message": f"Updated reference database to version {file_version}",
                **result,
            }

        return {
            "updated": False,
            "version": current_version,
            "message": "Reference database is already up to date.",
        }

    async def resolve_isin(self, isin: str) -> dict[str, Any] | None:
        """Resolve an ISIN against mutual fund schemes and national securities catalogs."""
        norm_isin = isin.strip().upper()
        if not norm_isin:
            return None

        async with self.session_factory() as session:
            # Query equity/debt ISIN reference
            stmt_isin = select(ISINReference).where(ISINReference.isin == norm_isin)
            isin_ref = (await session.execute(stmt_isin)).scalar_one_or_none()

            # Query scheme reference
            stmt_scheme = select(SchemeReference).where(
                SchemeReference.isin == norm_isin
            )
            scheme = (await session.execute(stmt_scheme)).scalars().first()

            # Query grandfathering NAV (31-Jan-2018)
            stmt_nav = select(GrandfatheringNAV.nav).where(
                GrandfatheringNAV.isin == norm_isin
            )
            gf_nav = await session.scalar(stmt_nav)

            if not isin_ref and not scheme:
                return None

            name = scheme.name if scheme else (isin_ref.name if isin_ref else "")
            symbol = isin_ref.symbol if isin_ref else ""
            exchange = isin_ref.exchange if isin_ref else ""
            security_type = "MF" if scheme else (isin_ref.type if isin_ref else "OTHER")

            return {
                "isin": norm_isin,
                "name": name,
                "symbol": symbol,
                "exchange": exchange,
                "security_type": security_type,
                "amfi_code": scheme.amfi_code if scheme else "",
                "rta": scheme.rta if scheme else "",
                "rta_code": scheme.rta_code if scheme else "",
                "amc_code": scheme.amc_code if scheme else "",
                "sebi_category": scheme.sebi_category if scheme else "",
                "type": scheme.type if scheme else (isin_ref.type if isin_ref else ""),
                "grandfathering_nav": gf_nav,
            }

    async def resolve_amfi_code(self, amfi_code: str) -> dict[str, Any] | None:
        """Resolve a mutual fund scheme by its AMFI code."""
        norm_code = amfi_code.strip()
        if not norm_code:
            return None

        async with self.session_factory() as session:
            stmt = select(SchemeReference).where(
                SchemeReference.amfi_code == norm_code
            )
            scheme = (await session.execute(stmt)).scalars().first()
            if not scheme:
                return None

            gf_nav = None
            if scheme.isin:
                stmt_nav = select(GrandfatheringNAV.nav).where(
                    GrandfatheringNAV.isin == scheme.isin
                )
                gf_nav = await session.scalar(stmt_nav)

            return {
                "id": scheme.id,
                "amfi_code": scheme.amfi_code,
                "isin": scheme.isin,
                "name": scheme.name,
                "rta": scheme.rta,
                "rta_code": scheme.rta_code,
                "amc_code": scheme.amc_code,
                "sebi_category": scheme.sebi_category,
                "type": scheme.type,
                "grandfathering_nav": gf_nav,
            }

    async def search_schemes(
        self, query: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search mutual fund schemes by text name, AMFI code, or ISIN."""
        norm = query.strip()
        if not norm:
            return []

        async with self.session_factory() as session:
            filters = [
                SchemeReference.name.ilike(f"%{norm}%"),
                SchemeReference.amfi_code == norm,
                SchemeReference.isin == norm.upper(),
            ]
            stmt = select(SchemeReference).where(or_(*filters)).limit(limit)
            result = await session.execute(stmt)
            schemes = result.scalars().all()

            return [
                {
                    "id": s.id,
                    "amfi_code": s.amfi_code,
                    "isin": s.isin,
                    "name": s.name,
                    "rta": s.rta,
                    "rta_code": s.rta_code,
                    "amc_code": s.amc_code,
                    "sebi_category": s.sebi_category,
                    "type": s.type,
                }
                for s in schemes
            ]

    async def get_grandfathering_nav(self, isin: str) -> Decimal | None:
        """Lookup the Section 112A LTCG fair market value on 31-Jan-2018."""
        norm_isin = isin.strip().upper()
        if not norm_isin:
            return None

        async with self.session_factory() as session:
            stmt = select(GrandfatheringNAV.nav).where(
                GrandfatheringNAV.isin == norm_isin
            )
            return await session.scalar(stmt)


__all__ = ["ISINService", "BATCH_SIZE"]
