"""In-process and standalone scheduler for recurring maintenance tasks.

Manages 6-hourly NAV refreshes and daily reference catalog updates via
APScheduler (pure-Python, thread-based).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.ext.asyncio import AsyncEngine

from folioman_client.db.engine import create_folioman_engine
from folioman_client.services.isin_service import ISINService
from folioman_client.services.nav_service import NAVService, REVALUE_HOURS

logger = logging.getLogger(__name__)

_REVALUE_HOURS_STR = ",".join(str(h) for h in sorted(REVALUE_HOURS))
_MISFIRE_GRACE_SECONDS = 4 * 60 * 60  # 4 hours


def _run_async(coro_fn):
    """Run an async coroutine inside a fresh event loop on the worker thread."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro_fn())
    finally:
        loop.close()


class FoliomanScheduler:
    """Manages recurring background jobs for NAV synchronization and reference updates."""

    def __init__(
        self,
        engine: AsyncEngine | None = None,
        database_url: str | None = None,
        revalue_hours: tuple[int, ...] = REVALUE_HOURS,
    ) -> None:
        self.engine = engine or create_folioman_engine(database_url)
        self.revalue_hours = revalue_hours
        self._scheduler: BackgroundScheduler | BlockingScheduler | None = None
        self._is_running = False

    @property
    def is_running(self) -> bool:
        """Return True if the scheduler is active."""
        return self._is_running and self._scheduler is not None and self._scheduler.running

    def _job_daily_extend(self) -> dict[str, Any]:
        """6-hourly NAV refresh and historical tail extension."""
        logger.info("Executing scheduled NAV refresh and daily extend tick...")

        async def _action():
            nav_svc = NAVService(engine=self.engine)
            refresh_summary = await nav_svc.refresh_navs()
            backfill_summary = await nav_svc.backfill_navs(force=False)
            return {"refresh": refresh_summary, "backfill": backfill_summary}

        try:
            res = _run_async(_action)
            logger.info("Completed scheduled NAV update: %s", res)
            return res
        except Exception as exc:
            logger.exception("Scheduled NAV update failed: %s", exc)
            return {"error": str(exc)}

    def _job_update_isin(self) -> dict[str, Any]:
        """Daily reference catalog update check."""
        logger.info("Executing scheduled ISIN reference update tick...")

        async def _action():
            isin_svc = ISINService(engine=self.engine)
            return await isin_svc.update_reference_data()

        try:
            res = _run_async(_action)
            logger.info("Completed scheduled ISIN update: %s", res)
            return res
        except Exception as exc:
            logger.exception("Scheduled ISIN update failed: %s", exc)
            return {"error": str(exc)}

    def start(self, *, blocking: bool = False, run_catchup: bool = False) -> None:
        """Start the scheduler.

        Args:
            blocking: If True, uses BlockingScheduler (for CLI foreground daemon).
                      If False, uses BackgroundScheduler (for embedded library mode).
            run_catchup: If True, queues an immediate execution of the daily extend pass.
        """
        if self.is_running:
            logger.warning("Scheduler is already running.")
            return

        scheduler_cls = BlockingScheduler if blocking else BackgroundScheduler
        self._scheduler = scheduler_cls()

        # Add 6-hourly NAV refresh & daily extend
        revalue_str = ",".join(str(h) for h in sorted(self.revalue_hours))
        self._scheduler.add_job(
            self._job_daily_extend,
            trigger=CronTrigger(hour=revalue_str, minute=0),
            id="nav_daily_extend",
            name="6-hourly NAV Refresh and Daily Extend",
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
            coalesce=True,
            max_instances=1,
        )

        # Add daily ISIN catalog check at 03:00
        self._scheduler.add_job(
            self._job_update_isin,
            trigger=CronTrigger(hour=3, minute=0),
            id="isin_catalog_update",
            name="Daily ISIN Catalog Update",
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
            coalesce=True,
            max_instances=1,
        )

        if run_catchup and not blocking:
            # Trigger an immediate run in a worker thread
            import threading
            threading.Thread(target=self._job_daily_extend, daemon=True).start()

        self._is_running = True
        logger.info("Starting Folioman %s scheduler...", "blocking" if blocking else "background")
        try:
            self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.shutdown()

    def shutdown(self, *, wait: bool = False) -> None:
        """Gracefully terminate the scheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
        self._is_running = False
        logger.info("Folioman scheduler shut down.")

    def trigger_job(self, job_id: str) -> dict[str, Any]:
        """Manually trigger one of the registered jobs on demand."""
        if job_id == "nav_daily_extend":
            return self._job_daily_extend()
        elif job_id == "isin_catalog_update":
            return self._job_update_isin()
        else:
            raise ValueError(f"Unknown job ID: {job_id}")
