"""NAV and price feed management service.

Handles JIT and scheduled NAV refreshes, historical price backfilling,
gap filling, and freshness tracking across asset types (mutual funds,
equities, ETFs, bonds, foreign equities, crypto).
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from folioman_client.core.models.security import SecurityType
from folioman_client.core.price_feeds import (
    amfi_bulk,
    captnemo,
    coingecko,
    mfapi,
    nse_bhavcopy,
    nse_history,
    yfinance_feed,
)
from folioman_client.core.price_feeds.errors import NAVFetchError, PriceFetchError
from folioman_client.core.trading_calendar import (
    completed_trading_day,
    last_trading_day,
    trading_days_between,
)
from folioman_client.db.engine import create_folioman_engine, create_sessionmaker
from folioman_client.db.migrations import init_schema
from folioman_client.db.models import Holding, NAVHistory, Security, Transaction

logger = logging.getLogger(__name__)

_QUOTE_TYPES = {
    SecurityType.EQUITY.value,
    SecurityType.ETF.value,
    SecurityType.BOND.value,
    SecurityType.FOREIGN_EQUITY.value,
}

REVALUE_HOURS: tuple[int, ...] = (4, 10, 16, 22)
_BACKFILL_TAIL_GRACE = timedelta(days=7)
_QUOTE_LOOKBACK_DAYS = 10
_BHAVCOPY_LOOKBACK = 5
_NSE_CHUNK_DAYS = 365
_MF_BULK_MAX_LAG = 14


def _feed_code(security: Security) -> str:
    """The identifier the refresh would query for this security, or empty string."""
    stype = security.security_type
    if stype == SecurityType.MF.value:
        return security.amfi_code or security.isin
    if stype in _QUOTE_TYPES:
        return security.symbol
    if stype == SecurityType.CRYPTO.value:
        return (security.metadata_json or {}).get("coin_id") or ""
    return ""


def _classify(security: Security, latest: date | None, lag: int | None) -> str:
    """Classify the freshness status of a security."""
    if security.nav_feed_closed:
        return "closed"
    if not _feed_code(security):
        return "no_feed"
    if latest is None:
        return "pending"
    if lag is None or lag <= 0:
        return "fresh"
    if lag == 1:
        return "grace"
    return "stale"


def next_scheduled_refresh(now: datetime | None = None) -> datetime:
    """The next scheduled NAV re-fetch local time."""
    if now is None:
        now = datetime.now()
    for hour in sorted(REVALUE_HOURS):
        if now.hour < hour:
            return now.replace(hour=hour, minute=0, second=0, microsecond=0)
    tomorrow = now.date() + timedelta(days=1)
    first = sorted(REVALUE_HOURS)[0]
    return datetime.combine(tomorrow, time(hour=first))


class _FeedClients:
    """Lazily-created pooled HTTP clients for a batch run."""

    def __init__(self) -> None:
        self._mfapi = None
        self._captnemo = None
        self._nse = None
        self._yahoo = None
        self._amfi = None

    @property
    def amfi(self):
        if self._amfi is None:
            self._amfi = amfi_bulk.shared_client()
        return self._amfi

    @property
    def mfapi(self):
        if self._mfapi is None:
            self._mfapi = mfapi.shared_client()
        return self._mfapi

    @property
    def captnemo(self):
        if self._captnemo is None:
            self._captnemo = captnemo.shared_client()
        return self._captnemo

    @property
    def nse(self):
        if self._nse is None:
            self._nse = nse_history.warmed_client()
        return self._nse

    @property
    def yahoo(self):
        if self._yahoo is None:
            self._yahoo = yfinance_feed.shared_client()
        return self._yahoo

    def close(self) -> None:
        for client in (self._mfapi, self._captnemo, self._nse, self._yahoo, self._amfi):
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass


def _fetch_mf_latest(
    security: Security, clients: _FeedClients
) -> tuple[date, Decimal, str] | None:
    """Fetch latest MF NAV: mfapi (amfi_code) primary, captnemo (isin) fallback."""
    if security.amfi_code:
        try:
            point = mfapi.fetch_latest_nav(security.amfi_code, client=clients.mfapi)
            if point:
                return (point.date, point.nav, "mfapi")
        except NAVFetchError as exc:
            if not security.isin:
                raise
            logger.debug(
                "mfapi latest failed for security %s (%s); trying captnemo: %s",
                security.id,
                security.name,
                exc,
            )
    if security.isin:
        point = captnemo.fetch_latest_nav(security.isin, client=clients.captnemo)
        if point:
            return (point.date, point.nav, "captnemo")
    return None


def _fetch_equity_latest(
    security: Security, clients: _FeedClients
) -> tuple[date, Decimal, str] | None:
    """Fetch latest equity close: NSE-first for Indian symbols, Yahoo fallback."""
    stype = security.security_type
    if stype != SecurityType.FOREIGN_EQUITY.value and security.exchange in ("", "NSE"):
        since = last_trading_day(date.today()) - timedelta(days=_QUOTE_LOOKBACK_DAYS)
        try:
            history = nse_history.fetch_history(
                security.symbol, start=since, client=clients.nse
            )
            if history is not None and history.points:
                latest = history.points[-1]
                return (latest.date, latest.nav, "nse")
        except PriceFetchError:
            pass
    quote = yfinance_feed.fetch_quote(
        security.symbol, exchange=security.exchange, client=clients.yahoo
    )
    return (quote.as_of, quote.price, quote.source) if quote else None


def _fetch_point(
    security: Security, clients: _FeedClients
) -> tuple[date, Decimal, str] | None:
    """Return (date, nav, source) for the latest price, or None if unavailable."""
    stype = security.security_type
    if stype == SecurityType.MF.value:
        return _fetch_mf_latest(security, clients)
    if stype in _QUOTE_TYPES and security.symbol:
        return _fetch_equity_latest(security, clients)
    if stype == SecurityType.CRYPTO.value:
        coin_id = (security.metadata_json or {}).get("coin_id")
        if coin_id:
            quote = coingecko.fetch_quote(coin_id)
            return (quote.as_of, quote.price, quote.source) if quote else None
    return None


def _prime_bulk(
    clients: _FeedClients,
) -> tuple[dict[str, tuple[date, Decimal, str]], dict[str, tuple[date, Decimal, str]]]:
    """Fetch whole-market snapshots once: AMFI NAVAll + NSE bhavcopy."""
    mf_map: dict[str, tuple[date, Decimal, str]] = {}
    eq_map: dict[str, tuple[date, Decimal, str]] = {}
    try:
        mf_map = {
            key: (p.date, p.nav, "amfi")
            for key, p in amfi_bulk.fetch_all_latest(client=clients.amfi).items()
        }
    except NAVFetchError as exc:
        logger.warning("AMFI bulk NAV unavailable — falling back per-scheme: %s", exc)

    try:
        bhav = nse_bhavcopy.warmed_client()
        try:
            day = completed_trading_day(date.today())
            for _ in range(_BHAVCOPY_LOOKBACK):
                closes = nse_bhavcopy.fetch_close_by_symbol(day, client=bhav)
                if closes:
                    eq_map = {
                        sym: (p.date, p.nav, "nse-bhavcopy")
                        for sym, p in closes.items()
                    }
                    break
                day = last_trading_day(day - timedelta(days=1))
        finally:
            bhav.close()
    except Exception as exc:
        logger.warning("NSE bhavcopy unavailable — falling back per-symbol: %s", exc)

    return mf_map, eq_map


def _bulk_point(
    security: Security, mf_map: dict, eq_map: dict
) -> tuple[date, Decimal, str] | None:
    """Lookup latest price in pre-fetched bulk maps."""
    stype = security.security_type
    if stype == SecurityType.MF.value:
        for key in (security.amfi_code, security.isin):
            if key and key in mf_map:
                return mf_map[key]
    elif (
        stype in _QUOTE_TYPES
        and stype != SecurityType.FOREIGN_EQUITY.value
        and security.symbol
        and security.exchange in ("", "NSE")
    ):
        return eq_map.get(security.symbol.upper())
    return None


def _fetch_mf_history(
    security: Security, *, since: date | None, mfapi_client, captnemo_client
):
    """Full MF history: captnemo (ISIN) primary, mfapi (AMFI) fallback."""
    if security.isin:
        try:
            history = captnemo.fetch_nav_history(
                security.isin, since=since, client=captnemo_client
            )
            return history, "captnemo"
        except NAVFetchError as exc:
            if not security.amfi_code:
                raise
            logger.debug(
                "captnemo backfill failed for %s (%s); trying mfapi: %s",
                security.id,
                security.name,
                exc,
            )
    if security.amfi_code:
        history = mfapi.fetch_nav_history(
            security.amfi_code, since=since, client=mfapi_client
        )
        return history, "mfapi"
    return None


def _fetch_equity_history(
    security: Security, *, since: date | None, nse_client, yahoo_client
):
    """Full equity history: NSE security-wise primary, Yahoo fallback."""
    if security.exchange in ("", "NSE"):
        try:
            history = nse_history.fetch_history(
                security.symbol, start=since, client=nse_client
            )
            if history is not None and history.points:
                return history, "nse"
        except PriceFetchError:
            pass
    return (
        yfinance_feed.fetch_history(
            security.symbol,
            exchange=security.exchange,
            start=since,
            client=yahoo_client,
        ),
        "yfinance",
    )


class NAVService:
    """Async service for refreshing, backfilling, and monitoring NAV data."""

    def __init__(
        self,
        engine: AsyncEngine | None = None,
        database_url: str | None = None,
        request_spacing: float = 0.05,
    ) -> None:
        self.engine = engine or create_folioman_engine(database_url)
        self.session_factory = create_sessionmaker(self.engine)
        self.request_spacing = request_spacing

    async def _span_start(
        self, session: AsyncSession, security: Security
    ) -> date | None:
        """Earliest date transactions or holdings require pricing back to."""
        stmt_txn = select(func.min(Transaction.date)).where(
            Transaction.security_id == security.id
        )
        txn_first = (await session.execute(stmt_txn)).scalar_one_or_none()
        stmt_hold = select(func.min(Holding.as_of_date)).where(
            Holding.security_id == security.id
        )
        hold_first = (await session.execute(stmt_hold)).scalar_one_or_none()
        dates = [d for d in (txn_first, hold_first) if d is not None]
        return min(dates) if dates else None

    async def _tail_candidate(
        self, session: AsyncSession, security: Security, cutoff: date
    ) -> tuple[date, date | None, bool] | None:
        """Candidate info for extending the series head, or None if current."""
        stmt = select(func.min(NAVHistory.date), func.max(NAVHistory.date)).where(
            NAVHistory.security_id == security.id
        )
        res = (await session.execute(stmt)).first()
        earliest, latest = (res[0], res[1]) if res else (None, None)

        if latest is not None:
            if latest >= cutoff:
                return None
            since = await self._span_start(session, security)
            reaches_back = since is None or (
                earliest is not None and earliest <= since + _BACKFILL_TAIL_GRACE
            )
            return latest + timedelta(days=1), latest, reaches_back

        since = await self._span_start(session, security)
        if since is None:
            return None
        return since, None, True

    async def refresh_navs(
        self,
        *,
        types: list[str] | None = None,
        securities: list[Security] | None = None,
    ) -> dict[str, int]:
        """Fetch and store the latest NAV / price point for held securities."""
        await init_schema(self.engine)
        summary = {"updated": 0, "skipped": 0, "errors": 0}
        clients = _FeedClients()
        live_fetched = False

        async with self.session_factory() as session:
            try:
                if securities is not None:
                    target_securities = securities
                else:
                    stmt = select(Security)
                    if types:
                        valid_types = [t.lower().strip() for t in types]
                        stmt = stmt.where(Security.security_type.in_(valid_types))
                    res = await session.execute(stmt)
                    target_securities = list(res.scalars().all())

                if not target_securities:
                    return summary

                # Fetch bulk snapshots in background thread
                mf_map, eq_map = await asyncio.to_thread(_prime_bulk, clients)

                for security in target_securities:
                    point = _bulk_point(security, mf_map, eq_map)
                    if point is None:
                        if live_fetched and self.request_spacing > 0:
                            await asyncio.sleep(self.request_spacing)
                        live_fetched = True
                        try:
                            point = await asyncio.to_thread(
                                _fetch_point, security, clients
                            )
                        except (NAVFetchError, PriceFetchError) as exc:
                            logger.warning(
                                "NAV refresh failed for security %s (%s): %s",
                                security.id,
                                security.name,
                                exc,
                            )
                            summary["errors"] += 1
                            continue

                    if point is None:
                        summary["skipped"] += 1
                        continue

                    on_date, nav_val, source = point
                    # Upsert into nav_history
                    stmt = select(NAVHistory).where(
                        NAVHistory.security_id == security.id,
                        NAVHistory.date == on_date,
                    )
                    existing = (await session.execute(stmt)).scalar_one_or_none()
                    if existing:
                        existing.nav = nav_val
                        existing.source = source
                    else:
                        new_nav = NAVHistory(
                            security_id=security.id,
                            date=on_date,
                            nav=nav_val,
                            source=source,
                        )
                        session.add(new_nav)

                    summary["updated"] += 1

                    if security.nav_feed_closed:
                        logger.info(
                            "Security %s (%s): feed reopened",
                            security.id,
                            security.name,
                        )
                        security.nav_feed_closed = False

                await session.commit()
            finally:
                clients.close()

        return summary

    async def backfill_navs(
        self,
        *,
        security_id: int | None = None,
        force: bool = False,
    ) -> dict[str, int]:
        """Backfill historical prices for securities."""
        await init_schema(self.engine)
        summary = {"securities": 0, "points": 0, "errors": 0, "skipped": 0, "closed": 0}
        cutoff = completed_trading_day(date.today())
        clients = _FeedClients()

        async with self.session_factory() as session:
            try:
                if security_id is not None:
                    stmt = select(Security).where(Security.id == security_id)
                    res = await session.execute(stmt)
                    securities = list(res.scalars().all())
                else:
                    types = [SecurityType.MF.value, *_QUOTE_TYPES]
                    stmt = select(Security).where(Security.security_type.in_(types))
                    res = await session.execute(stmt)
                    securities = list(res.scalars().all())

                if not securities:
                    return summary

                for security in securities:
                    if force:
                        start_date = await self._span_start(session, security)
                        if start_date is None and security_id is not None:
                            start_date = date(2000, 1, 1)
                        latest = None
                    else:
                        cand = await self._tail_candidate(session, security, cutoff)
                        if cand is None:
                            summary["skipped"] += 1
                            continue
                        start_date, latest, _ = cand

                    if start_date is None:
                        summary["skipped"] += 1
                        continue

                    # Fetch history
                    history = None
                    source = ""
                    try:
                        if security.security_type == SecurityType.MF.value:
                            fetched = await asyncio.to_thread(
                                _fetch_mf_history,
                                security,
                                since=start_date,
                                mfapi_client=clients.mfapi,
                                captnemo_client=clients.captnemo,
                            )
                            if fetched:
                                history, source = fetched
                        elif security.security_type in _QUOTE_TYPES:
                            if security.symbol:
                                fetched = await asyncio.to_thread(
                                    _fetch_equity_history,
                                    security,
                                    since=start_date,
                                    nse_client=clients.nse,
                                    yahoo_client=clients.yahoo,
                                )
                                if fetched:
                                    history, source = fetched
                    except (NAVFetchError, PriceFetchError) as exc:
                        logger.warning(
                            "Backfill failed for security %s (%s) since=%s: %s",
                            security.id,
                            security.name,
                            start_date,
                            exc,
                        )
                        summary["errors"] += 1
                        continue

                    if history and history.points:
                        # Find existing points
                        stmt_existing = select(NAVHistory.date).where(
                            NAVHistory.security_id == security.id
                        )
                        existing_dates = set(
                            (await session.execute(stmt_existing)).scalars().all()
                        )
                        to_add = [
                            NAVHistory(
                                security_id=security.id,
                                date=p.date,
                                nav=p.nav,
                                source=source,
                            )
                            for p in history.points
                            if p.date not in existing_dates
                        ]
                        if to_add:
                            session.add_all(to_add)
                            summary["points"] += len(to_add)
                            summary["securities"] += 1

                        if security.nav_feed_closed:
                            security.nav_feed_closed = False
                    elif latest is None and not security.nav_feed_closed:
                        # Feed responded with empty history for a completely unpriced security
                        logger.warning(
                            "Security %s (%s): feed returned no history — marking closed",
                            security.id,
                            security.name,
                        )
                        security.nav_feed_closed = True
                        summary["closed"] += 1

                await session.commit()
            finally:
                clients.close()

        return summary

    async def get_nav_freshness(
        self,
        *,
        investor_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Compute NAV freshness report per held security."""
        await init_schema(self.engine)
        cutoff = completed_trading_day(date.today())

        async with self.session_factory() as session:
            # Collect securities involved in transactions or holdings
            sec_query = select(Transaction.security_id).distinct()
            hold_query = select(Holding.security_id).distinct()
            if investor_ids:
                sec_query = sec_query.where(Transaction.investor_id.in_(investor_ids))
                hold_query = hold_query.where(Holding.investor_id.in_(investor_ids))

            txn_secs = set((await session.execute(sec_query)).scalars().all())
            hold_secs = set((await session.execute(hold_query)).scalars().all())
            target_ids = list(txn_secs | hold_secs)

            if not target_ids:
                return {
                    "as_of": cutoff,
                    "securities": [],
                    "last_refreshed_at": None,
                    "next_refresh_at": next_scheduled_refresh(),
                }

            # Retrieve securities
            stmt = select(Security).where(Security.id.in_(target_ids))
            securities = list((await session.execute(stmt)).scalars().all())

            # Retrieve NAV history stats
            stat_stmt = (
                select(
                    NAVHistory.security_id,
                    func.min(NAVHistory.date).label("first"),
                    func.max(NAVHistory.date).label("latest"),
                    func.count(NAVHistory.id).label("points"),
                )
                .where(NAVHistory.security_id.in_(target_ids))
                .group_by(NAVHistory.security_id)
            )
            stats = {row[0]: row for row in (await session.execute(stat_stmt)).all()}

            rows = []
            for sec in securities:
                stat = stats.get(sec.id)
                latest = stat[2] if stat else None
                lag = (
                    trading_days_between(latest, cutoff) if latest is not None else None
                )
                status = _classify(sec, latest, lag)
                rows.append(
                    {
                        "security_id": sec.id,
                        "name": sec.name,
                        "security_type": sec.security_type,
                        "identifier": sec.symbol or sec.isin or sec.amfi_code,
                        "feed_code": _feed_code(sec),
                        "latest_nav_date": latest,
                        "first_nav_date": stat[1] if stat else None,
                        "points": stat[3] if stat else 0,
                        "lag_trading_days": lag,
                        "status": status,
                    }
                )

            _order = {
                "stale": 0,
                "pending": 1,
                "closed": 2,
                "grace": 3,
                "no_feed": 4,
                "fresh": 5,
            }
            rows.sort(
                key=lambda r: (
                    _order[r["status"]],
                    -(r["lag_trading_days"] or 0),
                    r["name"],
                )
            )

            last_written_stmt = select(func.max(NAVHistory.updated_at)).where(
                NAVHistory.security_id.in_(target_ids)
            )
            last_written = (
                await session.execute(last_written_stmt)
            ).scalar_one_or_none()

            return {
                "as_of": cutoff,
                "securities": rows,
                "last_refreshed_at": last_written,
                "next_refresh_at": next_scheduled_refresh(),
            }
