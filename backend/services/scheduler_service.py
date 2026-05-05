"""
services/scheduler_service.py — APScheduler setup for background job scheduling.

Schedules:
  - Naukri scraper:    Every 4 hours
  - LinkedIn scraper:  Every 6 hours
  - Indeed scraper:    Every 6 hours
  - Telegram posting:  Every 15 minutes
  - Daily digest:      9 AM daily
  - Deduplication:     Daily 3 AM
  - Cleanup:           Weekly Sunday 2 AM
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from config import Config

logger = logging.getLogger(__name__)


class JobScheduler:
    """
    Wrapper around APScheduler's BackgroundScheduler.

    The scheduler runs in background threads, inside the Flask app context,
    so all DB operations work correctly.
    """

    def __init__(self, app=None):
        self.app = app
        self.cfg = Config.scheduler
        self._scheduler = BackgroundScheduler(
            timezone="Asia/Kolkata",   # IST for Indian job market
            job_defaults={
                "coalesce": True,       # Merge missed runs into one
                "max_instances": 1,     # No overlapping executions
                "misfire_grace_time": 300,  # 5 min grace before marking missed
            },
        )
        self._scheduler.add_listener(
            self._job_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR,
        )

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------
    def start(self) -> None:
        """Register all jobs and start the scheduler."""
        self._register_jobs()
        self._scheduler.start()
        logger.info("Scheduler started with %d jobs", len(self._scheduler.get_jobs()))

    def stop(self) -> None:
        """Gracefully stop the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def get_jobs(self) -> list:
        """Return info about all scheduled jobs."""
        return [
            {
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            }
            for job in self._scheduler.get_jobs()
        ]

    # -------------------------------------------------------------------------
    # Job registration
    # -------------------------------------------------------------------------
    def _register_jobs(self) -> None:
        """Add all scheduled tasks to the scheduler."""

        # ── All 3 scrapers run together at 6 AM IST ──────────────────────────
        self._scheduler.add_job(
            func=self._run_with_context(self._naukri_task),
            trigger=CronTrigger(hour=6, minute=0),   # 6:00 AM IST
            id="naukri_scraper_am",
            name="Naukri Walk-in Scraper (6 AM)",
            replace_existing=True,
        )
        self._scheduler.add_job(
            func=self._run_with_context(self._linkedin_task),
            trigger=CronTrigger(hour=6, minute=5),   # 6:05 AM IST (staggered)
            id="linkedin_scraper_am",
            name="LinkedIn RSS Scraper (6 AM)",
            replace_existing=True,
        )
        self._scheduler.add_job(
            func=self._run_with_context(self._indeed_task),
            trigger=CronTrigger(hour=6, minute=10),  # 6:10 AM IST (staggered)
            id="indeed_scraper_am",
            name="Indeed RSS Scraper (6 AM)",
            replace_existing=True,
        )

        # ── All 3 scrapers run together at 6 PM IST ──────────────────────────
        self._scheduler.add_job(
            func=self._run_with_context(self._naukri_task),
            trigger=CronTrigger(hour=18, minute=0),  # 6:00 PM IST
            id="naukri_scraper_pm",
            name="Naukri Walk-in Scraper (6 PM)",
            replace_existing=True,
        )
        self._scheduler.add_job(
            func=self._run_with_context(self._linkedin_task),
            trigger=CronTrigger(hour=18, minute=5),  # 6:05 PM IST (staggered)
            id="linkedin_scraper_pm",
            name="LinkedIn RSS Scraper (6 PM)",
            replace_existing=True,
        )
        self._scheduler.add_job(
            func=self._run_with_context(self._indeed_task),
            trigger=CronTrigger(hour=18, minute=10), # 6:10 PM IST (staggered)
            id="indeed_scraper_pm",
            name="Indeed RSS Scraper (6 PM)",
            replace_existing=True,
        )

        # ── Telegram posting — every 15 minutes, always ───────────────────────
        self._scheduler.add_job(
            func=self._run_with_context(self._telegram_post_task),
            trigger=IntervalTrigger(minutes=15),
            id="telegram_poster",
            name="Telegram Job Poster (every 15 min)",
            replace_existing=True,
        )

        # ── Daily deduplication — 3 AM IST ───────────────────────────────────
        self._scheduler.add_job(
            func=self._run_with_context(self._dedup_task),
            trigger=CronTrigger(hour=3, minute=0),
            id="deduplication",
            name="Daily Deduplication (3 AM)",
            replace_existing=True,
        )

        # ── Weekly cleanup — Sunday 2 AM IST ─────────────────────────────────
        self._scheduler.add_job(
            func=self._run_with_context(self._cleanup_task),
            trigger=CronTrigger(day_of_week="sun", hour=2, minute=0),
            id="cleanup",
            name="Weekly Job Cleanup (Sun 2 AM)",
            replace_existing=True,
        )

        logger.info("Registered %d scheduled jobs", len(self._scheduler.get_jobs()))

    # -------------------------------------------------------------------------
    # App context wrapper
    # -------------------------------------------------------------------------
    def _run_with_context(self, func):
        """
        Wrap a task function so it runs inside the Flask app context.
        This ensures SQLAlchemy DB operations work in background threads.
        """
        def wrapper():
            if self.app:
                with self.app.app_context():
                    func()
            else:
                func()
        wrapper.__name__ = func.__name__
        return wrapper

    # -------------------------------------------------------------------------
    # Task implementations
    # -------------------------------------------------------------------------
    def _naukri_task(self):
        from tasks.scraper_tasks import run_naukri_scraper
        run_naukri_scraper()

    def _linkedin_task(self):
        from tasks.scraper_tasks import run_linkedin_scraper
        run_linkedin_scraper()

    def _indeed_task(self):
        from tasks.scraper_tasks import run_indeed_scraper
        run_indeed_scraper()

    def _telegram_post_task(self):
        from tasks.scraper_tasks import post_unposted_jobs
        post_unposted_jobs()

    def _daily_digest_task(self):
        from tasks.scraper_tasks import send_daily_digest
        send_daily_digest()

    def _dedup_task(self):
        from tasks.scraper_tasks import run_deduplication
        run_deduplication()

    def _cleanup_task(self):
        from tasks.scraper_tasks import run_cleanup
        run_cleanup()

    # -------------------------------------------------------------------------
    # Event listener
    # -------------------------------------------------------------------------
    def _job_listener(self, event):
        """Log job execution results and send alerts on failure."""
        if event.exception:
            logger.error(
                "Scheduled job FAILED: %s — Error: %s",
                event.job_id, event.exception,
            )
            # Alert admin via Telegram
            try:
                from services.telegram_service import TelegramService
                TelegramService().send_admin_alert(
                    f"Scheduled job <b>{event.job_id}</b> failed!\n"
                    f"Error: {str(event.exception)[:200]}"
                )
            except Exception:
                pass
        else:
            logger.debug("Scheduled job completed: %s", event.job_id)
