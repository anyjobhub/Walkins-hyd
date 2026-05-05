"""
services/database_service.py — Repository pattern for database operations.

Three repositories:
  - JobRepository         : CRUD for jobs, filtering, stats
  - ScrapLogRepository    : Audit log management
  - TelegramUserRepository: User subscription management
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, or_, and_, desc
from sqlalchemy.exc import IntegrityError

from models.job import db, Job, ScrapLog, TelegramUser, JobDuplicate
from services.deduplication import DeduplicationService
from services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

dedup = DeduplicationService()
cleaner = DataCleaner()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =============================================================================
# Job Repository
# =============================================================================
class JobRepository:
    """
    Data access layer for Job records.

    All DB operations are wrapped in try/except blocks to prevent
    unhandled exceptions from propagating to the API layer.
    """

    # -------------------------------------------------------------------------
    # Insertion
    # -------------------------------------------------------------------------
    def add_job(self, job_dict: Dict[str, Any]) -> Optional[int]:
        """
        Add a single job to the database.

        Steps:
          1. Run data cleaning pipeline
          2. Validate
          3. Check for duplicate (hash + fuzzy)
          4. Insert if unique
          5. Return new job ID or None

        Returns:
            Job ID if inserted, None if skipped/error.
        """
        try:
            # Clean and validate
            job_dict = cleaner.process_job(job_dict)
            if not job_dict.get("_valid"):
                logger.warning(
                    "Job validation failed: %s — Errors: %s",
                    job_dict.get("title"), job_dict.get("_errors"),
                )
                return None

            # Compute hash
            if not job_dict.get("job_hash"):
                job_dict["job_hash"] = dedup.generate_job_hash(job_dict)

            # Check duplicate in DB
            existing = dedup.find_duplicate_in_db(job_dict)
            if existing:
                logger.debug(
                    "Skipping duplicate job: '%s' @ '%s'",
                    job_dict.get("title"), job_dict.get("company"),
                )
                return None

            # Remove internal cleaning keys
            for k in ("_valid", "_errors", "_duplicate_of", "_similarity_score",
                       "_all_urls"):
                job_dict.pop(k, None)

            job = Job.from_dict(job_dict)
            db.session.add(job)
            db.session.commit()
            logger.info(
                "Added job id=%d: '%s' @ '%s'", job.id, job.title, job.company
            )
            return job.id

        except IntegrityError:
            db.session.rollback()
            logger.debug(
                "IntegrityError (likely duplicate source_id) for '%s'",
                job_dict.get("title"),
            )
            return None
        except Exception as exc:
            db.session.rollback()
            logger.error("Error adding job '%s': %s", job_dict.get("title"), exc, exc_info=True)
            return None

    def add_batch_jobs(
        self, jobs_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Add multiple jobs with in-batch deduplication.

        Returns:
            {"added": int, "skipped": int, "errors": List[str]}
        """
        added = 0
        skipped = 0
        errors = []

        # In-memory dedup before hitting DB
        unique_jobs, duplicates = dedup.deduplicate_batch(jobs_list)
        skipped += len(duplicates)

        for job_dict in unique_jobs:
            job_id = self.add_job(job_dict)
            if job_id:
                added += 1
            else:
                skipped += 1

        logger.info(
            "Batch insert complete: %d added, %d skipped (from %d total)",
            added, skipped, len(jobs_list),
        )
        return {"added": added, "skipped": skipped, "errors": errors}

    # -------------------------------------------------------------------------
    # Querying
    # -------------------------------------------------------------------------
    def get_jobs_by_filter(
        self,
        location: str = None,
        company: str = None,
        walkin_only: bool = False,
        fresher_friendly: bool = False,
        salary_min: int = None,
        salary_max: int = None,
        experience_level: str = None,
        search_query: str = None,
        source: str = None,
        page: int = 1,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Get jobs with optional filters and pagination.

        Returns:
            {"jobs": [...], "total": int, "page": int, "pages": int}
        """
        query = Job.query.filter(Job.is_duplicate == False)

        if walkin_only:
            query = query.filter(Job.is_walkin == True)

        if fresher_friendly:
            query = query.filter(Job.is_fresher_friendly == True)

        if location:
            query = query.filter(
                or_(
                    Job.location.ilike(f"%{location}%"),
                    Job.location_normalized.ilike(f"%{location}%"),
                )
            )

        if company:
            query = query.filter(Job.company.ilike(f"%{company}%"))

        if salary_min is not None:
            query = query.filter(
                or_(Job.salary_min >= salary_min, Job.salary_min == None)
            )

        if salary_max is not None:
            query = query.filter(
                or_(Job.salary_max <= salary_max, Job.salary_max == None)
            )

        if experience_level:
            query = query.filter(Job.experience_level == experience_level)

        if source:
            query = query.filter(Job.source == source)

        if search_query:
            query = query.filter(
                or_(
                    Job.title.ilike(f"%{search_query}%"),
                    Job.company.ilike(f"%{search_query}%"),
                    Job.job_description.ilike(f"%{search_query}%"),
                )
            )

        total = query.count()
        pages = max(1, (total + limit - 1) // limit)
        offset = (page - 1) * limit

        jobs = (
            query
            .order_by(desc(Job.extracted_at))
            .offset(offset)
            .limit(limit)
            .all()
        )

        return {
            "jobs": [j.to_website_format() for j in jobs],
            "total": total,
            "page": page,
            "pages": pages,
            "limit": limit,
        }

    def get_job_by_id(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Get a single job by its primary key."""
        job = Job.query.get(job_id)
        return job.to_website_format() if job else None

    def get_recent_jobs(
        self, days: int = 7, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get jobs extracted within the last N days."""
        cutoff = _utcnow() - timedelta(days=days)
        jobs = (
            Job.query
            .filter(Job.extracted_at >= cutoff, Job.is_duplicate == False)
            .order_by(desc(Job.extracted_at))
            .limit(limit)
            .all()
        )
        return [j.to_dict() for j in jobs]

    def get_walkin_jobs(
        self, location: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get walk-in jobs, optionally filtered by location."""
        query = Job.query.filter(
            Job.is_walkin == True, Job.is_duplicate == False
        )
        if location:
            query = query.filter(
                or_(
                    Job.location.ilike(f"%{location}%"),
                    Job.location_normalized.ilike(f"%{location}%"),
                )
            )
        jobs = query.order_by(desc(Job.extracted_at)).limit(limit).all()
        return [j.to_website_format() for j in jobs]

    def get_unposted_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get jobs not yet posted to Telegram."""
        jobs = (
            Job.query
            .filter(
                Job.telegram_posted == False,
                Job.is_duplicate == False,
            )
            .order_by(Job.extracted_at)
            .limit(limit)
            .all()
        )
        return [j.to_dict() for j in jobs]

    # -------------------------------------------------------------------------
    # Updates
    # -------------------------------------------------------------------------
    def mark_as_posted_to_telegram(self, job_id: int) -> bool:
        """Mark a job as posted to Telegram."""
        try:
            job = Job.query.get(job_id)
            if not job:
                return False
            job.telegram_posted = True
            job.telegram_posted_at = _utcnow()
            db.session.commit()
            return True
        except Exception as exc:
            db.session.rollback()
            logger.error("Error marking job %d as posted: %s", job_id, exc)
            return False

    # -------------------------------------------------------------------------
    # Statistics
    # -------------------------------------------------------------------------
    def get_stats(self) -> Dict[str, Any]:
        """Return system-wide statistics."""
        now = _utcnow()
        week_ago = now - timedelta(days=7)
        month_ago = now - timedelta(days=30)

        total = Job.query.filter(Job.is_duplicate == False).count()
        walkin_total = Job.query.filter(
            Job.is_walkin == True, Job.is_duplicate == False
        ).count()
        fresher_total = Job.query.filter(
            Job.is_fresher_friendly == True, Job.is_duplicate == False
        ).count()
        this_week = Job.query.filter(
            Job.extracted_at >= week_ago, Job.is_duplicate == False
        ).count()
        this_month = Job.query.filter(
            Job.extracted_at >= month_ago, Job.is_duplicate == False
        ).count()
        unposted = Job.query.filter(
            Job.telegram_posted == False, Job.is_duplicate == False
        ).count()
        duplicate_count = Job.query.filter(Job.is_duplicate == True).count()

        # Source breakdown
        from sqlalchemy import text
        sources = db.session.execute(
            text(
                "SELECT source, COUNT(*) as count FROM jobs "
                "WHERE is_duplicate = FALSE GROUP BY source"
            )
        ).fetchall()

        last_scrape = db.session.query(func.max(ScrapLog.ended_at)).scalar()

        return {
            "total_jobs": total,
            "total_walkin_jobs": walkin_total,
            "total_fresher_jobs": fresher_total,
            "jobs_this_week": this_week,
            "jobs_this_month": this_month,
            "unposted_jobs": unposted,
            "duplicate_count": duplicate_count,
            "sources": {row.source: row.count for row in sources},
            "last_scrape_time": last_scrape.isoformat() if last_scrape else None,
        }

    def cleanup_old_jobs(self, days: int = 60) -> int:
        """Delete jobs older than N days. Returns count deleted."""
        try:
            cutoff = _utcnow() - timedelta(days=days)
            deleted = Job.query.filter(Job.extracted_at < cutoff).delete()
            db.session.commit()
            logger.info("Cleaned up %d old jobs (older than %d days)", deleted, days)
            return deleted
        except Exception as exc:
            db.session.rollback()
            logger.error("Error during cleanup: %s", exc)
            return 0


# =============================================================================
# ScrapLog Repository
# =============================================================================
class ScrapLogRepository:
    """Data access layer for scrape audit logs."""

    def add_log(
        self,
        source: str,
        status: str,
        jobs_found: int = 0,
        jobs_added: int = 0,
        jobs_skipped: int = 0,
        started_at: datetime = None,
        ended_at: datetime = None,
        error_message: str = None,
    ) -> Optional[int]:
        """Insert a new scrape log entry."""
        try:
            started = started_at or _utcnow()
            ended = ended_at or _utcnow()
            duration = (ended - started).total_seconds()

            log = ScrapLog(
                source=source,
                status=status,
                jobs_found=jobs_found,
                jobs_added=jobs_added,
                jobs_skipped=jobs_skipped,
                started_at=started,
                ended_at=ended,
                duration_secs=duration,
                error_message=error_message,
            )
            db.session.add(log)
            db.session.commit()
            return log.id
        except Exception as exc:
            db.session.rollback()
            logger.error("Error saving scrape log: %s", exc)
            return None

    def get_recent_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get the most recent scrape logs."""
        logs = (
            ScrapLog.query
            .order_by(desc(ScrapLog.started_at))
            .limit(limit)
            .all()
        )
        return [log.to_dict() for log in logs]

    def get_last_scrape(self, source: str) -> Optional[Dict[str, Any]]:
        """Get the most recent log for a specific source."""
        log = (
            ScrapLog.query
            .filter_by(source=source)
            .order_by(desc(ScrapLog.started_at))
            .first()
        )
        return log.to_dict() if log else None


# =============================================================================
# TelegramUser Repository
# =============================================================================
class TelegramUserRepository:
    """Data access layer for Telegram user subscriptions."""

    def add_or_update_user(
        self,
        user_id: int,
        username: str = None,
        first_name: str = None,
        last_name: str = None,
    ) -> bool:
        """Add a new user or update their info if they exist."""
        try:
            user = TelegramUser.query.filter_by(user_id=user_id).first()
            if user:
                user.username = username or user.username
                user.first_name = first_name or user.first_name
                user.last_name = last_name or user.last_name
                user.last_active = _utcnow()
                user.subscribed = True
            else:
                user = TelegramUser(
                    user_id=user_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    subscribed=True,
                )
                db.session.add(user)
            db.session.commit()
            return True
        except Exception as exc:
            db.session.rollback()
            logger.error("Error upserting telegram user %d: %s", user_id, exc)
            return False

    def subscribe_user(self, user_id: int) -> bool:
        """Subscribe a user to job notifications."""
        try:
            user = TelegramUser.query.filter_by(user_id=user_id).first()
            if user:
                user.subscribed = True
                user.last_active = _utcnow()
                db.session.commit()
                return True
            return False
        except Exception as exc:
            db.session.rollback()
            logger.error("Error subscribing user %d: %s", user_id, exc)
            return False

    def unsubscribe_user(self, user_id: int) -> bool:
        """Unsubscribe a user from job notifications."""
        try:
            user = TelegramUser.query.filter_by(user_id=user_id).first()
            if user:
                user.subscribed = False
                db.session.commit()
                return True
            return False
        except Exception as exc:
            db.session.rollback()
            logger.error("Error unsubscribing user %d: %s", user_id, exc)
            return False

    def get_all_subscribers(self) -> List[Dict[str, Any]]:
        """Get all currently subscribed users."""
        users = TelegramUser.query.filter_by(subscribed=True).all()
        return [u.to_dict() for u in users]

    def get_user_preferences(self, user_id: int) -> Optional[Dict]:
        """Get a user's job preferences."""
        user = TelegramUser.query.filter_by(user_id=user_id).first()
        return user.preferences if user else None

    def update_preferences(self, user_id: int, preferences: Dict) -> bool:
        """Update a user's job preferences."""
        try:
            user = TelegramUser.query.filter_by(user_id=user_id).first()
            if user:
                user.preferences = preferences
                db.session.commit()
                return True
            return False
        except Exception as exc:
            db.session.rollback()
            logger.error("Error updating preferences for user %d: %s", user_id, exc)
            return False

    def get_subscriber_count(self) -> int:
        """Return the total number of subscribed users."""
        return TelegramUser.query.filter_by(subscribed=True).count()
