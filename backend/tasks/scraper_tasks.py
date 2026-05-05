"""
tasks/scraper_tasks.py — Background tasks for running the Apify job scraper.
Integrated with the database and deduplication services.
"""

import logging
from typing import Any, Dict, List, Optional
from flask import Flask
from services.apify_service import fetch_jobs_from_apify
from services.deduplication import DeduplicationService
from models.job import db, Job
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

def run_scraper_pipeline(app: Flask):
    """
    Main background task to fetch jobs from Apify,
    deduplicate them, and save to database.
    """
    with app.app_context():
        logger.info("🚀 Starting Apify Scraper Pipeline...")
        
        try:
            # 1. Fetch from Apify
            apify_jobs = fetch_jobs_from_apify()
            
            if not apify_jobs:
                logger.warning("No jobs fetched from Apify. Pipeline finished.")
                return

            logger.info("Fetched %d raw jobs from Apify.", len(apify_jobs))

            # 2. Flatten and Clean List (Requirement 1 & 2)
            # Ensuring we have a flat list of dictionaries
            clean_jobs = []
            for item in apify_jobs:
                if isinstance(item, list):
                    # Flatten nested lists if they exist
                    for sub_item in item:
                        if isinstance(sub_item, dict):
                            clean_jobs.append(sub_item)
                elif isinstance(item, dict):
                    clean_jobs.append(item)
                else:
                    logger.warning("Invalid job skipped: %s", item)

            logger.info("Total jobs after flattening and cleaning: %d", len(clean_jobs))

            # 3. Initialise Deduplication
            dedup_service = DeduplicationService()
            new_jobs_count = 0
            
            # Fetch all existing jobs from DB once for efficiency
            # Convert them to dicts so the dedup service can handle them
            existing_jobs = [j.to_dict() for j in Job.query.all()]
            
            # 4. Process and Save
            for job_data in clean_jobs:
                try:
                    # Check if job already exists by URL
                    existing = Job.query.filter_by(job_url=job_data.get("job_url")).first()
                    if existing:
                        continue

                    # Safe Deduplication (Requirement 4 & 5)
                    is_duplicate = False
                    for existing_job in existing_jobs:
                        try:
                            # is_duplicate returns (bool, score)
                            is_dup, _ = dedup_service.is_duplicate(job_data, existing_job)
                            if is_dup:
                                is_duplicate = True
                                break
                        except Exception as e:
                            logger.error("Dedup error on individual job: %s", e)
                            continue

                    if is_duplicate:
                        continue

                    # 5. Save Job to DB (Requirement 6)
                    new_job = Job(
                        title=job_data.get("title"),
                        company=job_data.get("company"),
                        location=job_data.get("location"),
                        job_url=job_data.get("job_url"),
                        source=job_data.get("source"),
                        is_walkin=job_data.get("is_walkin", False),
                        is_fresher_friendly=job_data.get("is_fresher_friendly", False),
                        extracted_at=datetime.now(timezone.utc)
                    )
                    
                    db.session.add(new_job)
                    new_jobs_count += 1
                    
                    # Update local existing_jobs list to prevent duplicates within the same run
                    existing_jobs.append(job_data)

                except Exception as inner_e:
                    logger.error("Error processing job %s: %s", job_data.get("title"), inner_e)
                    continue

            db.session.commit()
            logger.info("✅ Pipeline Complete: %d new jobs saved to database.", new_jobs_count)
            
        except Exception as e:
            logger.error("Pipeline Global Error: %s", e, exc_info=True)
            db.session.rollback()

# =============================================================================
# Telegram tasks
# =============================================================================

def post_unposted_jobs() -> Dict[str, Any]:
    """
    Post exactly 1 unposted job to Telegram.
    Called as fallback by manual trigger / scrape-now endpoint.
    """
    from services.database_service import JobRepository
    from services.telegram_service import TelegramService

    svc = TelegramService()
    if not svc.is_configured:
        return {"sent": 0, "failed": 0, "skipped": "not configured"}

    repo = JobRepository()
    jobs = repo.get_unposted_jobs(limit=1)
    if not jobs:
        return {"sent": 0, "failed": 0}

    return svc.send_batch_jobs([jobs[0]], delay_seconds=0)


def post_jobs_spread_over_hours(app, hours: float = 4.0) -> None:
    """
    Post ALL unposted jobs spread evenly over `hours` hours.
    Runs in a background daemon thread after each scrape.
    """
    import time
    from services.database_service import JobRepository
    from services.telegram_service import TelegramService

    # Single app context wraps the entire function — NO nested contexts
    with app.app_context():
        svc = TelegramService()
        if not svc.is_configured:
            logger.warning("Telegram not configured — skipping spread poster")
            return

        repo = JobRepository()
        jobs = repo.get_unposted_jobs(limit=500)

        if not jobs:
            logger.info("No unposted jobs to spread")
            return

        total = len(jobs)
        interval = max(60, (hours * 3600) / total)  # min 60 sec between posts
        interval_min = round(interval / 60, 1)
        logger.info(
            "Spread poster: %d jobs over %.1fh → 1 post every %.1f min",
            total, hours, interval_min,
        )

        for i, job in enumerate(jobs):
            try:
                # No nested with app.app_context() — we're already inside one
                svc.send_batch_jobs([job], delay_seconds=0)
                logger.debug("Posted job %d/%d: %s", i + 1, total, job.get("title"))
            except Exception as exc:
                logger.error("Failed to post job %s: %s", job.get("id"), exc)

            if i < total - 1:       # no sleep after last job
                time.sleep(interval)

        logger.info("Spread poster complete: posted %d jobs", total)


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
