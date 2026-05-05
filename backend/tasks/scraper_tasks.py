"""
tasks/scraper_tasks.py — Orchestrated scraper pipeline tasks.

These functions are called by the APScheduler and also by the
/api/scraper/trigger admin endpoint.

Each task:
  1. Initialises the scraper
  2. Fetches jobs
  3. Cleans the data
  4. Deduplicates
  5. Inserts into DB
  6. Logs the result
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Individual scraper tasks
# =============================================================================

def run_naukri_scraper(location: str = "India") -> Dict[str, Any]:
    """Run the Naukri scraper and persist results to the DB."""
    return _run_scraper_task("naukri", location)


def run_linkedin_scraper(location: str = "India") -> Dict[str, Any]:
    """Run the LinkedIn RSS scraper and persist results to the DB."""
    return _run_scraper_task("linkedin", location)


def run_indeed_scraper(location: str = "India") -> Dict[str, Any]:
    """Run the Indeed RSS scraper and persist results to the DB."""
    return _run_scraper_task("indeed", location)


def run_scraper_pipeline(
    sources: List[str] = None,
    location: str = "India",
) -> Dict[str, Any]:
    """
    Run multiple scrapers in sequence.

    Args:
        sources: List of source names to run.
        location: Location to scrape for.

    Returns:
        Combined statistics dict.
    """
    sources = sources or ["naukri", "linkedin", "indeed"]
    results = []

    for source in sources:
        result = _run_scraper_task(source, location)
        results.append(result)

    # Aggregate
    total_found = sum(r.get("jobs_found", 0) for r in results)
    total_added = sum(r.get("jobs_added", 0) for r in results)
    total_skipped = sum(r.get("jobs_skipped", 0) for r in results)

    return {
        "sources": results,
        "total_found": total_found,
        "total_added": total_added,
        "total_skipped": total_skipped,
    }


# =============================================================================
# Telegram tasks
# =============================================================================

def post_unposted_jobs(batch_size: int = 10) -> Dict[str, Any]:
    """
    Fetch unposted jobs from DB and send them to Telegram.

    Called every 15 minutes by the scheduler.
    """
    from services.database_service import JobRepository
    from services.telegram_service import TelegramService

    svc = TelegramService()
    if not svc.is_configured:
        logger.warning("Telegram not configured — skipping post_unposted_jobs")
        return {"sent": 0, "failed": 0, "skipped": "not configured"}

    repo = JobRepository()
    jobs = repo.get_unposted_jobs(limit=batch_size)

    if not jobs:
        logger.debug("No unposted jobs to send")
        return {"sent": 0, "failed": 0}

    logger.info("Posting %d jobs to Telegram", len(jobs))
    result = svc.send_batch_jobs(jobs, delay_seconds=1.5)

    return result


def send_daily_digest() -> Dict[str, Any]:
    """
    Send a daily digest of today's new jobs to the Telegram channel.

    Called at 9 AM IST by the scheduler.
    """
    from services.database_service import JobRepository
    from services.telegram_service import TelegramService

    svc = TelegramService()
    if not svc.is_configured:
        return {"status": "skipped", "reason": "Telegram not configured"}

    jobs = JobRepository().get_recent_jobs(days=1, limit=30)
    success = svc.send_daily_digest(jobs)

    return {"status": "sent" if success else "failed", "job_count": len(jobs)}


# =============================================================================
# Maintenance tasks
# =============================================================================

def run_deduplication() -> Dict[str, Any]:
    """
    Run a full deduplication pass on recent jobs in the DB.

    Marks additional duplicates that may have been missed during insertion.
    Called daily at 3 AM.
    """
    from models.job import db, Job, JobDuplicate
    from services.deduplication import DeduplicationService

    logger.info("Starting daily deduplication pass")
    dedup = DeduplicationService()

    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)

    # Fetch recent non-duplicate jobs
    jobs = (
        Job.query
        .filter(Job.extracted_at >= cutoff, Job.is_duplicate == False)
        .order_by(Job.extracted_at.desc())
        .all()
    )

    jobs_as_dicts = [j.to_dict() for j in jobs]
    _, duplicates = dedup.deduplicate_batch(jobs_as_dicts)

    marked = 0
    for dup in duplicates:
        dup_id = dup.get("id")
        original = dup.get("_duplicate_of", {})
        if dup_id and original.get("id"):
            job_record = Job.query.get(dup_id)
            if job_record and not job_record.is_duplicate:
                job_record.is_duplicate = True
                job_record.duplicate_of_id = original["id"]

                # Record in job_duplicates table
                rel = JobDuplicate(
                    original_job_id=original["id"],
                    duplicate_job_id=dup_id,
                    similarity_score=dup.get("_similarity_score", 0),
                )
                db.session.merge(rel)
                marked += 1

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error("Dedup commit failed: %s", exc)
        return {"status": "error", "error": str(exc)}

    logger.info("Deduplication complete: marked %d additional duplicates", marked)
    return {"status": "success", "duplicates_marked": marked, "jobs_checked": len(jobs)}


def run_cleanup(days: int = None) -> Dict[str, Any]:
    """
    Delete old job records beyond the retention period.

    Called weekly on Sunday at 2 AM.
    """
    from services.database_service import JobRepository
    from config import Config

    retention = days or Config.scheduler.CLEANUP_DAYS
    deleted = JobRepository().cleanup_old_jobs(days=retention)

    return {"status": "success", "deleted": deleted, "retention_days": retention}


# =============================================================================
# Internal pipeline
# =============================================================================

def _run_scraper_task(source: str, location: str) -> Dict[str, Any]:
    """
    Internal orchestration function for a single scraper source.

    Runs: scrape → clean → dedup → DB insert → log.
    """
    from services.database_service import JobRepository, ScrapLogRepository

    started_at = datetime.now(timezone.utc)
    jobs_found = 0
    jobs_added = 0
    jobs_skipped = 0
    error_msg = None
    status = "failed"

    try:
        # ── Scrape ──────────────────────────────────────────────────────────
        scraper = _get_scraper(source)
        if not scraper:
            raise ValueError(f"Unknown source: {source}")

        logger.info("Starting %s scraper | location=%s", source, location)
        raw_jobs = scraper.scrape_jobs(location=location)
        jobs_found = len(raw_jobs)
        logger.info("%s scraper found %d jobs", source, jobs_found)

        # ── Persist ─────────────────────────────────────────────────────────
        repo = JobRepository()
        batch_result = repo.add_batch_jobs(raw_jobs)
        jobs_added = batch_result["added"]
        jobs_skipped = batch_result["skipped"]
        status = "success"

    except Exception as exc:
        error_msg = str(exc)
        logger.error(
            "%s scraper error: %s", source, exc, exc_info=True
        )
        status = "partial" if jobs_found > 0 else "failed"

    finally:
        ended_at = datetime.now(timezone.utc)
        # ── Log ─────────────────────────────────────────────────────────────
        try:
            ScrapLogRepository().add_log(
                source=source,
                status=status,
                jobs_found=jobs_found,
                jobs_added=jobs_added,
                jobs_skipped=jobs_skipped,
                started_at=started_at,
                ended_at=ended_at,
                error_message=error_msg,
            )
        except Exception as log_exc:
            logger.error("Failed to save scrape log: %s", log_exc)

    return {
        "source": source,
        "status": status,
        "jobs_found": jobs_found,
        "jobs_added": jobs_added,
        "jobs_skipped": jobs_skipped,
        "error": error_msg,
    }


def _get_scraper(source: str):
    """Factory: return the correct scraper instance for the source name."""
    if source == "naukri":
        from scrapers.naukri_scraper import NaukriScraper
        return NaukriScraper()
    elif source == "linkedin":
        from scrapers.linkedin_scraper import LinkedInScraper
        return LinkedInScraper()
    elif source == "indeed":
        from scrapers.indeed_scraper import IndeedScraper
        return IndeedScraper()
    return None
